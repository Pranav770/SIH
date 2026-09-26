"""Priority alerts panel (Step 9/10) — permanent bottom-right panel.

Shows the store's active alerts newest-highest first with per-alert
ACK / CLEAR actions. Acknowledging an alert only changes the alert (and
its hazard's status) — detections are never mutated or deleted by it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from models.alert import Alert, AlertPriority
from theme import (
    AMBER,
    BORDER,
    FONT,
    INSET_BG,
    PRIORITY_COLORS,
    RED,
    TXT_BRIGHT,
    TXT_DIM,
    TXT_MUTED,
    TXT_TEXT,
    small_button_qss,
)

_MAX_ROWS = 40


class _AlertRow(QFrame):
    ack_requested = Signal(str)
    clear_requested = Signal(str)

    def __init__(self, alert: Alert, parent=None):
        super().__init__(parent)
        self.alert_id = alert.id
        prio = alert.priority.label
        color = PRIORITY_COLORS.get(prio, TXT_TEXT)
        self.setStyleSheet(
            f"background-color: {INSET_BG}; border: 1px solid {BORDER}; "
            f"border-left: 3px solid {color}; border-radius: 2px;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(6)

        p = QLabel(prio)
        p.setFont(QFont(FONT, 9, QFont.Weight.Bold))
        p.setFixedWidth(22)
        p.setStyleSheet(f"color: {color};")
        p.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(p)

        t = QLabel(alert.age_text)
        t.setFont(QFont(FONT, 8))
        t.setMinimumWidth(1)          # shrinkable, capped by max
        t.setMaximumWidth(58)
        t.setStyleSheet(f"color: {TXT_DIM};")
        lay.addWidget(t)

        title = QLabel(alert.title)
        title.setFont(QFont(FONT, 8, QFont.Weight.Bold))
        title.setMinimumWidth(1)       # Qt treats min 0 as "unset" — use 1
        style = "text-decoration: line-through;" if alert.acknowledged else ""
        state = " · ACK" if alert.acknowledged else ""
        title.setStyleSheet(
            f"color: {TXT_TEXT}; {style}"
            + (f"color: {TXT_MUTED};" if alert.acknowledged else ""))
        title.setToolTip(alert.detail or alert.category)
        lay.addWidget(title, stretch=1)

        loc_text = alert.location
        if alert.lat is not None and alert.lon is not None:
            loc_text = f"{alert.lat:.3f},{alert.lon:.3f}"
        loc = QLabel(loc_text)
        loc.setFont(QFont(FONT, 7))
        loc.setMinimumWidth(1)
        loc.setMaximumWidth(88)
        loc.setStyleSheet(f"color: {TXT_MUTED};")
        loc.setToolTip(alert.location)
        lay.addWidget(loc)

        if alert.acknowledged:
            ack = QLabel("ACK" + state)
            ack.setFont(QFont(FONT, 7, QFont.Weight.Bold))
            ack.setFixedWidth(34)
            ack.setStyleSheet(f"color: #3ddc84;")
            lay.addWidget(ack)
        else:
            btn = QPushButton("ACK")
            btn.setFont(QFont(FONT, 7, QFont.Weight.Bold))
            btn.setFixedWidth(34)
            btn.setStyleSheet(small_button_qss("#3ddc84"))
            btn.clicked.connect(lambda: self.ack_requested.emit(self.alert_id))
            lay.addWidget(btn)

        clr = QPushButton("CLEAR")
        clr.setFont(QFont(FONT, 7, QFont.Weight.Bold))
        clr.setFixedWidth(44)
        clr.setStyleSheet(small_button_qss(AMBER))
        clr.clicked.connect(lambda: self.clear_requested.emit(self.alert_id))
        lay.addWidget(clr)


class AlertsPanel(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 6)
        lay.setSpacing(4)

        head = QHBoxLayout()
        title = QLabel("PRIORITY ALERTS")
        title.setFont(QFont(FONT, 10, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {RED};")
        head.addWidget(title)

        self.count = QLabel("0 active · 0 critical")
        self.count.setFont(QFont(FONT, 8))
        self.count.setStyleSheet(f"color: {TXT_MUTED};")
        head.addWidget(self.count)
        head.addStretch()

        self.ack_all = QPushButton("ACK ALL")
        self.ack_all.setFont(QFont(FONT, 8, QFont.Weight.Bold))
        self.ack_all.setStyleSheet(small_button_qss("#3ddc84"))
        self.ack_all.clicked.connect(lambda: self.store.acknowledge_all())
        head.addWidget(self.ack_all)
        lay.addLayout(head)

        self.empty = QLabel("no active alerts — pipeline quiet")
        self.empty.setStyleSheet(
            f"color: {TXT_DIM}; font-style: italic;")
        self.empty.setFont(QFont(FONT, 8))
        lay.addWidget(self.empty)

        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(3)
        self.body_lay.addStretch()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.body)
        self.scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}")
        lay.addWidget(self.scroll, stretch=1)

        self._rows: dict[str, _AlertRow] = {}

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        alerts = self.store.active_alerts
        critical = self.store.critical_alert_count
        unack = len(self.store.unacknowledged)
        self.count.setText(
            f"{len(alerts)} active · {critical} critical · {unack} unack")

        # keep only visible alerts, in priority order
        order = {AlertPriority.P1: 0, AlertPriority.P2: 1,
                 AlertPriority.P3: 2, AlertPriority.P4: 3}
        alerts = sorted(
            alerts,
            key=lambda a: (a.acknowledged, order.get(a.priority, 4),
                           -a.created),
        )[:_MAX_ROWS]

        ids = {a.id for a in alerts}

        # drop rows that were cleared
        for aid in list(self._rows):
            if aid not in ids:
                row = self._rows.pop(aid)
                self.body_lay.removeWidget(row)
                row.deleteLater()

        # insert / reorder
        for i, alert in enumerate(alerts):
            row = self._rows.get(alert.id)
            if row is None:
                row = _AlertRow(alert)
                row.ack_requested.connect(self.store.acknowledge_alert)
                row.clear_requested.connect(self.store.clear_alert)
                self._rows[alert.id] = row
            self.body_lay.insertWidget(i, row)

        has_any = bool(self._rows)
        self.empty.setVisible(not has_any)
        self.scroll.setVisible(has_any)
        self.ack_all.setEnabled(any(not a.acknowledged
                                    for a in self.store.active_alerts))
