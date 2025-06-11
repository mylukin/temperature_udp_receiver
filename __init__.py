import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN, PLATFORMS, MODBUS_DEVICE_ADDR_MIN, MODBUS_DEVICE_ADDR_MAX, 
    MODBUS_FUNCTION_CODE_READ, MODBUS_EXPECTED_LENGTH, OFFLINE_THRESHOLD, 
    HEARTBEAT_INDICATORS, REGISTRATION_INDICATORS, TEMPERATURE_SCALE, 
    TEMPERATURE_MIN, TEMPERATURE_MAX, ERROR_CODES
)

_LOGGER = logging.getLogger(__name__)

# ================== 入口点函数 ==================

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up from YAML (deprecated)."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """设置集成入口点"""
    _LOGGER.info("正在设置 Temperature UDP Receiver 集成")
    
    try:
        port = entry.data.get("port", 8889)
        udp_server = UDPTempServer(hass, port)
        await udp_server.start()
        
        # 保存服务器实例并注册服务
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = {"server": udp_server}
        await _register_services(hass, udp_server)
        
        # 设置传感器平台
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
        _LOGGER.info(f"Temperature UDP Receiver 设置完成，端口: {port}")
        return True
        
    except Exception as e:
        _LOGGER.error(f"设置 Temperature UDP Receiver 失败: {e}")
        return False

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置条目"""
    try:
        server_data = hass.data[DOMAIN].pop(entry.entry_id)
        await server_data["server"].stop()
        
        hass.services.async_remove(DOMAIN, "get_device_status")
        result = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        
        _LOGGER.info("Temperature UDP Receiver 已成功卸载")
        return result
        
    except Exception as e:
        _LOGGER.error(f"卸载 Temperature UDP Receiver 失败: {e}")
        return False

# ================== 服务注册 ==================

async def _register_services(hass: HomeAssistant, udp_server: 'UDPTempServer') -> None:
    """注册Home Assistant服务"""
    
    async def get_device_status(call):
        """获取设备状态服务"""
        try:
            status = udp_server.get_client_status()
            message = _format_device_status_message(status)
            
            await hass.services.async_call(
                'persistent_notification', 'create',
                {'message': message, 'title': 'Temperature UDP Receiver 设备状态'}
            )
            _LOGGER.debug(f"设备状态查询结果: {len(status)} 个设备")
        except Exception as e:
            _LOGGER.error(f"获取设备状态失败: {e}")
    
    hass.services.async_register(DOMAIN, "get_device_status", get_device_status)

def _format_device_status_message(status: Dict[str, Any]) -> str:
    """格式化设备状态消息"""
    if not status:
        return "设备状态:\n暂无设备连接"
    
    message = "设备状态:\n"
    for addr, info in status.items():
        online_status = "在线" if info['online'] else f"离线({info['offline_duration']:.0f}秒)"
        device_type = info.get('type', '未知')
        message += f"设备 {addr}: {online_status} ({device_type})\n"
    
    return message

# ================== UDP服务器 ==================

class UDPTempServer:
    """UDP温度传感器服务器"""
    
    def __init__(self, hass: HomeAssistant, port: int):
        self.hass = hass
        self.port = port
        self.transport = None
        self.protocol = None
        
    async def start(self) -> None:
        """启动UDP服务器"""
        try:
            loop = asyncio.get_event_loop()
            self.transport, self.protocol = await loop.create_datagram_endpoint(
                lambda: UDPProtocol(self.hass),
                local_addr=('0.0.0.0', self.port)
            )
            _LOGGER.info(f"UDP服务器已启动，监听端口: {self.port}")
        except Exception as e:
            _LOGGER.error(f"启动UDP服务器失败: {e}")
            raise
        
    async def stop(self) -> None:
        """停止UDP服务器"""
        if self.transport:
            self.transport.close()
            _LOGGER.info("UDP服务器已停止")
    
    def get_client_status(self) -> Dict[str, Any]:
        """获取客户端状态"""
        return self.protocol.get_client_status() if self.protocol else {}

# ================== UDP协议处理器 ==================

class UDPProtocol(asyncio.DatagramProtocol):
    """UDP协议处理器"""
    
    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self.known_clients: Dict[str, Dict[str, Any]] = {}
        self._modbus_parser = ModBusParser()
        
    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        """接收并处理UDP数据包"""
        addr_str = f"{addr[0]}:{addr[1]}"
        
        # 详细的数据包日志
        _LOGGER.info(f"收到UDP数据包 from {addr_str}: 长度={len(data)}字节")
        _LOGGER.debug(f"原始数据 (hex): {data.hex()}")
        _LOGGER.debug(f"原始数据 (bytes): {list(data)}")
        
        try:
            # 优先尝试解析ModBus数据
            _LOGGER.debug(f"尝试解析ModBus数据...")
            parsed_data = self._modbus_parser.parse(data)
            if parsed_data:
                _LOGGER.info(f"ModBus数据解析成功 from {addr_str}")
                self._handle_temperature_data(parsed_data, addr_str)
                return
            else:
                _LOGGER.debug(f"ModBus数据解析失败，尝试文本解析...")
                
            # 尝试解析文本数据
            text_data = self._try_decode_text(data)
            if text_data:
                _LOGGER.debug(f"文本解码成功: '{text_data[:100]}{'...' if len(text_data) > 100 else ''}'")
                if self._is_text_packet(text_data):
                    _LOGGER.info(f"识别为文本数据包 from {addr_str}")
                    self._handle_text_packet(text_data, addr_str)
                    return
                else:
                    _LOGGER.debug(f"文本数据不符合已知格式")
            else:
                _LOGGER.debug(f"文本解码失败")
            
            # 所有解析方法都失败
            _LOGGER.warning(f"无法解码UDP数据包 from {addr_str}")
            _LOGGER.warning(f"数据详情: 长度={len(data)}, hex={data.hex()}, bytes={list(data)}")
            
            # 尝试识别数据包类型
            self._analyze_unknown_packet(data, addr_str)
                
        except Exception as e:
            _LOGGER.error(f"处理UDP数据包失败 from {addr}: {e}")
            _LOGGER.error(f"异常数据: hex={data.hex()}, bytes={list(data)}")
    
    def _analyze_unknown_packet(self, data: bytes, addr_str: str) -> None:
        """分析未知数据包格式"""
        _LOGGER.debug(f"开始分析未知数据包格式 from {addr_str}")
        
        if len(data) == 0:
            _LOGGER.debug("空数据包")
            return
            
        # 检查是否为常见长度的数据包
        common_lengths = {
            7: "可能是简化的ModBus响应",
            8: "可能是标准温度数据",
            13: "可能是完整ModBus RTU包",
            17: "可能是ZQWL格式包"
        }
        
        if len(data) in common_lengths:
            _LOGGER.debug(f"数据包长度 {len(data)}: {common_lengths[len(data)]}")
        
        # 分析前几个字节
        if len(data) >= 1:
            _LOGGER.debug(f"第1字节 (设备地址?): 0x{data[0]:02X} ({data[0]})")
        if len(data) >= 2:
            _LOGGER.debug(f"第2字节 (功能码?): 0x{data[1]:02X} ({data[1]})")
        if len(data) >= 3:
            _LOGGER.debug(f"第3字节 (数据长度?): 0x{data[2]:02X} ({data[2]})")
            
        # 检查是否包含可打印字符
        try:
            ascii_chars = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in data)
            _LOGGER.debug(f"ASCII表示: '{ascii_chars}'")
        except:
            pass
            
        # 检查是否为JSON格式
        try:
            json.loads(data.decode('utf-8'))
            _LOGGER.debug("可能是JSON格式数据")
        except:
            _LOGGER.debug("不是JSON格式")
    
    def _try_decode_text(self, data: bytes) -> Optional[str]:
        """尝试多种编码解码文本数据"""
        encodings = ['utf-8', 'gbk', 'gb2312', 'ascii', 'latin1']
        
        for encoding in encodings:
            try:
                decoded = data.decode(encoding)
                _LOGGER.debug(f"使用 {encoding} 编码解码成功: '{decoded[:50]}{'...' if len(decoded) > 50 else ''}'")
                return decoded
            except (UnicodeDecodeError, UnicodeError) as e:
                _LOGGER.debug(f"使用 {encoding} 编码失败: {e}")
                continue
        
        _LOGGER.debug("所有编码方式都失败")
        return None
    
    def _is_text_packet(self, data: str) -> bool:
        """检查是否为文本数据包（心跳包或注册包）"""
        data_lower = data.lower()
        indicators = HEARTBEAT_INDICATORS + REGISTRATION_INDICATORS
        
        for indicator in indicators:
            if indicator in data_lower:
                _LOGGER.debug(f"匹配到指示符: '{indicator}'")
                return True
                
        _LOGGER.debug(f"未匹配到任何指示符，支持的指示符: {indicators}")
        return False
    
    def _handle_text_packet(self, data: str, addr: str) -> None:
        """处理文本数据包"""
        data_lower = data.lower()
        
        if any(indicator in data_lower for indicator in HEARTBEAT_INDICATORS):
            _LOGGER.info(f"处理心跳包 from {addr}")
            self._handle_heartbeat(data, addr)
        elif any(indicator in data_lower for indicator in REGISTRATION_INDICATORS):
            _LOGGER.info(f"处理注册包 from {addr}")
            self._handle_registration(data, addr)
        else:
            _LOGGER.debug(f"收到未知文本数据包 from {addr}: {data[:50]}")
    
    def _handle_temperature_data(self, temp_json: str, addr: str) -> None:
        """处理温度数据"""
        try:
            temp_data_obj = json.loads(temp_json)
            temp_data = temp_data_obj.get('temperature', {})
            
            if not temp_data:
                _LOGGER.warning(f"温度JSON中无temperature字段: {temp_json}")
                return
                
            # 更新客户端状态
            self._update_client_status(addr, 'temperature_sensor')
            
            # 触发温度数据事件
            event_data = {
                'event_type': 'temperature_data_received',
                'temperature_data': temp_data,
                'timestamp': temp_data_obj.get('timestamp'),
                'source_addr': addr,
                'device_type': temp_data_obj.get('device_type', '18B20')
            }
            
            self.hass.bus.async_fire(f'{DOMAIN}_event', event_data)
            
            # 记录温度数据
            temp_celsius = temp_data.get('celsius', 0)
            temp_status = temp_data.get('status', 'unknown')
            _LOGGER.info(f"温度数据更新 from {addr}: {temp_celsius:.1f}°C, 状态={temp_status}")
            
        except json.JSONDecodeError as e:
            _LOGGER.error(f"温度数据JSON解析失败 from {addr}: {e}")
            _LOGGER.debug(f"失败的JSON数据: {temp_json}")
        except Exception as e:
            _LOGGER.error(f"处理温度数据失败 from {addr}: {e}")
    
    def _handle_heartbeat(self, data: str, addr: str) -> None:
        """处理心跳包"""
        _LOGGER.debug(f"收到心跳包 from {addr}: '{data[:100]}'")
        self._update_client_status(addr, 'heartbeat')
        self._fire_event('device_heartbeat', {
            'device_addr': addr,
            'heartbeat_data': data[:100]
        })
    
    def _handle_registration(self, data: str, addr: str) -> None:
        """处理注册包"""
        _LOGGER.info(f"收到设备注册 from {addr}: '{data[:100]}'")
        self._update_client_status(addr, 'registration', {'registration_data': data})
        self._fire_event('device_registered', {
            'device_addr': addr,
            'registration_data': data
        })
    
    def _fire_event(self, event_type: str, event_data: Dict[str, Any]) -> None:
        """触发事件的通用方法"""
        event_data.update({
            'event_type': event_type,
            'timestamp': asyncio.get_event_loop().time()
        })
        self.hass.bus.async_fire(f'{DOMAIN}_event', event_data)
    
    def _update_client_status(self, addr: str, client_type: str, extra_data: Optional[Dict] = None) -> None:
        """更新客户端状态"""
        current_time = asyncio.get_event_loop().time()
        
        client_info = {
            'last_seen': current_time,
            'type': client_type
        }
        
        if extra_data:
            client_info.update(extra_data)
        
        # 保留特定的时间戳字段
        if client_type == 'heartbeat':
            client_info['last_heartbeat'] = current_time
        elif client_type == 'registration':
            client_info['last_registration'] = current_time
        
        self.known_clients[addr] = client_info
    
    def get_client_status(self) -> Dict[str, Dict[str, Any]]:
        """获取客户端状态信息"""
        current_time = asyncio.get_event_loop().time()
        status = {}
        
        for addr, info in self.known_clients.items():
            last_seen = info.get('last_seen', 0)
            offline_duration = current_time - last_seen
            
            status[addr] = {
                'type': info.get('type', 'unknown'),
                'last_seen': last_seen,
                'online': offline_duration < OFFLINE_THRESHOLD,
                'offline_duration': offline_duration
            }
        
        return status

# ================== ModBus数据解析器 ==================

class ModBusParser:
    """ModBus数据解析器 - 专门处理18B20温度传感器"""
    
    def parse(self, data: bytes) -> Optional[str]:
        """解析ModBus数据，返回JSON格式的温度数据"""
        _LOGGER.debug(f"开始ModBus解析，数据长度: {len(data)}")
        
        if not self._is_valid_modbus(data):
            _LOGGER.debug("ModBus格式验证失败")
            return None
            
        try:
            result = self._parse_modbus_response(data)
            _LOGGER.debug(f"ModBus解析成功")
            return result
        except Exception as e:
            _LOGGER.error(f"ModBus数据解析失败: {e}")
            _LOGGER.debug(f"失败的数据: hex={data.hex()}")
            return None
    
    def _is_valid_modbus(self, data: bytes) -> bool:
        """验证ModBus数据包格式和CRC校验"""
        _LOGGER.debug(f"验证ModBus格式...")
        
        if len(data) < 5:
            _LOGGER.debug(f"数据包太短: {len(data)} < 5")
            return False
        
        device_addr, function_code = data[0], data[1]
        _LOGGER.debug(f"设备地址: 0x{device_addr:02X} ({device_addr})")
        _LOGGER.debug(f"功能码: 0x{function_code:02X} ({function_code})")
        
        # 检查地址和功能码 - 只支持读取操作
        if not (MODBUS_DEVICE_ADDR_MIN <= device_addr <= MODBUS_DEVICE_ADDR_MAX):
            _LOGGER.debug(f"设备地址超出范围: {device_addr} not in [{MODBUS_DEVICE_ADDR_MIN}, {MODBUS_DEVICE_ADDR_MAX}]")
            return False
            
        if function_code != MODBUS_FUNCTION_CODE_READ:
            _LOGGER.debug(f"不支持的功能码: 0x{function_code:02X}, 期望: 0x{MODBUS_FUNCTION_CODE_READ:02X}")
            return False
        
        # 验证CRC校验
        if len(data) >= 4:
            received_crc = int.from_bytes(data[-2:], 'little')
            calculated_crc = self._calculate_crc16(data[:-2])
            
            _LOGGER.debug(f"CRC校验: 接收=0x{received_crc:04X}, 计算=0x{calculated_crc:04X}")
            
            if received_crc != calculated_crc:
                _LOGGER.debug(f"CRC校验失败")
                return False
            else:
                _LOGGER.debug(f"CRC校验通过")
        else:
            _LOGGER.debug("数据包长度不足，无法进行CRC校验")
            return False
            
        _LOGGER.debug("ModBus格式验证通过")
        return True
    
    def _parse_modbus_response(self, data: bytes) -> str:
        """解析ModBus读寄存器响应"""
        device_addr, function_code, data_length = data[0], data[1], data[2]
        
        _LOGGER.debug(f"解析ModBus响应: 设备=0x{device_addr:02X}, 功能码=0x{function_code:02X}, 数据长度={data_length}")
        
        if function_code != MODBUS_FUNCTION_CODE_READ:
            raise ValueError(f"不支持的功能码: 0x{function_code:02X}")
            
        if data_length < 2:
            raise ValueError(f"数据长度不足: {data_length} < 2")
        
        if len(data) < 3 + data_length:
            raise ValueError(f"数据包长度不足: {len(data)} < {3 + data_length}")
        
        # 提取温度寄存器数据（前2字节）
        register_data = data[3:5]
        temp_raw = int.from_bytes(register_data, 'big')
        
        _LOGGER.debug(f"提取温度数据: 寄存器={register_data.hex()}, 原始值=0x{temp_raw:04X} ({temp_raw})")
        
        return self._build_temperature_json(temp_raw)
    
    def _build_temperature_json(self, temp_raw: int) -> str:
        """构建温度数据的JSON格式"""
        _LOGGER.debug(f"构建温度JSON，原始值: 0x{temp_raw:04X} ({temp_raw})")
        
        # 处理负温度的补码形式
        temp_signed = temp_raw - 65536 if temp_raw > 32767 else temp_raw
        temp_celsius = temp_signed / TEMPERATURE_SCALE
        temp_fahrenheit = temp_celsius * 9/5 + 32
        
        _LOGGER.debug(f"温度转换: 有符号值={temp_signed}, 摄氏度={temp_celsius:.2f}, 华氏度={temp_fahrenheit:.2f}")
        
        # 判断温度状态
        status = "normal" if TEMPERATURE_MIN <= temp_celsius <= TEMPERATURE_MAX else "error"
        _LOGGER.debug(f"温度状态: {status} (范围: {TEMPERATURE_MIN}°C ~ {TEMPERATURE_MAX}°C)")
        
        # 构建温度数据
        temp_data = {
            "device_type": "18B20",
            "temperature": {
                "raw_value": temp_raw,
                "signed_value": temp_signed,
                "celsius": temp_celsius,
                "fahrenheit": temp_fahrenheit,
                "status": status
            },
            "timestamp": datetime.now().isoformat()
        }
        
        # 添加错误信息（如果有）
        error_message = ERROR_CODES.get(temp_raw)
        if error_message:
            temp_data["temperature"]["error_message"] = error_message
            temp_data["temperature"]["status"] = "error"
            _LOGGER.warning(f"温度传感器错误: 0x{temp_raw:04X} -> {error_message}")
        
        result_json = json.dumps(temp_data)
        _LOGGER.debug(f"生成温度JSON: {result_json}")
        
        return result_json
    
    def _calculate_crc16(self, data: bytes) -> int:
        """计算ModBus CRC16校验码"""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        return crc

