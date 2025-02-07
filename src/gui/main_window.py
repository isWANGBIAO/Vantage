import os
from PyQt5.QtGui import QFont, QPixmap, QIcon
from PyQt5.QtWidgets import (
    QApplication, QWidget, QTextEdit, QPushButton, QVBoxLayout,
    QSystemTrayIcon, QMenu, QAction, QHBoxLayout, QLabel
)
from PyQt5.QtCore import QObject, pyqtSignal, QEvent, QTimer
from PyQt5.QtCore import Qt
import sys
from gui.worker import WorkerThread
from manager.manager_main import ManagerMain
from cursor.code_runner import CodeRunner
from datetime import datetime
from PyQt5.QtCore import QTimer, QDateTime
import shutil


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
        self.main_window_size = (800, 800)
        self.resize_window()  # 调整窗口大小并且居中显示
        self.refresh_interval = 10  # 刷新间隔秒数
        self.manager_main = ManagerMain(self.refresh_interval)  # 传递间隔给ManagerMain
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

        # 创建主布局
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.text_edit)

        # 添加时钟插件
        self.time_label = self.create_clock_widget()
        main_layout.addWidget(self.time_label)

        # 创建一个水平布局，放置两个子窗口（显示照片和截图）
        photo_and_screenshot_layout = QHBoxLayout()

        photo_layout = QVBoxLayout()
        # 创建左侧的标签，用于显示照片文件名
        self.photo_filename_label = QLabel(self)
        self.photo_filename_label.setStyleSheet("border: 1px solid black;")  # 可以设置边框样式
        self.photo_filename_label.setAlignment(Qt.AlignCenter)  # 设置文本居中显示
        photo_layout.addWidget(self.photo_filename_label)

        # 创建左侧的窗口，显示照片
        self.photo_label = QLabel(self)
        self.photo_label.setFixedSize(self.main_window_size[0] * 0.5, self.main_window_size[1] * 0.6)  # 设置尺寸
        self.photo_label.setStyleSheet("border: 1px solid black;")
        photo_layout.addWidget(self.photo_label)

        screenshot_layout = QVBoxLayout()
        # 创建右侧的标签，用于显示截图文件名
        self.screenshot_filename_label = QLabel(self)
        self.screenshot_filename_label.setStyleSheet("border: 1px solid black;")  # 可以设置边框样式
        self.screenshot_filename_label.setAlignment(Qt.AlignCenter)  # 设置文本居中显示
        screenshot_layout.addWidget(self.screenshot_filename_label)
        # 创建右侧的窗口，显示截图
        self.screenshot_label = QLabel(self)
        self.screenshot_label.setFixedSize(self.main_window_size[0] * 0.5, self.main_window_size[1] * 0.6)  # 设置尺寸
        self.screenshot_label.setStyleSheet("border: 1px solid black;")
        screenshot_layout.addWidget(self.screenshot_label)

        # 将左侧和右侧的布局添加到水平布局
        photo_and_screenshot_layout.addLayout(photo_layout)
        photo_and_screenshot_layout.addLayout(screenshot_layout)

        # 将水平布局添加到主布局
        main_layout.addLayout(photo_and_screenshot_layout)

        main_layout.addWidget(self.manager_button)
        main_layout.addWidget(self.cursor_button)

        self.setLayout(main_layout)

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

        # 启动定时器，每 60 秒刷新图片
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_images)
        self.timer.start(self.refresh_interval * 1000)

    def create_clock_widget(self):
        clock_label = QLabel()
        clock_label.setStyleSheet("font-size: 24px; color: blue;")

        timer = QTimer(self)
        timer.timeout.connect(lambda: clock_label.setText(QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")))
        timer.start(1000)

        # 初始化显示时间
        clock_label.setText(QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss"))

        return clock_label

    def resize_window(self):
        screen = QApplication.primaryScreen()
        screen_rect = screen.availableGeometry()

        # 计算 75% 的宽度和高度
        width = int(screen_rect.width() * 0.90)
        height = int(screen_rect.height() * 0.90)
        self.main_window_size = (width, height)
        print(f"width: {width}, height: {height}")
        print(f"main_window_size: {self.main_window_size}")
        # 设置窗口大小
        self.resize(width, height)

        # 计算居中位置
        x = (screen_rect.width() - width) // 2
        y = (screen_rect.height() - height) // 2

        # 移动窗口到居中位置
        self.move(x, y)

    # 运行 manager 任务
    def run_manager_task(self):
        # 启动 manager 任务并传入刷新间隔
        self.start_thread(self.manager_main.run_task)

    # 运行 cursor 任务
    def run_cursor_task(self):
        self.start_thread(CodeRunner().run_code)

    # 统一线程启动方法
    def start_thread(self, func):
        self.thread = WorkerThread(func)
        self.thread.output_signal.connect(self.append_text)
        self.thread.start()

    # 正常输出
    def append_text(self, text):
        self.text_edit.append(f"<span style='color:black;'>{text}</span>")
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

    def update_images(self):
        latest_photo_size = self.display_latest_image('./logs/photos/', self.photo_label, self.photo_filename_label)
        latest_screenshot_size = self.display_latest_image('./logs/screenshots/', self.screenshot_label, self.screenshot_filename_label)
        # 计算 logs 文件夹大小
        logs_size = self.get_folder_size('./logs')

        # 获取磁盘剩余空间
        disk_free_space = self.get_disk_free_space('.')

        # 计算还能存多少组照片和截图
        total_group_size = latest_photo_size + latest_screenshot_size
        if total_group_size > 0:
            max_groups = disk_free_space // total_group_size
        else:
            max_groups = 0

        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 一组照片和截图大小: {total_group_size / (1024 ** 2):.2f} MB")
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} logs 文件夹大小: {logs_size / (1024 ** 3):.2f} GB = {logs_size / (1024 ** 2):.2f} MB")
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 磁盘剩余空间: {disk_free_space / (1024 ** 3):.2f} GB = {disk_free_space / (1024 ** 2):.2f} MB")
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 还能存储的最大组数: {max_groups}")
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 按照{self.refresh_interval}秒一组，还能存储的最大天数: {max_groups * self.refresh_interval / (60* 60 * 24):.0f} 天")

    def display_latest_image(self, folder_path, label, filename_label):
        if os.path.exists(folder_path):
            print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 正在查找最新图片...")
            files = self.get_files_from_subdirectories(folder_path)
            if files:
                latest_file = max(files, key=os.path.getmtime)
                pixmap = QPixmap(latest_file)
                label.setPixmap(pixmap.scaled(label.size(), aspectRatioMode=True))
                print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 显示最新图片：{latest_file}")
                # 显示文件名
                filename = os.path.basename(latest_file)
                filename_label.setText(filename)  # 设置文件名到对应的标签
                file_size = os.path.getsize(latest_file)  # 获取最新文件大小（字节）
                return file_size

    def get_files_from_subdirectories(self, folder_path):
        files = []
        for root, dirs, filenames in os.walk(folder_path):  # 使用os.walk递归遍历所有子目录
            for filename in filenames:
                file_path = os.path.join(root, filename)
                if os.path.isfile(file_path):  # 确保是文件而非目录
                    files.append(file_path)
        return files

    def get_folder_size(self, folder_path):
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.isfile(fp):
                    total_size += os.path.getsize(fp)
        return total_size

    def get_disk_free_space(self, path):
        total, used, free = shutil.disk_usage(path)
        return free
