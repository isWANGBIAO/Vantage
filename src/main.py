# main.py
import sys
from PyQt6.QtWidgets import QApplication
from gui.main_window import MainWindow


def main():
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
