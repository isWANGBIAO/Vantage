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
