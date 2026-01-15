import os
import subprocess
import sys
from datetime import datetime
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QLabel, QHBoxLayout, QWidget, QSplitter, QApplication
from PyQt6.QtGui import QFont, QIcon, QTextCursor, QPalette, QColor
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QEvent
try:
    import pythoncom
except ImportError:
    pythoncom = None

class GenerationWorker(QThread):
    finished_signal = pyqtSignal(bool, str)
    output_signal = pyqtSignal(str)
    stats_signal = pyqtSignal(dict)

    def run(self):
        if pythoncom:
            pythoncom.CoInitialize()
        try:
            # Locate run_prompt.py
            # Assuming we are in src/gui/
            current_dir = os.path.dirname(os.path.abspath(__file__))
            src_dir = os.path.dirname(current_dir) # src/
            script_path = os.path.join(src_dir, "scripts", "run_prompt.py")
            
            if not os.path.exists(script_path):
                 # Fallback: check relative to CWD if running from root
                 script_path = os.path.abspath("src/scripts/run_prompt.py")

            if not os.path.exists(script_path):
                self.finished_signal.emit(False, f"Could not find run_prompt.py at {script_path}")
                return

            self.output_signal.emit(f"🚀 Starting generation task...\nScript: {script_path}\n")

            # Run the command with bytes output to handle encoding manually
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8" # Try to force UTF-8 from child

            process = subprocess.Popen(
                [sys.executable, script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False, # Read bytes
                cwd=os.path.dirname(script_path),
                env=env
            )

            # Read output in real-time
            while True:
                line_bytes = process.stdout.readline()
                if line_bytes == b'' and process.poll() is not None:
                    break
                if line_bytes:
                    # Try decode with utf-8, fallback/replace if fails
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
                            json_str = line.replace("STATS_JSON:", "").strip()
                            import json
                            stats = json.loads(json_str)
                            self.stats_signal.emit(stats)
                        except Exception:
                            pass
            
            # Read any remaining stderr
            stderr_bytes = process.stderr.read()
            if stderr_bytes:
                 try:
                     stderr = stderr_bytes.decode('utf-8')
                 except UnicodeDecodeError:
                     try:
                         stderr = stderr_bytes.decode('gbk')
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
            if pythoncom:
                pythoncom.CoUninitialize()

class ActionPlanDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vantage - 今日 Action Plan")
        self.resize(1200, 900)
        self.init_ui()

    def is_dark_mode(self):
        # 简单判断：如果 WindowText 颜色比 Window 颜色亮，则是深色模式
        # Use QApplication.palette() which is standard for app-wide theme
        palette = QApplication.palette()
        
        window_color = palette.color(QPalette.ColorRole.Window)
        text_color = palette.color(QPalette.ColorRole.WindowText)
        return text_color.lightness() > window_color.lightness()
        
        
        self.current_target = "analysis" # analysis or plan
        
        # Start generation immediately
        # Start generation automatically
        self.start_generation()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.PaletteChange:
            self.apply_style()
        super().changeEvent(event)

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title
        title_label = QLabel(f"📅 User's Action Plan - {datetime.now().strftime('%Y-%m-%d')}")
        title_label.setObjectName("dialogTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Main Content Area (Splitter for Left/Right)
        content_layout = QHBoxLayout()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left Pane: Analysis
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_label = QLabel("📊 总体回复 (General Analysis)")
        left_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        self.left_text_edit = QTextEdit()
        self.left_text_edit.setReadOnly(True)
        self.left_text_edit.setObjectName("analysisContent")
        self.left_text_edit.setFont(QFont("Consolas", 11))
        left_layout.addWidget(left_label)
        left_layout.addWidget(self.left_text_edit)
        
        # Right Pane: Action Plan
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_label = QLabel("📝 今日计划 (Today's Action Plan)")
        right_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        self.right_text_edit = QTextEdit()
        self.right_text_edit.setReadOnly(True)
        self.right_text_edit.setObjectName("planContent")
        self.right_text_edit.setFont(QFont("Consolas", 11))
        right_layout.addWidget(right_label)
        right_layout.addWidget(self.right_text_edit)
        
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        
        layout.addWidget(splitter, stretch=1)

        # Stats Area (Red Box Area)
        self.stats_label = QLabel("")
        self.stats_label.setObjectName("statsLabel")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_label.setWordWrap(True)
        self.stats_label.hide() # Hidden until we have stats
        layout.addWidget(self.stats_label, stretch=0)

        # Buttons
        btn_layout = QHBoxLayout()
        
        self.regen_btn = QPushButton("🔄 重新生成 (Regenerate)")
        self.regen_btn.setObjectName("actionButton")
        self.regen_btn.clicked.connect(self.start_generation)
        btn_layout.addWidget(self.regen_btn)
        
        btn_layout.addStretch()
        
        close_btn = QPushButton("关闭 (Close)")
        close_btn.setObjectName("closeButton")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout, stretch=0)

        self.setLayout(layout)
        self.apply_style()
        
        # Start generation automatically
        self.start_generation()

    def apply_style(self):
        is_dark = self.is_dark_mode()
        
        # Define colors based on mode
        if is_dark:
            # Dark Mode Colors
            bg_color = "#2b2b2b"      # App window background (handled by system usually, but for specific widgets)
            text_color = "#ffffff"
            border_color = "#444444"
            stats_bg = "#333333"      # Dark gray for stats box
            stats_text = "#dddddd"
            stats_border = "#555555"
            primary_btn_bg = "#0d6efd"
            primary_btn_text = "#ffffff"
            text_edit_bg = "#1e1e1e"  # Slightly darker for input/text areas
            text_edit_border = "#444444"
            title_color = "#ffffff"
        else:
            # Light Mode Colors
            bg_color = "#ffffff"
            text_color = "#000000"
            border_color = "#cccccc"
            stats_bg = "#f8f9fa"      # Light gray for stats box
            stats_text = "#555555"
            stats_border = "#dee2e6"
            primary_btn_bg = "#0d6efd"
            primary_btn_text = "#ffffff"
            text_edit_bg = "#ffffff"
            text_edit_border = "#ccc"
            title_color = "#000000"

        self.setStyleSheet(f"""
            QLabel#dialogTitle {{
                font-size: 20px;
                font-weight: bold;
                margin-bottom: 5px;
                color: {title_color};
            }}
            QTextEdit {{
                font-family: "Consolas";
                font-size: 11pt;
                background-color: {text_edit_bg};
                color: {text_color};
                border: 1px solid {text_edit_border};
                border-radius: 8px;
                padding: 10px;
            }}
            QLabel#statsLabel {{
                font-size: 12px;
                color: {stats_text};
                background-color: {stats_bg};
                border-top: 1px solid {stats_border};
                border-radius: 4px;
                padding: 4px 8px;
                margin-top: 5px;
            }}
               
            QPushButton {{
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton#actionButton {{
                background-color: {primary_btn_bg};
                color: {primary_btn_text};
                border: none;
            }}
            QPushButton#actionButton:hover {{
                background-color: #0b5ed7; /* Slightly darker blue */
            }}
            QPushButton#actionButton:disabled {{
                background-color: #6c757d;
            }}
            QPushButton#closeButton {{
                border: 1px solid {border_color};
                color: {text_color};
                background-color: transparent;
            }}
            QPushButton#closeButton:hover {{
                border-color: #6c757d;
            }}
        """)


    def start_generation(self):
        self.left_text_edit.clear()
        self.right_text_edit.clear()
        self.current_target = "analysis"
        
        self.left_text_edit.setMarkdown("### ⏳ 正在分析数据 (Analyzing Data)...\n\n")
        self.right_text_edit.setMarkdown("### ⏳ 等待生成计划 (Waiting for Plan)...\n\n")
        self.accumulated_analysis_text = ""
        
        self.regen_btn.setEnabled(False)
        
        self.worker = GenerationWorker()
        self.worker.output_signal.connect(self.append_log)
        self.worker.finished_signal.connect(self.on_generation_finished)
        self.worker.stats_signal.connect(self.update_stats)
        self.worker.start()

    def update_stats(self, stats):
        # Update the stats label
        text = (
            f"📊 <b>Session Stats:</b> "
            f"Speed: {stats.get('speed', 'N/A')} | "
            f"Time: {stats.get('total_duration', 0):.2f}s | "
            f"Tokens: {stats.get('total_tokens', 0)} "
            f"(Prompt: {stats.get('prompt_tokens', 0)}, Completion: {stats.get('completion_tokens', 0)}) | "
            f"Turns: {stats.get('turns', 0)}"
        )
        self.stats_label.setText(text)
        self.stats_label.show()

    def append_log(self, text):
        # Check for start marker (to clear init logs)
        if "---ANALYSIS_START---" in text:
            parts = text.split("---ANALYSIS_START---")
            # If there's content after the marker, allow it to be processed
            # But primarily we want to clear the buffer
            self.accumulated_analysis_text = ""
            self.left_text_edit.clear()
            # Take the part after the marker if it exists in this chunk
            if len(parts) > 1:
                text = parts[1].strip()
            else:
                text = "" # valid marker but no content yet
            
            if not text:
                return # Nothing to add yet

        # Check for switching marker
        if "初始分析已完成。正在生成今日行动建议..." in text:
            self.current_target = "plan"
            self.right_text_edit.clear() # Clear waiting message
            self.right_text_edit.append("🚀 开始生成计划...\n")
        
        if self.current_target == "analysis":
            self.accumulated_analysis_text += text + "\n"
            self.left_text_edit.setMarkdown(self.accumulated_analysis_text)
            self.left_text_edit.moveCursor(QTextCursor.MoveOperation.End)
        else:
            self.right_text_edit.moveCursor(QTextCursor.MoveOperation.End)
            self.right_text_edit.insertPlainText(text + "\n")
            self.right_text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def on_generation_finished(self, success, message):
        self.right_text_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.right_text_edit.insertPlainText(f"```\n\n**Status**: {message}\n\n")
        
        if success:
            self.load_action_plan()
        
        self.regen_btn.setEnabled(True)

    def load_action_plan(self):
        # Look for latest action_plan_YYYYMMDD_*.md
        date_str = datetime.now().strftime('%Y%m%d')
        pattern = f"action_plan_{date_str}_"
        
        # Determine history dir
        # Logic matches what run_prompt.py does broadly
        # But here we just need to search likely locations
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
                # Filter for today's plans
                plan_files = [f for f in files if f.startswith(pattern) and f.endswith(".md")]
                
                if plan_files:
                    # Sort by name (which includes timestamp, so works for chronological)
                    plan_files.sort(reverse=True)
                    target_file = os.path.join(history_dir, plan_files[0])
                    break
            except Exception:
                continue
        
        if target_file and os.path.exists(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    self.right_text_edit.setMarkdown(content)
            except Exception as e:
                self.right_text_edit.setText(f"Error reading file {target_file}: {e}")
        else:
             self.right_text_edit.setMarkdown(f"# No Plan Found for Today :(\n\nLooking for pattern: `{pattern}*.md`")

