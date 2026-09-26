"""Hazard panel: type counters plus individual detection records.

Severity shown here is the *effective* severity — a backend-provided
severity always wins over the risk-model estimate — and status reflects
alert acknowledgement (ACTIVE / ACK) without mutating the detection.
"""

from __future__ import annotations

import time

from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, Signal as pyqtSignal
from PySide6.QtGui import QColor, QFont

from models.hazard import Hazard, HazardType
from theme import (
    AMBER,
    FONT,
    GREEN,
    HAZARD_COLORS,
    SEVERITY_COLORS,
    TXT_DIM,
    TXT_MUTED,
    table_qss,
)


HAZARD_ICONS = {
    HazardType.FIRE: ("FIRE", HAZARD_COLORS["FIRE"]),
    HazardType.FLOOD: ("FLOOD", HAZARD_COLORS["FLOOD"]),
    HazardType.DEBRIS: ("DEBRIS", HAZARD_COLORS["DEBRIS"]),
    HazardType.ELECTRICAL: ("ELEC", HAZARD_COLORS["ELEC"]),
    HazardType.STRUCTURAL: ("STRUCT", HAZARD_COLORS["STRUCT"]),
    HazardType.LANDSLIDE: ("LANDSL", HAZARD_COLORS["LANDSL"]),
    HazardType.CHEMICAL: ("CHEM", HAZARD_COLORS["CHEM"]),
    HazardType.SMOKE: ("SMOKE", HAZARD_COLORS["SMOKE"]),
}

_COLS = ["ID", "TYPE", "SEV", "ST", "AGE"]


class HazardPanel(QWidget):
    hazard_selected = pyqtSignal(str)      # hazard id

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        title = QLabel("HAZARD DETECTION")
        title.setStyleSheet(f"color: {AMBER}; font-weight: bold; padding: 4px;")
        title.setFont(QFont(FONT, 11))
        layout.addWidget(title)

        self._hazard_labels: dict[HazardType, tuple[QLabel, QLabel]] = {}
        self._count_label = QLabel("Total hazards: 0")
        self._count_label.setStyleSheet(f"color: {AMBER}; font-weight: bold; padding: 2px;")
        self._count_label.setFont(QFont(FONT, 9))
        self._count_label.setWordWrap(True)
        layout.addWidget(self._count_label)

        # dynamic type counters (unused — counts live in the label above)

        self.table = QTableWidget()
        self.table.setColumnCount(len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setStyleSheet(table_qss())
        self.table.itemSelectionChanged.connect(self._on_select)
        layout.addWidget(self.table)

        self._hazards: list[Hazard] = []
        self._reloading = False

    # ------------------------------------------------------------------
    def _on_select(self):
        if self._reloading:
            return
        row = self.table.currentRow()
        if 0 <= row < len(self._hazards):
            self.hazard_selected.emit(self._hazards[row].id)

    def select_id(self, hazard_id: str) -> None:
        for i, h in enumerate(self._hazards):
            if h.id == hazard_id:
                self._reloading = True
                self.table.selectRow(i)
                self._reloading = False
                return

    @staticmethod
    def _age_text(h: Hazard) -> str:
        if not h.timestamp:
            return "--"
        elapsed = max(0.0, time.time() - h.timestamp)
        return f"{elapsed:.0f}s" if elapsed < 60 else f"{elapsed / 60:.0f}m"

    def update_hazards(self, hazards: list[Hazard]):
        counts: dict[HazardType, int] = {}
        for h in hazards:
            counts[h.type] = counts.get(h.type, 0) + 1

        crit = sum(1 for h in hazards
                   if h.effective_severity.value == "critical")
        ackd = sum(1 for h in hazards if h.status == "ACK")
        parts = [f"Total hazards: {len(hazards)}"]
        for htype, (icon_text, color) in HAZARD_ICONS.items():
            n = counts.get(htype, 0)
            if n:
                parts.append(f"{n} {icon_text}")
        if crit:
            parts.append(f"{crit} CRITICAL")
        if ackd:
            parts.append(f"{ackd} ACK")
        self._count_label.setText(" · ".join(parts))

        # records table — highest effective severity first
        sel_id = None
        row = self.table.currentRow()
        if 0 <= row < len(self._hazards):
            sel_id = self._hazards[row].id

        self._hazards = sorted(
            hazards,
            key=lambda h: (-h.effective_severity.rank, -h.timestamp),
        )

        self._reloading = True
        self.table.setRowCount(len(self._hazards))
        sev_short = {"CRITICAL": "CRIT", "HIGH": "HIGH",
                     "MEDIUM": "MED", "LOW": "LOW"}
        select_row = -1
        for i, h in enumerate(self._hazards):
            sev = h.effective_severity
            type_txt = HAZARD_ICONS.get(h.type, (h.type.value.upper(), ""))[0]
            status = (h.status or "ACTIVE").upper()
            items = [
                QTableWidgetItem(h.id),
                QTableWidgetItem(type_txt),
                QTableWidgetItem(sev_short.get(sev.label, sev.label)),
                QTableWidgetItem("ACK" if status == "ACK" else "ACT"),
                QTableWidgetItem(self._age_text(h)),
            ]
            items[1].setToolTip(h.type.value.upper())
            items[2].setToolTip(sev.label)
            items[3].setToolTip(status)
            items[0].setToolTip(f"{h.id} · grid ({h.grid_x},{h.grid_y})")
            items[2].setForeground(QColor(SEVERITY_COLORS[sev.label]))
            items[3].setForeground(QColor(
                GREEN if status == "ACK" else AMBER if status == "ACTIVE"
                else TXT_MUTED))
            items[4].setForeground(QColor(TXT_DIM))
            for c, item in enumerate(items):
                self.table.setItem(i, c, item)
            if h.id == sel_id:
                select_row = i
        if select_row >= 0:
            self.table.selectRow(select_row)
        self._reloading = False
