# Vantage Linux 原生客户端

真正的 GTK4/PyGObject 桌面应用，不使用 Electron、React、HTML 或 WebView。业务与配置由唯一 `/api/v1` 后端负责。

## 运行

Ubuntu/Debian 的官方系统依赖：`python3-gi python3-cairo python3-gi-cairo gir1.2-gtk-4.0 fonts-noto-cjk`。录音可选 `pipewire-bin`（pw-record）或 `alsa-utils`（arecord）。GTK 4.8+、Python 3.10+。

```sh
/usr/bin/python3 src/native/linux/main.py --check
/usr/bin/python3 src/native/linux/main.py --backend-python .venv-backend-runtime-gpu/bin/python
# 或连接已运行的唯一后端
/usr/bin/python3 src/native/linux/main.py --connect-only --backend-url http://127.0.0.1:8000
```

打包版解压后运行 `./Vantage/vantage`。可选执行 `./Vantage/install-desktop-entry` 安装当前用户的启动器。无需管理员权限。包内含后端 runtime；归档附带官方 Noto CJK 字体和版权文件，仅在应用进程中注册，避免缺字；GTK 来自发行版，不能把这个归档描述为无系统依赖的 AppImage。

CI 完整归档在 Ubuntu 24.04 x64 构建和运行验证；上面的 GTK/Python 版本是界面源码要求，不保证预编译后端兼容更旧的 glibc 或任意发行版。其他发行版应在对应目标系统重建共享后端并验收。

后端地址优先级为命令行、VANTAGE_BACKEND_URL、VANTAGE_BACKEND_HOST/PORT、127.0.0.1:8000。仅 loopback；不接受重定向或环境代理。HTTPS/带路径代理仅连接，不能启动。先检测已运行服务，未运行时才启动随包后端。只终止自己启动的子进程，不终止已连接的其他后端。运行数据默认 `~/.local/share/Vantage`，遵循 VANTAGE_DATA_DIR，不写源码目录。

## 功能

- 原生 Markdown 标题、强调、列表/勾选项、表格、引用、代码与链接文字（无 HTML 执行）
- 原生首次引导、写入式密钥、完整 provider 保留、模型发现、语音/图像服务、模型参数、主题与语言
- 状态仪表盘、资源、久坐、空气质量、隐藏的媒体预览、目录打开
- 行动计划创建/加入、NDJSON 增量、重连游标/去重、截断恢复、显式取消、成功结果校验、调度信息
- 后端聊天上下文、流式回复/思考、清空、停止、音频文件转录、显式录音与临时音频清理
- 项目进度/提交、资产与预算、工作簿筛选、财务趋势、模型采购建议/隐藏/恢复
- 原生 Cairo 图表：分类/时间坐标、多 Y 轴/逆轴、堆积正负值、缺失值断点、雷达、数据检查与显示点数
- 历史人脸趋势/极值照片隐私展开、相机 MJPEG/检测框、进度、Excel 导出
- 模型用量统计/分组表/速度图、日志筛选/复制
- Linux StatusNotifier 托盘、XDG 登录启动、GTK 原生文件选择、locale、目录打开与剪贴板

GNOME 没有 StatusNotifier 扩展时托盘不可用，关闭窗口会退出；有托盘时关闭窗口隐藏，菜单“退出”或 Ctrl+Q 完全退出。相机硬件由共享后端拥有，GTK 显示已有后端视频；隐藏视频不表示关闭后端设备。录音只在点击后开始，由系统音频权限决定是否可用，不尝试绕过权限。

## 测试与打包

```sh
/usr/bin/python3 -m unittest discover -s src/native/linux/tests -p 'test_*.py'
dbus-run-session -- xvfb-run -a /usr/bin/python3 src/native/linux/smoke_test.py --output-dir /tmp/vantage-linux-smoke
/usr/bin/python3 src/native/linux/package.py --backend-runtime build/backend-runtime/stage/VantageBackend --output-dir dist/native/linux
```

烟测启动纯 stdlib 合成后端，无真实模型/硬件/个人数据，在真实 GTK 窗口遍历 10 页并截图，执行任务、聊天、清空、采购建议、引导流程。退出码非零即失败；`report.json` 明确检查内容。截图仅存在指定输出目录，不提交到公共仓库。完整硬件、桌面托盘宿主、录音权限、安装后自动启动仍需目标 Linux 桌面验收。

构建脚本要求预先构建的 Linux ELF `VantageBackend`，复制其完整 PyInstaller runtime 目录，输出 `Vantage-linux-<arch>.tar.gz`，同时验证 manifest/resource/fingerprint/架构、携带项目 LICENSE 和 Noto 字体许可，缺后端或字体许可时明确失败，不静默创建不可运行的包。
