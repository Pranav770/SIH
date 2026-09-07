import subprocess
import numpy as np
from PySide6.QtCore import QThread, Signal as pyqtSignal

STREAM_URL = "tcp://drone.local:8554"
WIDTH = 1280
HEIGHT = 720


class FFmpegReceiverThread(QThread):
    frame_signal = pyqtSignal(np.ndarray)

    def __init__(self, url: str = STREAM_URL):
        super().__init__()
        self.url = url
        self.running = True
        self._process: subprocess.Popen | None = None

    def run(self):
        frame_size = WIDTH * HEIGHT * 3

        self._process = subprocess.Popen(
            [
                "ffmpeg",
                "-i", self.url,
                "-f", "rawvideo",
                "-pix_fmt", "bgr24",
                "-v", "quiet",
                "-bufsize", "1024k",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        while self.running:
            raw = self._process.stdout.read(frame_size)
            if not raw or len(raw) < frame_size:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((HEIGHT, WIDTH, 3))
            self.frame_signal.emit(frame)

        self._cleanup()

    def stop(self):
        self.running = False
        self._cleanup()
        self.wait()

    def _cleanup(self):
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
