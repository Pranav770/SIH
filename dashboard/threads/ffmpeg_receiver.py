"""TCP/UDP video receiver with status reporting and automatic retry.

Upgrades over the original version:
* emits a human-readable ``status_signal`` (CONNECTING / LIVE / NO SIGNAL /
  STREAM ENDED / UNAVAILABLE) so the UI can stop pretending a dead stream
  is still healthy,
* probes the real stream resolution with ffprobe (falls back to 1280×720)
  instead of blindly reshaping bytes,
* reconnects with a 3 s backoff instead of exiting on the first stream end,
* reports a missing ffmpeg binary as UNAVAILABLE instead of crashing.
"""

import subprocess
import time

import numpy as np
from PySide6.QtCore import QThread, Signal as pyqtSignal

STREAM_URL = "tcp://drone.local:8554"
WIDTH = 1280
HEIGHT = 720
RETRY_DELAY_S = 3.0


def probe_size(url: str, timeout: float = 8.0) -> tuple[int, int] | None:
    """Return (width, height) of the first video stream, or None."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0",
                url,
            ],
            capture_output=True, text=True, timeout=timeout,
        )
        parts = (out.stdout or "").strip().split(",")
        if len(parts) >= 2:
            w, h = int(parts[0]), int(parts[1])
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass
    return None


class FFmpegReceiverThread(QThread):
    frame_signal = pyqtSignal(np.ndarray)
    status_signal = pyqtSignal(str)

    def __init__(self, url: str = STREAM_URL):
        super().__init__()
        self.url = url
        self.running = True
        self._process: subprocess.Popen | None = None

    def stop(self):
        self.running = False
        self._cleanup()
        self.wait(5000)

    def run(self):
        attempt = 0
        while self.running:
            attempt += 1
            self.status_signal.emit(f"CONNECTING · {self.url}")

            width, height = probe_size(self.url) or (WIDTH, HEIGHT)
            if not self.running:
                break

            try:
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
            except FileNotFoundError:
                self.status_signal.emit("UNAVAILABLE — ffmpeg not installed")
                return
            except Exception as exc:
                self.status_signal.emit(f"START FAILED — {exc}"[:80])
                self._sleep_retry()
                continue

            frame_size = width * height * 3
            frames = 0
            first = True
            while self.running:
                raw = self._process.stdout.read(frame_size)
                if not raw or len(raw) < frame_size:
                    break
                try:
                    frame = np.frombuffer(raw, dtype=np.uint8).reshape(
                        (height, width, 3))
                except ValueError:
                    self.status_signal.emit(
                        f"FRAME SIZE CHANGED — {width}×{height}")
                    break
                if first:
                    first = False
                    self.status_signal.emit(
                        f"LIVE · {width}×{height} · {self.url}")
                frames += 1
                self.frame_signal.emit(frame)

            self._cleanup()
            if not self.running:
                break
            if frames == 0:
                self.status_signal.emit("NO SIGNAL — retrying…")
            else:
                self.status_signal.emit("STREAM ENDED — retrying…")
            self._sleep_retry()

        self.status_signal.emit("STOPPED")

    def _sleep_retry(self) -> None:
        end = time.monotonic() + RETRY_DELAY_S
        while self.running and time.monotonic() < end:
            time.sleep(0.1)

    def _cleanup(self):
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
