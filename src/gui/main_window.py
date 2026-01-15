from PyQt6.QtWidgets import (
    QApplication, QWidget, QTextEdit, QLabel, QVBoxLayout, QHBoxLayout,
    QInputDialog, QLineEdit, QMessageBox, QSystemTrayIcon, QMenu, QPushButton,
    QTabWidget, QScrollArea, QGridLayout
)
from PyQt6.QtGui import QPalette, QColor, QImage, QPixmap, QAction, QFont, QIcon, QTextCursor
from PyQt6.QtCore import QTimer, QEvent, Qt, QDateTime, QThread, pyqtSignal
import subprocess
import os
import sys
import shutil
import cv2
import traceback
from datetime import datetime
from manager.manager_main import Monitor
from .worker import WorkerThread
from .emitting_stream import EmittingStream
from cv2_enumerate_cameras import enumerate_cameras


# main_window.py
class PlotWorker(QThread):
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, is_dark_mode=False):
        super().__init__()
        self.is_dark_mode = is_dark_mode

    def run(self):
        try:
            # Run plot.py as a subprocess to ensure isolation and proper matplotlib state
            # We assume plot.py is in the same directory as main.py (root)
            # We assume plot.py is in src/scripts
            # __file__ is src/gui/main_window.py -> src/gui -> src -> src/scripts/plot.py
            current_dir = os.path.dirname(os.path.abspath(__file__))
            src_dir = os.path.dirname(current_dir)
            script_path = os.path.join(src_dir, "scripts", "plot.py")
            
            if not os.path.exists(script_path):
                # Fallback: check relative to CWD if running from root
                script_path = os.path.abspath("src/scripts/plot.py")

            cmd = [sys.executable, script_path]
            if self.is_dark_mode:
                cmd.append("--dark")
                
            # Run blocking call
            subprocess.run(cmd, check=True, capture_output=True)
            self.finished_signal.emit(True, "Plots generated.")
        except subprocess.CalledProcessError as e:
            self.finished_signal.emit(False, f"Plot generation failed: {e}")
        except Exception as e:
            self.finished_signal.emit(False, f"Error: {e}")


class ActionPlanWorker(QThread):
    """Worker thread for generating Action Plan via run_prompt.py"""
    finished_signal = pyqtSignal(bool, str)
    output_signal = pyqtSignal(str)
    stats_signal = pyqtSignal(dict)

    def run(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            pass

        try:
            # Locate run_prompt.py
            # Locate run_prompt.py in src/scripts
            current_dir = os.path.dirname(os.path.abspath(__file__))
            src_dir = os.path.dirname(current_dir)
            script_path = os.path.join(src_dir, "scripts", "run_prompt.py")

            if not os.path.exists(script_path):
                 script_path = os.path.abspath("src/scripts/run_prompt.py")

            if not os.path.exists(script_path):
                self.finished_signal.emit(False, f"Could not find run_prompt.py at {script_path}")
                return

            self.output_signal.emit(f"🚀 Starting generation task...\nScript: {script_path}\n")

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            process = subprocess.Popen(
                [sys.executable, script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                cwd=os.path.dirname(script_path),
                env=env
            )

            while True:
                line_bytes = process.stdout.readline()
                if line_bytes == b'' and process.poll() is not None:
                    break
                if line_bytes:
                    try:
                        line = line_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        try:
                            line = line_bytes.decode('gbk')
                        except UnicodeDecodeError:
                            line = line_bytes.decode('utf-8', errors='replace')
                    self.output_signal.emit(line.strip())
                    
                    if line.startswith("STATS_JSON:"):
                        try:
                            import json
                            json_str = line.replace("STATS_JSON:", "").strip()
                            stats = json.loads(json_str)
                            self.stats_signal.emit(stats)
                        except Exception:
                            pass

            stderr_bytes = process.stderr.read()
            if stderr_bytes:
                try:
                    stderr = stderr_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    stderr = stderr_bytes.decode('utf-8', errors='replace')
                self.output_signal.emit(f"STDERR: {stderr}")

            if process.returncode == 0:
                self.finished_signal.emit(True, "Generation completed successfully.")
            else:
                self.finished_signal.emit(False, f"Generation failed with return code {process.returncode}")

        except Exception as e:
            self.finished_signal.emit(False, str(e))
        finally:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except:
                pass


class ChatWorker(QThread):
    """Worker thread for sending chat messages via run_prompt.py"""
    finished_signal = pyqtSignal(bool, str)
    output_signal = pyqtSignal(str)
    
    def __init__(self, message, context_file=None):
        super().__init__()
        self.message = message
        self.context_file = context_file

    def run(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            pass

        try:
            # Locate run_prompt.py (same logic as ActionPlanWorker)
            # Locate run_prompt.py in src/scripts
            current_dir = os.path.dirname(os.path.abspath(__file__))
            src_dir = os.path.dirname(current_dir)
            script_path = os.path.join(src_dir, "scripts", "run_prompt.py")

            if not os.path.exists(script_path):
                 script_path = os.path.abspath("src/scripts/run_prompt.py")

            if not os.path.exists(script_path):
                self.finished_signal.emit(False, f"Could not find run_prompt.py at {script_path}")
                return
            
            # Determine context file path
            if not self.context_file:
                 # Default to history/latest_context.json relative to script execution or logic
                 # We'll let run_prompt handle default if not passed, but run_prompt writes to history/latest_context.json
                 # We should pass it explicitly if we can to be safe, or just rely on run_prompt's default.
                 # Actually run_prompt saves to `history/latest_context.json`.
                 # Let's verify where that is.
                 # For now, we will pass the path explicitly if we can calculate it, otherwise let python handle it.
                 # Let's try to construct the path.
                 base_dir = os.path.dirname(script_path)
                 self.context_file = os.path.join(base_dir, "history", "latest_context.json")

            cmd = [
                sys.executable, 
                script_path, 
                "--chat_message", self.message,
                "--context_file", self.context_file
            ]
            
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                cwd=os.path.dirname(script_path),
                env=env
            )

            while True:
                line_bytes = process.stdout.readline()
                if line_bytes == b'' and process.poll() is not None:
                    break
                if line_bytes:
                    try:
                        line = line_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        try:
                            line = line_bytes.decode('gbk')
                        except UnicodeDecodeError:
                            line = line_bytes.decode('utf-8', errors='replace')
                    self.output_signal.emit(line.strip())

            stderr_bytes = process.stderr.read()
            if stderr_bytes:
                try:
                    stderr = stderr_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    stderr = stderr_bytes.decode('utf-8', errors='replace')
                # We won't emit stderr as regular output to avoid cluttering chat unless debugging
                # self.output_signal.emit(f"STDERR: {stderr}")
                print(f"[ChatWorker] STDERR: {stderr}")

            if process.returncode == 0:
                self.finished_signal.emit(True, "Message sent.")
            else:
                self.finished_signal.emit(False, f"Failed with return code {process.returncode}")

        except Exception as e:
            self.finished_signal.emit(False, str(e))
        finally:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except:
                pass


from .audio_utils import AudioRecorder

class AudioWorker(QThread):
    finished_signal = pyqtSignal(str)
    
    def __init__(self, audio_file):
        super().__init__()
        self.audio_file = audio_file
        
    def run(self):
        try:
            # Run run_prompt.py with --transcribe
            # Run run_prompt.py with --transcribe
            current_dir = os.path.dirname(os.path.abspath(__file__))
            src_dir = os.path.dirname(current_dir)
            script_path = os.path.join(src_dir, "scripts", "run_prompt.py")

            if not os.path.exists(script_path):
                 script_path = os.path.abspath("src/scripts/run_prompt.py")
                 
            cmd = [sys.executable, script_path, "--transcribe", self.audio_file]
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            
            result = subprocess.run(cmd, capture_output=True, text=False, cwd=os.path.dirname(script_path), env=env)
            
            output = ""
            try:
                output = result.stdout.decode('utf-8')
            except:
                output = result.stdout.decode('gbk', errors='replace')
                
            transcription = ""
            for line in output.splitlines():
                if line.startswith("TRANSCRIPTION_RESULT:"):
                    transcription = line.replace("TRANSCRIPTION_RESULT:", "").strip()
                    break
            
            self.finished_signal.emit(transcription)
            
        except Exception as e:
            print(f"AudioWorker Error: {e}")
            self.finished_signal.emit("")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        
        # 主题模式标志
        self.is_dark_mode = False
        
        # Initialize Audio Recorder
        self.recorder = AudioRecorder()
        self.is_recording = False

        # 初始化日志记录
        self.init_file_logging()

        # 重定向 stdout 和 stderr (尽早进行，以捕获初始化日志)
        sys.stdout = EmittingStream()
        sys.stderr = EmittingStream()
        sys.stdout.output_signal.connect(self.append_text)
        sys.stderr.output_signal.connect(self.append_error)

        # 初始化界面
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} MainWindow 开始初始化")
        
        self.init_ui()
        # Window will be shown after Action Plan generation completes
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} MainWindow 初始化完成，等待 Action Plan 生成...")

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

        QTimer.singleShot(0, self._start_bootstrap_thread)

    def _start_bootstrap_thread(self):
        """Start bootstrap in a thread to prevent UI freeze."""
        from threading import Thread
        self._bootstrap_thread = Thread(target=self._bootstrap_runtime_safe, daemon=True)
        self._bootstrap_thread.start()

    def _bootstrap_runtime_safe(self):
        """Wrapper to safely run bootstrap_runtime and handle exceptions."""
        try:
            self.bootstrap_runtime()
        except Exception as e:
            print(f"[ERROR] Bootstrap failed: {e}", file=sys.stderr)

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
        
    def init_file_logging(self):
        # 确保 logs 目录存在
        self.logs_dir = os.path.join(os.getcwd(), 'logs')
        if not os.path.exists(self.logs_dir):
            os.makedirs(self.logs_dir)
            print(f"Created logs directory: {self.logs_dir}")
            
        # 设置今日日志文件路径
        date_str = datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
        self.log_file_path = os.path.join(self.logs_dir, f"log_{date_str}.log")
        print(f"Logging to file: {self.log_file_path}")

        # 设置全局异常捕获
        sys.excepthook = self.exception_hook

    def exception_hook(self, exctype, value, tb):
        """捕获未处理的异常并记录到日志"""
        # 格式化异常信息
        error_msg = "".join(traceback.format_exception(exctype, value, tb))
        
        # 打印到控制台（会被重定向的 stderr 捕获）
        sys.__stderr__.write(error_msg)
        
        # 强制写入日志文件
        self.log_to_file(f"[CRITICAL ERROR] Uncaught Exception:\n{error_msg}")
        
    def log_to_file(self, text):
        try:
            with open(self.log_file_path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception as e:
            sys.__stderr__.write(f"Failed to write to log file: {e}\n")


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
        self.is_dark_mode = False
        palette = QPalette()
        # 背景颜色
        palette.setColor(QPalette.ColorRole.Window, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(245, 245, 245))
        # 文本颜色
        palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Text, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(128, 128, 128))
        # 按钮颜色
        palette.setColor(QPalette.ColorRole.Button, QColor(240, 240, 240))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(0, 0, 0))
        # 高亮颜色
        palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 120, 215))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        
        QApplication.instance().setPalette(palette)
        self._apply_theme_styles()
        print("已切换到浅色主题")

    def set_dark_theme(self):
        self.is_dark_mode = True
        palette = QPalette()
        # 背景颜色
        palette.setColor(QPalette.ColorRole.Window, QColor(45, 45, 45))
        palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
        # 文本颜色
        palette.setColor(QPalette.ColorRole.WindowText, QColor(230, 230, 230))
        palette.setColor(QPalette.ColorRole.Text, QColor(230, 230, 230))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(150, 150, 150))
        # 按钮颜色
        palette.setColor(QPalette.ColorRole.Button, QColor(60, 60, 60))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(230, 230, 230))
        # 高亮颜色
        palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        
        QApplication.instance().setPalette(palette)
        self._apply_theme_styles()
        print("已切换到深色主题")
    
    def _apply_theme_styles(self):
        """根据当前主题应用样式到各个组件"""
        if self.is_dark_mode:
            # 深色主题样式
            chat_bg = "#2d2d2d"
            input_style = "font-size: 14px; padding: 5px; background-color: #3d3d3d; color: #e6e6e6; border: 1px solid #555;"
            btn_style = "font-size: 14px; font-weight: bold; padding-left: 15px; padding-right: 15px; background-color: #404040; color: #e6e6e6;"
        else:
            # 浅色主题样式
            chat_bg = "#ffffff"
            input_style = "font-size: 14px; padding: 5px; background-color: #ffffff; color: #000000; border: 1px solid #ccc;"
            btn_style = "font-size: 14px; font-weight: bold; padding-left: 15px; padding-right: 15px;"
        
        # 应用到Chat组件
        if hasattr(self, 'chat_history_text'):
            self.chat_history_text.setStyleSheet(f"border: none; background-color: {chat_bg};")
        if hasattr(self, 'chat_input'):
            self.chat_input.setStyleSheet(input_style)
        if hasattr(self, 'voice_btn'):
            self.voice_btn.setStyleSheet(btn_style)
        if hasattr(self, 'chat_send_btn'):
            self.chat_send_btn.setStyleSheet(btn_style.replace("15px", "20px"))
    # 显示摄像头画面

    def display_frame(self, frame):
        # 将 OpenCV 图像转换为 PyQt 可以显示的格式
        image = QImage(frame, frame.shape[1], frame.shape[0], QImage.Format.Format_RGB8888)
        pixmap = QPixmap.fromImage(image)
        self.camera_label.setPixmap(pixmap)

    # 显示 run_task 处理结果
    def display_task_result(self, result):
        self.text_edit.append(result)  # 显示到文本框中

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

            self.camera_label.setPixmap(scaled_image)

    # ========== ACTION PLAN TAB ==========
    def init_action_plan_tab(self):
        from PyQt6.QtWidgets import QSplitter
        
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Create Tab Widget for "Plan" and "Chat"
        self.sub_tab_widget = QTabWidget()
        
        # --- TAB 1: Analysis & Plan (Original View) ---
        plan_widget = QWidget()
        plan_layout = QVBoxLayout(plan_widget)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left: Analysis
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_label = QLabel("📊 总体回复 (General Analysis)")
        left_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        self.action_plan_left_text = QTextEdit()
        self.action_plan_left_text.setReadOnly(True)
        self.action_plan_left_text.setObjectName("logView")
        self.action_plan_left_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        left_layout.addWidget(left_label)
        left_layout.addWidget(self.action_plan_left_text)
        
        # Right: Plan
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_label = QLabel("📝 今日计划 (Today's Action Plan)")
        right_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        self.action_plan_right_text = QTextEdit()
        self.action_plan_right_text.setReadOnly(True)
        self.action_plan_right_text.setObjectName("logView")
        self.action_plan_right_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        right_layout.addWidget(right_label)
        right_layout.addWidget(self.action_plan_right_text)
        
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        
        plan_layout.addWidget(splitter)
        self.sub_tab_widget.addTab(plan_widget, "📋 计划详情 (Plan)")
        
        # --- TAB 2: Chat (New Voice Interaction) ---
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.setSpacing(10)
        
        # Chat History with Bubble Style
        self.chat_history_text = QTextEdit()
        self.chat_history_text.setReadOnly(True)
        self.chat_history_text.setStyleSheet("border: none; background-color: #ffffff;") 
        chat_layout.addWidget(self.chat_history_text, stretch=1)
        
        # Controls Area
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0) # Zero margins for inner layout
        controls_layout.setSpacing(10)
        
        # Chat Input (Left, stretches)
        self.chat_input = QTextEdit()
        self.chat_input.setPlaceholderText("Type a message...")
        self.chat_input.setFixedHeight(50) 
        self.chat_input.setStyleSheet("font-size: 14px; padding: 5px;")
        self.chat_input.installEventFilter(self)
        
        # Voice Button (Right, Auto Width)
        self.voice_btn = QPushButton("🎤 Record")
        self.voice_btn.setToolTip("Click to Toggle Recording")
        self.voice_btn.setFixedHeight(50) # Fixed height only
        self.voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.voice_btn.setStyleSheet("font-size: 14px; font-weight: bold; padding-left: 15px; padding-right: 15px;")
        self.voice_btn.clicked.connect(self.toggle_recording)

        # Send Button (Right, Auto Width)
        self.chat_send_btn = QPushButton("Send")
        self.chat_send_btn.setToolTip("Send Message (Ctrl+Enter)")
        self.chat_send_btn.setFixedHeight(50) # Fixed height only
        self.chat_send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chat_send_btn.setStyleSheet("font-size: 14px; font-weight: bold; padding-left: 20px; padding-right: 20px;")
        self.chat_send_btn.clicked.connect(self.send_chat_message)
        
        # Layout: Input (Stretch) -> Voice (Fixed) -> Send (Fixed)
        controls_layout.addWidget(self.chat_input, 1) 
        controls_layout.addWidget(self.voice_btn, 0)  
        controls_layout.addWidget(self.chat_send_btn, 0) 
        
        chat_layout.addLayout(controls_layout)
        
        self.sub_tab_widget.addTab(chat_widget, "💬 对话 (Chat)")
        
        layout.addWidget(self.sub_tab_widget)

        # Bottom Bar: Stats & Regenerate
        bottom_layout = QHBoxLayout()
        self.action_plan_stats_label = QLabel("")
        bottom_layout.addWidget(self.action_plan_stats_label)
        
        self.action_plan_regen_btn = QPushButton("🔄 重新生成 (Regenerate)")
        self.action_plan_regen_btn.setFixedHeight(40)
        self.action_plan_regen_btn.clicked.connect(self.start_action_plan_generation)
        bottom_layout.addWidget(self.action_plan_regen_btn)
        
        layout.addLayout(bottom_layout)

        return tab

    def eventFilter(self, obj, event):
        if obj == self.chat_input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                self.send_chat_message()
                return True
        return super().eventFilter(obj, event)

    # --- CHAT & VOICE LOGIC ---
    def toggle_recording(self):
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        self.is_recording = True
        self.voice_btn.setText("🔴 Stop")
        self.voice_btn.setToolTip("Click to Stop Recording")
        self.voice_btn.setStyleSheet("background-color: #ffcccc; color: #cc0000; border: 1px solid #cc0000; font-size: 14px; font-weight: bold; padding-left: 15px; padding-right: 15px;")
        self.recorder.start_recording()
        self.chat_input.setPlaceholderText("Listening...")
        self.chat_input.setEnabled(False)

    def stop_recording(self):
        if not self.is_recording:
            return
        self.is_recording = False
        self.voice_btn.setText("🎤 Record")
        self.voice_btn.setToolTip("Click to Start Recording")
        self.voice_btn.setStyleSheet("font-size: 14px; font-weight: bold; padding-left: 15px; padding-right: 15px;") # Restore default style
        
        file_path = self.recorder.stop_recording()
        if file_path:
            self.chat_input.setPlaceholderText("Transcribing...")
            # Run transcription in worker
            self.audio_worker = AudioWorker(file_path)
            self.audio_worker.finished_signal.connect(self.on_transcription_finished)
            self.audio_worker.start()
        else:
            self.chat_input.setEnabled(True)
            self.chat_input.setPlaceholderText("Type a message...")

    def on_transcription_finished(self, text):
        self.chat_input.setEnabled(True)
        if text:
            self.chat_input.setPlainText(text)
            self.chat_input.setFocus()
        else:
            self.chat_input.setPlaceholderText("Transcription failed or empty.")

    def append_chat_bubble(self, role, text):
        # 根据主题选择颜色
        if self.is_dark_mode:
            user_bg = "#2d5a3d"  # 深绿色
            assistant_bg = "#3d3d3d"  # 深灰色
            text_color = "#e6e6e6"
            table_border = "#555"
            th_bg = "#404040"
        else:
            user_bg = "#dcf8c6"  # 浅绿色
            assistant_bg = "#f0f0f0"  # 浅灰色
            text_color = "#000000"
            table_border = "#ccc"
            th_bg = "#e0e0e0"
        
        # Allow HTML styling
        if role == "user":
            style = f"background-color: {user_bg}; color: {text_color}; padding: 10px; border-radius: 10px; margin: 5px; float: right; clear: both;"
            align = "right"
            prefix = "User"
        else:
            style = f"background-color: {assistant_bg}; color: {text_color}; padding: 10px; border-radius: 10px; margin: 5px; float: left; clear: both;"
            align = "left"
            prefix = "Assistant"
            
        # Table CSS to make them look good
        table_css = f"""
        <style>
        table {{ border-collapse: collapse; width: 100%; margin-top: 10px; margin-bottom: 10px; }}
        th, td {{ border: 1px solid {table_border}; padding: 6px; text-align: left; color: {text_color}; }}
        th {{ background-color: {th_bg}; font-weight: bold; }}
        </style>
        """

        # Convert markdown to html
        try:
            import markdown
            # Enable nl2br to preserve newlines, tables for grids
            formatted_text = markdown.markdown(text, extensions=['nl2br', 'tables'])
        except ImportError:
            formatted_text = text.replace("\n", "<br>")

        html = f"""
        <div style='width: 100%; overflow: hidden;'>
            <div style='{style} max-width: 80%;'>
                {table_css}
                <b>{prefix}:</b><br>{formatted_text}
            </div>
        </div>
        """
        self.chat_history_text.append(html)
        # Scroll to bottom
        cursor = self.chat_history_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.chat_history_text.setTextCursor(cursor)

    def send_chat_message(self):
        message = self.chat_input.toPlainText().strip()
        if not message:
            return

        self.chat_input.clear()
        self.append_chat_bubble("user", message)
        
        self.chat_input.setEnabled(False)
        self.chat_send_btn.setEnabled(False)
        self.chat_send_btn.setText("...")

        self.chat_worker = ChatWorker(message)
        self.chat_worker.output_signal.connect(self.on_chat_output_stream)
        self.chat_worker.finished_signal.connect(self.on_chat_finished)
        self.chat_worker.start()
        
        # 初始化流式响应缓存
        self.chat_response_buffer = ""
        self.chat_thinking_buffer = ""
        self.chat_streaming_started = False

    def on_chat_output_stream(self, text):
        from PyQt6.QtGui import QTextCursor
        
        # 跳过非内容行
        if text.startswith("Mode:") or text.startswith("Thinking") or text.startswith("---CHAT_START---"):
            return
        if text.startswith("STREAM_DONE:") or text.startswith("Context saved"):
            return
        
        # 跳过统计信息和系统输出
        skip_prefixes = [
            "STATS_JSON:", "======", "------", "本次会话统计", "对话轮数:", 
            "本次消耗", "历史总消耗", "Prompt:", "Completion:", "已更新统计报告",
            "历史总", "- Prompt", "- Completion", "="
        ]
        for prefix in skip_prefixes:
            if text.startswith(prefix) or text.strip().startswith(prefix):
                return
        
        # 跳过空行和纯符号行
        if not text.strip() or text.strip() in ["=", "-", "==", "--"]:
            return
        
        # 解析流式标记
        if text.startswith("STREAM_THINKING:"):
            thinking_chunk = text[len("STREAM_THINKING:"):]
            self.chat_thinking_buffer += thinking_chunk
            self._update_chat_status_indicator()
            return
        
        if text.startswith("STREAM_CONTENT:"):
            content_chunk = text[len("STREAM_CONTENT:"):]
            self.chat_response_buffer += content_chunk
            self._update_chat_status_indicator()
            return
        
        if text.startswith("STREAM_ERROR:"):
            error_msg = text[len("STREAM_ERROR:"):]
            self.chat_response_buffer += f"\n[Error: {error_msg}]"
            return
        
        # 兼容旧格式（非流式输出）- 但仍需过滤统计内容
        if "tokens" in text.lower() and ("prompt" in text.lower() or "completion" in text.lower()):
            return
        self.chat_response_buffer += text + "\n"
        self._update_chat_status_indicator()
    
    def _update_chat_status_indicator(self):
        """更新发送按钮显示进度"""
        # 显示已接收的字符数作为进度指示
        total_chars = len(self.chat_thinking_buffer) + len(self.chat_response_buffer)
        self.chat_send_btn.setText(f"... {total_chars}")

    def on_chat_finished(self, success, message):
        from PyQt6.QtGui import QTextCursor
        
        # 使用正确的气泡格式显示完整响应
        if self.chat_response_buffer or self.chat_thinking_buffer:
            full_response = ""
            if self.chat_thinking_buffer:
                full_response += f"💭 *思考:* {self.chat_thinking_buffer}\n\n"
            full_response += self.chat_response_buffer
            self.append_chat_bubble("assistant", full_response.strip())
        elif not success:
            self.append_chat_bubble("assistant", f"[Error: {message}]")

        # 重置状态
        self.chat_response_buffer = ""
        self.chat_thinking_buffer = ""
        self.chat_streaming_started = False
        self.chat_input.setEnabled(True)
        self.chat_send_btn.setEnabled(True)
        self.chat_send_btn.setText("发送 (Send)")
        self.chat_input.setFocus()

    def start_action_plan_generation(self):

        from PyQt6.QtGui import QTextCursor
        self.action_plan_left_text.clear()
        self.action_plan_right_text.clear()
        self.action_plan_current_target = "analysis"
        self.action_plan_accumulated_text = ""
        self.action_plan_accumulated_thinking = ""
        self.action_plan_plan_text = ""
        self.action_plan_plan_thinking = ""
        
        self.action_plan_left_text.setMarkdown("### ⏳ 正在分析数据 (Analyzing Data)...\n\n")
        self.action_plan_right_text.setMarkdown("### ⏳ 等待生成计划 (Waiting for Plan)...\n\n")
        
        self.action_plan_regen_btn.setEnabled(False)
        
        self.action_plan_worker = ActionPlanWorker()
        self.action_plan_worker.output_signal.connect(self.append_action_plan_log)
        self.action_plan_worker.finished_signal.connect(self.on_action_plan_finished)
        self.action_plan_worker.stats_signal.connect(self.update_action_plan_stats)
        self.action_plan_worker.start()

    def render_markdown_to_html(self, text):
        # 根据主题选择颜色
        if self.is_dark_mode:
            heading_color = "#e6e6e6"
            code_bg = "#3d3d3d"
            blockquote_border = "#666"
            blockquote_text = "#aaa"
            table_border = "#555"
            th_bg = "#404040"
            tr_even_bg = "#353535"
            thinking_color = "#aaa"
            thinking_bg = "#3a3a3a"
        else:
            heading_color = "#333"
            code_bg = "#f0f0f0"
            blockquote_border = "#ccc"
            blockquote_text = "#666"
            table_border = "#ddd"
            th_bg = "#f5f5f5"
            tr_even_bg = "#fafafa"
            thinking_color = "#888"
            thinking_bg = "#f9f9f9"
        
        style = f"""
        <style>
        h1, h2, h3 {{ color: {heading_color}; margin-top: 20px; margin-bottom: 10px; }}
        p {{ line-height: 1.6; margin-bottom: 10px; }}
        ul, ol {{ margin-bottom: 10px; margin-left: 20px; }}
        li {{ margin-bottom: 5px; }}
        code {{ background-color: {code_bg}; padding: 2px 4px; border-radius: 4px; font-family: monospace; }}
        pre {{ background-color: {code_bg}; padding: 10px; border-radius: 5px; margin-bottom: 15px; }}
        blockquote {{ border-left: 4px solid {blockquote_border}; padding-left: 10px; color: {blockquote_text}; margin-bottom: 15px; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 15px; margin-bottom: 15px; }}
        th, td {{ border: 1px solid {table_border}; padding: 8px; text-align: left; }}
        th {{ background-color: {th_bg}; font-weight: bold; }}
        tr:nth-child(even) {{ background-color: {tr_even_bg}; }}
        .thinking {{ color: {thinking_color}; font-style: italic; background-color: {thinking_bg}; padding: 10px; border-radius: 5px; margin-bottom: 15px; border-left: 3px solid {blockquote_border}; }}
        </style>
        """
        try:
            import markdown
            html_content = markdown.markdown(text, extensions=['nl2br', 'tables', 'fenced_code'])
            return style + html_content
        except ImportError:
            return f"<pre>{text}</pre>"

    def render_with_thinking(self, thinking_text, content_text):
        """渲染包含思考内容的HTML"""
        # 根据主题选择颜色
        if self.is_dark_mode:
            heading_color = "#e6e6e6"
            code_bg = "#3d3d3d"
            blockquote_border = "#666"
            blockquote_text = "#aaa"
            table_border = "#555"
            th_bg = "#404040"
            thinking_color = "#aaa"
            thinking_bg = "#3a3a3a"
        else:
            heading_color = "#333"
            code_bg = "#f0f0f0"
            blockquote_border = "#ccc"
            blockquote_text = "#666"
            table_border = "#ddd"
            th_bg = "#f5f5f5"
            thinking_color = "#888"
            thinking_bg = "#f9f9f9"
        
        style = f"""
        <style>
        h1, h2, h3 {{ color: {heading_color}; margin-top: 20px; margin-bottom: 10px; }}
        p {{ line-height: 1.6; margin-bottom: 10px; }}
        ul, ol {{ margin-bottom: 10px; margin-left: 20px; }}
        li {{ margin-bottom: 5px; }}
        code {{ background-color: {code_bg}; padding: 2px 4px; border-radius: 4px; font-family: monospace; }}
        pre {{ background-color: {code_bg}; padding: 10px; border-radius: 5px; margin-bottom: 15px; }}
        blockquote {{ border-left: 4px solid {blockquote_border}; padding-left: 10px; color: {blockquote_text}; margin-bottom: 15px; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 15px; margin-bottom: 15px; }}
        th, td {{ border: 1px solid {table_border}; padding: 8px; text-align: left; }}
        th {{ background-color: {th_bg}; font-weight: bold; }}
        </style>
        """
        
        html = style
        
        # 添加思考区域
        if thinking_text:
            html += f'<div style="color: {thinking_color}; font-style: italic; background-color: {thinking_bg}; padding: 10px; border-radius: 5px; margin-bottom: 15px; border-left: 3px solid {blockquote_border};"><b>💭 思考过程:</b><br>{thinking_text}</div>'
        
        # 添加正文内容
        if content_text:
            try:
                import markdown
                html += markdown.markdown(content_text, extensions=['nl2br', 'tables', 'fenced_code'])
            except ImportError:
                html += f"<pre>{content_text}</pre>"
        
        return html

    def append_action_plan_log(self, text):
        from PyQt6.QtGui import QTextCursor
        
        # 检测阶段切换标记
        if "---ANALYSIS_START---" in text:
            self.action_plan_current_target = "analysis"
            self.action_plan_accumulated_text = ""
            self.action_plan_accumulated_thinking = ""
            self.action_plan_left_text.clear()
            return
        
        if "---PLAN_START---" in text:
            self.action_plan_current_target = "plan"
            self.action_plan_plan_text = ""
            self.action_plan_plan_thinking = ""
            self.action_plan_right_text.clear()
            self.action_plan_right_text.append("🚀 开始生成计划...\n")
            return

        if "初始分析已完成。正在生成今日行动建议..." in text:
            # 阶段切换提示
            return
        
        # 解析流式标记
        if text.startswith("STREAM_THINKING:"):
            thinking_chunk = text[len("STREAM_THINKING:"):]
            if self.action_plan_current_target == "analysis":
                self.action_plan_accumulated_thinking += thinking_chunk
                # 实时更新思考内容显示
                self._update_analysis_display()
            else:
                self.action_plan_plan_thinking += thinking_chunk
                self._update_plan_display()
            return
        
        if text.startswith("STREAM_CONTENT:"):
            content_chunk = text[len("STREAM_CONTENT:"):]
            if self.action_plan_current_target == "analysis":
                self.action_plan_accumulated_text += content_chunk
                self._update_analysis_display()
            else:
                self.action_plan_plan_text += content_chunk
                self._update_plan_display()
            return
        
        if text.startswith("STREAM_DONE:") or text.startswith("STREAM_ERROR:"):
            return
        
        # 兼容旧格式的非流式输出
        if self.action_plan_current_target == "analysis":
            self.action_plan_accumulated_text += text + "\n"
            self._update_analysis_display()
        else:
            self.action_plan_plan_text += text + "\n"
            self._update_plan_display()
    
    def _update_analysis_display(self):
        """更新分析区域的显示"""
        from PyQt6.QtGui import QTextCursor
        
        html = self.render_with_thinking(
            self.action_plan_accumulated_thinking, 
            self.action_plan_accumulated_text
        )
        self.action_plan_left_text.setHtml(html)
        self.action_plan_left_text.moveCursor(QTextCursor.MoveOperation.End)
    
    def _update_plan_display(self):
        """更新计划区域的显示"""
        from PyQt6.QtGui import QTextCursor
        
        html = self.render_with_thinking(
            self.action_plan_plan_thinking, 
            self.action_plan_plan_text
        )
        self.action_plan_right_text.setHtml(html)
        self.action_plan_right_text.moveCursor(QTextCursor.MoveOperation.End)

    def update_action_plan_stats(self, stats):
        # 历史总tokens以百万计算
        historical_tokens = stats.get('historical_total_tokens', 0)
        historical_m = historical_tokens / 1_000_000
        
        text = (
            f"📊 <b>Session:</b> "
            f"Speed: {stats.get('speed', 'N/A')} | "
            f"Time: {stats.get('total_duration', 0):.1f}s | "
            f"Tokens: {stats.get('total_tokens', 0):,} | "
            f"<b>History:</b> {historical_m:.2f}M tokens"
        )
        self.action_plan_stats_label.setText(text)
        self.action_plan_stats_label.show()

    def on_action_plan_finished(self, success, message):
        from PyQt6.QtGui import QTextCursor
        self.action_plan_right_text.moveCursor(QTextCursor.MoveOperation.End)
        self.action_plan_right_text.insertPlainText(f"\n\n**Status**: {message}\n\n")
        
        if success:
            self.load_action_plan_file()
            # Populate Chat Tab with initial analysis and plan
            analysis_text = self.action_plan_left_text.toPlainText()
            plan_text = self.action_plan_right_text.toPlainText()
            combined_text = f"**General Analysis**:\n{analysis_text}\n\n**Today's Action Plan**:\n{plan_text}"
            self.append_chat_bubble("assistant", combined_text)
        
        self.action_plan_regen_btn.setEnabled(True)
        
        # Show window after Action Plan generation completes
        if not self.isVisible():
            self.show()
            print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Action Plan 已生成，显示主窗口")

    def load_action_plan_file(self):
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m%d')
        pattern = f"action_plan_{date_str}_"
        
        possible_history_dirs = [
            os.path.join("history"),
            os.path.join("..", "history"),
            os.path.join(os.path.expanduser("~"), "gitee", "ai", "history")
        ]
        
        target_file = None
        
        for history_dir in possible_history_dirs:
            if not os.path.exists(history_dir):
                continue
            try:
                files = os.listdir(history_dir)
                plan_files = [f for f in files if f.startswith(pattern) and f.endswith(".md")]
                if plan_files:
                    plan_files.sort(reverse=True)
                    target_file = os.path.join(history_dir, plan_files[0])
                    break
            except Exception:
                continue
        
        if target_file and os.path.exists(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    self.action_plan_right_text.setHtml(self.render_markdown_to_html(content))
            except Exception as e:
                self.action_plan_right_text.setText(f"Error reading file {target_file}: {e}")
        else:
            msg = f"# No Plan Found for Today :(\n\nLooking for pattern: `{pattern}*.md`"
            self.action_plan_right_text.setHtml(self.render_markdown_to_html(msg))

    # ========== PLOTS TAB ==========
    def init_plots_tab(self):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)
        
        # Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setObjectName("plotScrollArea")
        
        # Container widget with grid layout
        self.plot_grid_container = QWidget()
        self.plot_grid_layout = QGridLayout(self.plot_grid_container)
        self.plot_grid_layout.setSpacing(12)
        self.plot_grid_layout.setContentsMargins(16, 16, 16, 16)
        
        # Placeholder label
        self.plot_loading_label = QLabel("⏳ 点击下方按钮生成图表...")
        self.plot_loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plot_loading_label.setObjectName("plotPlaceholder")
        self.plot_loading_label.setStyleSheet("font-size: 16px; color: #888;")
        self.plot_grid_layout.addWidget(self.plot_loading_label, 0, 0)
        
        scroll.setWidget(self.plot_grid_container)
        tab_layout.addWidget(scroll, stretch=1)
        
        # Refresh Button - Fixed at bottom
        refresh_btn = QPushButton("🔄 刷新图表 (Refresh Plots)")
        refresh_btn.setObjectName("actionButton")
        refresh_btn.setFixedHeight(48)
        refresh_btn.clicked.connect(self.refresh_plots)
        tab_layout.addWidget(refresh_btn)
        
        return tab

    def refresh_plots(self):
        # Show loading state
        self._clear_plot_grid()
        self.plot_loading_label = QLabel("⏳ 正在生成图表，请稍候...")
        self.plot_loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plot_loading_label.setStyleSheet("font-size: 18px; color: #888; padding: 40px;")
        self.plot_grid_layout.addWidget(self.plot_loading_label, 0, 0)
        
        is_dark = self.is_dark_mode
        self.plot_worker = PlotWorker(is_dark_mode=is_dark)
        self.plot_worker.finished_signal.connect(self.on_plot_finished)
        self.plot_worker.start()
    
    def _clear_plot_grid(self):
        """Clear all widgets from the plot grid layout."""
        while self.plot_grid_layout.count():
            item = self.plot_grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def on_plot_finished(self, success, message):
        self._clear_plot_grid()
        
        if not success:
            error_label = QLabel(f"❌ {message}")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_label.setStyleSheet("font-size: 16px; color: #ff6666; padding: 40px;")
            self.plot_grid_layout.addWidget(error_label, 0, 0)
            return
        
        # Load the merged collage image
        plot_dir = os.path.join(os.getcwd(), "plot_outputs")
        collage_path = os.path.join(plot_dir, "plot_collage.png")
        
        if not os.path.exists(collage_path):
            error_label = QLabel("❌ 未找到合并图表文件")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.plot_grid_layout.addWidget(error_label, 0, 0)
            return
        
        # Create image label for collage
        img_label = QLabel()
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_label.setObjectName("plotImage")
        
        try:
            from PyQt6.QtGui import QImageReader
            reader = QImageReader(collage_path)
            reader.setAutoTransform(True)
            image = reader.read()
            
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                # Get available size from parent scroll area (use window size as reference)
                available_width = int(self.width() * 0.95)
                available_height = int(self.height() * 0.85)
                
                # Scale to fit window while keeping aspect ratio
                scaled_pixmap = pixmap.scaled(
                    available_width, available_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                img_label.setPixmap(scaled_pixmap)
                print(f"Loaded collage: {pixmap.width()}x{pixmap.height()} -> scaled to {scaled_pixmap.width()}x{scaled_pixmap.height()}")
            else:
                error_msg = reader.errorString()
                print(f"Failed to load collage: {error_msg}")
                img_label.setText(f"⚠️ 无法加载合并图表")
        except Exception as e:
            print(f"Exception loading collage: {e}")
            img_label.setText("⚠️ 加载错误")
        
        self.plot_grid_layout.addWidget(img_label, 0, 0)

    def init_dashboard_tab(self):
        tab = QWidget()

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setObjectName("logView")
        
        # Log Section Layout
        log_layout = QVBoxLayout()
        log_title = QLabel("📝 运行日志 (System Logs)")
        log_title.setObjectName("sectionTitle")
        log_layout.addWidget(log_title)
        log_layout.addWidget(self.text_edit)

        # ✅ 设置字体和大小
        font = QFont('Consolas', 14)  # 字体：Consolas，大小：14
        self.text_edit.setFont(font)
        self.text_edit.setMinimumHeight(220)



        # 创建主布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)
        # main_layout.addWidget(self.text_edit)
        main_layout.addLayout(log_layout)

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

        camera_title = QLabel("📷 实时监控 (Camera Feed)")
        camera_title.setObjectName("sectionTitle")
        camera_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        camera_layout.insertWidget(0, camera_title) # Add to top
        
        camera_layout.addWidget(self.camera_label)

        photo_layout = QVBoxLayout()
        # 创建左侧的标签，用于显示照片文件名
        self.photo_filename_label = QLabel(self)
        self.photo_filename_label.setObjectName("filenameLabel")
        self.photo_filename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 设置文本居中显示
        
        photo_title = QLabel("🖼️ 最新照片 (Latest Photo)")
        photo_title.setObjectName("sectionTitle")
        photo_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        photo_layout.addWidget(photo_title)
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
        
        screenshot_title = QLabel("🖥️ 最新截图 (Latest Screenshot)")
        screenshot_title.setObjectName("sectionTitle")
        screenshot_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        screenshot_layout.addWidget(screenshot_title)
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

        # 组合布局
        main_layout.addLayout(photo_and_screenshot_layout)

        tab.setLayout(main_layout)
        return tab

    def init_ui(self):
        # Window setup
        self.setWindowTitle('Vantage - 任务管理器')
        self.main_window_size = (800, 800)
        
        # NOTE: resize_window logic calls default implementation or customized in class
        # But we need to call it before creating widgets if it sets self.main_window_size used by widgets
        # The original code set self.main_window_size then called resize_window which calculates centering
        # then widgets used self.main_window_size.
        # So we must call it early.
        self.resize_window() # Sets size and position

        self.init_tray_icon()
        
        # --- TAB SETUP ---
        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")
        
        # Add Tabs - Action Plan FIRST
        self.tabs.addTab(self.init_action_plan_tab(), "📅 今日计划 (Action Plan)")
        self.tabs.addTab(self.init_dashboard_tab(), "📊 仪表盘 (Dashboard)")
        self.tabs.addTab(self.init_plots_tab(), "📈 数据图表 (Plots)")
        
        # Main Layout
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)
        self.setLayout(layout)
        
        # Final Setup
        self.apply_style()
        
        # Listeners
        self.installEventFilter(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        
        # Auto-start Action Plan generation on startup
        QTimer.singleShot(1000, self.start_action_plan_generation)
        
        # Auto-refresh plots on startup (slightly delayed to let UI initialize)
        QTimer.singleShot(2000, self.refresh_plots)

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
    def changeEvent(self, event):
        if event.type() == QEvent.Type.PaletteChange:
            self.apply_style()
            self.refresh_plots()
        super().changeEvent(event)

    def append_text(self, text):
        if not hasattr(self, 'text_edit'):
            return
        color = "white" if self.is_dark_mode else "black"
        self.text_edit.append(f"<span style='color:{color};'>{text}</span>")
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.log_to_file(text)

    # 错误输出
    def append_error(self, text):
        if not hasattr(self, 'text_edit'):
            return
        error_color = "#FF6666" if self.is_dark_mode else "red"
        self.text_edit.append(f"<span style='color:{error_color};'>{text}</span>")
        self.log_to_file(f"[ERROR] {text}")

    # 托盘菜单
    def init_tray_icon(self):
        # 创建系统托盘图标
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon('icon.png'))  # 图标路径

        # 创建托盘菜单
        tray_menu = QMenu()
        
        restore_action = QAction("🖥️ 恢复窗口", self)
        restore_action.triggered.connect(self.request_password)
        
        quit_action = QAction("❌ 退出", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        
        tray_menu.addAction(restore_action)
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
        # Simplified Style using System Palette
        # We rely on QPalette for base colors (Window, Text, Base)
        # We only style specific components to add structure without forcing colors
        
        is_dark = self.is_dark_mode
        
        if is_dark:
            # Dark Mode
            text_color = "#ffffff"
            border_color = "#444444" 
            text_edit_bg = "#1e1e1e"
            label_border = "#555555"
            btn_text = "#ffffff"
            secondary_btn_border = "#666666"
            secondary_btn_hover = "#0d6efd"
            menu_bg = "#2b2b2b"
            menu_border = "#444444"
            menu_item_hover = "#0d6efd"
        else:
            # Light Mode
            text_color = "#000000"
            border_color = "#cccccc"
            text_edit_bg = "#ffffff"
            label_border = "#cccccc"
            btn_text = "#000000"
            secondary_btn_border = "#cccccc"
            secondary_btn_hover = "#0066cc"
            menu_bg = "#ffffff"
            menu_border = "#cccccc"
            menu_item_hover = "#0066cc"

        self.setStyleSheet(f"""
            QWidget {{
                font-family: "Segoe UI", "Inter", "Microsoft YaHei";
                font-size: 14px;
            }}
            
            /* Section Titles */
            QLabel#sectionTitle {{
                font-size: 14px;
                font-weight: bold;
                /* color: {text_color}; */
                padding-bottom: 4px;
            }}
            
            /* Logs Area */
            QTextEdit#logView {{
                border: 1px solid {border_color};
                background-color: {text_edit_bg};
                color: {text_color};
                border-radius: 8px;
                padding: 8px;
            }}
            
            /* Time Label - Keep distinctive but possibly adapt border */
            QLabel#timeLabel {{
                background-color: #0066cc; /* Keep accent color for time */
                color: #ffffff;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 18px;
                font-weight: bold;
            }}
            
            /* Image Preview Labels */
            QLabel#previewLabel {{
                border: 1px solid {label_border};
                border-radius: 8px;
                padding: 2px;
            }}
            
            /* Filename Labels */
            QLabel#filenameLabel {{
                /* Use a translucent background or border instead of fixed color */
                border: 1px solid {label_border};
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: 500;
            }}
            
            /* Buttons - Standardize with slight modernization */
            QPushButton {{
                padding: 10px 18px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 14px;
            }}
            
            QPushButton#primaryButton {{
                background-color: #0066cc;
                color: white;
                border: none;
            }}
            QPushButton#primaryButton:hover {{
                background-color: #0052a3;
            }}
            
            QPushButton#secondaryButton {{
                border: 1px solid {secondary_btn_border};
                color: {text_color};
                background-color: transparent;
            }}
            QPushButton#secondaryButton:hover {{
                border-color: {secondary_btn_hover};
            }}
            
            QPushButton#actionButton {{
                background-color: #34c759;
                color: white;
                border: none;
            }}
            QPushButton#actionButton:hover {{
                background-color: #248a3d;
            }}
            
            /* Menu */
            QMenu {{
                background-color: {menu_bg};
                border: 1px solid {menu_border};
                padding: 5px;
                border-radius: 6px;
            }}
            QMenu::item {{
                padding: 6px 20px;
                border-radius: 4px;
                color: {text_color};
            }}
            QMenu::item:selected {{
                background-color: {menu_item_hover};
                color: white;
            }}

            /* Tabs */
            QTabWidget::pane {{
                border: 1px solid {border_color};
                border-radius: 6px;
                top: -1px; 
            }}
            QTabBar::tab {{
                background: {menu_bg};
                border: 1px solid {border_color};
                padding: 8px 12px;
                margin-right: 4px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                color: {text_color};
            }}
            QTabBar::tab:selected {{
                background: {secondary_btn_hover};
                color: white;
                border-color: {secondary_btn_hover};
            }}
            
            /* Scroll Area */
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
            QScrollArea#plotScrollArea {{
                background-color: {text_edit_bg};
            }}
            
            /* Plot Cards */
            QWidget#plotCard {{
                background-color: {menu_bg};
                border: 1px solid {border_color};
                border-radius: 12px;
                padding: 0px;
            }}
            QWidget#plotCard:hover {{
                border-color: {secondary_btn_hover};
            }}
            
            QLabel#plotImage {{
                padding: 8px;
            }}
            
            QLabel#plotTitle {{
                color: {text_color};
                font-size: 11px;
                padding: 4px 8px 8px 8px;
            }}
            
            QLabel#plotPlaceholder {{
                color: {text_color};
                font-size: 16px;
                padding: 60px;
            }}
        """)
            


    def update_tray_icon_tooltip(self):
        """更新托盘图标的提示文本"""
        # 获取当前任务状态或任何你想要显示的信息
        tooltip_text = "任务管理器 - 运行中..."  # 替换为你实际的状态信息
        self.tray_icon.setToolTip(tooltip_text)

