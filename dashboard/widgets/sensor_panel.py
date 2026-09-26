"""Sensor health panel (Step 13).

Renders the store's per-sensor health with glyph + state colour. Sensors
nobody reported show ``· UNKNOWN`` — never a fabricated ✓.
"""

from __future__ import annotations

import re

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from models.sensors import SENSOR_KEYS, Health, SensorStatus
from theme import (
    AMBER,
    FONT,
    GREEN,
    RED,
    TXT_BRIGHT,
    TXT_DIM,
    TXT_MUTED,
    TXT_TEXT,
)

_HAS_AGE = re.compile(r"\d\s*s\b")

_STATE_COLOR = {
    Health.HEALTHY: GREEN,
    Health.DEGRADED: AMBER,
    Health.OFFLINE: RED,
    Health.UNKNOWN: TXT_DIM,
}


class SensorPanel(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        head = QLabel("SENSOR HEALTH")
        head.setStyleSheet(f"color: {AMBER}; font-weight: bold;")
        head.setFont(QFont(FONT, 9))
        lay.addWidget(head)

        self.src = QLabel("DATA SOURCE: —")
        self.src.setStyleSheet(f"color: {TXT_MUTED}; font-weight: bold;")
        self.src.setFont(QFont(FONT, 7))
        self.src.setWordWrap(True)
        lay.addWidget(self.src)

        self._rows: dict[str, QLabel] = {}
        for key, name in SENSOR_KEYS:
            row = QLabel()
            row.setFont(QFont(FONT, 8))
            row.setStyleSheet(f"color: {TXT_TEXT};")
            lay.addWidget(row)
            self._rows[key] = row

        self._note = QLabel("health derived from reported message ages and "
                            "sensor hints — unreported sensors stay UNKNOWN")
        self._note.setStyleSheet(f"color: {TXT_DIM}; font-style: italic;")
        self._note.setFont(QFont(FONT, 7))
        self._note.setWordWrap(True)
        lay.addWidget(self._note)
        lay.addStretch()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.src.setText(self.store.data_source_text())

        for key, name in SENSOR_KEYS:
            s: SensorStatus = self.store.sensors.get(key)
            if s is None:
                self._rows[key].setText(f"· {name} — UNKNOWN")
                continue
            color = _STATE_COLOR[s.health]
            glyph = s.health.glyph
            state = s.health.value.upper()
            detail = s.detail or ""
            # append the raw age only when the detail does not already
            # carry one (details like "3D · 0.0 s ago" or "live · 1.2s"
            # must not be followed by a duplicate age)
            suffix = ""
            if s.last_rx is not None and not _HAS_AGE.search(detail):
                suffix = f" · {s.age_text}"
            self._rows[key].setText(
                f"<span style='color:{color}'>{glyph} {state:9s}</span> "
                f"<span style='color:{TXT_MUTED}'>{name}</span> "
                f"<span style='color:{TXT_DIM}'>· {detail}{suffix}</span>")
