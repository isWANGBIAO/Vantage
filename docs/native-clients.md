# 原生桌面客户端

Vantage 提供三个使用系统控件的客户端，共享唯一 Python/FastAPI 后端与 `/api/v1` 契约。

- Windows：[`src/native/windows`](../src/native/windows/README.md)，WinUI 3 / Windows App SDK，.NET 8
- macOS：[`src/native/macos`](../src/native/macos/README.md)，SwiftUI / AppKit / CoreGraphics，macOS 14+
- Linux：[`src/native/linux`](../src/native/linux/README.md)，GTK4 / PyGObject / Cairo

这些客户端不装载 WebView、React 页面或 Electron runtime。原有 React/Electron 客户端继续使用同一后端；原生界面不复制配置持久化、provider 路由、模型执行、工作簿分析或自动调度规则。

## 功能范围

三端采用各自的原生导航、对话框、表格、图表、文本与媒体控件，覆盖：

1. 首次引导、语言/主题、provider 与语音/图像配置、模型发现和高级参数
2. 仪表盘：系统资源、久坐/专注、空气质量、显式展开的照片/截图与相机预览
3. 行动计划：保存结果、Markdown、模型参数、创建/加入任务、增量观察、重连、取消、调度状态
4. 对话：权威历史、流式正文/推理、统计、停止、确认清空、录音和音频文件转录
5. 项目进度、任务和提交记录
6. 财务摘要、资产/预算、原始工作表、趋势与采购建议的生成/隐藏/恢复
7. 原生分析图表，包括多轴、堆积、时间/分类坐标、缺失数据与雷达数据
8. 面部历史趋势、实时状态、分析进度、隐私展开与 Excel 保存
9. 模型用量、调用明细与速度趋势
10. 日志筛选/暂停/复制、运行目录、系统区域与原生偏好

系统集成包括文件选择、剪贴板、窗口/主题、登录启动和托盘或菜单栏。Linux 没有 StatusNotifier 宿主时明确降级为关窗退出，不把程序隐藏到无法找回的位置。操作系统拒绝设备权限时显示错误与恢复入口，不绕过权限。

## 状态与生命周期

- 客户端先探测服务与 API 主版本；已有服务只连接，不拥有其进程
- 仅在直连 loopback HTTP 且没有现存服务时启动随包后端；HTTPS/路径前缀代理必须已运行
- 显式客户端地址、`VANTAGE_BACKEND_URL`、host/port 环境变量、默认 `127.0.0.1:8000` 依次优先
- 设置读取、保存和回读都使用后端。密码控件为空表示不修改；清除凭据有独立语义；完整 provider 集合不能被一个编辑项意外替换
- 行动计划切页、隐藏或断流只停止观察。取消必须调用 job cancel；后端自动检查不依赖任何客户端 UI 定时器
- NDJSON 单行有大小上限，重复序号忽略，截断回读快照，过期 job 回读保存结果。只有成功状态、完整 result 与当前保存结果一致才显示成功
- 聊天需要明确完成记录后读取权威上下文；中断不自动重发。清空恢复行动计划基础上下文，并不保证消息列表为空
- 应用退出只回收自己启动的后端。退出该后端将终止其中未完成的任务；复用其他客户端的后端不会把它杀掉

## 构建与打包

所有命令从仓库根目录执行，具体系统依赖和运行方式见各客户端 README。

先构建并实际启动验证共享后端：

```sh
python scripts/build_native_backend.py
```

它复用 `.venv-backend-runtime-gpu`、依赖闭包/指纹、PyInstaller 与现有运行时验证器。原生验证使用全新临时数据与未占用 loopback 端口，去掉继承的用户数据路径和模型密钥，不终止其他 Vantage 进程。验证包含服务启动、CLI/MCP 与打包后的面部分析入口帮助命令。

随后在目标系统运行：

```powershell
./src/native/windows/build.ps1 -BackendRuntime build/backend-runtime/stage/VantageBackend
```

```sh
bash src/native/macos/scripts/package.sh --backend-runtime build/backend-runtime/stage/VantageBackend --output build/native/macos
/usr/bin/python3 src/native/linux/package.py --backend-runtime build/backend-runtime/stage/VantageBackend --output-dir dist/native/linux
```

独立打包入口再检查 backend manifest、必要资源、fingerprint 平台及 PE/Mach-O/ELF 实际 CPU 架构。目录中只有一个同名可执行文件不算有效 backend bundle。此静态检查不替代前一步启动验证。

产物为 Windows 自包含 ZIP、macOS `.app` ZIP 和 Linux tar.gz。Linux 的 GTK/PyGObject 来自发行版，不能称作无系统依赖的 AppImage。macOS 只做 ad-hoc 签名；CI 不读取发行签名证书，不公证，不发 Release，不修改现有 Electron 发布流程。

## 验证证据与验收边界

[`Native desktop` 工作流](../.github/workflows/native.yml) 在 Windows x64、macOS arm64/x64 和 Ubuntu x64 分别运行原生编译/测试、真实窗口合成数据检查、共享后端启动验证和打包。每份 artifact 名称带完整 commit SHA，截图与 JSON 报告单独保存。必须按实际 SHA 检查结果，不能把另一版的通过状态移植到当前源码。

测试层次保持分明：

- 纯协议/状态测试：错误地址、凭据保留、真实 DTO、流分片/上限、重连/截断/取消、结果身份、图表数据含义
- 独立 fixture 契约测试：合成数据必须匹配当前业务响应字段和单位，不能增加客户端专属假字段来掩盖问题
- 原生窗口 smoke：真实系统控件与图表渲染，截图、非空页面、应用动作；报告注明通过按钮还是 view-model 发起
- 安装与硬件验收：真实相机/麦克风授权、托盘宿主、登录启动、辅助功能、DPI/多屏、物理设备和个人真实数据

前三层通过不能替代第四层。无硬件或没有桌面权限时，必须明确记录“未验证”；不能把编译、源代码检查或 API 返回成功当作设备/窗口行为通过。

## 目标系统手工验收清单

1. 新数据目录首次启动；拒绝/取消 provider 设置后可以继续或重试，未完成引导不会跳过
2. 双击重复启动、关窗恢复、退出、重开；已有 backend 不被误杀，启动失败可以重试
3. 创建行动计划后切页/隐藏/重开，继续观察同一任务；明确取消后不得发布半份结果
4. 聊天停止/重发、清空 Cancel/Confirm、刷新与另一客户端修改会话后的同步
5. 录音权限拒绝、等待授权时切页、录音中隐藏/退出；不留下录音文件或后台录音
6. 默认图片遮挡，显示/隐藏、相机断开、真实面部历史分析与导出保存失败处理
7. 每张图表的单位、多个轴、堆积、缺失点、单点、时间跨度；中文与英文、深浅色均可读
8. 设置保存失败、密钥不改/明确清除、provider 改地址、删除/改路由、模型手工输入/发现
9. 大工作表/长日志/长回复的滚动、键盘导航、屏幕阅读器与不同 DPI
