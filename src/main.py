# main.py
import os
import sys
from PyQt6.QtWidgets import QApplication
from gui.main_window import MainWindow
import psutil


def is_already_running():
    current_pid = os.getpid()
    current_name = os.path.basename(sys.argv[0])
    print(f"current_pid: {current_pid}, current_name: {current_name}")
    for process in psutil.process_iter(attrs=['pid', 'name']):
        if process.info['name'] == current_name and process.info['pid'] != current_pid:
            print("程序已在运行中，不允许重复启动！")
            sys.exit(0)


def set_working_directory():
    if getattr(sys, 'frozen', False):  # 如果是打包后的 exe 运行
        base_dir = os.path.abspath(os.path.join(os.path.dirname(sys.executable), "..", ".."))
        # 指定工作目录在上层文件夹的上层文件夹
    else:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    print(f"base_dir: {base_dir}")
    os.chdir(base_dir)  # 统一工作目录
    print(f"当前工作目录: {os.getcwd()}")
    print("程序启动...")


def main():
    # 检查程序是否已经在运行
    is_already_running()
    # 设置工作目录
    set_working_directory()
    try:
        # 每个 PyQt6 程序都需要一个 QApplication 对象，它负责管理应用程序的控制流和主要设置。
        # sys.argv 用于处理命令行参数，通常可以直接写成 QApplication([])。
        app = QApplication(sys.argv)
        window = MainWindow()
        # window.show() #注释后，程序启动时不会自动显示窗口
        sys.exit(app.exec())
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == '__main__':
    main()
