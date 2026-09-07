from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor
from models.hazard import Hazard, HazardType


HAZARD_ICONS = {
    HazardType.FIRE: ("FIRE", "#ff4400"),
    HazardType.FLOOD: ("FLOOD", "#0088ff"),
    HazardType.DEBRIS: ("DEBRIS", "#ffaa00"),
    HazardType.ELECTRICAL: ("ELEC", "#ffff00"),
    HazardType.STRUCTURAL: ("STRUCT", "#ff0000"),
    HazardType.LANDSLIDE: ("LANDSL", "#885500"),
    HazardType.CHEMICAL: ("CHEM", "#aa00ff"),
    HazardType.SMOKE: ("SMOKE", "#888888"),
}


class HazardPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        title = QLabel("Hazard Detection")
        title.setStyleSheet("color: #ffaa00; font-weight: bold; padding: 4px;")
        title.setFont(QFont("monospace", 11))
        layout.addWidget(title)

        self._hazard_labels: dict[str, tuple[QLabel, QLabel]] = {}
        self._count_label = QLabel("Total hazards: 0")
        self._count_label.setStyleSheet("color: #ffaa00; font-weight: bold; padding: 2px;")
        self._count_label.setFont(QFont("monospace", 9))
        layout.addWidget(self._count_label)

        layout.addStretch()

    def update_hazards(self, hazards: list[Hazard]):
        counts: dict[HazardType, int] = {}
        for h in hazards:
            counts[h.type] = counts.get(h.type, 0) + 1

        for htype, (icon_text, color) in HAZARD_ICONS.items():
            count = counts.get(htype, 0)
            if htype.value not in self._hazard_labels:
                row = QHBoxLayout()
                icon = QLabel(f"[{icon_text}]")
                icon.setStyleSheet(f"color: {color}; font-weight: bold;")
                icon.setFont(QFont("monospace", 9))
                icon.setFixedWidth(70)
                count_label = QLabel("0")
                count_label.setStyleSheet(f"color: {color};")
                count_label.setFont(QFont("monospace", 10))
                self._hazard_labels[htype.value] = (icon, count_label)
                row.addWidget(icon)
                row.addWidget(count_label)
                row.addStretch()
                self.layout().insertLayout(
                    self.layout().count() - 1, row
                )
            else:
                _, count_label = self._hazard_labels[htype.value]
                count_label.setText(str(count))

        self._count_label.setText(f"Total hazards: {len(hazards)}")
