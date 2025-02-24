from PyQt6.QtCore import QObject, pyqtSignal


class EmittingStream(QObject):
    output_signal = pyqtSignal(str)

    def write(self, text):
        if text.strip():  # 过滤空行
            self.output_signal.emit(text)

    def flush(self):
        pass  # 保持兼容性
