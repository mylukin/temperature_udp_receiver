"""Temperature UDP Receiver 常量定义"""

# 集成域名
DOMAIN = "temp_udp_receiver"

# 平台列表
PLATFORMS = ["sensor"]

# ModBus 协议配置 - 18B20温度传感器
MODBUS_DEVICE_ADDR_MIN = 0
MODBUS_DEVICE_ADDR_MAX = 247
MODBUS_FUNCTION_CODE_READ = 0x03  # 读保持寄存器
MODBUS_EXPECTED_LENGTH = 13  # 3字节头部 + 8字节数据 + 2字节CRC

# 客户端状态配置
OFFLINE_THRESHOLD = 10  # 10s离线阈值 (秒)

# 温度数据转换配置
TEMPERATURE_SCALE = 10.0  # 温度除数因子（温度值需要除以10）
TEMPERATURE_MIN = -55.0   # DS18B20最小温度
TEMPERATURE_MAX = 125.0   # DS18B20最大温度

# 错误代码映射
ERROR_CODES = {
    0x7FFF: "传感器断开连接",
    0x0550: "传感器初始化失败"
}

# 文本数据包指示符
HEARTBEAT_INDICATORS = [
    'heartbeat', 'ping', 'alive', 'keep-alive', 'heart_beat', 'keepalive'
]

REGISTRATION_INDICATORS = [
    'register', 'registration', 'connect', 'login', 'device_info', 'client_info'
]

# 默认配置
DEFAULT_CONFIG = {
    'port': 8889
} 