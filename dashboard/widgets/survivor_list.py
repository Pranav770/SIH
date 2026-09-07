from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLabel,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor
from models.survivor import Survivor


class SurvivorList(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        title = QLabel("Detected Survivors")
        title.setStyleSheet("color: #ff6666; font-weight: bold; padding: 4px;")
        title.setFont(QFont("monospace", 11))
        layout.addWidget(title)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["#", "Grid", "Confidence", "Time"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(
            "QTableWidget { background-color: #1a1a2e; color: #ddd; "
            "gridline-color: #333; } "
            "QHeaderView::section { background-color: #16213e; color: #aaa; "
            "padding: 4px; border: 1px solid #333; }"
        )
        layout.addWidget(self.table)

        self.count_label = QLabel("Survivors found: 0")
        self.count_label.setStyleSheet("color: #ff6666; font-weight: bold; padding: 2px;")
        self.count_label.setFont(QFont("monospace", 9))
        layout.addWidget(self.count_label)

        self._survivors: list[Survivor] = []

    def update_survivors(self, survivors: list[Survivor]):
        new_ids = {s.id for s in survivors}
        old_ids = {s.id for s in self._survivors}
        self._survivors = survivors

        self.table.setRowCount(len(survivors))
        for i, s in enumerate(survivors):
            self.table.setItem(i, 0, QTableWidgetItem(s.id))
            grid_item = QTableWidgetItem(f"({s.grid_x}, {s.grid_y})")
            self.table.setItem(i, 1, grid_item)
            conf_item = QTableWidgetItem(f"{s.confidence:.0%}")
            self.table.setItem(i, 2, conf_item)
            import time

            elapsed = time.time() - s.timestamp if s.timestamp else 0
            time_item = QTableWidgetItem(f"{elapsed:.0f}s ago")
            self.table.setItem(i, 3, time_item)

            if s.id in new_ids - old_ids:
                for col in range(4):
                    item = self.table.item(i, col)
                    if item:
                        item.setBackground(QColor(100, 30, 30))

        self.count_label.setText(f"Survivors found: {len(survivors)}")
