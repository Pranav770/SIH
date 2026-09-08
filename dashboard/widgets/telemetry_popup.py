from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsDropShadowEffect
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor


class TelemetryPopup(QWidget):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet(
            "background-color: #1e1e2ee0; border: 1px solid #444; border-radius: 8px;"
        )
        self.setMinimumWidth(320)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.setGraphicsEffect(shadow)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 12, 16, 12)
        self._layout.setSpacing(8)

        self._title = QLabel("TELEMETRY DETAILS")
        self._title.setStyleSheet("color: #88aaff; font-weight: bold; border: none;")
        self._title.setFont(QFont("monospace", 11, QFont.Weight.Bold))
        self._layout.addWidget(self._title)
        self._layout.addWidget(self._separator())

        self._sections: dict[str, tuple[QLabel, list[QLabel]]] = {}

        self._build_section("flight", "FLIGHT", "#6688ff")
        self._build_section("battery", "BATTERY & POWER", "#66cc66")
        self._build_section("gps", "GPS & NAVIGATION", "#44cccc")
        self._build_section("position", "POSITION", "#cc8844")
        self._build_section("attitude", "ATTITUDE", "#aa66cc")

    def _separator(self) -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #444; border: none;")
        return line

    def _build_section(self, key: str, title: str, color: str):
        header = QLabel(title)
        header.setStyleSheet(f"color: {color}; font-weight: bold; margin-top: 4px; border: none;")
        header.setFont(QFont("monospace", 9, QFont.Weight.Bold))
        self._layout.addWidget(header)

        value_labels = []
        for _ in range(6):
            lbl = QLabel("")
            lbl.setStyleSheet("color: #ddd; border: none;")
            lbl.setFont(QFont("monospace", 9))
            self._layout.addWidget(lbl)
            value_labels.append(lbl)

        sep = self._separator()
        self._layout.addWidget(sep)

        self._sections[key] = (header, value_labels, sep)

    def update_telemetry(self, data: dict):
        self._update_flight(data)
        self._update_battery(data)
        self._update_gps(data)
        self._update_position(data)
        self._update_attitude(data)

    def _set_values(self, key: str, pairs: list[tuple[str, str]]):
        _, labels, _ = self._sections[key]
        for i, label in enumerate(labels):
            if i < len(pairs):
                lbl_text, val_text = pairs[i]
                label.setText(f"  {lbl_text}: {val_text}")
                label.show()
            else:
                label.hide()

    def _update_flight(self, d: dict):
        mode = d.get("mode", "---")
        armed = "ARMED" if d.get("armed") else "DISARMED"
        sys_status = d.get("system_status", "---")
        heading = f"{d.get('heading', 0):.0f}°" if "heading" in d else "---"
        speed = f"{d.get('groundspeed', 0):.1f} m/s" if "groundspeed" in d else "---"
        climb = f"{d.get('climb', 0):.1f} m/s" if "climb" in d else "---"
        self._set_values("flight", [
            ("Mode", str(mode)),
            ("Armed", armed),
            ("Status", str(sys_status)),
            ("Heading", heading),
            ("Speed", speed),
            ("Climb", climb),
        ])

    def _update_battery(self, d: dict):
        bat = d.get("battery", None)
        voltage = d.get("voltage", None)
        bat_str = f"{bat}%" if bat is not None else "---"
        volt_str = f"{voltage / 1000:.2f} V" if voltage is not None else "---"
        self._set_values("battery", [
            ("Remaining", bat_str),
            ("Voltage", volt_str),
            ("", ""),
            ("", ""),
            ("", ""),
            ("", ""),
        ])

    def _update_gps(self, d: dict):
        fix_types = {
            0: "No GPS",
            1: "No Fix",
            2: "2D Fix",
            3: "3D Fix",
            4: "DGPS",
            5: "RTK Float",
            6: "RTK Fixed",
        }
        fix = d.get("gps_fix", 0)
        sats = d.get("gps_satellites", "---")
        fix_str = fix_types.get(fix, f"Unknown ({fix})")
        self._set_values("gps", [
            ("Fix Type", fix_str),
            ("Satellites", str(sats)),
            ("", ""),
            ("", ""),
            ("", ""),
            ("", ""),
        ])

    def _update_position(self, d: dict):
        x = d.get("x", None)
        y = d.get("y", None)
        z = d.get("z", None)
        alt = d.get("alt", None)
        pairs = []
        if x is not None:
            pairs.append(("X (NED)", f"{x:.1f} m"))
        if y is not None:
            pairs.append(("Y (NED)", f"{y:.1f} m"))
        if z is not None:
            pairs.append(("Z (NED)", f"{z:.1f} m"))
        if alt is not None:
            pairs.append(("Altitude", f"{alt:.1f} m"))
        if not pairs:
            pairs = [("---", "---")]
        self._set_values("position", pairs)

    def _update_attitude(self, d: dict):
        roll = d.get("roll", None)
        pitch = d.get("pitch", None)
        yaw = d.get("yaw", None)
        pairs = []
        if roll is not None:
            pairs.append(("Roll", f"{roll:.1f}°"))
        if pitch is not None:
            pairs.append(("Pitch", f"{pitch:.1f}°"))
        if yaw is not None:
            pairs.append(("Yaw", f"{yaw:.1f}°"))
        if not pairs:
            pairs = [("---", "---")]
        self._set_values("attitude", pairs)

    def mousePressEvent(self, event):
        if not self.rect().contains(event.pos()):
            self.close()
            self.closed.emit()
