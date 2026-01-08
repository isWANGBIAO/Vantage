from PyQt6.QtWidgets import (
    QApplication, QWidget, QTextEdit, QLabel, QVBoxLayout, QHBoxLayout,
    QInputDialog, QLineEdit, QMessageBox, QSystemTrayIcon, QMenu, QPushButton
)
from PyQt6.QtGui import QPalette, QColor, QImage, QPixmap, QAction, QFont, QIcon, QTextCursor
from PyQt6.QtCore import QTimer, QEvent, Qt, QDateTime
import subprocess
import os
import sys
import shutil
import cv2
from datetime import datetime
from manager.manager_main import Monitor
from .worker import WorkerThread
from .emitting_stream import EmittingStream
from .action_plan_dialog import ActionPlanDialog
from cv2_enumerate_cameras import enumerate_cameras


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
        self.cam = None
        self.paths = {
            'photo': None,
            'screenshot': None
        }
        self.photos_path = None
        self.screenshots_path = None
        self.refresh_interval_seconds = 10  # ??????????????????
        self.refresh_interval = self.refresh_interval_seconds * 1000  # ?????????????????????
        self.monitor = None

        QTimer.singleShot(0, self.bootstrap_runtime)
        
        # 自动弹出今日计划 (Auto-show action plan on startup)
        QTimer.singleShot(1000, self.show_action_plan)

    def bootstrap_runtime(self):
        camera_index = 0
        system_model = self.get_system_model()
        if system_model == "MRGF-XX":
            for camera_info in enumerate_cameras(cv2.CAP_MSMF):
                print(f'{camera_info.index}: {camera_info.name}')
                if "USB Camera" in camera_info.name:
                    camera_index = camera_info.index
            print(f"MRGF-XX ??????????????????????????????????????????USB Camera, camera_index = {camera_index}")

        self.cam = cv2.VideoCapture(camera_index)
        # ?????????????????????????????????
        if not self.cam.isOpened():
            print('Failed to open camera.', file=sys.stderr)
            return

        # ??????????????????????????????????????????        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Setting camera resolution")
        resolution = self.set_max_camera_resolution()
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Setting camera resolution to {resolution}")

        # Identify folder location
        self.photos_path, self.screenshots_path = self.identify_logs_folder()

        self.monitor = Monitor(self.cam, self.paths, self.photos_path, self.screenshots_path)  # ?????? logs_path
        self.monitor.run_task()  # ????????????????????????        
        self.update_images()  # ??????????????????
        # 1?????? ???????????? update_frame
        self.frame_thread = WorkerThread(self.update_frame)
        self.frame_thread.set_interval(15)
        self.frame_thread.output_signal.connect(self.display_frame)
        self.frame_thread.start()

        # # 2?????? ???????????? run_task ????????????
        self.task_thread = WorkerThread(self.monitor.run_task)
        self.task_thread.set_interval(self.refresh_interval)
        self.task_thread.output_signal.connect(self.display_task_result)
        self.task_thread.start()

        # 3?????? ???????????? update_images ????????????????????????
        self.image_thread = WorkerThread(self.update_images)
        self.image_thread.set_interval(self.refresh_interval * 0.1)
        self.image_thread.output_signal.connect(self.display_images)
        self.image_thread.start()

        # ??????????????????????????????
        self.update_tray_icon_tooltip()
        self.tray_icon_tooltip_timer = QTimer(self)
        self.tray_icon_tooltip_timer.timeout.connect(self.update_tray_icon_tooltip)
        self.tray_icon_tooltip_timer.start(5000)  # ???5 ???????????????
    def identify_logs_folder(self):

        # 先尝试环境变量
        onedrive_path = os.environ.get("OneDrive", "")

        # 如果环境变量未找到，再检查可能的路径
        if not onedrive_path or not os.path.exists(onedrive_path):
            possible_paths = [
                os.path.expanduser("~/OneDrive"),
                os.path.expanduser("~/OneDrive - Personal"),
                os.path.expanduser("~/OneDrive - Business")
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    onedrive_path = path
                break

        print("OneDrive 目录:", onedrive_path)

        pictures_path = f"{onedrive_path}\\Pictures\\" if os.path.exists(f"{onedrive_path}\\Pictures") else f"{onedrive_path}\\图片"
        screenshots_path = f"{pictures_path}\\Screenshots" if os.path.exists(f"{pictures_path}\\Screenshots") else f"{pictures_path}\\屏幕截图"

        print("OneDrive 图片目录:", pictures_path)
        print("OneDrive 截图目录:", screenshots_path)

        # C:\Users\97012\OneDrive\图片\本机照片
        photos_path = pictures_path + "\\本机照片"

        return photos_path, screenshots_path

    def set_light_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(255, 255, 255))  # 白色背景
        palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 0, 0))    # 黑色文本
        QApplication.instance().setPalette(palette)
        print("已切换到浅色主题")

    def set_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))     # 深灰色背景
        palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))  # 白色文本
        QApplication.instance().setPalette(palette)
        print("已切换到深色主题")
    # 显示摄像头画面

    def display_frame(self, frame):
        # 将 OpenCV 图像转换为 PyQt 可以显示的格式
        image = QImage(frame, frame.shape[1], frame.shape[0], QImage.Format.Format_RGB8888)
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
            qt_image = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            # 获取标签的大小
            label_size = self.camera_label.size()

            # 使用scaled方法，调整顺序
            scaled_image = QPixmap.fromImage(qt_image).scaled(
                label_size,
                Qt.AspectRatioMode.KeepAspectRatio,  # 保持宽高比
                Qt.TransformationMode.FastTransformation  # 快速变换
            )

    # 设置到标签
            self.camera_label.setPixmap(scaled_image)

    def init_ui(self):
        # print("已切换到浅色主题")
        # self.set_light_theme()
        self.setWindowTitle('任务管理器')
        self.main_window_size = (800, 800)
        self.resize_window()  # 调整窗口大小并且居中显示

        self.init_tray_icon()

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setObjectName("logView")

        # ✅ 设置字体和大小
        font = QFont('Consolas', 14)  # 字体：Consolas，大小：14
        self.text_edit.setFont(font)
        self.text_edit.setMinimumHeight(220)

        # 控制按钮
        self.manager_button = QPushButton('🚀 运行 Manager 任务')
        self.cursor_button = QPushButton('🎯 运行 Cursor 任务')
        
        self.plan_button = QPushButton('📅 查看今日计划')
        self.plan_button.setIcon(QIcon('plan_icon.png'))
        self.plan_button.setObjectName("actionButton")
        self.plan_button.clicked.connect(self.show_action_plan)
        
        self.manager_button.setIcon(QIcon('run_icon.png'))  # 添加图标
        self.cursor_button.setIcon(QIcon('cursor_icon.png'))
        self.manager_button.setObjectName("primaryButton")
        self.cursor_button.setObjectName("secondaryButton")

        # self.manager_button.clicked.connect(self.run_manager_task)
        # self.cursor_button.clicked.connect(self.run_cursor_task)

        # 创建主布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)
        main_layout.addWidget(self.text_edit)

        # 创建一个水平布局，放置两个子窗口（显示照片和截图）
        photo_and_screenshot_layout = QHBoxLayout()
        photo_and_screenshot_layout.setSpacing(12)

        # Bottom: Real-time camera, latest photo, latest screenshot
        camera_layout = QVBoxLayout()
        # 添加时钟插件
        self.time_label = QLabel()
        self.time_label.setObjectName("timeLabel")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 设置文本居中显示
        self.timer4 = QTimer(self)
        self.timer4.timeout.connect(lambda: self.time_label.setText(QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")))
        self.timer4.start(1000)

        # 初始化显示时间
        self.time_label.setText(QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss"))

        camera_layout.addWidget(self.time_label)

        # 创建左侧的窗口，显示实时摄像头
        self.camera_label = QLabel('Real-time Camera')
        self.camera_label.setObjectName("previewLabel")
        width = int(self.main_window_size[0] * 0.3)
        height = int(self.main_window_size[1] * 0.3)

        self.camera_label.setFixedSize(width, height)  # 设置尺寸
        self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 图片居中
        # self.camera_label.setScaledContents(True)       # 图片自适应缩放
        camera_layout.addWidget(self.camera_label)

        photo_layout = QVBoxLayout()
        # 创建左侧的标签，用于显示照片文件名
        self.photo_filename_label = QLabel(self)
        self.photo_filename_label.setObjectName("filenameLabel")
        self.photo_filename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 设置文本居中显示
        photo_layout.addWidget(self.photo_filename_label)

        # 创建左侧的窗口，显示照片
        self.photo_label = QLabel(self)
        self.photo_label.setObjectName("previewLabel")
        self.photo_label.setFixedSize(width, height)  # 设置尺寸
        self.photo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 图片居中
        # self.photo_label.setScaledContents(True)       # 图片自适应缩放
        photo_layout.addWidget(self.photo_label)

        screenshot_layout = QVBoxLayout()
        # 创建右侧的标签，用于显示截图文件名
        self.screenshot_filename_label = QLabel(self)
        self.screenshot_filename_label.setObjectName("filenameLabel")
        self.screenshot_filename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 设置文本居中显示
        screenshot_layout.addWidget(self.screenshot_filename_label)
        # 创建右侧的窗口，显示截图
        self.screenshot_label = QLabel(self)
        self.screenshot_label.setObjectName("previewLabel")
        self.screenshot_label.setFixedSize(width, height)  # 设置尺寸
        self.screenshot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 图片居中
        # self.screenshot_label.setScaledContents(True)       # 图片自适应缩放
        screenshot_layout.addWidget(self.screenshot_label)

        # 将左侧和右侧的布局添加到水平布局（实时摄像头放中间）
        photo_and_screenshot_layout.addLayout(photo_layout)
        photo_and_screenshot_layout.addLayout(camera_layout)
        photo_and_screenshot_layout.addLayout(screenshot_layout)

        # 按钮布局
        button_layout = QVBoxLayout()
        button_layout.addWidget(self.manager_button)
        button_layout.addWidget(self.cursor_button)
        button_layout.addWidget(self.plan_button)
        button_layout.setSpacing(12)

        # 组合布局
        main_layout.addLayout(photo_and_screenshot_layout)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)
        self.apply_style()

        # 监听最小化和关闭事件
        self.installEventFilter(self)
        # 只有当你的程序窗口处于活动状态（即窗口在最前面、已被点击或激活）时，按键事件才会被接收。
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # 强制窗口接收键盘事件
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

    def is_dark_mode(self):
        # 检测全局调色板的文本颜色和背景颜色
        palette = QApplication.palette()
        text_color = palette.color(QPalette.ColorRole.Text)
        background_color = palette.color(QPalette.ColorRole.Base)

        # 如果文本颜色比背景色亮，通常是深色模式
        return text_color.lightness() > background_color.lightness()

    # 正常输出
    def append_text(self, text):
        color = "white" if self.is_dark_mode() else "black"
        self.text_edit.append(f"<span style='color:{color};'>{text}</span>")
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)

    # 错误输出
    def append_error(self, text):
        error_color = "#FF6666" if self.is_dark_mode() else "red"
        self.text_edit.append(f"<span style='color:{error_color};'>{text}</span>")
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)

    # 托盘菜单
    def init_tray_icon(self):
        # 创建系统托盘图标
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon('icon.png'))  # 图标路径

        # 创建托盘菜单
        tray_menu = QMenu()
        
        view_plan_action = QAction("📅 查看今日计划", self)
        view_plan_action.triggered.connect(self.show_action_plan)
        
        restore_action = QAction("🖥️ 恢复窗口", self)
        restore_action.triggered.connect(self.request_password)
        
        quit_action = QAction("❌ 退出", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        
        tray_menu.addAction(view_plan_action)
        tray_menu.addSeparator()
        tray_menu.addAction(restore_action)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    # 关闭时隐藏到托盘
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Close:
            event.ignore()
            self.hide()
            # self.tray_icon.showMessage("任务管理器", "程序已最小化到托盘。", QSystemTrayIcon.Information, 2000)
        elif event.type() == QEvent.Type.KeyPress:  # 监听按键事件
            if event.key() == Qt.Key.Key_Space:
                print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Simulating camera reconnect...", file=sys.stderr)
                self.cam.release()
                print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Old camera released.", file=sys.stderr)
            elif event.key() == Qt.Key.Key_Escape:
                self.close()  # 手动关闭程序
            elif event.key() == Qt.Key.Key_W and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.hide()
                # self.tray_icon.showMessage("任务管理器", "程序已最小化到托盘。", QSystemTrayIcon.Information, 2000)
            return True  # 表示事件已处理
        return super().eventFilter(obj, event)

    def request_password(self):
        # 检查是否启用密码验证
        use_password_protection = False  # 默认关闭密码保护
        
        if use_password_protection:
            # 弹出密码输入对话框
            password, ok = QInputDialog.getText(self, "密码验证", "请输入密码：", QLineEdit.EchoMode.Password)
            if ok:
                if password == "789456":
                    self.show_normal()
                else:
                    QMessageBox.warning(self, "错误", "密码错误，请重试。")
        else:
            # 直接显示窗口，不进行密码验证
            self.show_normal()
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
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.request_password()
            # self.show_normal()

    # 关闭事件处理，最小化到托盘

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        # self.tray_icon.showMessage("任务管理器", "程序已最小化到托盘。", QSystemTrayIcon.Information, 2000)

    def update_images(self):
        # 获取路径
        photo_path = self.paths.get('photo')
        screenshot_path = self.paths.get('screenshot')
        if not photo_path and not screenshot_path:
            return

        # 如果路径存在，显示图片并计算大小
        latest_photo_size = self.display_image(photo_path, self.photo_label, self.photo_filename_label)

        latest_screenshot_size = self.display_image(screenshot_path, self.screenshot_label, self.screenshot_filename_label)

        logs_size = self.get_folder_size(self.photos_path) + self.get_folder_size(self.screenshots_path)

        # 获取磁盘剩余空间
        total, used, disk_free_space = shutil.disk_usage(self.photos_path)
        # 计算还能存多少组照片和截图
        total_group_size = latest_photo_size + latest_screenshot_size
        if total_group_size > 0:
            max_groups = disk_free_space // total_group_size
        else:
            max_groups = 0

        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 一组照片和截图大小: {total_group_size / (1024 ** 2):.2f} MB | 照片和截图文件夹大小: {logs_size / (1024 ** 3):.2f} GB | 磁盘剩余空间: {disk_free_space / (1024 ** 3):.2f} GB")
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 还能存储的最大组数: {max_groups} | 按照{self.refresh_interval_seconds}秒一组，还能存储的最大天数: {max_groups * self.refresh_interval_seconds / (60 * 60 * 24):.0f} 天")

    def display_image(self, file_path, label, filename_label):
        if file_path and os.path.exists(file_path):
            print(f"Time {QDateTime.currentDateTime().toString('yyyy-MM-dd HH:mm:ss')} 正在显示图片: {file_path}")
            pixmap = QPixmap(file_path)
            # 使用正确的 scaled 方法
            label.setPixmap(pixmap.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))

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
            # Using timeout to prevent hanging
            output = subprocess.check_output('wmic csproduct get name', shell=True, timeout=10)
            lines = output.decode('utf-8', errors='ignore').split('\n')
            # Filter out empty lines
            non_empty_lines = [line.strip() for line in lines if line.strip()]
            if len(non_empty_lines) > 1:
                return non_empty_lines[1]  # Return the second non-empty line (after headers)
            else:
                return "未知电脑型号"
        except subprocess.TimeoutExpired:
            print("WMIC command timed out, using default model detection")
            return "未知电脑型号"
        except Exception as e:
            print(f"Error getting system model: {e}")
            return "未知电脑型号"

    def apply_style(self):
        # Modern Glassmorphism-inspired Light Theme
        self.setStyleSheet("""
            QWidget {
                background-color: #f0f2f5;
                color: #1d1d1f;
                font-family: "Segoe UI", "Inter", "Microsoft YaHei";
                font-size: 14px;
            }
            
            /* Logs Area */
            QTextEdit#logView {
                background-color: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 12px;
                padding: 12px;
                selection-background-color: #0066cc;
            }
            
            /* Time Label */
            QLabel#timeLabel {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0066cc, stop:1 #0099ff);
                color: #ffffff;
                border-radius: 10px;
                padding: 8px 16px;
                font-size: 18px;
                font-weight: bold;
                border: 1px solid rgba(255, 255, 255, 0.2);
            }
            
            /* Image Preview Labels */
            QLabel#previewLabel {
                background-color: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 12px;
                padding: 2px;
            }
            
            /* Filename Labels */
            QLabel#filenameLabel {
                background-color: #e8eaed;
                color: #5f6368;
                border: none;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: 500;
            }
            
            /* Primary Button (Manager) */
            QPushButton#primaryButton {
                background-color: #0066cc;
                color: #ffffff;
                border: none;
                border-radius: 10px;
                padding: 12px 20px;
                font-weight: 600;
                font-size: 15px;
            }
            QPushButton#primaryButton:hover {
                background-color: #0052a3;
            }
            QPushButton#primaryButton:pressed {
                background-color: #003d7a;
            }
            
            /* Secondary Button (Cursor) */
            QPushButton#secondaryButton {
                background-color: #ffffff;
                color: #1d1d1f;
                border: 1px solid #d1d1d6;
                border-radius: 10px;
                padding: 12px 20px;
                font-weight: 600;
                font-size: 15px;
            }
            QPushButton#secondaryButton:hover {
                background-color: #f5f5f7;
                border-color: #0066cc;
            }
            
            /* Action Button (Plan) */
            QPushButton#actionButton {
                background-color: #34c759;
                color: #ffffff;
                border: none;
                border-radius: 10px;
                padding: 12px 20px;
                font-weight: 600;
                font-size: 15px;
            }
            QPushButton#actionButton:hover {
                background-color: #248a3d;
            }
            
            /* Tooltip */
            QToolTip {
                background-color: #333333;
                color: white;
                border: none;
                padding: 5px;
            }
            
            /* Menu */
            QMenu {
                background-color: white;
                border: 1px solid #d1d1d6;
                padding: 5px;
                border-radius: 8px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #0066cc;
                color: white;
            }
        """)

    def update_tray_icon_tooltip(self):
        """更新托盘图标的提示文本"""
        # 获取当前任务状态或任何你想要显示的信息
        tooltip_text = "任务管理器 - 运行中..."  # 替换为你实际的状态信息
        self.tray_icon.setToolTip(tooltip_text)

    def show_action_plan(self):
        """Show the Action Plan Dialog"""
        if hasattr(self, 'plan_dialog') and self.plan_dialog.isVisible():
            self.plan_dialog.raise_()
            self.plan_dialog.activateWindow()
            return
            
        self.plan_dialog = ActionPlanDialog(self)
        self.plan_dialog.show()
