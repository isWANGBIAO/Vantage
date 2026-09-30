# Vantage 原生 macOS 客户端

完整应用包要求 macOS 15+，SwiftUI + AppKit + CPU/CoreGraphics 图表；没有 WebView、Electron 或 React 运行时。复用同一个 `/api/v1` Python 后端。

界面源码 Swift Package 的 API target 为 macOS 14；Python 运行时与完整 `.app` 按 macOS 15 构建和验收（Apple Silicon / Intel），`LSMinimumSystemVersion` 为 15.0。尚未验证整包在 macOS 14 上运行。

## 构建和启动

在仓库根目录：

```sh
swift test --package-path src/native/macos
swift build --package-path src/native/macos
VANTAGE_PYTHON="$PWD/.venv/bin/python" VANTAGE_PROJECT_ROOT="$PWD" \
  swift run --package-path src/native/macos VantageMac
```

源码模式也将个人数据写入系统 Application Support/Vantage（或明确的 `VANTAGE_DATA_DIR`），不写入仓库。也可以先启动后端，再使用 `VANTAGE_BACKEND_URL` 连接。地址只允许 loopback HTTP(S)，拒绝重定向与 URL 凭据。HTTPS/路径前缀代理不由客户端启动。

打包需先按仓库构建脚本生成本机架构的完整 PyInstaller onedir 后端：

```sh
src/native/macos/scripts/package.sh \
  --backend-runtime build/backend-runtime/stage/VantageBackend \
  --output build/native/macos
open build/native/macos/Vantage.app
```

脚本严格要求真实后端 runtime，将其整体复制到 `Contents/Resources/backend-runtime/VantageBackend`，可执行文件为 `Contents/MacOS/Vantage`。仅本机 ad-hoc 签名，不执行公证、发布或读取签名账号。Apple Silicon 与 Intel 必须分别构建匹配架构的客户端/后端。

## 功能与边界

- 本机引导、provider/语音/图像设置、模型发现、采样参数和模型 profile；凭据 SecureField/write-only，不写 UserDefaults
- 仪表盘、隐私默认隐藏的媒体预览、AQI/专注状态、项目进度/提交、财务工作表/趋势/预测/采购建议隐藏与恢复
- CPU/CoreGraphics 原生绘图展示后端 ECharts 数据契约，包括 time/category、缺失段、stack、pie/radar 和分轴；鼠标/键盘选点、缩放和平移；原始工作表/图表数据可筛选。绘图使用真实 NSView 的 CPU draw，不要求 Metal 设备
- 共享后台行动计划任务发现、提交、重连、取消、去重与截断处理；不会以 EOF 或部分正文判断成功
- 权威聊天上下文、明确完成流、清空会话、模型选择、语音录制/转录；录音临时文件自动清理
- 面部历史、分析进度、导出、显式相机预览、AVFoundation→JPEG 后端桥；未授权不自动启动设备
- 用量、可筛选实时日志、原生菜单/菜单栏、登录启动项、系统 locale、文件选择、复制与主题
- 宿主只退出自己启动的后端；已有外部后端保持独立。关闭窗口保留菜单栏，Quit 终止本应用拥有的后台进程

聊天流不是可恢复任务：中断后重新读取后端上下文，不自动重发用户消息。行动计划任务可跨页面继续，显式取消才取消生成；整个宿主退出时，会关闭它拥有的后端。

## 验证

Core tests 覆盖 loopback 验证/地址优先级/路径前缀、类型解析、真实 NDJSON 前缀、UTF-8 分片/末行/上限、去重/截断、完整结果门槛、JPEG 边界、图表格式和 HTTP 写入不重试/intent/媒体路径。

真实 native-window smoke 入口：

```sh
VANTAGE_BACKEND_URL=http://127.0.0.1:PORT \
  build/native/macos/Vantage.app/Contents/MacOS/Vantage \
  --smoke-test /tmp/vantage-macos-smoke.json
```

只连接隔离合成 fixture，不申请硬件/登录项权限；逐页等待 API 完成，保存 SwiftUI/AppKit 窗口截图并输出 `success/pages/errors`。这不替代相机、麦克风、登录项、关闭/重开、DPI、真实数据和安装后验收。Linux 工作区不具备 Swift/Xcode，不能据静态检查宣称 macOS 编译或 UI 已通过；以 macOS CI 的实际结果为准。

系统 API 参考：[MenuBarExtra](https://developer.apple.com/documentation/swiftui/menubarextra)、[SMAppService.register](https://developer.apple.com/documentation/servicemanagement/smappservice/register())。
