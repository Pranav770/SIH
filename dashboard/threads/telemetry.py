"""MAVLink telemetry thread (LIVE / SITL).

Upgrades over the original version:
* configurable connection string (``--mavlink`` CLI arg; ``udpin:…:14551``
  when QGC occupies 14550),
* bounded heartbeat wait + automatic reconnect with backoff — never blocks
  forever and never claims "LINK OK" without a heartbeat,
* ArduPilot/PX4 mode names decoded via pymavlink's own ``flightmode``
  (no more raw ``153`` numbers),
* parses EKF_STATUS_REPORT, GLOBAL_POSITION_INT, GPS_RAW_INT lat/lon/eph,
  MISSION_CURRENT, GPS_GLOBAL_ORIGIN, OPTICAL_FLOW_RAD, DISTANCE_SENSOR,
* thread-safe command queue (ABORT/PAUSE/RETURN/START are sent as real
  MAVLink commands from the UI thread) with per-command result feedback.

All message handling is best-effort: any parse failure skips the message
instead of killing the link.
"""

import math
import queue
import time

from PySide6.QtCore import QThread, Signal as pyqtSignal
from pymavlink import mavutil

DEFAULT_CONNECTION = "udpin:0.0.0.0:14550"

# messages the stock ArduPilot data streams may not include by default
_EXTRA_MESSAGE_INTERVALS = (
    ("MAVLINK_MSG_ID_EKF_STATUS_REPORT", 1_000_000),   # µs between messages
    ("MAVLINK_MSG_ID_MISSION_CURRENT", 1_000_000),
    ("MAVLINK_MSG_ID_GPS_GLOBAL_ORIGIN", 5_000_000),
)


def mode_command(*candidates: str):
    """Build a command that sets the first supported flight mode.

    ``mode_command("LOITER", "HOLD")`` works on ArduPilot and PX4 vehicles.
    Raises ``RuntimeError`` when none of the modes exist — the UI shows the
    failure instead of silently doing nothing.
    """

    def _send(master) -> str:
        mapping = master.mode_mapping() or {}
        for name in candidates:
            if name in mapping:
                master.set_mode(name)
                return f"MODE {name} SENT"
        raise RuntimeError("mode not supported: " + "/".join(candidates))

    return _send


class TelemetryThread(QThread):
    telemetry_signal = pyqtSignal(dict)
    connection_status = pyqtSignal(bool, str)     # (ok, human detail)
    command_result = pyqtSignal(str, bool, str)   # (name, ok, message)

    def __init__(self, connection_string: str = DEFAULT_CONNECTION):
        super().__init__()
        self.connection_string = connection_string
        self.running = True
        self._cmd_q: queue.Queue = queue.Queue()

    # -- control API (safe from any thread) -------------------------------
    def submit_command(self, name: str, fn) -> None:
        self._cmd_q.put((name, fn))

    def stop(self):
        self.running = False
        self.wait(5000)

    # -- helpers -----------------------------------------------------------
    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while self.running and time.monotonic() < end:
            time.sleep(0.1)

    @staticmethod
    def _bind_error_detail(exc: Exception) -> str:
        text = str(exc).lower()
        if "address already in use" in text or "errno 98" in text:
            return "PORT IN USE — another GCS holds this UDP port"
        return f"CONNECTION FAILED — {exc}"[:120]

    def _drain_commands(self, master) -> None:
        while True:
            try:
                name, fn = self._cmd_q.get_nowait()
            except queue.Empty:
                return
            try:
                note = fn(master)
                self.command_result.emit(name, True, str(note or "SENT"))
            except Exception as exc:            # surface the failure
                self.command_result.emit(name, False, str(exc)[:100])

    def _configure_streams(self, master) -> None:
        try:
            master.mav.request_data_stream_send(
                master.target_system,
                master.target_component,
                mavutil.mavlink.MAV_DATA_STREAM_ALL,
                10,
                1,
            )
        except Exception:
            pass
        for const_name, interval_us in _EXTRA_MESSAGE_INTERVALS:
            msg_id = getattr(mavutil.mavlink, const_name, None)
            if not msg_id:
                continue
            try:
                master.mav.command_long_send(
                    master.target_system,
                    master.target_component,
                    getattr(mavutil.mavlink, "MAV_CMD_SET_MESSAGE_INTERVAL", 511),
                    0,
                    msg_id,
                    interval_us,
                    0, 0, 0, 0, 0,
                )
            except Exception:
                pass

    # -- message handling --------------------------------------------------
    def _handle(self, master, msg) -> None:
        msg_type = msg.get_type()
        data: dict = {}

        if msg_type == "HEARTBEAT":
            # pymavlink decodes the mode per-vehicle (fixes raw numbers)
            try:
                mode = master.flightmode or ""
            except Exception:
                mode = ""
            if not mode:
                mode = f"MODE({getattr(msg, 'custom_mode', '?')})"
            data["mode"] = str(mode)
            data["armed"] = bool(
                msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            data["system_status"] = int(msg.system_status)
            data["autopilot"] = int(msg.autopilot)

        elif msg_type == "SYS_STATUS":
            if msg.battery_remaining is not None and msg.battery_remaining >= 0:
                data["battery"] = int(msg.battery_remaining)
            if msg.voltage_battery and msg.voltage_battery < 65535:
                data["voltage"] = int(msg.voltage_battery)
            if msg.current_battery is not None and msg.current_battery >= 0:
                data["current"] = int(msg.current_battery)

        elif msg_type == "GPS_RAW_INT":
            data["gps_fix"] = int(msg.fix_type)
            data["gps_satellites"] = int(msg.satellites_visible)
            eph = int(getattr(msg, "eph", 0) or 0)
            if 0 < eph < 65535:
                # MAVLink: eph = HDOP × 10 (some senders use ×100)
                hdop = eph / 10.0
                if hdop > 30:
                    hdop = eph / 100.0
                if hdop <= 30:
                    data["gps_hdop"] = round(hdop, 1)
            h_acc = getattr(msg, "h_acc", None)   # MAVLink2 ext, cm
            if isinstance(h_acc, int) and 0 < h_acc <= 100_000:
                data["gps_accuracy_m"] = round(h_acc / 100.0, 2)
            if int(msg.fix_type) >= 2 and (msg.lat or msg.lon):
                data["lat"] = msg.lat / 1e7
                data["lon"] = msg.lon / 1e7

        elif msg_type == "GLOBAL_POSITION_INT":
            if msg.lat or msg.lon:
                data["lat"] = msg.lat / 1e7
                data["lon"] = msg.lon / 1e7
            data["relative_alt"] = msg.relative_alt / 1000.0
            data["vx"] = msg.vx / 100.0
            data["vy"] = msg.vy / 100.0
            data["vz"] = msg.vz / 100.0

        elif msg_type == "LOCAL_POSITION_NED":
            data["x"] = msg.x
            data["y"] = msg.y
            data["z"] = msg.z

        elif msg_type == "ATTITUDE":
            data["roll"] = math.degrees(msg.roll)
            data["pitch"] = math.degrees(msg.pitch)
            data["yaw"] = math.degrees(msg.yaw)

        elif msg_type == "VFR_HUD":
            data["heading"] = int(msg.heading) % 360
            data["groundspeed"] = msg.groundspeed
            data["alt"] = msg.alt
            data["climb"] = msg.climb

        elif msg_type == "EKF_STATUS_REPORT":
            data["ekf_reported"] = True
            data["ekf_flags"] = int(msg.flags)
            var_h = float(getattr(msg, "pos_horiz_variance", 0) or 0)
            var_v = float(getattr(msg, "velocity_variance", 0) or 0)
            data["ekf_horiz_acc"] = math.sqrt(var_h) if var_h > 0 else None
            data["ekf_vel_err"] = math.sqrt(var_v) if var_v > 0 else None

        elif msg_type == "MISSION_CURRENT":
            data["wp_seq"] = int(msg.seq)

        elif msg_type == "GPS_GLOBAL_ORIGIN":
            data["origin"] = [msg.latitude / 1e7, msg.longitude / 1e7]

        elif msg_type == "OPTICAL_FLOW_RAD":
            data["nav_sources"] = ["of"]

        elif msg_type == "DISTANCE_SENSOR":
            data["nav_sources"] = ["lidar"]

        if data:
            data["source"] = "live"
            self.telemetry_signal.emit(data)

    # -- main loop ---------------------------------------------------------
    def run(self):
        backoff = 1.0
        while self.running:
            # 1) connect ----------------------------------------------------
            try:
                master = mavutil.mavlink_connection(self.connection_string)
            except Exception as exc:
                self.connection_status.emit(False,
                                            self._bind_error_detail(exc))
                self._sleep(backoff)
                backoff = min(5.0, backoff * 1.5)
                continue

            # 2) bounded heartbeat wait -------------------------------------
            try:
                hb = master.recv_match(type="HEARTBEAT", blocking=True,
                                       timeout=5)
            except Exception:
                hb = None
            if hb is None:
                self.connection_status.emit(
                    False, f"NO HEARTBEAT — {self.connection_string}")
                try:
                    master.close()
                except Exception:
                    pass
                self._sleep(backoff)
                backoff = min(5.0, backoff * 1.5)
                continue

            backoff = 1.0
            self.connection_status.emit(
                True, f"HEARTBEAT · sys {hb.get_srcSystem()} · "
                      f"{self.connection_string}")
            self._configure_streams(master)
            last_rx = time.monotonic()
            silent_reported = False

            # 3) message loop -----------------------------------------------
            while self.running:
                self._drain_commands(master)
                try:
                    msg = master.recv_match(blocking=True, timeout=0.5)
                except Exception:
                    msg = None

                if msg is None:
                    silence = time.monotonic() - last_rx
                    if silence > 8 and not silent_reported:
                        silent_reported = True
                        self.connection_status.emit(
                            False, f"NO DATA FOR {silence:.0f}s")
                    continue

                last_rx = time.monotonic()
                if silent_reported:
                    silent_reported = False
                    self.connection_status.emit(True, "TELEMETRY RESTORED")
                try:
                    self._handle(master, msg)
                except Exception:
                    continue   # never let one bad message kill the link

            try:
                master.close()
            except Exception:
                pass

        # shutting down: fail any queued commands honestly
        while True:
            try:
                name, _ = self._cmd_q.get_nowait()
            except queue.Empty:
                return
            self.command_result.emit(name, False, "LINK CLOSING")
