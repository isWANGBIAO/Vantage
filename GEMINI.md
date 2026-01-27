# Gemini Agent Guidelines

此文件包含 Gemini Agent 在处理本项目时的特定指南和规则。

## 1. 核心原则 (集成自 AGENTS.md)
*   **语言**: 必须使用中文进行交流和注释。
*   **运行环境**: 所有的命令执行和程序运行必须在项目的根目录下进行。
*   **脚本修改**: 如果修改了 Python 脚本，必须重新运行以验证更改。
*   **调试限制**: 这是一个长期挂机的程序。在调试运行时，请务必加上 60秒的时间限制 (timeout)，并通过查看日志文件 (`run_stderr.log`, `run_stdout.log`) 来进行 debug，而不是无限期等待。

## 2. 项目理解
这是一个自动化个人管家工具，主要包含以下部分：
*   **GUI**: 基于 Electron (`src/webapp`)，提供现代化 Web 界面，包含 Action Plan、Chat、实时监控等功能。
*   **后端**: 基于 FastAPI (`src/server.py`)，处理核心逻辑、LLM 调用和文件操作。
*   **功能模块**:
    *   `src/manager/take_photo`: 摄像头拍照。
    *   `src/manager/screenshot`: 屏幕截图。
    *   `src/cursor`: 代码自动化处理模块 (读写、扫描、错误处理)。
*   **运行方式**: 双击 `START_ELECTRON.bat` 启动（自动启动后端和前端）。

## 3. 编码规范
*   保持现有代码风格。
*   修改 UI 相关代码 (`src/gui`) 时，注意多线程交互 (`worker.py`, `emitting_stream.py`)，避免阻塞主线程。
*   添加新功能时，确保在 `README.md` 中更新相关说明。

## 4. 常用命令备忘
*   **安装依赖**: `pip install -r requirements.txt`
*   **运行主程序**: `python src/main.py`
*   **打包**: `./build.bat`
