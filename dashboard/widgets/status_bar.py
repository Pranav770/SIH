from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QMouseEvent


class TelemetryBadge(QLabel):
    """A QLabel badge that supports hover tooltips and double-click signals."""

    double_clicked = Signal(str)

    def __init__(self, text: str, bg: str, badge_name: str, parent=None):
        super().__init__(text, parent)
        self._badge_name = badge_name
        self._default_bg = bg
        self.setStyleSheet(
            f"background-color: {bg}; color: #ddd; padding: 4px 8px; "
            f"border-radius: 4px; font-weight: bold;"
        )
        self.setFont(QFont("monospace", 9))
        self.setMinimumWidth(100)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._badge_name)
        super().mouseDoubleClickEvent(event)


class StatusBar(QWidget):
    telemetry_detail_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setStyleSheet(
            "background-color: #1e1e2e; border-bottom: 1px solid #333;"
        )

        self._telemetry_data: dict = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(16)

        self.mode_badge = TelemetryBadge("MODE: ---", "#3b3b5c", "mode")
        self.armed_badge = TelemetryBadge("DISARMED", "#5c3b3b", "armed")
        self.battery_bar = TelemetryBadge("BAT: --%", "#3b5c3b", "battery")
        self.gps_badge = TelemetryBadge("GPS: --", "#3b3b5c", "gps")
        self.heading_badge = TelemetryBadge("HDG: ---", "#3b3b5c", "heading")
        self.alt_badge = TelemetryBadge("ALT: --", "#3b3b5c", "altitude")
        self.speed_badge = TelemetryBadge("SPD: --", "#3b3b5c", "speed")

        self.mission_label = QLabel("Mission: Idle")
        self.mission_label.setStyleSheet("color: #aaa; font-weight: bold;")
        self.mission_label.setFont(QFont("monospace", 10))

        self.progress_label = QLabel("0%")
        self.progress_label.setStyleSheet("color: #aaa;")
        self.progress_label.setFont(QFont("monospace", 10))

        self._badges = [
            self.mode_badge,
            self.armed_badge,
            self.battery_bar,
            self.gps_badge,
            self.heading_badge,
            self.alt_badge,
            self.speed_badge,
        ]

        for badge in self._badges:
            badge.double_clicked.connect(self.telemetry_detail_clicked.emit)

        for w in [
            *self._badges,
            self.mission_label,
            self.progress_label,
        ]:
            layout.addWidget(w)

        layout.addStretch()

    def _build_tooltips(self):
        d = self._telemetry_data
        if not d:
            return

        mode = d.get("mode", "---")
        armed = "ARMED" if d.get("armed") else "DISARMED"
        sys_status = d.get("system_status", "---")
        bat = d.get("battery")
        voltage = d.get("voltage")
        fix = d.get("gps_fix", 0)
        sats = d.get("gps_satellites", 0)
        heading = d.get("heading")
        alt = d.get("alt")
        climb = d.get("climb")
        speed = d.get("groundspeed")
        roll = d.get("roll")
        pitch = d.get("pitch")
        yaw = d.get("yaw")
        x = d.get("x")
        y = d.get("y")
        z = d.get("z")

        fix_types = {0: "No GPS", 1: "No Fix", 2: "2D", 3: "3D", 4: "DGPS", 5: "RTK Float", 6: "RTK Fixed"}

        self.mode_badge.setToolTip(
            f"Flight Mode: {mode}\n"
            f"System Status: {sys_status}\n"
            f"Armed: {armed}"
        )

        status_text = "Armed" if d.get("armed") else "Disarmed"
        self.armed_badge.setToolTip(
            f"Armed State: {status_text}\n"
            f"Flight Mode: {mode}\n"
            f"System Status: {sys_status}"
        )

        bat_parts = [f"Battery: {bat}%"] if bat is not None else ["Battery: ---"]
        if voltage is not None:
            bat_parts.append(f"Voltage: {voltage / 1000:.2f} V")
        self.battery_bar.setToolTip("\n".join(bat_parts))

        fix_str = fix_types.get(fix, f"Unknown ({fix})")
        self.gps_badge.setToolTip(
            f"GPS Fix: {fix_str}\n"
            f"Satellites: {sats}"
        )

        hdg_parts = [f"Heading: {heading:.0f}°"] if heading is not None else ["Heading: ---"]
        cardinal = self._cardinal(heading) if heading is not None else ""
        if cardinal:
            hdg_parts.append(f"Cardinal: {cardinal}")
        if roll is not None:
            hdg_parts.append(f"Roll: {roll:.1f}°")
        if pitch is not None:
            hdg_parts.append(f"Pitch: {pitch:.1f}°")
        self.heading_badge.setToolTip("\n".join(hdg_parts))

        alt_parts = []
        if alt is not None:
            alt_parts.append(f"Altitude: {alt:.1f} m")
        if climb is not None:
            alt_parts.append(f"Climb Rate: {climb:.1f} m/s")
        if z is not None:
            alt_parts.append(f"Z (NED): {z:.1f} m")
        if not alt_parts:
            alt_parts = ["Altitude: ---"]
        self.alt_badge.setToolTip("\n".join(alt_parts))

        spd_parts = []
        if speed is not None:
            spd_parts.append(f"Ground Speed: {speed:.1f} m/s")
        if x is not None and y is not None:
            spd_parts.append(f"Position: ({x:.1f}, {y:.1f})")
        if not spd_parts:
            spd_parts = ["Speed: ---"]
        self.speed_badge.setToolTip("\n".join(spd_parts))

    @staticmethod
    def _cardinal(heading) -> str:
        if heading is None:
            return ""
        dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        idx = round(heading / 45) % 8
        return dirs[idx]

    def update_telemetry(self, data: dict):
        self._telemetry_data.update(data)

        if "mode" in data:
            self.mode_badge.setText(f"MODE: {data['mode']}")
        if "armed" in data:
            armed = data["armed"]
            self.armed_badge.setText("ARMED" if armed else "DISARMED")
            self.armed_badge.setStyleSheet(
                "background-color: #3b5c3b; color: #4f4; padding: 4px 8px; "
                "border-radius: 4px; font-weight: bold;"
                if armed
                else "background-color: #5c3b3b; color: #f66; padding: 4px 8px; "
                "border-radius: 4px; font-weight: bold;"
            )
        if "battery" in data:
            bat = data["battery"]
            color = "#3b5c3b" if bat > 50 else "#5c5c3b" if bat > 20 else "#5c3b3b"
            self.battery_bar.setText(f"BAT: {bat}%")
            self.battery_bar.setStyleSheet(
                f"background-color: {color}; color: #ddd; padding: 4px 8px; "
                f"border-radius: 4px; font-weight: bold;"
            )
        if "gps_satellites" in data:
            fix = data.get("gps_fix", 0)
            sats = data["gps_satellites"]
            self.gps_badge.setText(f"GPS: {sats}sats Fix:{fix}")
        if "heading" in data:
            self.heading_badge.setText(f"HDG: {data['heading']:.0f}")
        if "alt" in data:
            self.alt_badge.setText(f"ALT: {data['alt']:.1f}m")
        if "groundspeed" in data:
            self.speed_badge.setText(f"SPD: {data['groundspeed']:.1f}m/s")

        self._build_tooltips()

    def update_mission(self, phase_text: str, progress: float):
        self.mission_label.setText(f"Mission: {phase_text}")
        self.progress_label.setText(f"{progress:.0f}%")
