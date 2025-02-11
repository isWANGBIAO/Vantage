import subprocess
import time
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QWidget, QTextEdit, QLabel, QVBoxLayout, QHBoxLayout, QSizePolicy
import os
from PyQt5.QtGui import QFont, QPixmap, QIcon
from PyQt5.QtWidgets import (
    QApplication, QWidget, QTextEdit, QPushButton, QVBoxLayout,
    QSystemTrayIcon, QMenu, QAction, QHBoxLayout, QLabel
)
from PyQt5.QtCore import QObject, pyqtSignal, QEvent, QTimer
from PyQt5.QtCore import Qt
import sys
from manager.manager_main import Monitor
# from cursor.code_runner import CodeRunner
from datetime import datetime
from PyQt5.QtCore import QTimer, QDateTime
import shutil
import cv2
from .worker import WorkerThread


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

        # 初始化界面
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} MainWindow 开始初始化")
        self.init_ui()
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} MainWindow 初始化完成")

        # 重定向 stdout 和 stderr
        sys.stdout = EmittingStream()
        sys.stderr = EmittingStream()
        sys.stdout.output_signal.connect(self.append_text)
        sys.stderr.output_signal.connect(self.append_error)

        self.cam = cv2.VideoCapture(0)
        # 检查摄像头是否成功打开
        if not self.cam.isOpened():
            print('Failed to open camera.', file=sys.stderr)
            return False

        # 自动调整到摄像头最高的清晰度
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Setting camera resolution")
        resolution = self.set_max_camera_resolution()
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Setting camera resolution to {resolution}")

        # 用于存储最新的照片和截图路径
        self.paths = {
            'photo': None,
            'screenshot': None
        }
        self.refresh_interval_seconds = 10  # 刷新间隔秒数
        self.refresh_interval = self.refresh_interval_seconds * 1000  # 刷新间隔毫秒数

        self.monitor = Monitor(self.cam, self.paths)  # 传入 paths 字典
        self.monitor.run_task()  # 运行一次截图任务
        self.update_images()  # 显示最新图片

        # 1️⃣ 线程处理 update_frame
        self.frame_thread = WorkerThread(self.update_frame)
        self.frame_thread.set_interval(15)
        self.frame_thread.output_signal.connect(self.display_frame)
        self.frame_thread.start()

        # # 2️⃣ 线程处理 run_task 拍照截图
        self.task_thread = WorkerThread(self.monitor.run_task)
        self.task_thread.set_interval(self.refresh_interval)
        self.task_thread.output_signal.connect(self.display_task_result)
        self.task_thread.start()

        # 3️⃣ 线程处理 update_images 显示最新图片截图
        self.image_thread = WorkerThread(self.update_images)
        self.image_thread.set_interval(self.refresh_interval * 0.1)
        self.image_thread.output_signal.connect(self.display_images)
        self.image_thread.start()

    # 显示摄像头画面
    def display_frame(self, frame):
        # 将 OpenCV 图像转换为 PyQt 可以显示的格式
        image = QImage(frame, frame.shape[1], frame.shape[0], QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(image)
        self.camera_label.setPixmap(pixmap)

    # 显示 run_task 处理结果
    def display_task_result(self, result):
        self.output_area.append(result)  # 显示到文本框中

    # 显示最新图片
    def display_images(self, images):
        self.image_label.setPixmap(QPixmap.fromImage(images))

    def update_frame(self):
        ret, frame = self.cam.read()
        if ret:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            qt_image = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            self.camera_label.setPixmap(QPixmap.fromImage(qt_image).scaled(
                self.camera_label.size(),
                aspectRatioMode=Qt.KeepAspectRatio  # 保持宽高比
            ))

    def init_ui(self):
        self.setWindowTitle('任务管理器')
        self.main_window_size = (800, 800)
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
        self.manager_button = QPushButton('🚀 运行 Manager 任务')
        self.cursor_button = QPushButton('🎯 运行 Cursor 任务')
        self.manager_button.setIcon(QIcon('run_icon.png'))  # 添加图标
        self.cursor_button.setIcon(QIcon('cursor_icon.png'))

        # self.manager_button.clicked.connect(self.run_manager_task)
        # self.cursor_button.clicked.connect(self.run_cursor_task)

        # 创建主布局
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.text_edit)

        # 创建一个水平布局，放置两个子窗口（显示照片和截图）
        photo_and_screenshot_layout = QHBoxLayout()

        # Bottom: Real-time camera, latest photo, latest screenshot
        camera_layout = QVBoxLayout()
        # 添加时钟插件
        self.time_label = QLabel()
        self.time_label.setStyleSheet("font-size: 24px; color: blue; border: 1px solid black;")
        self.time_label.setAlignment(Qt.AlignCenter)  # 设置文本居中显示
        self.timer4 = QTimer(self)
        self.timer4.timeout.connect(lambda: self.time_label.setText(QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")))
        self.timer4.start(1000)

        # 初始化显示时间
        self.time_label.setText(QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss"))

        camera_layout.addWidget(self.time_label)

        # 创建左侧的窗口，显示实时摄像头
        self.camera_label = QLabel('Real-time Camera')
        width = int(self.main_window_size[0] * 0.3)
        height = int(self.main_window_size[1] * 0.3)

        self.camera_label.setFixedSize(width, height)  # 设置尺寸
        self.camera_label.setStyleSheet("border: 1px solid black;")
        self.camera_label.setAlignment(Qt.AlignCenter)  # 图片居中
        # self.camera_label.setScaledContents(True)       # 图片自适应缩放
        camera_layout.addWidget(self.camera_label)

        photo_layout = QVBoxLayout()
        # 创建左侧的标签，用于显示照片文件名
        self.photo_filename_label = QLabel(self)
        self.photo_filename_label.setStyleSheet("border: 1px solid black;")  # 可以设置边框样式
        self.photo_filename_label.setAlignment(Qt.AlignCenter)  # 设置文本居中显示
        photo_layout.addWidget(self.photo_filename_label)

        # 创建左侧的窗口，显示照片
        self.photo_label = QLabel(self)
        self.photo_label.setFixedSize(width, height)  # 设置尺寸
        self.photo_label.setStyleSheet("border: 1px solid black;")
        self.photo_label.setAlignment(Qt.AlignCenter)  # 图片居中
        # self.photo_label.setScaledContents(True)       # 图片自适应缩放
        photo_layout.addWidget(self.photo_label)

        screenshot_layout = QVBoxLayout()
        # 创建右侧的标签，用于显示截图文件名
        self.screenshot_filename_label = QLabel(self)
        self.screenshot_filename_label.setStyleSheet("border: 1px solid black;")  # 可以设置边框样式
        self.screenshot_filename_label.setAlignment(Qt.AlignCenter)  # 设置文本居中显示
        screenshot_layout.addWidget(self.screenshot_filename_label)
        # 创建右侧的窗口，显示截图
        self.screenshot_label = QLabel(self)
        self.screenshot_label.setFixedSize(width, height)  # 设置尺寸
        self.screenshot_label.setStyleSheet("border: 1px solid black;")
        self.screenshot_label.setAlignment(Qt.AlignCenter)  # 图片居中
        # self.screenshot_label.setScaledContents(True)       # 图片自适应缩放
        screenshot_layout.addWidget(self.screenshot_label)

        # 将左侧和右侧的布局添加到水平布局
        photo_and_screenshot_layout.addLayout(camera_layout)
        photo_and_screenshot_layout.addLayout(photo_layout)
        photo_and_screenshot_layout.addLayout(screenshot_layout)

        # 按钮布局
        button_layout = QVBoxLayout()
        button_layout.addWidget(self.manager_button)
        button_layout.addWidget(self.cursor_button)
        button_layout.setSpacing(20)

        # 组合布局
        main_layout.addLayout(photo_and_screenshot_layout)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

        # 监听最小化和关闭事件
        self.installEventFilter(self)
        # 只有当你的程序窗口处于活动状态（即窗口在最前面、已被点击或激活）时，按键事件才会被接收。
        self.setFocusPolicy(Qt.StrongFocus)  # 强制窗口接收键盘事件
        self.setFocus()                      # 主动获取焦点

        # 双击托盘图标恢复窗口
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

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
        elif event.type() == QEvent.KeyPress:  # 监听按键事件
            if event.key() == Qt.Key_Space:
                print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Simulating camera reconnect...", file=sys.stderr)
                self.cam.release()
                print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Old camera released.", file=sys.stderr)
            elif event.key() == Qt.Key_Escape:
                self.close()  # 手动关闭程序
            elif event.key() == Qt.Key_W and event.modifiers() & Qt.ControlModifier:
                self.hide()
                self.tray_icon.showMessage("任务管理器", "程序已最小化到托盘。", QSystemTrayIcon.Information, 2000)
            return True  # 表示事件已处理
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
        # 获取路径
        photo_path = self.paths.get('photo')
        screenshot_path = self.paths.get('screenshot')
        if not photo_path and not screenshot_path:
            return

        # 如果路径存在，显示图片并计算大小
        latest_photo_size = self.display_image(photo_path, self.photo_label, self.photo_filename_label)

        latest_screenshot_size = self.display_image(screenshot_path, self.screenshot_label, self.screenshot_filename_label)

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
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 按照{self.refresh_interval_seconds}秒一组，还能存储的最大天数: {max_groups * self.refresh_interval_seconds / (60 * 60 * 24):.0f} 天")

    def display_image(self, file_path, label, filename_label):
        if file_path and os.path.exists(file_path):
            print(f"Time {QDateTime.currentDateTime().toString('yyyy-MM-dd HH:mm:ss')} 正在显示图片: {file_path}")
            pixmap = QPixmap(file_path)
            label.setPixmap(pixmap.scaled(label.size(), aspectRatioMode=True))
            filename_label.setText(os.path.basename(file_path))  # 显示文件名
            return os.path.getsize(file_path)  # 返回文件大小
        else:
            print(f"Time {QDateTime.currentDateTime().toString('yyyy-MM-dd HH:mm:ss')} 图片路径无效或不存在: {file_path}")
            return 0

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

    def set_max_camera_resolution(self):
        # 获取电脑型号
        system_model = self.get_system_model()
        if system_model == "MRGF-XX":
            # MRGF-XX笔记本摄像头最大分辨率为1280x720
            width = 1280
            height = 720
            self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            return (width, height)
        else:
            # 常见分辨率列表，从高到低排列
            resolutions = [
                # (7680, 4320),  # 8K UHD
                # (5120, 2880),  # 5K
                (3840, 2160),  # 4K UHD
                (1280, 720),   # 720p
                (2560, 1600),  # WQXGA
                (2560, 1440),  # QHD
                (2048, 1080),  # 2K
                (1920, 1200),  # WUXGA
                (1920, 1080),  # 1080p
                (1600, 900),   # HD+
                (1440, 900),   # WXGA+
                (1366, 768),   # FWXGA
                (1280, 800),   # WXGA
                (1280, 720),   # 720p
                (1024, 768),   # XGA
                (800, 600),    # SVGA
                (640, 480),    # VGA
                (320, 240)     # QVGA
            ]

            # 从高到低尝试设置最大支持分辨率
            for width, height in resolutions:
                self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                actual_width = int(self.cam.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_height = int(self.cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
                if actual_width == width and actual_height == height:
                    return (width, height)
            # 如果无法匹配到任何分辨率，使用默认分辨率
            default_width = int(self.cam.get(cv2.CAP_PROP_FRAME_WIDTH))
            default_height = int(self.cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
            return (default_width, default_height)

    def get_system_model(self):
        try:
            output = subprocess.check_output('wmic csproduct get name', shell=True)
            return output.decode().split('\n')[1].strip()
        except:
            return "未知电脑型号"
