# gui/main_window.py
from PyQt5.QtGui import QFont  # 导入 QFont
from gui.worker import WorkerThread  # 处理长任务
from PyQt5.QtWidgets import QWidget, QTextEdit, QPushButton, QVBoxLayout
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton
from PyQt5.QtWidgets import (
    QApplication, QWidget, QTextEdit, QPushButton, QVBoxLayout,
    QSystemTrayIcon, QMenu, QAction
)
from gui.worker import WorkerThread
from manager.manager_main import ManagerMain
from cursor.code_runner import CodeRunner
from PyQt5.QtGui import QScreen
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import QObject, pyqtSignal, QEvent
from PyQt5.QtGui import QIcon
import sys


class EmittingStream(QObject):
    output_signal = pyqtSignal(str)

    def write(self, text):
        if text.strip():  # 过滤空行
            self.output_signal.emit(text)

    def flush(self):
        pass  # 保持兼容性


# main_window.py
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('任务管理器')
        self.resize_window()  # 调整窗口大小并且居中显示

        # 🖼️ 托盘图标设置
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon('icon.png'))  # 替换成你的图标路径
        self.create_tray_menu()

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)

        # ✅ 设置字体和大小
        font = QFont('Consolas', 14)  # 字体：Consolas，大小：14
        self.text_edit.setFont(font)

        # 控制按钮
        self.manager_button = QPushButton('运行 Manager 任务')
        self.cursor_button = QPushButton('运行 Cursor 任务')

        self.manager_button.clicked.connect(self.run_manager_task)
        self.cursor_button.clicked.connect(self.run_cursor_task)

        layout = QVBoxLayout()
        layout.addWidget(self.text_edit)
        layout.addWidget(self.manager_button)
        layout.addWidget(self.cursor_button)
        self.setLayout(layout)

        # 重定向 stdout 和 stderr
        sys.stdout = EmittingStream()
        sys.stderr = EmittingStream()
        sys.stdout.output_signal.connect(self.append_text)
        sys.stderr.output_signal.connect(self.append_error)

        # 监听最小化和关闭事件
        self.installEventFilter(self)

        # 双击托盘图标恢复窗口
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

        # 🚀 窗口打开时自动运行 Manager 任务
        self.run_manager_task()

    def resize_window(self):
        screen = QApplication.primaryScreen()
        screen_rect = screen.availableGeometry()

        # 计算 75% 的宽度和高度
        width = int(screen_rect.width() * 0.75)
        height = int(screen_rect.height() * 0.75)

        # 设置窗口大小
        self.resize(width, height)

        # 计算居中位置
        x = (screen_rect.width() - width) // 2
        y = (screen_rect.height() - height) // 2

        # 移动窗口到居中位置
        self.move(x, y)
    # 运行 manager 任务

    def run_manager_task(self):
        self.start_thread(ManagerMain().run_task)

    # 运行 cursor 任务
    def run_cursor_task(self):
        self.start_thread(CodeRunner().run_code)

    # 统一线程启动方法
    def start_thread(self, func):
        print("任务开始...")
        self.thread = WorkerThread(func)
        self.thread.output_signal.connect(self.append_text)
        self.thread.start()

    # 正常输出
    def append_text(self, text):
        self.text_edit.append(f"{text}")
        self.text_edit.moveCursor(self.text_edit.textCursor().End)

    # 错误输出（用红色标识）
    def append_error(self, text):
        self.text_edit.append(f"<span style='color:red;'>{text}</span>")
        self.text_edit.moveCursor(self.text_edit.textCursor().End)

        # 托盘菜单
    def create_tray_menu(self):
        tray_menu = QMenu()
        restore_action = QAction("恢复窗口", self)
        quit_action = QAction("退出", self)

        restore_action.triggered.connect(self.show_normal)
        quit_action.triggered.connect(QApplication.instance().quit)

        tray_menu.addAction(restore_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    # 关闭时隐藏到托盘
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Close:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage("任务管理器", "程序已最小化到托盘。", QSystemTrayIcon.Information, 2000)
        return super().eventFilter(obj, event)

    # 恢复窗口
    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # 退出程序
    def exit_program(self):
        self.tray_icon.hide()
        QApplication.instance().quit()

    # 托盘图标双击事件处理
    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_normal()

    # 关闭事件处理，最小化到托盘
    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage("任务管理器", "程序已最小化到托盘。", QSystemTrayIcon.Information, 2000)
