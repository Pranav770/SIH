import socket
import numpy as np
from PySide6.QtCore import QThread, Signal as pyqtSignal
from models.survivor import Survivor
from models.hazard import Hazard, HazardType
from utils.protocol import decode_map_packet, MAP_PORT


class MapReceiverThread(QThread):
    map_signal = pyqtSignal(
        np.ndarray, list, tuple, list, dict
    )

    def __init__(self, port: int = MAP_PORT):
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
                result = decode_map_packet(data)
                if result is not None:
                    grid, survivors_raw, drone_pos, hazards_raw, mission = result

                    survivors = []
                    for s in survivors_raw:
                        survivors.append(
                            Survivor(
                                id=s["id"],
                                grid_x=s["grid_x"],
                                grid_y=s["grid_y"],
                                confidence=s["confidence"],
                                timestamp=s.get("timestamp", 0),
                            )
                        )

                    hazards = []
                    for h in hazards_raw:
                        try:
                            htype = HazardType(h["type"])
                        except ValueError:
                            htype = HazardType.DEBRIS
                        hazards.append(
                            Hazard(
                                type=htype,
                                grid_x=h["grid_x"],
                                grid_y=h["grid_y"],
                                severity=h.get("severity", 1),
                                timestamp=h.get("timestamp", 0),
                            )
                        )

                    self.map_signal.emit(
                        grid, survivors, drone_pos, hazards, mission
                    )
            except socket.timeout:
                continue
            except Exception:
                continue

        sock.close()

    def stop(self):
        self.running = False
        self.wait()
