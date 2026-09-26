"""Detected survivors table: geo-tag, confidence, rescue priority and age.

Sorted highest-priority first (P1 before P4) so the operator reads the
most actionable row on top; clicking a row reports the survivor id so the
fusion bar / map can show detail for the same detection.
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

from models.survivor import Survivor
from theme import (
    BORDER,
    CYAN,
    FONT,
    MAGENTA,
    PRIORITY_COLORS,
    TXT_BRIGHT,
    TXT_DIM,
    TXT_MUTED,
    table_qss,
)

_COLS = ["ID", "Grid", "Geo", "Conf", "PR", "Time"]
_PR_ORDER = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}


class SurvivorList(QWidget):
    survivor_selected = pyqtSignal(str)     # survivor id

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        title = QLabel("DETECTED SURVIVORS")
        title.setStyleSheet(f"color: {MAGENTA}; font-weight: bold; padding: 4px;")
        title.setFont(QFont(FONT, 11))
        layout.addWidget(title)

        self.table = QTableWidget()
        self.table.setColumnCount(len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            _COLS.index("Geo"), QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            _COLS.index("PR"), QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setStyleSheet(table_qss())
        self.table.itemSelectionChanged.connect(self._on_select)
        layout.addWidget(self.table)

        self.count_label = QLabel("Survivors found: 0")
        self.count_label.setStyleSheet(f"color: {MAGENTA}; font-weight: bold; padding: 2px;")
        self.count_label.setFont(QFont(FONT, 9))
        self.count_label.setWordWrap(True)
        layout.addWidget(self.count_label)

        self._survivors: list[Survivor] = []
        self._reloading = False

    # ------------------------------------------------------------------
    def _on_select(self):
        if self._reloading:
            return
        row = self.table.currentRow()
        if 0 <= row < len(self._survivors):
            self.survivor_selected.emit(self._survivors[row].id)

    def select_id(self, survivor_id: str) -> None:
        for i, s in enumerate(self._survivors):
            if s.id == survivor_id:
                self._reloading = True
                self.table.selectRow(i)
                self._reloading = False
                return

    @staticmethod
    def _geo_text(s: Survivor) -> str:
        if s.lat is not None and s.lon is not None:
            return f"{s.lat:.5f},{s.lon:.5f}"
        return "GEO PENDING"

    def update_survivors(self, survivors: list[Survivor]):
        new_ids = {s.id for s in survivors}
        old_ids = {s.id for s in self._survivors}

        # keep current selection across refreshes
        sel_id = None
        row = self.table.currentRow()
        if 0 <= row < len(self._survivors):
            sel_id = self._survivors[row].id

        # highest rescue priority first, newest inside a band
        self._survivors = sorted(
            survivors,
            key=lambda s: (_PR_ORDER.get(s.priority or "P4", 3),
                           -s.timestamp),
        )

        self._reloading = True
        self.table.setRowCount(len(self._survivors))
        select_row = -1
        for i, s in enumerate(self._survivors):
            items = [
                QTableWidgetItem(s.id),
                QTableWidgetItem(f"({s.grid_x}, {s.grid_y})"),
                QTableWidgetItem(self._geo_text(s)),
                QTableWidgetItem(f"{s.confidence:.0%}"),
                QTableWidgetItem(s.priority or "P4"),
                QTableWidgetItem(self._time_text(s)),
            ]
            items[2].setForeground(QColor(
                TXT_MUTED if s.lat is not None else TXT_DIM))
            pr = s.priority or "P4"
            items[4].setForeground(QColor(PRIORITY_COLORS.get(pr, TXT_BRIGHT)))
            for c, item in enumerate(items):
                self.table.setItem(i, c, item)

            if s.id in new_ids - old_ids:
                for c in range(len(_COLS)):
                    item = self.table.item(i, c)
                    if item:
                        item.setBackground(QColor(72, 30, 66))

            if s.id == sel_id:
                select_row = i

        if select_row >= 0:
            self.table.selectRow(select_row)
        self._reloading = False

        p1 = sum(1 for s in self._survivors if s.priority == "P1")
        extra = f" · {p1} × P1" if p1 else ""
        self.count_label.setText(
            f"Survivors found: {len(self._survivors)}{extra}")

    @staticmethod
    def _time_text(s: Survivor) -> str:
        if not s.timestamp:
            return "--"
        elapsed = max(0.0, time.time() - s.timestamp)
        if elapsed < 60:
            return f"{elapsed:.0f}s ago"
        return f"{elapsed / 60:.0f}m ago"
