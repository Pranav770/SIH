"""NIDAR ground-station UDP receiver (perception uplink, default port 5556).

Decodes the packet with :func:`utils.protocol.decode_map_packet` and passes
the raw structures straight through — the dashboard store is the single
parser for detections (no second schema that could drift from the first).
The optional ``extra`` block (detections / ai / comms / origin / …) travels
along untouched, so senders that only produce the original 5-field packet
keep working unchanged.
"""

import socket

import numpy as np
from PySide6.QtCore import QThread, Signal as pyqtSignal

from utils.protocol import decode_map_packet, MAP_PORT


class MapReceiverThread(QThread):
    # grid, survivors, drone_pos, hazards, mission, extra
    map_signal = pyqtSignal(np.ndarray, list, tuple, list, dict, dict)
    status_signal = pyqtSignal(str)

    def __init__(self, port: int = MAP_PORT):
        super().__init__()
        self.port = port
        self.running = True

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.5)
        try:
            sock.bind(("0.0.0.0", self.port))
        except OSError as exc:
            if getattr(exc, "errno", None) == 98:
                self.status_signal.emit(
                    f"PORT IN USE — UDP {self.port}")
            else:
                self.status_signal.emit(
                    f"BIND FAILED — {exc}"[:80])
            sock.close()
            return

        self.status_signal.emit(f"LISTENING · UDP {self.port}")
        malformed = 0

        while self.running:
            try:
                data, _ = sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                result = decode_map_packet(data)
            except Exception:
                result = None
            if result is None:
                malformed += 1
                if malformed == 1 or malformed % 100 == 0:
                    self.status_signal.emit(
                        f"RECEIVING · {malformed} malformed packets ignored")
                continue
            if malformed:
                malformed = 0
                self.status_signal.emit(f"RECEIVING · UDP {self.port}")
            grid, survivors, drone_pos, hazards, mission, extra = result
            self.map_signal.emit(grid, survivors, drone_pos, hazards,
                                 mission, extra)

        sock.close()
        self.status_signal.emit("STOPPED")

    def stop(self):
        self.running = False
        self.wait(5000)
