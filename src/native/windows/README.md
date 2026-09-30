# Vantage Windows 原生客户端

真实 WinUI 3 / Windows App SDK 桌面界面；没有 Electron、浏览器、WebView 或 React 运行时。HTTP 业务唯一使用共享 Python `/api/v1`。

## 构建

需要 Windows 10 1809+（推荐 Windows 11）、.NET 8 SDK、Visual Studio 的 Windows 应用开发工具与 Windows SDK。Windows App SDK 固定为官方 NuGet 的 1.8.260804001 稳定维护版本。

```powershell
dotnet test src/native/windows/Vantage.Core.Tests/Vantage.Core.Tests.csproj -c Release
dotnet build src/native/windows/Vantage.Windows/Vantage.Windows.csproj -c Release -p:Platform=x64
# 使用现有 Python 构建流程先生成真实后端 bundle，然后原生打包
./src/native/windows/build.ps1 -BackendRuntime ./build/backend-runtime/stage/VantageBackend
```

输出 `build/native/windows/Vantage/Vantage.Windows.exe` 和 `Vantage-Windows-x64.zip`。包包含 .NET、Windows App SDK 与完整 `backend-runtime/VantageBackend`；不在启动时下载依赖。压缩包尚未签名，不是已发布安装器。ARM64 需匹配架构的后端 bundle。

开发时先运行共享后端再启动程序，或显式设置 `VANTAGE_BACKEND_EXECUTABLE` 指向已构建的后台程序。连接优先级：显式地址 → `VANTAGE_BACKEND_URL` → host/port → `http://127.0.0.1:8000`。只允许 loopback，HTTPS/path-prefix 仅连接，不自动启动。HTTP 重定向关闭。运行目录默认 `%LOCALAPPDATA%/Vantage`，支持共享 `VANTAGE_*_DIR` 环境变量。

## 页面与平台适配

- 引导与安全的 write-only Provider 配置；模型发现、采样与模型 profiles、语音/图像服务设置
- 概览：系统资源、久坐/专注、可信 AQI、MJPEG 相机、照片/截图；敏感图像默认遮挡
- 行动计划：后端任务创建/加入、实际参数、游标重连、截断重读、显式取消、完整保存结果；后台调度保留在 Python
- 对话：权威会话、流式正文/推理、统计、停止/清空、模型/推理/层级选择；原生麦克风录音和文件转录
- 项目任务与提交；资产摘要、趋势/预测、完整工作表、建议生成/隐藏/恢复
- 原生 XAML 图表：时间/分类轴、折线、散点、堆积柱、多Y轴、雷达/饼图，图例切换、范围选择、tooltip 与数据明细
- 面部报告/时间范围/实时数据、历史分析与 Excel 导出；模型用量与系统日志筛选
- 原生主题/标题栏、系统 locale、双语言、托盘、登录启动、目录/保存选择器、权限设置入口

关闭窗口隐藏到托盘，退出菜单才结束应用。只停止自己启动的后端；连接外部已运行后端不拥有其生命周期。整个后端关闭将终止其活动任务，单纯切页/隐藏不会取消行动计划。命名 app mutex 防重复窗口；非线程绑定的启动锁在探活前后串行启动。

## 验证

Core tests 使用合成 HTTP/流，不访问真实 Provider 或用户数据。Windows CI 编译、打包并运行实际 WinUI 窗口的 fixture smoke：

```powershell
$env:VANTAGE_BACKEND_URL='http://127.0.0.1:<fixture-port>'
./build/native/windows/Vantage/Vantage.Windows.exe --smoke-test <report.json>
```

smoke 只连接该后端，不启动真实硬件/模型；导航十个业务页，读取非空 native visual tree，执行任务、聊天、清空与本地目录 intent 契约，并输出 success/pages/errors。该入口只供显式测试，不能指向个人真实 backend。测试不会点击外部服务或录音权限。

Linux 上的源码检查不能证明 WinUI 编译或系统行为；相机/麦克风权限、托盘恢复、真实启动项、DPI、多显示器、辅助功能与完整安装包仍需 Windows 真机验收。请区分 CI fixture 通过与真实数据/硬件验收。

官方参考：[WinUI 3 非打包部署](https://learn.microsoft.com/windows/apps/package-and-deploy/unpackage-winui-app)、[Windows App SDK 1.8](https://learn.microsoft.com/windows/apps/windows-app-sdk/release-notes/windows-app-sdk-1-8)、[MediaCapture](https://learn.microsoft.com/windows/apps/develop/camera/basic-photo-capture)。
