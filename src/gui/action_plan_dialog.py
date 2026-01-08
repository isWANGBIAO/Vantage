import os
import subprocess
import sys
from datetime import datetime
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QLabel, QHBoxLayout
from PyQt6.QtGui import QFont, QIcon, QTextCursor
from PyQt6.QtCore import Qt, QThread, pyqtSignal

class GenerationWorker(QThread):
    finished_signal = pyqtSignal(bool, str)
    output_signal = pyqtSignal(str)

    def run(self):
        try:
            # Locate run_prompt.py
            # Assuming we are in src/gui/ or src/ so we need to go up to find run_prompt.py
            # Best way is to find the project root.
            # Using relative path from CWD which is usually project root main.py launch
            
            script_path = "run_prompt.py"
            # Ensure absolute path resolution
            if not os.path.isabs(script_path):
                # Try to find run_prompt.py in likely locations if not in CWD
                if not os.path.exists(script_path):
                     current_dir = os.path.dirname(os.path.abspath(__file__))
                     # Try ../../run_prompt.py (assuming src/gui/ -> root)
                     candidate = os.path.normpath(os.path.join(current_dir, "..", "..", "run_prompt.py"))
                     if os.path.exists(candidate):
                         script_path = candidate
                     else:
                         # Fallback to checking CWD again, but make it absolute
                         script_path = os.path.abspath(script_path)
                else:
                    script_path = os.path.abspath(script_path)

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

class ActionPlanDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("今日 Action Plan")
        self.resize(700, 800)
        self.init_ui()
        
        # Start generation immediately
        self.start_generation()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title
        title_label = QLabel(f"📅 User's Action Plan - {datetime.now().strftime('%Y-%m-%d')}")
        title_label.setObjectName("dialogTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Content Area
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setObjectName("planContent")
        self.text_edit.setFont(QFont("Consolas", 12))
        layout.addWidget(self.text_edit)

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
        
        layout.addLayout(btn_layout)

        self.setLayout(layout)
        self.apply_style()

    def start_generation(self):
        self.text_edit.clear()
        self.text_edit.setMarkdown("### ⏳ 正在生成今日计划 (Generating Action Plan)...\n\nThis process may take a few seconds. Please wait.\n\n```\n")
        
        self.regen_btn.setEnabled(False)
        
        self.worker = GenerationWorker()
        self.worker.output_signal.connect(self.append_log)
        self.worker.finished_signal.connect(self.on_generation_finished)
        self.worker.start()

    def append_log(self, text):
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.text_edit.insertPlainText(text + "\n")
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def on_generation_finished(self, success, message):
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.text_edit.insertPlainText(f"```\n\n**Status**: {message}\n\n")
        
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
                    self.text_edit.setMarkdown(content)
            except Exception as e:
                self.text_edit.setText(f"Error reading file {target_file}: {e}")
        else:
             self.text_edit.setMarkdown(f"# No Plan Found for Today :(\n\nLooking for pattern: `{pattern}*.md`")

    def apply_style(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QLabel#dialogTitle {
                font-size: 24px;
                font-weight: bold;
                color: #ffffff;
                margin-bottom: 10px;
            }
            QTextEdit#planContent {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 8px;
                padding: 10px;
                color: #ffffff;
            }
            QPushButton#actionButton {
                background-color: #0d6efd;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton#actionButton:hover {
                background-color: #0b5ed7;
            }
            QPushButton#actionButton:disabled {
                background-color: #495057;
                color: #868e96;
            }
            QPushButton#closeButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton#closeButton:hover {
                background-color: #5c636a;
            }
        """)
