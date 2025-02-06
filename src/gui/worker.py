# worker.py
from PyQt5.QtCore import QThread, pyqtSignal


class WorkerThread(QThread):
    output_signal = pyqtSignal(str)

    def __init__(self, func):
        super().__init__()
        self.func = func

    def run(self):
        for output in self.func():
            self.output_signal.emit(output)
