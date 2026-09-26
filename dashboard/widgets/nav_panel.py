"""Navigation health panel (Step 4): GPS / GPS-denied state.

Everything shown here is derived by :func:`models.nav.derive_navigation`
from real inputs (GPS fix+age, EKF health, explicit backend hints) — a
genuine in-flight GPS loss produces exactly the same display as the demo
scenario, and sources nobody reported stay UNKNOWN instead of being
claimed active.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from models.nav import PositionSource, SourceState
from theme import (
    AMBER,
    CYAN,
    FONT,
    GREEN,
    INSET_BG,
    RED,
    TXT_BRIGHT,
    TXT_DIM,
    TXT_MUTED,
    TXT_TEXT,
    BORDER,
    chip_qss,
    panel_qss,
)

_STATE_STYLE = {
    SourceState.ACTIVE: (GREEN, "ACTIVE"),
    SourceState.STANDBY: (AMBER, "STANDBY"),
    SourceState.UNKNOWN: (TXT_DIM, "UNKNOWN"),
}

_SOURCE_ORDER = [
    PositionSource.GPS,
    PositionSource.EKF,
    PositionSource.IMU,
    PositionSource.VO,
    PositionSource.VSLAM,
    PositionSource.OPTICAL_FLOW,
    PositionSource.LIDAR,
]


def _section(title: str, accent: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setStyleSheet(panel_qss(accent))
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(6, 4, 6, 6)
    lay.setSpacing(3)
    head = QLabel(title)
    head.setStyleSheet(f"color: {accent}; font-weight: bold;")
    head.setFont(QFont(FONT, 8))
    lay.addWidget(head)
    return frame, lay


def _value_row(grid: QGridLayout, row: int, key: str) -> QLabel:
    k = QLabel(key)
    k.setStyleSheet(f"color: {TXT_MUTED};")
    k.setFont(QFont(FONT, 8))
    v = QLabel("--")
    v.setStyleSheet(f"color: {TXT_BRIGHT}; font-weight: bold;")
    v.setFont(QFont(FONT, 8))
    v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    grid.addWidget(k, row, 0)
    grid.addWidget(v, row, 1)
    return v


class NavPanel(QWidget):
    """GPS block + EKF block + position-source grid + derivation reason."""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # -- banner -------------------------------------------------------
        self.banner = QLabel("NAVIGATION: AWAITING DATA")
        self.banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner.setFont(QFont(FONT, 10, QFont.Weight.Bold))
        self.banner.setFixedHeight(30)
        self.banner.setStyleSheet(chip_qss(TXT_DIM))
        self.banner.setWordWrap(False)
        lay.addWidget(self.banner)

        # -- GPS ----------------------------------------------------------
        gps_frame, gps_lay = _section("GPS RECEIVER", GREEN)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        self.v_fix = _value_row(g, 0, "FIX")
        self.v_sats = _value_row(g, 1, "SATELLITES")
        self.v_hdop = _value_row(g, 2, "HDOP")
        self.v_acc = _value_row(g, 3, "H-ACCURACY")
        self.v_age = _value_row(g, 4, "LAST UPDATE")
        gps_lay.addLayout(g)
        lay.addWidget(gps_frame)

        # -- EKF ----------------------------------------------------------
        ekf_frame, ekf_lay = _section("EKF / INS FUSION", CYAN)
        e = QGridLayout()
        e.setHorizontalSpacing(8)
        self.v_ekf_state = _value_row(e, 0, "STATE")
        self.v_ekf_acc = _value_row(e, 1, "HORIZ ERROR")
        self.v_ekf_vel = _value_row(e, 2, "VEL ERROR")
        ekf_lay.addLayout(e)
        lay.addWidget(ekf_frame)

        # -- sources ------------------------------------------------------
        src_frame, src_lay = _section("POSITION SOURCES", AMBER)
        sg = QGridLayout()
        sg.setHorizontalSpacing(6)
        sg.setVerticalSpacing(3)
        self._src_chips: dict[PositionSource, QLabel] = {}
        for i, src in enumerate(_SOURCE_ORDER):
            name = QLabel(src.label)
            name.setStyleSheet(f"color: {TXT_MUTED};")
            name.setFont(QFont(FONT, 8))
            chip = QLabel("·")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setFont(QFont(FONT, 7, QFont.Weight.Bold))
            chip.setFixedWidth(74)
            row, col = divmod(i, 2)
            sg.addWidget(name, row, col * 2)
            sg.addWidget(chip, row, col * 2 + 1)
            self._src_chips[src] = chip
        sg.setColumnStretch(0, 1)
        sg.setColumnStretch(2, 1)
        src_lay.addLayout(sg)
        lay.addWidget(src_frame)

        # -- reason -------------------------------------------------------
        self.reason = QLabel("No positioning data received yet")
        self.reason.setStyleSheet(f"color: {TXT_DIM}; font-style: italic;")
        self.reason.setFont(QFont(FONT, 8))
        self.reason.setWordWrap(True)
        lay.addWidget(self.reason)
        lay.addStretch()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        store = self.store
        nav, gps, ekf = store.nav, store.gps, store.ekf

        # banner
        if not nav.reported:
            text, color = nav.banner, TXT_DIM
        elif nav.gps_denied:
            text, color = nav.banner, RED
        elif nav.degraded:
            text, color = nav.banner, AMBER
        else:
            text, color = nav.banner, GREEN
        self.banner.setText(text)
        self.banner.setStyleSheet(chip_qss(color))

        # GPS values
        self.v_fix.setText(f"{gps.fix_label} · {gps.state}")
        self.v_fix.setStyleSheet(
            "color: %s; font-weight: bold;" %
            (GREEN if gps.state == "OK" else
             AMBER if gps.state == "STALE" else
             RED if gps.state == "LOST" else TXT_DIM))
        self.v_sats.setText(str(gps.satellites)
                            if gps.satellites is not None else "N/A")
        self.v_hdop.setText(f"{gps.hdop:.1f}"
                            if gps.hdop is not None else "N/A")
        self.v_acc.setText(f"{gps.accuracy_m:.2f} m"
                           if gps.accuracy_m is not None else "N/A")
        self.v_age.setText(gps.age_text)
        self.v_age.setStyleSheet(f"color: {TXT_BRIGHT}; font-weight: bold;")

        # EKF values
        self.v_ekf_state.setText(ekf.state)
        self.v_ekf_state.setStyleSheet(
            "color: %s; font-weight: bold;" %
            (GREEN if ekf.state == "OK" else
             AMBER if ekf.state in ("DEGRADED", "DEAD RECKONING") else
             TXT_DIM if ekf.state == "UNKNOWN" else RED))
        self.v_ekf_acc.setText(f"{ekf.horiz_acc:.2f} m"
                               if ekf.horiz_acc is not None else "N/A")
        self.v_ekf_vel.setText(f"{ekf.vel_err:.2f} m/s"
                               if ekf.vel_err is not None else "N/A")

        # source chips
        for src, chip in self._src_chips.items():
            state = nav.state_of(src)
            color, label = _STATE_STYLE[state]
            chip.setText(label)
            chip.setStyleSheet(
                f"background-color: {INSET_BG}; color: {color}; "
                f"border: 1px solid {BORDER}; border-radius: 2px; "
                f"font-weight: bold;")

        self.reason.setText(nav.reason or "Awaiting positioning data")
