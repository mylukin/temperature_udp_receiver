from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import UnitOfTemperature
from homeassistant.util import dt as dt_util
import logging
import asyncio
from typing import Dict, Any, Optional, Union

from .const import (
    DOMAIN, TEMPERATURE_SCALE, TEMPERATURE_MIN, TEMPERATURE_MAX, ERROR_CODES
)

_LOGGER = logging.getLogger(__name__)

# ================== 传感器设置 ==================

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry, 
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置传感器实体"""
    try:
        sensors = [
            TemperatureSensor(hass, entry.entry_id),        # 温度传感器（摄氏度）
            TemperatureFSensor(hass, entry.entry_id),       # 温度传感器（华氏度）
            RawValueSensor(hass, entry.entry_id),           # 原始数值传感器
            DeviceStatusSensor(hass, entry.entry_id),       # 设备状态传感器
            LastUpdateSensor(hass, entry.entry_id),         # 最后更新传感器
        ]
        
        async_add_entities(sensors, True)
        _LOGGER.info(f"已创建 {len(sensors)} 个温度传感器实体")
        
    except Exception as e:
        _LOGGER.error(f"设置传感器实体失败: {e}")

# ================== 基础传感器类 ==================

class BaseTempSensor(SensorEntity):
    """温度传感器基类"""
    
    def __init__(self, hass: HomeAssistant, entry_id: str, sensor_type: str, 
                 name: str, unique_id: str, icon: str = "mdi:thermometer"):
        self.hass = hass
        self.entry_id = entry_id
        self.sensor_type = sensor_type
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{unique_id}_{entry_id}"
        self._attr_icon = icon
        self._attr_native_value = None
        self._attr_should_poll = False
        
    async def async_added_to_hass(self) -> None:
        """注册事件监听"""
        await super().async_added_to_hass()
        
        @callback
        def handle_temp_event(event):
            try:
                if not self.entity_id:
                    _LOGGER.debug(f"{self.sensor_type}传感器实体ID尚未设置，跳过更新")
                    return
                
                if event.data.get('event_type') == 'temperature_data_received':
                    self._handle_temp_data(event.data.get('temperature_data', {}))
                    
            except Exception as e:
                _LOGGER.error(f"{self.sensor_type}传感器事件处理失败: {e}")
        
        self.async_on_remove(
            self.hass.bus.async_listen(f'{DOMAIN}_event', handle_temp_event)
        )
    
    def _handle_temp_data(self, temp_data: Dict[str, Any]) -> None:
        """处理温度数据 - 子类需要重写此方法"""
        raise NotImplementedError("子类必须实现 _handle_temp_data 方法")
    
    def _update_state(self, value: Union[int, float, str], log_message: str = "") -> None:
        """更新传感器状态"""
        self._attr_native_value = value
        self.async_write_ha_state()
        
        if log_message:
            _LOGGER.info(f"{self.sensor_type}: {log_message}")

# ================== 温度传感器实体 ==================

class TemperatureSensor(BaseTempSensor):
    """温度传感器（摄氏度）"""
    
    def __init__(self, hass: HomeAssistant, entry_id: str):
        super().__init__(
            hass, entry_id, "温度", "Temp UDP Temperature", "temp_udp_temperature", "mdi:thermometer"
        )
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_suggested_unit_of_measurement = UnitOfTemperature.CELSIUS
        
    def _handle_temp_data(self, temp_data: Dict[str, Any]) -> None:
        if 'celsius' in temp_data:
            temp_celsius = temp_data['celsius']
            status = temp_data.get('status', 'unknown')
            self._update_state(temp_celsius, f"温度更新为 {temp_celsius:.1f}°C, 状态: {status}")
    
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        if self._attr_native_value is None:
            return {}
            
        temp_c = self._attr_native_value
        temp_f = temp_c * 9/5 + 32
        
        # 判断温度状态
        is_normal = TEMPERATURE_MIN <= temp_c <= TEMPERATURE_MAX
        temp_status = "正常" if is_normal else "异常"
        temp_level = "normal" if is_normal else "error"
        
        return {
            "temperature_celsius": temp_c,
            "temperature_fahrenheit": round(temp_f, 2),
            "temperature_status": temp_status,
            "temperature_level": temp_level,
            "valid_range": f"{TEMPERATURE_MIN}°C ~ {TEMPERATURE_MAX}°C",
            "description": "DS18B20温度传感器数据"
        }

class TemperatureFSensor(BaseTempSensor):
    """温度传感器（华氏度）"""
    
    def __init__(self, hass: HomeAssistant, entry_id: str):
        super().__init__(
            hass, entry_id, "温度(华氏)", "Temp UDP Temperature F", "temp_udp_temperature_f", "mdi:thermometer"
        )
        self._attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_suggested_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
        
    def _handle_temp_data(self, temp_data: Dict[str, Any]) -> None:
        if 'fahrenheit' in temp_data:
            temp_fahrenheit = temp_data['fahrenheit']
            status = temp_data.get('status', 'unknown')
            self._update_state(temp_fahrenheit, f"温度更新为 {temp_fahrenheit:.1f}°F, 状态: {status}")
    
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        if self._attr_native_value is None:
            return {}
            
        temp_f = self._attr_native_value
        temp_c = (temp_f - 32) * 5/9
        
        return {
            "temperature_fahrenheit": temp_f,
            "temperature_celsius": round(temp_c, 2),
            "description": "DS18B20温度传感器数据（华氏度）"
        }

class RawValueSensor(BaseTempSensor):
    """原始数值传感器"""
    
    def __init__(self, hass: HomeAssistant, entry_id: str):
        super().__init__(
            hass, entry_id, "原始数值", "Temp UDP Raw Value", "temp_udp_raw_value", "mdi:numeric"
        )
        
    def _handle_temp_data(self, temp_data: Dict[str, Any]) -> None:
        if 'raw_value' in temp_data:
            raw_value = temp_data['raw_value']
            signed_value = temp_data.get('signed_value', raw_value)
            self._update_state(raw_value, f"原始数值更新为 {raw_value} (有符号: {signed_value})")
    
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        if self._attr_native_value is None:
            return {}
            
        raw_val = self._attr_native_value
        signed_val = raw_val - 65536 if raw_val > 32767 else raw_val
        
        return {
            "raw_value": raw_val,
            "signed_value": signed_val,
            "hex_value": f"0x{raw_val:04X}",
            "binary_value": format(raw_val, '016b'),
            "calculated_temp": round(signed_val / TEMPERATURE_SCALE, 2),
            "error_code": ERROR_CODES.get(raw_val, "无"),
            "description": "ModBus寄存器原始数值"
        }

# ================== 状态监控传感器 ==================

class DeviceStatusSensor(SensorEntity):
    """设备状态传感器"""
    
    def __init__(self, hass: HomeAssistant, entry_id: str):
        self.hass = hass
        self.entry_id = entry_id
        self._attr_name = "Temp UDP Device Status"
        self._attr_unique_id = f"{DOMAIN}_temp_udp_device_status_{entry_id}"
        self._attr_native_value = "等待连接"
        self._attr_should_poll = True
        self._attr_icon = "mdi:connection"
        self._last_activity = None
        self._offline_threshold = 10  # 离线阈值（秒）
        
    async def async_added_to_hass(self) -> None:
        """注册事件监听"""
        @callback
        def update_activity(event):
            try:
                self._last_activity = asyncio.get_event_loop().time()
                self._update_status_immediate()
            except Exception as e:
                _LOGGER.error(f"设备状态更新失败: {e}")
        
        self.async_on_remove(
            self.hass.bus.async_listen(f'{DOMAIN}_event', update_activity)
        )
        
    def _update_status_immediate(self) -> None:
        """立即更新状态为在线"""
        self._attr_native_value = "在线"
        self._attr_icon = "mdi:check-network"
        self.async_write_ha_state()
        _LOGGER.debug("设备状态更新为: 在线")
        
    async def async_update(self) -> None:
        """定期检查离线状态"""
        self._update_status()
        
    def _update_status(self) -> None:
        """更新设备状态"""
        try:
            if self._last_activity is None:
                self._attr_native_value = "等待连接"
                self._attr_icon = "mdi:connection"
            else:
                current_time = asyncio.get_event_loop().time()
                offline_duration = current_time - self._last_activity
                
                if offline_duration < self._offline_threshold:
                    self._attr_native_value = "在线"
                    self._attr_icon = "mdi:check-network"
                else:
                    minutes_offline = int(offline_duration // 60)
                    self._attr_native_value = f"离线 {minutes_offline}分钟"
                    self._attr_icon = "mdi:network-off"
            
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(f"状态更新失败: {e}")
        
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """返回额外状态属性"""
        base_attrs = {
            "offline_threshold_minutes": self._offline_threshold // 60,
            "device_type": "18B20温度传感器"
        }
        
        if self._last_activity is None:
            base_attrs.update({
                "last_activity": None,
                "status": "等待连接"
            })
        else:
            try:
                current_time = asyncio.get_event_loop().time()
                offline_duration = current_time - self._last_activity
                last_activity_dt = dt_util.utc_from_timestamp(self._last_activity).astimezone(dt_util.DEFAULT_TIME_ZONE)
                is_online = offline_duration < self._offline_threshold
                
                base_attrs.update({
                    "last_activity": last_activity_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "offline_duration_seconds": int(offline_duration),
                    "is_online": is_online,
                    "status": "在线" if is_online else "离线"
                })
            except Exception as e:
                _LOGGER.error(f"获取状态属性失败: {e}")
                
        return base_attrs

class LastUpdateSensor(BaseTempSensor):
    """最后更新时间传感器"""
    
    def __init__(self, hass: HomeAssistant, entry_id: str):
        super().__init__(
            hass, entry_id, "最后更新", "Temp UDP Last Update", "temp_udp_last_update", "mdi:clock-outline"
        )
        self._attr_native_value = "从未更新"
        self._attr_state_class = None
        self._attr_force_update = True
        
    def _handle_temp_data(self, temp_data: Dict[str, Any]) -> None:
        """处理更新时间"""
        current_time = dt_util.now().strftime("%Y-%m-%d %H:%M:%S")
        self._update_state(current_time, f"温度数据更新时间: {current_time}")
    
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """返回额外状态属性"""
        return {
            "update_source": "18B20温度传感器",
            "update_protocol": "ModBus-RTU over UDP",
            "description": "最后一次接收到温度数据的时间"
        }

