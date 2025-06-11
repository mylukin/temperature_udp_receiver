# Temperature UDP Receiver

[![GitHub stars](https://img.shields.io/github/stars/mylukin/temperature_udp_receiver)](https://github.com/mylukin/temperature_udp_receiver/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/mylukin/temperature_udp_receiver)](https://github.com/mylukin/temperature_udp_receiver/network)
[![GitHub issues](https://img.shields.io/github/issues/mylukin/temperature_udp_receiver)](https://github.com/mylukin/temperature_udp_receiver/issues)
[![License](https://img.shields.io/github/license/mylukin/temperature_udp_receiver)](https://github.com/mylukin/temperature_udp_receiver/blob/main/LICENSE)

一个用于 Home Assistant 的自定义集成，通过 UDP 协议接收 18B20 温度传感器数据，支持 ModBus-RTU over UDP 协议。

## ✨ 功能特性

### 🌡️ 温度监测
- **温度传感器（摄氏度）** - 实时温度监测，单位 °C
- **温度传感器（华氏度）** - 实时温度监测，单位 °F  
- **原始数值传感器** - 显示 ModBus 寄存器原始数值
- **设备状态传感器** - 实时监控设备在线/离线状态
- **最后更新传感器** - 显示数据最后更新时间

### 📡 协议支持
- **ModBus-RTU over UDP** - 支持标准 ModBus 协议通过 UDP 传输
- **18B20 温度传感器** - 专为 DS18B20 数字温度传感器优化
- **多编码支持** - 自动检测 UTF-8、GBK、GB2312 等编码
- **心跳包检测** - 支持设备心跳包和注册包

### 🔧 智能特性
- **温度范围检测** - 自动检测超出 DS18B20 测量范围（-55°C ~ +125°C）
- **错误状态识别** - 识别传感器断开连接和初始化失败
- **实时事件系统** - 基于 Home Assistant 事件的实时数据更新
- **离线检测** - 10秒离线检测阈值

## 🚀 安装

### 方法一：HACS 安装（推荐）

1. 确保您已安装 [HACS](https://hacs.xyz/)
2. 在 HACS 中搜索 "Temperature UDP Receiver"
3. 点击安装并重启 Home Assistant

### 方法二：手动安装

1. 将代码复制到 `custom_components` 目录：
```bash
cd /config/custom_components/
cp -r temperature_udp_receiver ./
```

2. 重启 Home Assistant

3. 在 Home Assistant 中添加集成：
   - 进入 **设置** → **设备与服务**
   - 点击 **添加集成**
   - 搜索 "Temperature UDP Receiver"

## ⚙️ 配置

### 基本设置
- **UDP 端口**：默认 8889（可自定义）
- **设备地址**：支持 ModBus 地址 0-247
- **数据格式**：ModBus 读寄存器响应（功能码 0x03）

### 设备连接
确保温度传感器设备配置为：
- 目标 IP：Home Assistant 服务器 IP
- 目标端口：8889（或您配置的端口）
- 协议：ModBus-RTU over UDP

## 📊 传感器列表

| 传感器名称 | 实体ID | 单位 | 描述 |
|-----------|--------|------|------|
| Temp UDP Temperature | `sensor.temp_udp_temperature` | °C | 摄氏度温度 |
| Temp UDP Temperature F | `sensor.temp_udp_temperature_f` | °F | 华氏度温度 |
| Temp UDP Raw Value | `sensor.temp_udp_raw_value` | - | ModBus 原始数值 |
| Temp UDP Device Status | `sensor.temp_udp_device_status` | - | 设备连接状态 |
| Temp UDP Last Update | `sensor.temp_udp_last_update` | - | 最后更新时间 |

### 温度传感器属性
- `temperature_celsius`: 摄氏度值
- `temperature_fahrenheit`: 华氏度值  
- `temperature_status`: 温度状态（正常/异常）
- `valid_range`: 有效测量范围

### 原始数值传感器属性
- `raw_value`: 原始数值
- `signed_value`: 有符号数值
- `hex_value`: 十六进制显示
- `calculated_temp`: 计算后的温度
- `error_code`: 错误代码（如有）

## 📡 数据格式

### ModBus 数据包结构
```
字节 0: 设备地址 (0-247)
字节 1: 功能码 (0x03)  
字节 2: 数据长度 (≥2)
字节 3-4: 温度数据 (16位，大端序)
字节 N-1 到 N: CRC16 校验 (小端序)
```

### 温度数据转换
- **原始值** → **实际温度** = 原始值 ÷ 10
- **负温度处理**：自动处理 16位补码形式
- **范围检查**：-55.0°C ~ +125.0°C

## 🛠️ 服务

### `temp_udp_receiver.get_device_status`
获取所有连接设备的状态信息
```yaml
service: temp_udp_receiver.get_device_status
```

## 📈 自动化示例

### 温度告警
```yaml
automation:
  - alias: "高温告警"
    trigger:
      platform: numeric_state
      entity_id: sensor.temp_udp_temperature
      above: 30
    action:
      service: notify.mobile_app_your_phone
      data:
        message: "温度过高: {{ states('sensor.temp_udp_temperature') }}°C"
```

### 设备离线通知
```yaml
automation:
  - alias: "温度传感器离线"
    trigger:
      platform: state
      entity_id: sensor.temp_udp_device_status
      to: "离线"
    action:
      service: persistent_notification.create
      data:
        message: "温度传感器离线，请检查连接"
```

## 🔧 故障排除

### 常见问题
1. **数据不更新**
   - 检查 UDP 端口 8889 是否被占用
   - 确认设备 IP 和端口配置
   - 检查 ModBus 数据格式

2. **温度显示异常**
   - 检查是否超出 DS18B20 测量范围
   - 查看原始数值传感器的错误代码
   - 确认 CRC 校验是否正确

3. **设备显示离线**
   - 检查网络连接
   - 确认 UDP 数据包是否到达
   - 查看 Home Assistant 日志

### 调试日志
```yaml
# configuration.yaml
logger:
  logs:
    custom_components.temp_udp_receiver: debug
```

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 本项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📄 许可证

本项目基于 MIT 许可证开源 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🙏 致谢

- 感谢 Home Assistant 社区的支持
- 感谢所有贡献者的努力

---

**⭐ 如果这个项目对你有帮助，请给个 Star！** 

**支持的传感器**: DS18B20 数字温度传感器  
**协议**: ModBus-RTU over UDP  
**默认端口**: 8889 