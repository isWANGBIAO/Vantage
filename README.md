# 项目功能

这个项目是一个自动化个人管家工具，具有以下主要功能：

- **自动化项目管理和功能验证**：帮助开发者在 Python 项目中自动化一些常规任务，如项目初始化、函数分离、自动测试等。
- **摄像头监控**：调用摄像头拍照，监控用户状态，并将照片记录在知识库中。
- **实时显示**：在 QT 界面中，上面上面是输出程序的print，黑色字体输出错误信息。下面三个窗口实时显示摄像头画面、最新的照片和截图。
- **托盘运行**：程序可以最小化到托盘运行。

# 界面说明

- 上方区域显示程序的输出，黑色字体显示错误信息。
- 下方左侧窗口实时显示摄像头画面，上方显示实时时间。
- 中间窗口显示最新的照片文件，上方显示文件名。
- 右侧窗口显示最新的截图文件，上方显示文件名。


# 安装步骤

## 使用 pip 安装依赖

**pip 加速**：使用清华大学的镜像源加速 pip 安装。

1. 设置 pip 加速：

   ```sh
   pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
   ```
2. 安装依赖：

   ```sh
   pip install -r requirements.txt
   ```

## 使用 conda 安装依赖

**conda 使用**：提供 `environment.yml` 文件，方便使用 conda 创建和管理环境。

1. 安装 Miniconda 或 Anaconda。
2. 根据 `environment.yml` 文件创建环境：

   ```sh
   conda env create -f environment.yml
   ```
3. 激活环境：

   ```sh
   conda activate ai
   ```

# 使用方法

1. 运行主程序：

   ```sh
   python src/main.py
   ```
2. 打包程序：

   ```sh
   ./build.bat
   ```

# 目录结构

- `src/`：源代码目录
  - `output_model.py`：输出模型名称和统计信息。
  - `manager/`：管理模块
    - `take_photo/`：拍照模块
      - `take_a_photo.py`：拍照并保存照片。
      - `get_best_photo.py`：获取最清晰的照片。
    - `screenshot/`：截图模块
      - `take_a_screenshot.py`：截取屏幕并保存截图。
    - `manager_main.py`：管理主程序。
    - `get_location.py`：获取地理位置信息。
  - `gui/`：图形用户界面模块
    - `main_window.py`：主窗口界面。
    - `worker.py`：工作线程类。
    - `emitting_stream.py`：重定向输出流。
  - `cursor/`：代码处理模块
    - `process.py`：处理代码文件。
    - `file_scanner.py`：扫描代码文件。
    - `error_handler.py`：处理代码错误。
    - `code_write.py`：写入代码文件。
    - `code_runner.py`：运行代码文件。
    - `code_read.py`：读取代码文件。
    - `code_modifier.py`：修改代码文件。
    - `code_adder.py`：增加代码功能。
    - `backup_folder.py`：备份目录。
  - `detect.py`：检测照片中的人物。
- `requirements.txt`：pip 依赖文件。
- `environment.yml`：conda 环境配置文件。
- `convert_icon.py`：图标转换脚本。
- `build.bat`：打包脚本。
- `.gitignore`：Git 忽略文件配置。

# 其他说明

# CHECKLIST

**必须保证的功能点：**
- **UI 界面**： 主界面信息框应该要有清晰的标题（系统日志、实时监控、最新照片、最新截图等等），表明这个信息框的用途。
- **Action Plan 对话框**：采用左右分栏布局，左侧展示总体回复，右侧展示今日计划，均支持 Markdown 渲染。底部清晰展示 Token 统计信息（包含每秒处理速度（“处理速度”现仅基于生成 Token (Completion Tokens) 计算，排除了 Prompt 处理时间的影响，真实反映模型生成效率。）、总消耗等），需包含处理速度、多少tokens/s 、总tokens还要有时间等等；
比例协调：分栏内容区域占据主要空间，统计信息栏为紧凑的底部栏样式。
样式美观：标题大小和统计栏的配色字体，整体协调。




- **主题适配**：界面需根据系统设置自动切换白天/黑夜模式，确保字体与背景颜色匹配。注意Qt6自带有这个功能，但是保证界面字体是颜色是匹配的。跟随系统主题：自动根据 Windows 的深色/浅色模式切换背景和文字颜色。保证可读性：文本框和标签使用中性样式或系统默认色，彻底解决了深色模式下“白字白底”的问题。

程序除了再系统日志框显示日志外，也要将日志输出到文件中，这个日志指的是所有的输出，包括系统的报错等等，文件路径为 `logs/` 目录下，方便调试。日志文件名为 `log_YYYY-MM-DD-HH-MM-SS.log`，所有终端输出（包括初始化信息）都完整记录。


常用Prompt：
请你查看`logs/` 目录下，最新的日志文件，有没有bug，如果有，请修复bug；如果没有请提出改进建议
