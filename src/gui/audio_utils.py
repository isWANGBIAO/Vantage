import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
import tempfile
import os
import threading

class AudioRecorder:
    def __init__(self, sample_rate=16000, channels=1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.recording = False
        self.frames = []
        self.thread = None

    def start_recording(self):
        if self.recording:
            return
        self.recording = True
        self.frames = []
        self.thread = threading.Thread(target=self._record)
        self.thread.start()
        print("Audio recording started...")

    def _record(self):
        with sd.InputStream(samplerate=self.sample_rate, channels=self.channels, dtype='int16', callback=self._callback):
            while self.recording:
                sd.sleep(100)

    def _callback(self, indata, frames, time, status):
        if status:
            print(f"Audio status: {status}")
        self.frames.append(indata.copy())

    def stop_recording(self):
        if not self.recording:
            return None
        self.recording = False
        if self.thread:
            self.thread.join()
        
        print("Audio recording stopped.")
        
        if not self.frames:
            return None

        # Concatenate all frames
        recording_data = np.concatenate(self.frames, axis=0)
        
        # Save to temp file
        temp_dir = tempfile.gettempdir()
        filename = os.path.join(temp_dir, f"recording_{os.getpid()}.wav")
        wav.write(filename, self.sample_rate, recording_data)
        
        return filename
