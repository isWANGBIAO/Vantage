import sys
from PyQt6.QtCore import QObject, pyqtSignal


class EmittingStream(QObject):
    output_signal = pyqtSignal(str)

    def write(self, text):
        if text.strip():  # 过滤空行
            try:
                self.output_signal.emit(text)
            except RuntimeError:
                # C++ object might be deleted on exit
                pass
        # 同时输出到终端 (stdout 或 stderr)
        if self is sys.stdout:
            sys.__stdout__.write(text)
        elif self is sys.stderr:
            sys.__stderr__.write(text)
        else:
            # 默认写入 stdout
            sys.__stdout__.write(text)
        self.flush()

    def flush(self):
        # 刷新终端输出
        sys.__stdout__.flush()
        sys.__stderr__.flush()  # 保持兼容性
