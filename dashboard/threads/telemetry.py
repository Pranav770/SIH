import time
from PySide6.QtCore import QThread, Signal as pyqtSignal
from pymavlink import mavutil


class TelemetryThread(QThread):
    telemetry_signal = pyqtSignal(dict)
    connection_status = pyqtSignal(bool)

    def __init__(self, connection_string: str = "udpin:0.0.0.0:14550"):
        super().__init__()
        self.connection_string = connection_string
        self.running = True

    def run(self):
        try:
            master = mavutil.mavlink_connection(self.connection_string)
            master.wait_heartbeat()
            self.connection_status.emit(True)
        except Exception:
            self.connection_status.emit(False)
            return

        master.mav.request_data_stream_send(
            master.target_system,
            master.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL,
            10,
            1,
        )

        while self.running:
            try:
                msg = master.recv_match(
                    blocking=True, timeout=1
                )
                if msg is None:
                    continue

                msg_type = msg.get_type()
                data = {}

                if msg_type == "HEARTBEAT":
                    mode_map = mavutil.mavlink_mode_mapping.get(
                        msg.autopilot, {}
                    )
                    data["mode"] = msg.custom_mode
                    data["armed"] = msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                    data["system_status"] = msg.system_status

                elif msg_type == "SYS_STATUS":
                    data["battery"] = msg.battery_remaining
                    data["voltage"] = msg.voltage_battery

                elif msg_type == "GPS_RAW_INT":
                    data["gps_fix"] = msg.fix_type
                    data["gps_satellites"] = msg.satellites_visible

                elif msg_type == "LOCAL_POSITION_NED":
                    data["x"] = msg.x
                    data["y"] = msg.y
                    data["z"] = msg.z

                elif msg_type == "ATTITUDE":
                    import math
                    data["roll"] = math.degrees(msg.roll)
                    data["pitch"] = math.degrees(msg.pitch)
                    data["yaw"] = math.degrees(msg.yaw)

                elif msg_type == "VFR_HUD":
                    data["heading"] = msg.heading
                    data["groundspeed"] = msg.groundspeed
                    data["alt"] = msg.alt
                    data["climb"] = msg.climb

                if data:
                    self.telemetry_signal.emit(data)

            except Exception:
                time.sleep(0.1)
                continue

    def stop(self):
        self.running = False
        self.wait()
