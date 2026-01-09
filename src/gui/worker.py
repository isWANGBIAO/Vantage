from PyQt6.QtCore import QThread, pyqtSignal
import traceback

try:
    import pythoncom
except ImportError:
    pythoncom = None


# 通用的工作线程类


class WorkerThread(QThread):
    output_signal = pyqtSignal(object)  # 线程间通信信号

    def __init__(self, task_func, interval=0):  # 默认间隔 1000 毫秒
        super().__init__()
        self.task_func = task_func
        self.interval = interval
        self.running = True

    def run(self):
        if pythoncom:
            pythoncom.CoInitialize()
        
        try:
            while self.running:
                try:
                    result = self.task_func()
                except Exception:
                    traceback.print_exc()
                    result = None
                if result is not None:
                    self.output_signal.emit(result)
                self.msleep(int(self.interval))  # 线程休眠，控制任务频率
        finally:
            if pythoncom:
                pythoncom.CoUninitialize()

    def set_interval(self, interval):
        self.interval = interval   # 支持动态调整间隔

    def stop(self):
        self.running = False
        self.quit()
        self.wait()
