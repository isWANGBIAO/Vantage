# main.py
import sys
from PyQt5.QtWidgets import QApplication
from gui.main_window import MainWindow


def main():
    # 每个 PyQt5 程序都需要一个 QApplication 对象，它负责管理应用程序的控制流和主要设置。
    # sys.argv 用于处理命令行参数，通常可以直接写成 QApplication([])。
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show() #注释后，程序启动时不会自动显示窗口
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
