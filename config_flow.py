import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
import logging

from .const import DOMAIN, DEFAULT_CONFIG

_LOGGER = logging.getLogger(__name__)

class TempUDPConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Temperature UDP Receiver 配置流程"""
    
    VERSION = 1
    
    async def async_step_user(self, user_input=None):
        """处理用户配置步骤"""
        errors = {}
        
        if user_input is not None:
            try:
                # 验证端口号
                port = user_input.get("port", 8889)
                if not (1 <= port <= 65535):
                    errors["port"] = "端口号必须在1-65535范围内"
                else:
                    # 创建配置条目
                    await self.async_set_unique_id(f"temp_udp_{port}")
                    self._abort_if_unique_id_configured()
                    
                    _LOGGER.info(f"创建Temperature UDP Receiver配置，端口: {port}")
                    return self.async_create_entry(
                        title=f"Temperature UDP Receiver (端口: {port})",
                        data=user_input,
                    )
            except Exception as e:
                _LOGGER.error(f"配置验证失败: {e}")
                errors["base"] = "配置验证失败"
            
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Optional("port", default=DEFAULT_CONFIG["port"]): vol.All(
                    vol.Coerce(int), 
                    vol.Range(min=1, max=65535)
                ),
            }),
            errors=errors,
            description_placeholders={
                "port_info": f"UDP服务器监听端口，默认{DEFAULT_CONFIG['port']}"
            }
        )

