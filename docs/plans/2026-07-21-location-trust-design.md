# 通用可信定位设计

## 背景

Vantage 当前存在两条互不一致的定位链路：后台截图和照片通过 Windows
`Geolocator` 获取坐标，Dashboard 则通过浏览器 `navigator.geolocation`
把经纬度直接传给 AQI 接口。两条链路都丢弃了来源、精度和时间戳等可信度
信息；AQI 在没有前端坐标时还会回退到写死的上海交大闵行坐标。

这会把 Windows 手动默认位置、IP 粗定位或代理出口当成真实位置。软件不能
依赖任何预设城市，也不能通过某一台机器的工位位置解决公共版本的问题。

## 已确认目标

- 不依赖 Windows 默认位置或任何硬编码城市。
- 无法得到可信位置时，AQI 显示不可用，照片和截图不写 GPS EXIF。
- 不调用外部 IP 定位或反向地理编码服务，不增加隐私和网络依赖。
- Windows、macOS 和浏览器定位统一进入同一可信度判断。
- 保留 `VANTAGE_STATIC_LATITUDE` 和 `VANTAGE_STATIC_LONGITUDE` 作为用户明确
  配置的可选覆盖，但默认运行不依赖它们。
- 不改变照片、截图、AQI 之外的运行逻辑。

## 方案比较

### 方案一：元数据可信度门控（采用）

将定位统一表示为包含坐标、精度、来源、时间戳和远程来源标志的样本，经过
纯本地可信度解析后才能被业务使用。该方案无需知道用户在哪座城市，也不依赖
第三方服务。

### 方案二：Windows 与浏览器双源一致

双源相近可以提高置信度，但两者可能同时受同一 IP 或代理影响，而且没有
Windows 定位的系统无法使用。它只适合作为未来增强，不作为必需条件。

### 方案三：外部 IP 或地图服务复核

代理仍会污染 IP 定位，并带来隐私、API 和网络可用性问题，因此不采用。

## 架构

新增一个与平台无关的定位可信度模块，定义：

- `LocationSample`：原始纬度、经度、精度、采样时间、来源、是否远程。
- `LocationPurpose`：`AQI` 或 `EXIF`，对应不同精度要求。
- `LocationDecision`：`TRUSTED` 或 `UNKNOWN`，同时包含供日志和测试使用的
  原因码。
- `LocationTrustResolver`：校验样本并维护短期内最后一个可信样本，用于识别
  不可能的瞬时跳变；绝不把旧样本作为无新定位时的业务回退。

数据流如下：

```text
WinRT Geolocator / navigator.geolocation / explicit environment override
                              |
                              v
                       LocationSample
                              |
                              v
                    LocationTrustResolver
                     /                 \
              TRUSTED                 UNKNOWN
              /     \                 /      \
            AQI     EXIF         AQI unavailable  no GPS EXIF
```

## 可信度规则

所有样本首先必须满足：

- 经纬度和精度均为有限数值，经纬度范围合法，精度为正数。
- 采集时间戳可解析，不能明显来自未来，并且足够新鲜。WinRT 使用本机
  `Geocoordinate.timestamp`；不使用可能与本机时钟无关的
  `position_source_timestamp` 做新鲜度判断。
- `is_remote_source` 不为真。

来源分级：

- 显式配置、卫星、Wi-Fi：允许进入用途精度判断。
- 蜂窝网络：只允许用于 AQI，不用于 EXIF。
- 浏览器：因没有标准来源字段，仅允许足够高精度的样本用于 AQI；不能仅凭
  浏览器声明的精度写入 EXIF。
- IP 地址、Windows 手动默认位置、未知、模糊位置：一律判为 `UNKNOWN`，
  即使它们宣称精度很高。

用途规则：

- EXIF 使用 100 米和 60 秒的严格门槛，只写入可以代表实际拍摄位置的
  元数据丰富定位。
- AQI 使用略宽的精度门槛，但仍不能接受 IP、默认位置或代理来源。
- 同一运行期内若新样本在极短时间产生不可能的跨城跳变，则判为
  `UNKNOWN`；速度使用扣除前后精度半径后的距离计算，且只比较时间严格
  递增的样本。经过较长无样本间隔后重置连续性比较，允许用户正常旅行。

阈值集中定义为具名常量，并通过边界测试固定语义，不增加用户设置。

## 平台接入

### Windows 后端

`get_location.py` 读取 WinRT `Geocoordinate` 的 `accuracy`、`timestamp`、
`position_source` 和 `is_remote_source`，构造样本后交给可信度解析器。现有
显式静态环境变量构造 `configured` 来源样本。旧版 Windows 若不提供
`is_remote_source`，平台适配器按无法证明非远程处理并降级为 `UNKNOWN`。

### 浏览器和 macOS

Dashboard 将 `position.coords.accuracy` 和 `position.timestamp` 与经纬度一起
发送给后端，并标记来源为 `browser`。后端不再相信只有经纬度的请求。

### AQI

删除上海交大闵行硬编码回退。坐标可信时请求 Open-Meteo；不可信或缺失时
直接返回现有结构的不可用结果，`lat` 和 `lon` 为 `null`，不发起外部 AQI
请求。

### 照片和截图

只有 EXIF 用途判定为可信的样本才进入现有保存函数。`UNKNOWN` 延续当前
“保存图片但跳过 GPS EXIF”的行为。

## 错误处理与日志

- 定位权限拒绝、超时、平台 API 不可用和不可信样本均正常降级为
  `UNKNOWN`，不抛出到采集主循环。
- 日志记录来源、精度和拒绝原因，不记录不必要的完整坐标。
- AQI 上游超时继续返回 `status=unavailable`，HTTP 响应结构保持稳定。

## 测试

按 TDD 增加以下覆盖：

- 合法的卫星和 Wi-Fi 样本按用途被接受；高精度浏览器样本只用于 AQI。
- Windows `DEFAULT`、IP、远程、模糊、未知来源即使精度看似很高也被拒绝。
- 非有限、越界、非正精度、陈旧和未来样本被拒绝。
- 蜂窝网络可用于 AQI 但不能写 EXIF。
- 短时间跨城跳变被拒绝，长时间间隔后允许重新建立可信基线。
- AQI 不再回退上海；不可信请求不调用 Open-Meteo。
- Dashboard 发送经纬度、精度和时间戳。
- 定位不可用时图片仍保存但不写 GPS EXIF。
- 现有 Python、前端、打包和安装版健康检查继续通过。
