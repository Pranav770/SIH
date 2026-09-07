import socket
import numpy as np
from PySide6.QtCore import QThread, Signal as pyqtSignal
from utils.protocol import decode_frame, VIDEO_PORT


class VideoReceiverThread(QThread):
    frame_signal = pyqtSignal(np.ndarray)

    def __init__(self, port: int = VIDEO_PORT):
        super().__init__()
        self.port = port
        self.running = True

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.5)
        sock.bind(("0.0.0.0", self.port))

        while self.running:
            try:
                data, _ = sock.recvfrom(65536)
                frame = decode_frame(data)
                if frame is not None:
                    self.frame_signal.emit(frame)
            except socket.timeout:
                continue
            except Exception:
                continue

        sock.close()

    def stop(self):
        self.running = False
        self.wait()
