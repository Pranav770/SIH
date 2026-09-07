from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor


class StatusBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setStyleSheet(
            "background-color: #1e1e2e; border-bottom: 1px solid #333;"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(16)

        self.mode_badge = self._badge("MODE: ---", "#3b3b5c")
        self.armed_badge = self._badge("DISARMED", "#5c3b3b")
        self.battery_bar = self._badge("BAT: --%", "#3b5c3b")
        self.gps_badge = self._badge("GPS: --", "#3b3b5c")
        self.heading_badge = self._badge("HDG: ---", "#3b3b5c")
        self.alt_badge = self._badge("ALT: --", "#3b3b5c")
        self.speed_badge = self._badge("SPD: --", "#3b3b5c")

        self.mission_label = QLabel("Mission: Idle")
        self.mission_label.setStyleSheet("color: #aaa; font-weight: bold;")
        self.mission_label.setFont(QFont("monospace", 10))

        self.progress_label = QLabel("0%")
        self.progress_label.setStyleSheet("color: #aaa;")
        self.progress_label.setFont(QFont("monospace", 10))

        for w in [
            self.mode_badge,
            self.armed_badge,
            self.battery_bar,
            self.gps_badge,
            self.heading_badge,
            self.alt_badge,
            self.speed_badge,
            self.mission_label,
            self.progress_label,
        ]:
            layout.addWidget(w)

        layout.addStretch()

    def _badge(self, text: str, bg: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"background-color: {bg}; color: #ddd; padding: 4px 8px; "
            f"border-radius: 4px; font-weight: bold;"
        )
        label.setFont(QFont("monospace", 9))
        label.setMinimumWidth(100)
        return label

    def update_telemetry(self, data: dict):
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

    def update_mission(self, phase_text: str, progress: float):
        self.mission_label.setText(f"Mission: {phase_text}")
        self.progress_label.setText(f"{progress:.0f}%")
