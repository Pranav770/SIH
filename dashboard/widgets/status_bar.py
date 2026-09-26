from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QMouseEvent
from theme import (
    PANEL_BG,
    BORDER,
    TXT_BRIGHT,
    TXT_MUTED,
    CYAN,
    GREEN,
    AMBER,
    RED,
    TEAL,
    MAGENTA,
    BLUE,
    FONT,
    badge_qss,
)


class TelemetryBadge(QLabel):
    """Glass-cockpit datablock: cyan tag + bright value on an inset panel."""

    double_clicked = Signal(str)

    def __init__(self, text: str, accent: str, badge_name: str, parent=None):
        super().__init__(text, parent)
        self._badge_name = badge_name
        self._accent = accent
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setStyleSheet(badge_qss(accent))
        self.setFont(QFont(FONT, 9))
        self.setMinimumWidth(96)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_readout(self, tag: str, value: str, accent=None, value_color=None):
        accent = accent or self._accent
        self.setStyleSheet(badge_qss(accent))
        tag_html = f"<span style='color:{CYAN};'>{tag}:</span> " if tag else ""
        val_html = f"<span style='color:{value_color or TXT_BRIGHT};'>{value}</span>"
        self.setText(f"{tag_html}{val_html}")

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
            f"background-color: {PANEL_BG}; border-bottom: 1px solid {BORDER};"
        )

        self._telemetry_data: dict = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)

        self.mode_badge = TelemetryBadge("MODE ---", CYAN, "mode")
        self.armed_badge = TelemetryBadge("ARM ---", RED, "armed")
        self.battery_bar = TelemetryBadge("BAT --%", GREEN, "battery")
        self.gps_badge = TelemetryBadge("GPS --", TEAL, "gps")
        self.heading_badge = TelemetryBadge("HDG ---", MAGENTA, "heading")
        self.alt_badge = TelemetryBadge("ALT --", AMBER, "altitude")
        self.speed_badge = TelemetryBadge("SPD --", BLUE, "speed")
        self.vert_badge = TelemetryBadge("VERT --", TEAL, "vert")
        self.time_badge = TelemetryBadge("TIME --:--:--", CYAN, "time")
        self._gps_lost = False

        self.mission_label = QLabel()
        self.mission_label.setTextFormat(Qt.TextFormat.RichText)
        self.mission_label.setFont(QFont(FONT, 10))
        self.mission_label.setMinimumWidth(130)

        self.progress_label = QLabel("0%")
        self.progress_label.setStyleSheet(
            f"color: {CYAN}; border: 1px solid {BORDER}; border-radius: 2px; "
            f"padding: 3px 10px; font-weight: bold;"
        )
        self.progress_label.setFont(QFont(FONT, 10, QFont.Weight.Bold))

        self._badges = [
            self.mode_badge,
            self.armed_badge,
            self.battery_bar,
            self.gps_badge,
            self.heading_badge,
            self.alt_badge,
            self.speed_badge,
            self.vert_badge,
            self.time_badge,
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

        self.drone_label = QLabel("DRONE-01")
        self.drone_label.setStyleSheet(f"color: {TXT_MUTED};")
        self.drone_label.setFont(QFont(FONT, 9, QFont.Weight.Bold))
        layout.addWidget(self.drone_label, 0, Qt.AlignmentFlag.AlignRight)

        self._set_mission("IDLE", 0.0)

    def _set_mission(self, phase_text: str, progress: float):
        self.mission_label.setText(
            f"<span style='color:{CYAN};'>MISSION:</span> "
            f"<span style='color:{TXT_BRIGHT};'>{phase_text}</span>"
        )
        pct = min(100.0, max(0.0, progress))
        self.progress_label.setText(f"{pct:.0f}%")

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

        fix_types = {
            0: "No GPS",
            1: "No Fix",
            2: "2D",
            3: "3D",
            4: "DGPS",
            5: "RTK Float",
            6: "RTK Fixed",
        }

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
            self.mode_badge.set_readout("MODE", str(data["mode"]))

        if "armed" in data:
            armed = data["armed"]
            text = "ARMED" if armed else "DISARMED"
            color = GREEN if armed else RED
            self.armed_badge.set_readout("", text, accent=color, value_color=color)

        if "battery" in data:
            bat = data["battery"]
            color = GREEN if bat > 50 else AMBER if bat > 20 else RED
            self.battery_bar.set_readout("BAT", f"{bat}%", accent=color)

        if "gps_satellites" in data and not self._gps_lost:
            fix = data.get("gps_fix", 0)
            sats = data["gps_satellites"]
            self.gps_badge.set_readout("GPS", f"{sats}S F{fix}")

        if "heading" in data:
            self.heading_badge.set_readout("HDG", f"{data['heading']:.0f}°")

        if "alt" in data:
            self.alt_badge.set_readout("ALT", f"{data['alt']:.1f}M")

        if "groundspeed" in data:
            self.speed_badge.set_readout("SPD", f"{data['groundspeed']:.1f}M/S")

        if "climb" in data:
            # units live in the tooltip — keeps the 9-badge row inside
            # the 1280 px minimum window without clipping
            self.vert_badge.set_readout("VERT", f"{data['climb']:+.1f}")

        self._build_tooltips()

    def set_gps_state(self, denied: bool) -> None:
        """GPS-denied overrides the receiver readout (receiver truth stays
        available in the tooltip and the NAV panel)."""
        denied = bool(denied)
        if denied == self._gps_lost:
            return
        self._gps_lost = denied
        if denied:
            self.gps_badge.set_readout("GPS", "LOST", accent=RED,
                                       value_color=RED)
            self.gps_badge.setToolTip(
                "GPS-DENIED NAVIGATION — position held by EKF/INS fallback\n"
                "(receiver values in telemetry detail popup)")
        else:
            d = self._telemetry_data
            if "gps_satellites" in d:
                self.gps_badge.set_readout(
                    "GPS",
                    f"{d['gps_satellites']}S F{d.get('gps_fix', 0)}")

    def update_mission(self, phase_text: str, progress: float,
                       timer_text: str | None = None):
        self._set_mission(phase_text, progress)
        if timer_text is not None:
            # compact MM:SS while under an hour (full HH:MM:SS in the
            # MISSION tab); keeps the row from clipping
            if timer_text.startswith("00:"):
                timer_text = timer_text[3:]
            self.time_badge.set_readout("TIME", timer_text)