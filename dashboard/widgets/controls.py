"""Bottom control bar: flight/mission commands, KML area load and honest
link status.

* ABORT asks for confirmation before emitting (it becomes an RTL command).
* The link chip is tri-state — it starts as ``NO DATA`` (nothing has been
  measured yet) instead of a misleading ``LINK OK``.
* Command results (SENT / FAILED / NO LINK) appear next to the chip so the
  operator always sees what actually happened to a command.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)
from PySide6.QtCore import QTimer, Signal as pyqtSignal
from PySide6.QtGui import QFont
from theme import (
    AMBER,
    BORDER,
    CYAN,
    GREEN,
    INSET_BG,
    PANEL_BG,
    RED,
    TXT_DIM,
    FONT,
    button_qss,
)


class Controls(QWidget):
    abort_signal = pyqtSignal()
    pause_signal = pyqtSignal()
    return_home_signal = pyqtSignal()
    start_mission_signal = pyqtSignal()
    load_area_signal = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self.setStyleSheet(
            f"background-color: {PANEL_BG}; border-top: 1px solid {BORDER};"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        self.btn_abort = QPushButton("EMERGENCY ABORT")
        self.btn_abort.setStyleSheet(
            button_qss(RED, "#ffffff", bg="#6e1618", hover="#7d1d20",
                       pressed="#5e1416")
        )
        self.btn_abort.setFont(QFont(FONT, 10, QFont.Weight.Bold))
        self.btn_abort.clicked.connect(self._on_abort)

        self.btn_pause = QPushButton("PAUSE MISSION")
        self.btn_pause.setStyleSheet(button_qss(AMBER, AMBER))
        self.btn_pause.setFont(QFont(FONT, 9, QFont.Weight.Bold))
        self.btn_pause.clicked.connect(self.pause_signal.emit)

        self.btn_return = QPushButton("RETURN HOME")
        self.btn_return.setStyleSheet(button_qss(CYAN, CYAN))
        self.btn_return.setFont(QFont(FONT, 9, QFont.Weight.Bold))
        self.btn_return.clicked.connect(self.return_home_signal.emit)

        self.btn_start = QPushButton("START MISSION")
        self.btn_start.setStyleSheet(button_qss(GREEN, GREEN))
        self.btn_start.setFont(QFont(FONT, 9, QFont.Weight.Bold))
        self.btn_start.clicked.connect(self.start_mission_signal.emit)

        self.btn_area = QPushButton("LOAD AREA")
        self.btn_area.setStyleSheet(button_qss(CYAN, CYAN))
        self.btn_area.setFont(QFont(FONT, 9, QFont.Weight.Bold))
        self.btn_area.setToolTip("Load a KML/KMZ disaster area outline")
        self.btn_area.clicked.connect(self.load_area_signal.emit)

        for b in (self.btn_abort, self.btn_pause, self.btn_return,
                  self.btn_start, self.btn_area):
            layout.addWidget(b)

        layout.addStretch()

        # -- command feedback (SENT / FAILED / NO LINK) --------------------
        self.feedback_label = QLabel("")
        self.feedback_label.setFont(QFont(FONT, 8, QFont.Weight.Bold))
        self.feedback_label.setMinimumWidth(200)
        layout.addWidget(self.feedback_label)

        # -- link chip (tri-state) ----------------------------------------
        self.status_label = QPushButton("NO DATA")
        self.status_label.setEnabled(False)
        self.status_label.setFont(QFont(FONT, 9, QFont.Weight.Bold))
        self._set_link(None, "")
        layout.addWidget(self.status_label)

        self._fb_timer = QTimer(self)
        self._fb_timer.setSingleShot(True)
        self._fb_timer.timeout.connect(self._clear_feedback)

    # ------------------------------------------------------------------
    def _on_abort(self):
        """Confirm before the abort is dispatched (RTL to the vehicle)."""
        reply = QMessageBox.question(
            self,
            "EMERGENCY ABORT",
            "Send EMERGENCY ABORT?\n\n"
            "The mission stops immediately and the drone returns home "
            "(RTL).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.abort_signal.emit()

    # ------------------------------------------------------------------
    def set_paused(self, paused: bool) -> None:
        self.btn_pause.setText("RESUME MISSION" if paused
                               else "PAUSE MISSION")

    def show_command_result(self, name: str, ok: bool, message: str) -> None:
        color = GREEN if ok else RED
        self.feedback_label.setText(
            f"<span style='color:{TXT_DIM}'>{name}:</span> "
            f"<span style='color:{color};'>{message}</span>")
        self.feedback_label.setStyleSheet(
            f"background-color: {INSET_BG}; border: 1px solid {BORDER}; "
            f"border-left: 3px solid {color}; border-radius: 2px; "
            f"padding: 3px 8px;")
        self._fb_timer.start(6000)

    def _clear_feedback(self) -> None:
        self.feedback_label.setText("")

    # ------------------------------------------------------------------
    def set_connection_status(self, connected: bool | None,
                              detail: str = "",
                              text: str | None = None) -> None:
        """Tri-state link chip: True / False / None (no data yet).

        ``text`` overrides the chip label (e.g. SIM MODE where there is no
        vehicle link by design); ``detail`` always lands in the tooltip.
        """
        self._set_link(connected, detail, text)

    def _set_link(self, connected: bool | None, detail: str = "",
                  text: str | None = None):
        if connected:
            text_def, fg, bg, border = "LINK OK", GREEN, "#0f2317", "#1f5f3a"
        elif connected is False:
            text_def, fg, bg, border = "LINK LOST", RED, "#2a1214", "#6b2525"
        else:
            text_def, fg, bg, border = "NO DATA", AMBER, "#2a2114", "#6b5425"
        text = text or text_def
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"background-color: {bg}; color: {fg}; "
            f"border: 1px solid {border}; border-radius: 2px; "
            f"padding: 4px 12px; font-weight: bold;"
        )
        self.status_label.setToolTip(detail or text)
