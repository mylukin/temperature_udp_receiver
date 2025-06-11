import asyncio
import json
import logging
import socket
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.exceptions import ConfigEntryNotReady

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
    """设置集成入口点 - 实现最佳实践的资源管理"""
    _LOGGER.info("正在设置 Temperature UDP Receiver 集成")
    
    # 初始化域数据结构
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    
    port = entry.data.get("port", 8889)
    entry_id = entry.entry_id
    
    try:
        # 检查并清理已存在的实例
        await _cleanup_existing_instance(hass, entry_id, port)
        
        # 检查端口可用性
        _LOGGER.debug(f"检查端口 {port} 可用性...")
        if not await _check_port_available(port):
            _LOGGER.error(f"端口 {port} 被占用，无法启动服务")
            raise ConfigEntryNotReady(f"端口 {port} 不可用")
        _LOGGER.debug(f"端口 {port} 检查通过")
        
        # 创建并启动UDP服务器
        udp_server = UDPTempServer(hass, port)
        await udp_server.start()
        
        # 保存服务器实例
        hass.data[DOMAIN][entry_id] = {
            "server": udp_server,
            "port": port,
            "entry": entry
        }
        
        # 注册服务
        await _register_services(hass, udp_server)
        
        # 设置传感器平台
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
        _LOGGER.info(f"Temperature UDP Receiver 设置完成，端口: {port}")
        return True
        
    except ConfigEntryNotReady:
        # 重新抛出ConfigEntryNotReady异常
        raise
    except Exception as e:
        _LOGGER.error(f"设置 Temperature UDP Receiver 失败: {e}")
        # 确保清理部分创建的资源
        await _cleanup_failed_setup(hass, entry_id)
        raise ConfigEntryNotReady(f"设置失败: {e}")

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置条目 - 确保完全清理资源"""
    entry_id = entry.entry_id
    _LOGGER.info(f"开始卸载 Temperature UDP Receiver (entry_id: {entry_id})")
    
    try:
        # 获取并清理服务器实例
        server_data = hass.data[DOMAIN].get(entry_id)
        if server_data:
            udp_server = server_data.get("server")
            if udp_server:
                await udp_server.stop()
                _LOGGER.debug("UDP服务器已停止")
            
            # 从数据字典中移除
            hass.data[DOMAIN].pop(entry_id, None)
        
        # 移除服务（只在没有其他实例时）
        if not hass.data[DOMAIN]:  # 如果没有其他实例了
            if hass.services.has_service(DOMAIN, "get_device_status"):
                hass.services.async_remove(DOMAIN, "get_device_status")
                _LOGGER.debug("已移除设备状态服务")
        
        # 卸载平台
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        
        if unload_ok:
            _LOGGER.info("Temperature UDP Receiver 已成功卸载")
        else:
            _LOGGER.warning("Temperature UDP Receiver 卸载过程中出现警告")
            
        return unload_ok
        
    except Exception as e:
        _LOGGER.error(f"卸载 Temperature UDP Receiver 失败: {e}")
        return False

# ================== 资源管理辅助函数 ==================

async def _cleanup_existing_instance(hass: HomeAssistant, entry_id: str, port: int) -> None:
    """清理已存在的实例"""
    try:
        # 检查是否有相同entry_id的实例
        existing_data = hass.data.get(DOMAIN, {}).get(entry_id)
        if existing_data:
            _LOGGER.warning(f"发现已存在的实例 (entry_id: {entry_id})，正在清理...")
            existing_server = existing_data.get("server")
            if existing_server:
                await existing_server.stop()
            hass.data[DOMAIN].pop(entry_id, None)
            _LOGGER.info("已清理旧实例")
        
        # 检查是否有相同端口的实例
        for existing_entry_id, data in list(hass.data.get(DOMAIN, {}).items()):
            if data.get("port") == port and existing_entry_id != entry_id:
                _LOGGER.warning(f"发现端口 {port} 被其他实例占用 (entry_id: {existing_entry_id})，正在清理...")
                existing_server = data.get("server")
                if existing_server:
                    await existing_server.stop()
                hass.data[DOMAIN].pop(existing_entry_id, None)
                _LOGGER.info(f"已清理端口冲突的实例: {existing_entry_id}")
                
    except Exception as e:
        _LOGGER.error(f"清理已存在实例时出错: {e}")

async def _check_port_available(port: int) -> bool:
    """检查端口是否可用"""
    sock = None
    try:
        # 尝试绑定UDP端口
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # 尝试设置 SO_REUSEPORT（如果可用）
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            # SO_REUSEPORT 在某些系统上不可用，忽略
            pass
        
        sock.bind(('0.0.0.0', port))
        _LOGGER.debug(f"端口 {port} 可用")
        return True
        
    except OSError as e:
        _LOGGER.debug(f"端口 {port} 不可用: {e}")
        return False
    except Exception as e:
        _LOGGER.error(f"检查端口可用性时出错: {e}")
        return False
    finally:
        if sock:
            try:
                sock.close()
            except:
                pass

async def _cleanup_failed_setup(hass: HomeAssistant, entry_id: str) -> None:
    """清理失败的设置过程中创建的资源"""
    try:
        if DOMAIN in hass.data and entry_id in hass.data[DOMAIN]:
            server_data = hass.data[DOMAIN].get(entry_id)
            if server_data and "server" in server_data:
                await server_data["server"].stop()
            hass.data[DOMAIN].pop(entry_id, None)
            _LOGGER.debug(f"已清理失败设置的资源: {entry_id}")
    except Exception as e:
        _LOGGER.error(f"清理失败设置资源时出错: {e}")

# ================== 服务注册 ==================

async def _register_services(hass: HomeAssistant, udp_server: 'UDPTempServer') -> None:
    """注册Home Assistant服务"""
    
    # 检查服务是否已注册（支持多实例）
    if hass.services.has_service(DOMAIN, "get_device_status"):
        _LOGGER.debug("设备状态服务已存在，跳过注册")
        return
    
    async def get_device_status(call):
        """获取设备状态服务"""
        try:
            # 获取所有实例的状态
            all_status = {}
            for entry_id, data in hass.data.get(DOMAIN, {}).items():
                server = data.get("server")
                if server:
                    port = data.get("port", "未知")
                    status = server.get_client_status()
                    all_status[f"端口{port}"] = status
            
            message = _format_device_status_message(all_status)
            
            await hass.services.async_call(
                'persistent_notification', 'create',
                {'message': message, 'title': 'Temperature UDP Receiver 设备状态'}
            )
            _LOGGER.debug(f"设备状态查询结果: {len(all_status)} 个端口")
        except Exception as e:
            _LOGGER.error(f"获取设备状态失败: {e}")
    
    hass.services.async_register(DOMAIN, "get_device_status", get_device_status)
    _LOGGER.debug("已注册设备状态服务")

def _format_device_status_message(all_status: Dict[str, Dict[str, Any]]) -> str:
    """格式化设备状态消息"""
    if not all_status:
        return "设备状态:\n暂无设备连接"
    
    message = "设备状态:\n"
    for port_info, status in all_status.items():
        message += f"\n{port_info}:\n"
        if not status:
            message += "  暂无设备连接\n"
        else:
            for addr, info in status.items():
                online_status = "在线" if info['online'] else f"离线({info['offline_duration']:.0f}秒)"
                device_type = info.get('type', '未知')
                message += f"  设备 {addr}: {online_status} ({device_type})\n"
    
    return message

# ================== UDP服务器 ==================

class UDPTempServer:
    """UDP温度传感器服务器 - 增强版本，支持优雅重启"""
    
    def __init__(self, hass: HomeAssistant, port: int):
        self.hass = hass
        self.port = port
        self.transport = None
        self.protocol = None
        self._running = False
        self._start_lock = asyncio.Lock()
        
    async def start(self) -> None:
        """启动UDP服务器，带重试机制"""
        async with self._start_lock:
            if self._running:
                _LOGGER.warning(f"UDP服务器已在端口 {self.port} 运行")
                return
                
            max_retries = 3
            retry_delay = 1.0
            
            for attempt in range(max_retries):
                sock = None
                try:
                    _LOGGER.debug(f"尝试启动UDP服务器，端口: {self.port} (尝试 {attempt + 1}/{max_retries})")
                    
                    # 创建UDP套接字并设置重用选项
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    
                    # 在某些系统上需要设置 SO_REUSEPORT
                    try:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                    except (AttributeError, OSError):
                        # SO_REUSEPORT 在某些系统上不可用，忽略
                        pass
                    
                    # 绑定到指定端口
                    sock.bind(('0.0.0.0', self.port))
                    
                    # 使用预先配置的套接字创建数据报端点
                    loop = asyncio.get_event_loop()
                    self.transport, self.protocol = await loop.create_datagram_endpoint(
                        lambda: UDPProtocol(self.hass),
                        sock=sock
                    )
                    
                    self._running = True
                    _LOGGER.info(f"UDP服务器已启动，监听端口: {self.port}")
                    return
                    
                except OSError as e:
                    if sock:
                        try:
                            sock.close()
                        except:
                            pass
                    
                    error_msg = str(e).lower()
                    if any(msg in error_msg for msg in ["address already in use", "only one usage", "permission denied"]):
                        _LOGGER.warning(f"端口 {self.port} 启动失败: {e} (尝试 {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            _LOGGER.debug(f"等待 {retry_delay} 秒后重试...")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # 指数退避
                        else:
                            raise ConfigEntryNotReady(f"端口 {self.port} 无法启动: {e}")
                    else:
                        _LOGGER.error(f"UDP服务器启动失败 (非端口问题): {e}")
                        raise
                except Exception as e:
                    if sock:
                        try:
                            sock.close()
                        except:
                            pass
                    _LOGGER.error(f"启动UDP服务器失败: {e}")
                    if attempt == max_retries - 1:
                        raise ConfigEntryNotReady(f"UDP服务器启动失败: {e}")
                    _LOGGER.debug(f"等待 {retry_delay} 秒后重试...")
                    await asyncio.sleep(retry_delay)
        
    async def stop(self) -> None:
        """停止UDP服务器，确保完全清理"""
        async with self._start_lock:
            if not self._running:
                _LOGGER.debug("UDP服务器未运行，无需停止")
                return
                
            try:
                if self.transport:
                    _LOGGER.debug("正在关闭UDP传输...")
                    self.transport.close()
                    
                    # 等待传输完全关闭
                    max_wait = 5.0  # 最多等待5秒
                    wait_time = 0.1
                    total_waited = 0
                    
                    while not self.transport.is_closing() and total_waited < max_wait:
                        await asyncio.sleep(wait_time)
                        total_waited += wait_time
                    
                    if total_waited >= max_wait:
                        _LOGGER.warning("UDP传输关闭超时")
                    else:
                        _LOGGER.debug(f"UDP传输已关闭 (等待时间: {total_waited:.2f}s)")
                
                self.transport = None
                self.protocol = None
                self._running = False
                
                # 额外等待，确保端口释放
                await asyncio.sleep(0.5)
                
                _LOGGER.info(f"UDP服务器已停止，端口 {self.port} 已释放")
                
            except Exception as e:
                _LOGGER.error(f"停止UDP服务器时出错: {e}")
                # 即使出错也要标记为已停止
                self._running = False
                self.transport = None
                self.protocol = None
    
    def get_client_status(self) -> Dict[str, Any]:
        """获取客户端状态"""
        if not self._running or not self.protocol:
            return {}
        return self.protocol.get_client_status()
    
    @property
    def is_running(self) -> bool:
        """检查服务器是否正在运行"""
        return self._running and self.transport is not None

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

