"""Local microphone lifecycle, isolated from GTK for failure-path testing."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile


class Recorder:
    """Recording is explicit. Cleanup never prevents navigation or app exit."""
    def __init__(self):
        self.process = None
        self.path = None
        self.tool = shutil.which("pw-record") or shutil.which("arecord")

    def start(self):
        if not self.tool:
            raise RuntimeError("录音需要 pw-record 或 arecord；也可选择音频文件")
        if self.process:
            return
        fd, self.path = tempfile.mkstemp(prefix="vantage-voice-", suffix=".wav")
        os.close(fd)
        args = [self.tool, "--rate", "16000", "--channels", "1", self.path] if Path(self.tool).name == "pw-record" else [self.tool, "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", self.path]
        try:
            self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self._remove_file()
            raise RuntimeError("无法启动录音设备 / Could not start the microphone recorder") from None

    def stop(self):
        process, self.process = self.process, None
        if process:
            try:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            except OSError:
                self._remove_file()
                raise RuntimeError("录音设备已断开 / Recording device disconnected") from None
            if process.returncode not in {0, -signal.SIGINT}:
                self._remove_file()
                raise RuntimeError("麦克风不可用或权限被拒绝 / Microphone unavailable or permission denied")
        return self.path

    def _remove_file(self):
        path, self.path = self.path, None
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass

    def discard(self):
        try:
            self.stop()
        except (RuntimeError, subprocess.TimeoutExpired):
            # User-visible Stop reports errors. Shutdown/navigation must finish.
            pass
        finally:
            self._remove_file()
