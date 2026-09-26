"""RGB+thermal sensor-fusion bar (Step 7).

Shows, for the selected detection, what each sensor contributed and which
fusion rule combined them — including the honest single-sensor labels
(`RGB ONLY` / `THERMAL ONLY` / `NOT REPORTED`) produced by
:func:`models.detection.fused_confidence`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from models.detection import DetectionView
from theme import (
    AMBER,
    BORDER,
    CYAN,
    FONT,
    GREEN,
    INSET_BG,
    MAGENTA,
    TXT_BRIGHT,
    TXT_DIM,
    TXT_MUTED,
    TXT_TEXT,
)


def _cell(label: str) -> tuple[QLabel, QLabel]:
    k = QLabel(label)
    k.setStyleSheet(f"color: {TXT_MUTED};")
    k.setFont(QFont(FONT, 7))
    v = QLabel("--")
    v.setStyleSheet(f"color: {TXT_BRIGHT}; font-weight: bold;")
    v.setFont(QFont(FONT, 9))
    v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return k, v


class FusionBar(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._selected_id: str | None = None
        self.setFixedHeight(64)
        self.setStyleSheet(
            f"background-color: {INSET_BG}; border: 1px solid {BORDER}; "
            f"border-top: 2px solid {CYAN}; border-radius: 3px;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 3, 8, 3)
        lay.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(14)

        title = QLabel("SENSOR FUSION")
        title.setStyleSheet(f"color: {CYAN}; font-weight: bold;")
        title.setFont(QFont(FONT, 8))
        top.addWidget(title)

        self.k_rgb, self.v_rgb = _cell("RGB")
        self.k_th, self.v_th = _cell("THERMAL")
        self.k_fused, self.v_fused = _cell("FUSED")
        for k, v in ((self.k_rgb, self.v_rgb), (self.k_th, self.v_th),
                     (self.k_fused, self.v_fused)):
            top.addWidget(k)
            top.addWidget(v)

        self.mode_chip = QLabel("NOT REPORTED")
        self.mode_chip.setFont(QFont(FONT, 8, QFont.Weight.Bold))
        self.mode_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_chip.setStyleSheet(
            f"background-color: {INSET_BG}; color: {TXT_DIM}; "
            f"border: 1px solid {BORDER}; border-left: 3px solid {TXT_DIM}; "
            f"border-radius: 2px; padding: 2px 10px;")
        top.addWidget(self.mode_chip)
        top.addStretch()

        self.target = QLabel("no detection selected")
        self.target.setStyleSheet(f"color: {TXT_MUTED};")
        self.target.setFont(QFont(FONT, 8))
        top.addWidget(self.target)

        lay.addLayout(top)

        self.note = QLabel("rule: fused = 1 − (1 − rgb) · (1 − thermal); "
                           "single-sensor detections keep their own confidence")
        self.note.setStyleSheet(f"color: {TXT_DIM}; font-style: italic;")
        self.note.setFont(QFont(FONT, 7))
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

    # ------------------------------------------------------------------
    def show_detection_id(self, detection_id: str | None) -> None:
        self._selected_id = detection_id
        self.refresh()

    def show_view(self, v: DetectionView | None) -> None:
        if v is None:
            self._render(None)
            return
        self._selected_id = v.id
        self._render(v)

    def refresh(self) -> None:
        v = None
        if self._selected_id:
            for cand in self.store.detection_views():
                if cand.id == self._selected_id:
                    v = cand
                    break
        if v is None:
            views = self.store.detection_views()
            v = views[0] if views else None   # default: newest detection
        self._render(v)

    # ------------------------------------------------------------------
    def _render(self, v: DetectionView | None) -> None:
        if v is None:
            self.v_rgb.setText("--")
            self.v_th.setText("--")
            self.v_fused.setText("--")
            self.mode_chip.setText("NO DETECTIONS")
            self._style_chip(TXT_DIM)
            self.target.setText("no detection selected")
            return

        self.target.setText(f"{v.id} · {v.cls}")

        # hazards carry a detector score, not an RGB/thermal fusion — say so
        # rather than labelling a single number as "fused"
        if v.kind == "hazard":
            self.v_rgb.setText("N/A")
            self.v_th.setText("N/A")
            self.v_fused.setText(self._pct(v.confidence))
            self.mode_chip.setText("DETECTOR")
            self._style_chip(TXT_DIM)
            self.note.setText(
                "hazard confidence is the detector score — RGB/thermal "
                "fusion applies to survivor detections")
            self.note.setStyleSheet(f"color: {TXT_DIM}; font-style: italic;")
            return

        self.v_rgb.setText(self._pct(v.rgb_confidence))
        self.v_th.setText(self._pct(v.thermal_confidence))
        self.v_fused.setText(self._pct(v.fused))

        color = {"DUAL": GREEN, "RGB ONLY": CYAN, "THERMAL ONLY": AMBER
                 }.get(v.fusion_mode, TXT_DIM)
        self.mode_chip.setText(v.fusion_mode)
        self._style_chip(color)

        # honest notes for single-sensor / missing data
        if v.fusion_mode == "THERMAL ONLY":
            self.note.setText(
                "RGB confirmation unavailable — fused = thermal confidence "
                "alone (no cross-sensor agreement claimed)")
            self.note.setStyleSheet(f"color: {AMBER}; font-style: italic;")
        elif v.fusion_mode == "RGB ONLY":
            self.note.setText(
                "Thermal not reported — fused = RGB confidence alone "
                "(no cross-sensor agreement claimed)")
            self.note.setStyleSheet(f"color: {AMBER}; font-style: italic;")
        elif v.fusion_mode == "NOT REPORTED":
            self.note.setText(
                "no sensor confidences reported for this detection")
            self.note.setStyleSheet(f"color: {TXT_DIM}; font-style: italic;")
        else:
            self.note.setText(
                "rule: fused = 1 − (1 − rgb) · (1 − thermal); single-sensor "
                "detections keep their own confidence")
            self.note.setStyleSheet(f"color: {TXT_DIM}; font-style: italic;")

    def _style_chip(self, color: str) -> None:
        self.mode_chip.setStyleSheet(
            f"background-color: {INSET_BG}; color: {color}; "
            f"border: 1px solid {BORDER}; border-left: 3px solid {color}; "
            f"border-radius: 2px; padding: 2px 10px; font-weight: bold;")

    @staticmethod
    def _pct(value) -> str:
        return "N/A" if value is None else f"{value:.0%}"
