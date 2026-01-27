from PyQt6.QtWidgets import (
    QApplication, QWidget, QTextEdit, QLabel, QVBoxLayout, QHBoxLayout,
    QInputDialog, QLineEdit, QMessageBox, QSystemTrayIcon, QMenu, QPushButton,
    QTabWidget, QScrollArea, QGridLayout
)
from PyQt6.QtGui import QPalette, QColor, QImage, QPixmap, QAction, QFont, QIcon, QTextCursor
from PyQt6.QtCore import QTimer, QEvent, Qt, QDateTime, QThread, pyqtSignal, QUrl, QObject, pyqtSlot
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
import subprocess
import os
import sys
import shutil
import cv2
import traceback
import json
from datetime import datetime
from manager.manager_main import Monitor
from .worker import WorkerThread
from .emitting_stream import EmittingStream
from cv2_enumerate_cameras import enumerate_cameras

class ChatBridge(QObject):
    """Bridge for communication between Python and Web JS"""
    messageSent = pyqtSignal(str)

    @pyqtSlot(str)
    def sendMessageToPython(self, text):
        # Triggered from JS
        self.messageSent.emit(text)


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

    def __init__(self, context_file=None):
        super().__init__()
        self.context_file = context_file

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
            
            cmd = [sys.executable, script_path]
            if self.context_file:
                cmd.extend(["--context_file", self.context_file])

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
                    if line.startswith("STATS_JSON:"):
                        try:
                            import json
                            json_str = line.replace("STATS_JSON:", "").strip()
                            stats = json.loads(json_str)
                            self.stats_signal.emit(stats)
                        except Exception:
                            pass
                        continue  # Skip emitting STATS_JSON to UI

                    if line.startswith("Response saved to:") or line.startswith("已生成今日行动建议:"):
                         # Optional: Log to console but skip UI
                         print(f"[ActionPlanWorker] {line.strip()}")
                         continue

                    self.output_signal.emit(line.strip())

            stderr_bytes = process.stderr.read()
            if stderr_bytes:
                try:
                    stderr = stderr_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    stderr = stderr_bytes.decode('utf-8', errors='replace')
                # Filter out INFO logs from STDERR that clutter the UI
                if "INFO" in stderr or "Mode:" in stderr:
                     print(f"[ActionPlanWorker] STDERR (Hidden): {stderr}")
                else:
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
                 # Should have been passed, but fallback to relative path if not
                 # logic usually handled by caller
                 pass

            cmd = [
                sys.executable, 
                script_path, 
                "--chat_message", self.message
            ]
            
            if self.context_file:
                 cmd.extend(["--context_file", self.context_file])
            
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
                    
                    if line.startswith("STATS_JSON:"):
                        continue
                    if line.startswith("Response saved to:") or line.startswith("已生成今日行动建议:"):
                         print(f"[ChatWorker] {line.strip()}")
                         continue

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
        photos_path = os.path.join(pictures_path, "本机照片")
        if not os.path.exists(photos_path):
             # Fallback if "本机照片" doesn't exist
             photos_path = pictures_path

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
            btn_style = "font-size: 14px; font-weight: bold; padding-left: 15px; padding-right: 15px; background-color: #404040; color: #e6e6e6;"
            theme_mode = "dark"
        else:
            # 浅色主题样式
            btn_style = "font-size: 14px; font-weight: bold; padding-left: 15px; padding-right: 15px;"
            theme_mode = "light"
        
        # 应用到Chat组件
        if hasattr(self, 'web_view'):
            # Call JS to set theme
             self.web_view.page().runJavaScript(f"setTheme('{theme_mode}')")

        if hasattr(self, 'voice_btn'):
            self.voice_btn.setStyleSheet(btn_style)

    # Shared Context File Path
    @property
    def SHARED_CONTEXT_FILE(self):
        # Use a fixed path for both Action Plan and Chat
        # This ensures they share the same history
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
        history_dir = os.path.join(root_dir, "history")
        if not os.path.exists(history_dir):
            os.makedirs(history_dir)
        return os.path.join(history_dir, "latest_context.json")

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
        try:
            if not self.cam.isOpened():
                return
                
            ret, frame = self.cam.read()
            if ret and hasattr(self, 'camera_label') and self.camera_label.isVisible():
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = frame.shape
                bytes_per_line = ch * w
                qt_image = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                
                # Double check before accessing C++ object
                if self.camera_label is None: 
                    return
                    
                # 获取标签的大小
                try:
                    label_size = self.camera_label.size()
                except RuntimeError:
                    return # Widget deleted

                # 使用scaled方法，调整顺序
                scaled_image = QPixmap.fromImage(qt_image).scaled(
                    label_size,
                    Qt.AspectRatioMode.KeepAspectRatio,  # 保持宽高比
                    Qt.TransformationMode.FastTransformation  # 快速变换
                )

                self.camera_label.setPixmap(scaled_image)
        except Exception as e:
            pass # Suppress closing errors

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
        
        # --- TAB 2: Chat (New Web Interaction) ---
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)
        
        # Web View for Chat
        self.web_view = QWebEngineView()
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu) # Optional
        
        # Setup WebChannel
        self.channel = QWebChannel()
        self.bridge = ChatBridge()
        self.bridge.messageSent.connect(self.handle_web_message)
        self.channel.registerObject("chatBridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        
        # Load index.html
        current_dir = os.path.dirname(os.path.abspath(__file__))
        url = QUrl.fromLocalFile(os.path.join(current_dir, "web", "index.html"))
        self.web_view.setUrl(url)
        
        chat_layout.addWidget(self.web_view, stretch=1)
        
        # Voice Controls Area (Keep Voice Button)
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(10, 10, 10, 10)
        controls_layout.setSpacing(10)
        
        # Voice Button (Center or Right?) -> Let's put it on the right to match potential sending flow, or float.
        # Let's simple toolbar at bottom.
        
        self.voice_btn = QPushButton("🎤 Record")
        self.voice_btn.setToolTip("Click to Toggle Recording")
        self.voice_btn.setFixedHeight(40) 
        self.voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.voice_btn.setStyleSheet("font-size: 14px; font-weight: bold; padding-left: 15px; padding-right: 15px;")
        self.voice_btn.clicked.connect(self.toggle_recording)
        
        # Add to layout
        controls_layout.addStretch()
        controls_layout.addWidget(self.voice_btn)
        controls_layout.addStretch()
        
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
        if hasattr(self, 'web_view'):
            self.web_view.page().runJavaScript("document.getElementById('chat-input').placeholder = 'Listening...'; document.getElementById('chat-input').disabled = true;")

    def stop_recording(self):
        if not self.is_recording:
            return
        self.is_recording = False
        self.voice_btn.setText("🎤 Record")
        self.voice_btn.setToolTip("Click to Start Recording")
        self.voice_btn.setStyleSheet("font-size: 14px; font-weight: bold; padding-left: 15px; padding-right: 15px;") # Restore default style
        
        file_path = self.recorder.stop_recording()
        if file_path:
            if hasattr(self, 'web_view'):
                self.web_view.page().runJavaScript("document.getElementById('chat-input').placeholder = 'Transcribing...';")
            
            # Run transcription in worker
            self.audio_worker = AudioWorker(file_path)
            self.audio_worker.finished_signal.connect(self.on_transcription_finished)
            self.audio_worker.start()
        else:
            if hasattr(self, 'web_view'):
                self.web_view.page().runJavaScript("document.getElementById('chat-input').disabled = false; document.getElementById('chat-input').placeholder = 'Type a message...';")

    def on_transcription_finished(self, text):
        if hasattr(self, 'web_view'):
            if text:
                import json
                escaped_text = json.dumps(text)
                self.web_view.page().runJavaScript(f"document.getElementById('chat-input').value = {escaped_text}; document.getElementById('chat-input').disabled = false; document.getElementById('chat-input').focus();")
            else:
                 self.web_view.page().runJavaScript("document.getElementById('chat-input').disabled = false; document.getElementById('chat-input').placeholder = 'Transcription failed.';")

    def append_chat_bubble(self, role, text):
        if hasattr(self, 'web_view'):
            import json
            json_text = json.dumps(text)
            self.web_view.page().runJavaScript(f"addMessage('{role}', {json_text})")

    def handle_web_message(self, message):
        """Handle message sent from Web JS"""
        message = message.strip()
        if not message:
            return

        # Start Worker
        self.chat_worker = ChatWorker(message, context_file=self.SHARED_CONTEXT_FILE)
        self.chat_worker.output_signal.connect(self.on_chat_output_stream)
        self.chat_worker.finished_signal.connect(self.on_chat_finished)
        self.chat_worker.start()
        
        # 初始化流式响应缓存
        self.chat_response_buffer = ""
        self.chat_thinking_buffer = ""
        self.chat_streaming_started = False

    def on_chat_output_stream(self, text):
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
        content_to_stream = ""
        
        if text.startswith("STREAM_THINKING:"):
            raw = text[len("STREAM_THINKING:"):]
            try:
                thinking_chunk = json.loads(raw)
            except json.JSONDecodeError:
                thinking_chunk = raw
            self.chat_thinking_buffer += thinking_chunk
            return
        
        elif text.startswith("STREAM_CONTENT:"):
            raw = text[len("STREAM_CONTENT:"):]
            try:
                content_chunk = json.loads(raw)
            except json.JSONDecodeError:
                content_chunk = raw
            self.chat_response_buffer += content_chunk
            content_to_stream = self.chat_response_buffer # Send FULL buffer to JS to re-render markdown
        
        elif text.startswith("STREAM_ERROR:"):
            raw = text[len("STREAM_ERROR:"):]
            try:
                error_msg = json.loads(raw)
            except json.JSONDecodeError:
                error_msg = raw
            self.chat_response_buffer += f"\n[Error: {error_msg}]"
            content_to_stream = self.chat_response_buffer
            
        # 兼容旧格式
        elif "tokens" in text.lower() and ("prompt" in text.lower() or "completion" in text.lower()):
            return
        else:
            self.chat_response_buffer += text + "\n"
            content_to_stream = self.chat_response_buffer

        # Call JS to update stream
        if hasattr(self, 'web_view') and content_to_stream:
            import json
            json_text = json.dumps(content_to_stream)
            # We send the ACCUMULATED buffer every time because markdown rendering often needs context (e.g. unclosed bold tag)
            self.web_view.page().runJavaScript(f"updateStreamResponse({json_text})")


    def on_chat_finished(self, success, message):
        # Finalize Stream
        if hasattr(self, 'web_view'):
             self.web_view.page().runJavaScript("endStreamResponse();")

        # 重置状态 / 重新启用输入
        if hasattr(self, 'web_view'):
             self.web_view.page().runJavaScript("document.getElementById('chat-input').disabled = false; document.getElementById('chat-input').focus();")
        
        # If failure, append error bubbles (success handled by stream)
        if not success:
             self.append_chat_bubble("assistant", f"**Error:** {message}")

        self.chat_response_buffer = ""
        self.chat_thinking_buffer = ""
        self.chat_streaming_started = False

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
        
        self.action_plan_worker = ActionPlanWorker(context_file=self.SHARED_CONTEXT_FILE)
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
        import json

        # 检测阶段切换标记
        if "---ANALYSIS_START---" in text:
            self.action_plan_current_target = "analysis"
            self.action_plan_accumulated_text = ""
            self.action_plan_accumulated_thinking = ""
            self.action_plan_left_text.clear()
            
            # 同步到聊天界面：添加用户模拟消息和开始 AI 响应
            if hasattr(self, 'web_view'):
                self.web_view.page().runJavaScript("addMessage('user', '请进行数据分析并生成今日行动建议。');")
                self.web_view.page().runJavaScript("startStreamResponse();")
            return
        
        if "---PLAN_START---" in text or "初始分析已完成。正在生成今日行动建议..." in text:
            # 阶段切换逻辑
            if self.action_plan_current_target == "analysis" and hasattr(self, 'web_view'):
                # 结束第一轮（分析）的显示
                self.web_view.page().runJavaScript("endStreamResponse();")
                # 开始第二轮（计划）的显示
                self.web_view.page().runJavaScript("startStreamResponse();")

            self.action_plan_current_target = "plan"
            self.action_plan_plan_text = ""
            self.action_plan_plan_thinking = ""
            self.action_plan_right_text.clear()
            self.action_plan_right_text.append("🚀 开始生成计划...\n")
            return
        
        # 解析流式标记
        if text.startswith("STREAM_THINKING:"):
            raw_chunk = text[len("STREAM_THINKING:"):]
            try:
                thinking_chunk = json.loads(raw_chunk)
            except json.JSONDecodeError:
                thinking_chunk = raw_chunk
                
            if self.action_plan_current_target == "analysis":
                self.action_plan_accumulated_thinking += thinking_chunk
                self._update_analysis_display()
            else:
                self.action_plan_plan_thinking += thinking_chunk
                self._update_plan_display()
            return
        
        if text.startswith("STREAM_CONTENT:"):
            raw_chunk = text[len("STREAM_CONTENT:"):]
            try:
                content_chunk = json.loads(raw_chunk)
            except json.JSONDecodeError:
                content_chunk = raw_chunk
                
            if self.action_plan_current_target == "analysis":
                self.action_plan_accumulated_text += content_chunk
                self._update_analysis_display()
                # 同步更新 Chat 里的分析气泡
                if hasattr(self, 'web_view'):
                    json_data = json.dumps(self.action_plan_accumulated_text)
                    self.web_view.page().runJavaScript(f"updateStreamResponse({json_data});")
            else:
                self.action_plan_plan_text += content_chunk
                self._update_plan_display()
                # 同步更新 Chat 里的计划气泡
                if hasattr(self, 'web_view'):
                    json_data = json.dumps(self.action_plan_plan_text)
                    self.web_view.page().runJavaScript(f"updateStreamResponse({json_data});")
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
            # Pass preserve_left=True so we don't wipe out the stream-generated analysis on the left
            self.load_action_plan_file(preserve_left=True)
            # We skip appending combined_text here because it's already synced via append_action_plan_log real-time
        
        # End Stream
        if hasattr(self, 'web_view'):
            self.web_view.page().runJavaScript("endStreamResponse();")
        
        self.action_plan_regen_btn.setEnabled(True)
        
        # Show window after Action Plan generation completes
        if not self.isVisible():
            self.show()
            print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Action Plan 已生成，显示主窗口")

    def load_action_plan_file(self, preserve_left=False):
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m%d')
        pattern = f"action_plan_{date_str}_"
        
        # Robustly find root dir based on this file's location
        current_file_dir = os.path.dirname(os.path.abspath(__file__)) # src/gui
        root_dir = os.path.abspath(os.path.join(current_file_dir, "..", "..")) # src/gui/../../ -> root
        history_path_abs = os.path.join(root_dir, "history")

        possible_history_dirs = [
            history_path_abs,
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
                    
                # Split content if separator exists
                # Direct load: The file contains the Action Plan.
                # No separation logic needed.
                if not preserve_left:
                    self.action_plan_left_text.setHtml(self.render_markdown_to_html("### 📊 Analysis (See Logs)\n\nThe analysis for this plan was generated in a previous step."))
                    
                self.action_plan_right_text.setHtml(self.render_markdown_to_html(content))
            except Exception as e:
                self.action_plan_right_text.setText(f"Error reading file {target_file}: {e}")
        else:
            msg = f"# No Plan Found for Today :(\n\nLooking for pattern: `{pattern}*.md`"
            self.action_plan_right_text.setHtml(self.render_markdown_to_html(msg))
            self.action_plan_left_text.clear()

    # ========== PLOTS TAB (CAROUSEL) ==========
    def init_plots_tab(self):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(10)
        
        # Main Display Area (Image + Info)
        self.plot_display_container = QWidget()
        display_layout = QVBoxLayout(self.plot_display_container)
        display_layout.setContentsMargins(20, 20, 20, 20)
        
        # Image Label
        self.plot_image_label = QLabel("⏳ 点击下方按钮生成图表...")
        self.plot_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plot_image_label.setObjectName("plotCarouselImage")
        self.plot_image_label.setStyleSheet("background-color: transparent;")
        # Fix size policy to allow expansion
        from PyQt6.QtWidgets import QSizePolicy
        self.plot_image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        display_layout.addWidget(self.plot_image_label, stretch=1)
        
        # Info Label (filename, index)
        self.plot_info_label = QLabel("")
        self.plot_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plot_info_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #555; margin-top: 10px;")
        display_layout.addWidget(self.plot_info_label, stretch=0)
        
        tab_layout.addWidget(self.plot_display_container, stretch=1)
        
        # Bottom Controls
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(20, 10, 20, 20)
        
        prev_btn = QPushButton("◀ 上一张 (Prev)")
        prev_btn.clicked.connect(self.prev_plot)
        prev_btn.setFixedHeight(40)
        
        next_btn = QPushButton("下一张 (Next) ▶")
        next_btn.clicked.connect(self.next_plot)
        next_btn.setFixedHeight(40)
        
        refresh_btn = QPushButton("🔄 刷新图表 (Refresh)")
        refresh_btn.setObjectName("actionButton")
        refresh_btn.setFixedHeight(40)
        refresh_btn.clicked.connect(self.refresh_plots)
        
        controls_layout.addWidget(prev_btn)
        controls_layout.addWidget(refresh_btn)
        controls_layout.addWidget(next_btn)
        
        tab_layout.addLayout(controls_layout)
        
        return tab

    def wheelEvent(self, event):
        # Handle scroll for plot navigation if in Plots tab
        if self.tabs.currentIndex() == 2:
            angle = event.angleDelta().y()
            if angle > 0:
                self.prev_plot()
            else:
                self.next_plot()
        super().wheelEvent(event)

    def refresh_plots(self):
        # Show loading state
        self.plot_image_label.setText("⏳ 正在生成图表，请稍候...")
        
        is_dark = self.is_dark_mode
        self.plot_worker = PlotWorker(is_dark_mode=is_dark)
        self.plot_worker.finished_signal.connect(self.on_plot_finished)
        self.plot_worker.start()
    
    def on_plot_finished(self, success, message):
        if not success:
            self.plot_image_label.setText(f"❌ {message}")
            return
        
        self.load_plot_images()
        
    def load_plot_images(self):
        import math
        plot_dir = os.path.join(os.getcwd(), "plot_outputs")
        if not os.path.exists(plot_dir):
            self.plot_image_label.setText("❌ 未找到 plot_outputs 目录")
            return

        # Listing logic similar to plot.py
        files = []
        try:
             files = [f for f in os.listdir(plot_dir) if f.endswith(".png") and not f.startswith("plot_collage") and not f.endswith("_screen.png")]
        except Exception as e:
            self.plot_image_label.setText(f"❌ 读取目录失败: {e}")
            return

        if not files:
            self.plot_image_label.setText("⚠️ 未找到任何图表")
            return

        # Sort Logic
        order = [
            "weight_bodyfat",
            "time_allocation_bar",
            "time_trend_screen_remaining",
            "time_trend_averages",
            "time_trend_delta",
            "running_pace",
            "radar_goal",
            "hhh_frequency",
            "hhh_interval_trend",
            "balance_sheet",
        ]
        
        def sort_key(name):
            for index, prefix in enumerate(order):
                if name.startswith(prefix):
                    # Sort by prefix index, then by length (shorter first usually means generic), then alphabetical
                    return (index, name)
            return (len(order), name)

        self.plot_files = sorted(files, key=sort_key)
        self.current_plot_index = 0
        self.update_plot_display()

    def prev_plot(self):
        if not self.plot_files:
            return
        self.current_plot_index = (self.current_plot_index - 1) % len(self.plot_files)
        self.update_plot_display()

    def next_plot(self):
        if not self.plot_files:
            return
        self.current_plot_index = (self.current_plot_index + 1) % len(self.plot_files)
        self.update_plot_display()

    def update_plot_display(self):
        if not self.plot_files:
            self.plot_image_label.setText("No plots available")
            self.plot_info_label.setText("")
            return
            
        filename = self.plot_files[self.current_plot_index]
        path = os.path.join(os.getcwd(), "plot_outputs", filename)
        
        # Update Info
        self.plot_info_label.setText(f"[{self.current_plot_index + 1}/{len(self.plot_files)}] {filename}")
        
        # Load and Scale Image
        if os.path.exists(path):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                # Target Size: 16:9 Aspect Ratio based on Window Width?
                # Or just fit to available container size.
                # User requested "16:9" view. We can try to restrict the container.
                
                container_size = self.plot_image_label.size()
                w = container_size.width()
                h = container_size.height()
                
                # If we want to enforce visual 16:9, we might handle it here, 
                # but "fit center" is usually best for variable content.
                # Let's just fit inside safely.
                
                scaled_pixmap = pixmap.scaled(
                    w, h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.plot_image_label.setPixmap(scaled_pixmap)
            else:
                self.plot_image_label.setText("Failed to load image")
        else:
            self.plot_image_label.setText("File not found")


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
        
        # Plot Navigation State
        self.plot_files = []
        self.current_plot_index = 0

        
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
            
            # Plot Navigation Keys (Only when Plots tab is active)
            elif self.tabs.currentIndex() == 2: # Plots Tab
                if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
                    self.prev_plot()
                elif event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down):
                    self.next_plot()
            
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

