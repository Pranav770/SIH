"""MODEL tab — analytical profile of the on-device detector.

Static facts (architecture, benchmark, dataset, edge target) plus the live
status of the local inference engine.  Everything here is reference data
sourced from ``sih_model.inference`` so the dashboard label map and the model
ontology can never drift apart.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QGridLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from theme import (
    AMBER,
    BORDER,
    CYAN,
    GREEN,
    INSET_BG,
    MAGENTA,
    RED,
    TXT_BRIGHT,
    TXT_DIM,
    TXT_MUTED,
    TXT_TEXT,
    table_qss,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from sih_model.inference import (  # noqa: E402
    CLASS_DESCRIPTIONS,
    DATASET_SUMMARY,
    DATASET_TABLE,
    END_TO_END,
    LATENCY_TABLE,
    MAP_TABLE,
    MODEL_PROFILE,
    ROADMAP,
    TRAINING,
)


def _section(title: str, color: str = CYAN) -> QLabel:
    lbl = QLabel(title)
    lbl.setStyleSheet(f"color: {color}; font-weight: bold; padding-top: 4px;")
    lbl.setFont(QFont("monospace", 9))
    return lbl


def _facts(rows: list[tuple[str, str]]) -> QWidget:
    w = QWidget()
    g = QGridLayout(w)
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(8)
    g.setVerticalSpacing(2)
    for i, (k, v) in enumerate(rows):
        kl = QLabel(k)
        kl.setStyleSheet(f"color: {TXT_MUTED};")
        kl.setFont(QFont("monospace", 7))
        vl = QLabel(v)
        vl.setStyleSheet(f"color: {TXT_BRIGHT};")
        vl.setFont(QFont("monospace", 7, QFont.Weight.Bold))
        vl.setWordWrap(True)
        g.addWidget(kl, i, 0, Qt.AlignmentFlag.AlignTop)
        g.addWidget(vl, i, 1)
    g.setColumnStretch(1, 1)
    return w


def _table(headers: list[str], rows: list[list]) -> QTableWidget:
    t = QTableWidget()
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    t.setStyleSheet(table_qss())
    t.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            t.setItem(r, c, QTableWidgetItem(str(val)))
    t.setMinimumHeight(min(240, 30 + 24 * len(rows)))
    return t


class ModelPanel(QWidget):
    def __init__(self, store=None, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(3)

        title = QLabel("DETECTOR MODEL PROFILE")
        title.setStyleSheet(f"color: {CYAN}; font-weight: bold;")
        title.setFont(QFont("monospace", 10))
        lay.addWidget(title)

        sub = QLabel("On-device AI · YOLO26n → ONNX Opset 18 · Qualcomm Hexagon NPU")
        sub.setStyleSheet(f"color: {TXT_DIM}; font-style: italic;")
        sub.setFont(QFont("monospace", 7))
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # -- live local inference status ----------------------------------
        self.status = QLabel("EDGE AI: (no model loaded)")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"background-color: {INSET_BG}; color: {TXT_BRIGHT}; "
            f"border: 1px solid {BORDER}; border-left: 3px solid {AMBER}; "
            f"border-radius: 2px; padding: 5px;")
        self.status.setFont(QFont("monospace", 8))
        lay.addWidget(self.status)

        # -- architecture ---------------------------------------------------
        lay.addWidget(_section("ARCHITECTURE"))
        lay.addWidget(_facts([
            ("ARCH", MODEL_PROFILE["architecture"]),
            ("PARAMS", MODEL_PROFILE["parameters"]),
            ("LAYERS", MODEL_PROFILE["layers"]),
            ("COMPUTE", MODEL_PROFILE["compute"]),
            ("INPUT", MODEL_PROFILE["input"]),
            ("OUTPUT", MODEL_PROFILE["output"]),
            ("PyTorch (FP16)", MODEL_PROFILE["pt_fp16"]),
            ("ONNX (Opset 18)", MODEL_PROFILE["onnx"]),
        ]))

        # -- performance ----------------------------------------------------
        lay.addWidget(_section("DETECTION PERFORMANCE (mAP)"))
        lay.addWidget(_table(
            ["CLASS", "mAP", "SAR IMPACT"],
            [[name, f"{score:.3f}", impact] for name, score, impact in MAP_TABLE]))
        road = QLabel("ROADMAP: " + ROADMAP)
        road.setWordWrap(True)
        road.setStyleSheet(f"color: {AMBER}; font-style: italic;")
        road.setFont(QFont("monospace", 7))
        lay.addWidget(road)

        # -- latency --------------------------------------------------------
        lay.addWidget(_section("EDGE LATENCY (per image)"))
        lay.addWidget(_table(
            ["STAGE", "LATENCY"],
            [[stage, f"{ms:.1f} ms"] for stage, ms in LATENCY_TABLE]
            + [["END-TO-END", END_TO_END]]))

        # -- training -------------------------------------------------------
        lay.addWidget(_section("TRAINING"))
        lay.addWidget(_facts([
            ("PHASE 1", TRAINING["phase1"]),
            ("PHASE 2", TRAINING["phase2"]),
            ("AUGMENT", TRAINING["augment"]),
            ("HARDWARE", TRAINING["hardware"]),
        ]))

        # -- dataset --------------------------------------------------------
        lay.addWidget(_section("UNIFIED DATASET BENCHMARK"))
        ds = QLabel(DATASET_SUMMARY)
        ds.setWordWrap(True)
        ds.setStyleSheet(f"color: {TXT_DIM}; font-style: italic;")
        ds.setFont(QFont("monospace", 7))
        lay.addWidget(ds)
        lay.addWidget(_table(
            ["ID", "CLASS", "TRAIN", "VAL"],
            [[i, name, f"{tr:,}", f"{va:,}"] for i, name, _src, tr, va in DATASET_TABLE]))

        # -- target ---------------------------------------------------------
        lay.addWidget(_section("TARGET PLATFORM"))
        lay.addWidget(_facts([
            ("NPU", MODEL_PROFILE["target"]),
            ("CLOUD DEP.", MODEL_PROFILE["cloud_dependency"]),
        ]))

        lay.addStretch()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Static content — nothing to poll."""

    def set_inference_status(self, status: dict | None) -> None:
        if not status:
            return
        if not status.get("available"):
            self.status.setText(
                "EDGE AI: UNAVAILABLE — "
                + (status.get("reason") or "no model loaded"))
            self.status.setStyleSheet(
                f"background-color: {INSET_BG}; color: {AMBER}; "
                f"border: 1px solid {BORDER}; border-left: 3px solid {AMBER}; "
                f"border-radius: 2px; padding: 5px;")
            return
        self.status.setText(
            f"EDGE AI: READY · {status.get('backend')} · {status.get('model')}  |  "
            f"{status.get('fps', 0):.1f} FPS · {status.get('latency_ms', 0):.1f} ms · "
            f"{status.get('detections', 0)} detections")
        self.status.setStyleSheet(
            f"background-color: {INSET_BG}; color: {TXT_BRIGHT}; "
            f"border: 1px solid {BORDER}; border-left: 3px solid {GREEN}; "
            f"border-radius: 2px; padding: 5px;")
