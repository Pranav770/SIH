import time
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QTimer, Signal as pyqtSignal
from PySide6.QtGui import QFont
from theme import (
    AMBER,
    GREEN,
    HEADER_BG,
    INSET_BG,
    PANEL_BG,
    BORDER,
    TXT_BRIGHT,
    TXT_MUTED,
    TXT_TEXT,
    TXT_DIM,
    CYAN,
    FONT,
)

_MODE_QSS = (
    f"QPushButton {{ background-color: {INSET_BG}; color: {TXT_DIM}; "
    f"border: 1px solid {BORDER}; border-radius: 2px; padding: 3px 9px; "
    f"font-weight: bold; }}"
    f"QPushButton:checked {{ background-color: {HEADER_BG}; color: {CYAN}; "
    f"border: 1px solid {CYAN}; }}"
    f"QPushButton:hover:!checked {{ background-color: {HEADER_BG}; "
    f"color: {TXT_TEXT}; }}"
)


class HeaderBar(QWidget):
    """Glass-cockpit mission header: NIDAR branding, data-source badge,
    single global mode switch (LIVE / SITL / SIMULATION) + ZULU clock."""

    mode_selected = pyqtSignal(str)      # "LIVE" | "SITL" | "SIMULATION"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(46)
        self.setStyleSheet(
            f"background-color: {PANEL_BG}; border-bottom: 1px solid {BORDER};"
        )
        self.setProperty("glassHeader", True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 3, 14, 3)
        layout.setSpacing(12)

        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)

        brand = QLabel(
            f"<span style='font-size:16px; font-weight:700; color:{TXT_BRIGHT};'>NIDAR</span>"
            f"<span style='color:{TXT_DIM};'>  </span>"
            f"<span style='font-size:16px; font-weight:700; color:{CYAN};'>AIRMOUSE</span>"
        )
        brand.setTextFormat(Qt.TextFormat.RichText)
        brand.setFont(QFont(FONT, 9, QFont.Weight.Bold))
        brand_box.addWidget(brand)

        subtitle = QLabel(
            "GROUND CONTROL STATION   //   TRACK 1 · DRONE INNOVATION"
        )
        subtitle.setStyleSheet(f"color: {TXT_MUTED};")
        subtitle.setFont(QFont(FONT, 7))
        brand_box.addWidget(subtitle)

        layout.addLayout(brand_box)
        layout.addStretch()

        # -- data source badge (honest provenance at a glance) -------------
        self.source_badge = QLabel("DATA SOURCE: LIVE")
        self.source_badge.setFont(QFont(FONT, 8, QFont.Weight.Bold))
        self.source_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.source_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        # -- single global mode switch -------------------------------------
        self._mode_buttons: dict[str, QPushButton] = {}
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        for mode in ("LIVE", "SITL", "SIMULATION"):
            btn = QPushButton(mode)
            btn.setCheckable(True)
            btn.setFont(QFont(FONT, 8, QFont.Weight.Bold))
            btn.setStyleSheet(_MODE_QSS)
            btn.setToolTip({
                "LIVE": "All real: telemetry, perception and video from "
                        "the actual aircraft",
                "SITL": "Telemetry from the SITL vehicle is real; "
                        "perception + video are simulation",
                "SIMULATION": "Everything simulated (no vehicle, no "
                              "network dependency)",
            }[mode])
            btn.clicked.connect(
                lambda _=False, m=mode: self.mode_selected.emit(m))
            self._mode_group.addButton(btn)
            self._mode_buttons[mode] = btn
            layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._mode_buttons["LIVE"].setChecked(True)

        self.clock_label = QLabel("ZULU --:--:--")
        self.clock_label.setStyleSheet(f"color: {CYAN};")
        self.clock_label.setFont(QFont(FONT, 13, QFont.Weight.Bold))
        layout.addWidget(self.clock_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._clock = QTimer(self)
        self._clock.timeout.connect(self._update_clock)
        self._clock.start(1000)
        self._update_clock()

    # ------------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        """Reflect the active mode (initial value / programmatic change)."""
        btn = self._mode_buttons.get(mode)
        if btn is None:
            mode, btn = "LIVE", self._mode_buttons["LIVE"]
        btn.setChecked(True)
        badge = {
            "LIVE": ("DATA SOURCE: LIVE", GREEN),
            "SITL": ("DATA SOURCE: TELEM LIVE · SIM PERCEPTION", AMBER),
            "SIMULATION": ("DATA SOURCE: SIMULATION", AMBER),
        }[mode]
        self.source_badge.setText(badge[0])
        self.source_badge.setStyleSheet(
            f"background-color: {INSET_BG}; color: {badge[1]}; "
            f"border: 1px solid {BORDER}; border-left: 3px solid {badge[1]}; "
            f"border-radius: 2px; padding: 3px 8px; font-weight: bold;")

    def _update_clock(self):
        self.clock_label.setText("ZULU " + time.strftime("%H:%M:%S", time.gmtime()))

    def stop(self):
        self._clock.stop()