"""AI perception panel (Step 6): edge-inference status, class counters and
individual detection records with an explainable detail card.

Values come from the store — where nothing was reported this panel renders
``N/A`` / ``NOT REPORTED`` instead of inventing measurements.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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

from models.ai import AIInferenceStatus
from models.detection import ALL_CLASSES, DetectionView
from theme import (
    AMBER,
    BORDER,
    CYAN,
    FONT,
    GREEN,
    INSET_BG,
    MAGENTA,
    PRIORITY_COLORS,
    RED,
    SEVERITY_COLORS,
    TXT_BRIGHT,
    TXT_DIM,
    TXT_MUTED,
    TXT_TEXT,
)

_COLS = ["ID", "CLASS", "CONF", "SENSOR", "LOC", "PRIO"]


class AIPanel(QWidget):
    detection_selected = Signal(str)     # detection id

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._rows: list[DetectionView] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # -- on-device AI status ------------------------------------------
        head = QLabel("ON-DEVICE AI")
        head.setStyleSheet(f"color: {CYAN}; font-weight: bold;")
        head.setFont(QFont(FONT, 9))
        lay.addWidget(head)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(8)
        self._vals: dict[str, QLabel] = {}
        rows = [
            ("state", "STATE"), ("model", "MODEL"),
            ("fps", "FPS"), ("lat", "LATENCY"),
            ("cpu", "CPU"), ("gpu", "GPU"),
            ("ram", "RAM"), ("cloud", "CLOUD DEP."),
        ]
        for i, (key, label) in enumerate(rows):
            k = QLabel(label)
            k.setStyleSheet(f"color: {TXT_MUTED};")
            k.setFont(QFont(FONT, 7))
            v = QLabel("N/A")
            v.setStyleSheet(f"color: {TXT_BRIGHT}; font-weight: bold;")
            v.setFont(QFont(FONT, 8))
            v.setAlignment(Qt.AlignmentFlag.AlignRight)
            r, c = divmod(i, 2)
            self.grid.addWidget(k, r, c * 2)
            self.grid.addWidget(v, r, c * 2 + 1)
            self._vals[key] = v
        lay.addLayout(self.grid)

        self.meta = QLabel("AI STATUS: N/A")
        self.meta.setStyleSheet(f"color: {TXT_DIM};")
        self.meta.setFont(QFont(FONT, 7))
        lay.addWidget(self.meta)

        # -- local on-device inference (dashboard host) --------------------
        self.edge = QLabel("LOCAL EDGE INFERENCE: idle")
        self.edge.setWordWrap(True)
        self.edge.setStyleSheet(
            f"background-color: {INSET_BG}; color: {TXT_DIM}; "
            f"border: 1px solid {BORDER}; border-left: 3px solid {TXT_DIM}; "
            f"border-radius: 2px; padding: 4px;")
        self.edge.setFont(QFont(FONT, 7))
        lay.addWidget(self.edge)

        # -- class counters ------------------------------------------------
        chead = QLabel("DETECTOR COUNTERS")
        chead.setStyleSheet(f"color: {CYAN}; font-weight: bold;")
        chead.setFont(QFont(FONT, 9))
        lay.addWidget(chead)

        self.counter_chips: dict[str, QLabel] = {}
        cg = QGridLayout()
        cg.setHorizontalSpacing(4)
        cg.setVerticalSpacing(3)
        for i, cls in enumerate(ALL_CLASSES):
            chip = QLabel(f"{cls} · 0")
            chip.setFont(QFont(FONT, 7, QFont.Weight.Bold))
            chip.setStyleSheet(
                f"background-color: {INSET_BG}; color: {TXT_DIM}; "
                f"border: 1px solid {BORDER}; border-radius: 2px; "
                f"padding: 2px 5px;")
            r, c = divmod(i, 2)
            cg.addWidget(chip, r, c)
            self.counter_chips[cls] = chip
        cg.setColumnStretch(0, 1)
        cg.setColumnStretch(1, 1)
        lay.addLayout(cg)

        # -- detection records ---------------------------------------------
        dhead = QLabel("DETECTION RECORDS")
        dhead.setStyleSheet(f"color: {MAGENTA}; font-weight: bold;")
        dhead.setFont(QFont(FONT, 9))
        lay.addWidget(dhead)

        self.table = QTableWidget()
        self.table.setColumnCount(len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        from theme import table_qss
        self.table.setStyleSheet(table_qss())
        self.table.setMinimumHeight(110)
        self.table.itemSelectionChanged.connect(self._on_select)
        lay.addWidget(self.table, stretch=1)

        # -- explainable detail card ---------------------------------------
        self.detail = QLabel("Select a detection record to see how it was "
                             "fused and why it was prioritised.")
        self.detail.setTextFormat(Qt.TextFormat.RichText)
        self.detail.setStyleSheet(
            f"background-color: {INSET_BG}; color: {TXT_TEXT}; "
            f"border: 1px solid {BORDER}; border-left: 3px solid {MAGENTA}; "
            f"border-radius: 2px; padding: 5px;")
        self.detail.setFont(QFont(FONT, 8))
        self.detail.setWordWrap(True)
        self.detail.setMinimumHeight(74)
        lay.addWidget(self.detail)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        ai: AIInferenceStatus = self.store.ai
        reported = ai.reported
        self._vals["state"].setText(
            ("ON-DEVICE" if ai.on_device else "OFFLOADED")
            if ai.on_device is not None else "NOT REPORTED")
        self._vals["state"].setStyleSheet(
            "color: %s; font-weight: bold;" %
            (GREEN if ai.on_device and not ai.stale else
             AMBER if reported else TXT_DIM))
        self._vals["model"].setText(ai.model or "N/A")
        self._vals["fps"].setText(AIInferenceStatus.fmt(ai.fps, digits=1))
        self._vals["lat"].setText(AIInferenceStatus.fmt(ai.latency_ms, " ms"))
        self._vals["cpu"].setText(AIInferenceStatus.fmt(ai.cpu_pct, "%"))
        self._vals["gpu"].setText(AIInferenceStatus.fmt(ai.gpu_pct, "%"))
        if ai.ram_used_gb is not None:
            total = (f"/{ai.ram_total_gb:.0f}G"
                     if ai.ram_total_gb is not None else "")
            self._vals["ram"].setText(f"{ai.ram_used_gb:.1f}G{total}")
        else:
            self._vals["ram"].setText("N/A")
        self._vals["cloud"].setText(ai.cloud_dependency or "N/A")

        if not reported:
            self.meta.setText("AI STATUS: N/A — nothing reported yet")
            self.meta.setStyleSheet(f"color: {TXT_DIM};")
        else:
            age = ai.age_s
            stale = ai.stale
            if age is None:
                age_txt = "time unknown"
            elif age < 1:
                age_txt = "just now"
            else:
                age_txt = f"{age:.0f}s ago"
            src = {"live": "LIVE", "sim": "SIMULATION"}.get(
                ai.source, "UNKNOWN")
            state = "STALE" if stale else "LIVE"
            self.meta.setText(
                f"AI STATUS: {state} · source {src} · updated {age_txt}")
            self.meta.setStyleSheet(
                f"color: {AMBER if stale else GREEN}; font-weight: bold;")

        # counters
        counts = self.store.class_counts()
        for cls, chip in self.counter_chips.items():
            n = counts.get(cls, 0)
            chip.setText(f"{cls} · {n}")
            if n:
                chip.setStyleSheet(
                    f"background-color: {INSET_BG}; color: {TXT_BRIGHT}; "
                    f"border: 1px solid {BORDER}; "
                    f"border-left: 3px solid {MAGENTA}; "
                    f"border-radius: 2px; padding: 2px 5px; "
                    f"font-weight: bold;")
            else:
                chip.setStyleSheet(
                    f"background-color: {INSET_BG}; color: {TXT_DIM}; "
                    f"border: 1px solid {BORDER}; border-radius: 2px; "
                    f"padding: 2px 5px;")

        self._reload_table()

    def set_local_inference(self, status: dict | None) -> None:
        """Live status of the dashboard-host YOLO engine (edge AI)."""
        if not status:
            return
        if not status.get("available"):
            self.edge.setText(
                "LOCAL EDGE INFERENCE: UNAVAILABLE — "
                + (status.get("reason") or "no model loaded"))
            self.edge.setStyleSheet(
                f"background-color: {INSET_BG}; color: {AMBER}; "
                f"border: 1px solid {BORDER}; border-left: 3px solid {AMBER}; "
                f"border-radius: 2px; padding: 4px;")
            return
        self.edge.setText(
            f"LOCAL EDGE INFERENCE: {status.get('backend')} · "
            f"{status.get('model')}\n"
            f"{status.get('fps', 0):.1f} FPS · {status.get('latency_ms', 0):.1f} ms · "
            f"{status.get('detections', 0)} detections")
        self.edge.setStyleSheet(
            f"background-color: {INSET_BG}; color: {TXT_BRIGHT}; "
            f"border: 1px solid {BORDER}; border-left: 3px solid {GREEN}; "
            f"border-radius: 2px; padding: 4px;")

    def _reload_table(self) -> None:
        selected = None
        row = self.table.currentRow()
        if 0 <= row < len(self._rows):
            selected = self._rows[row].id

        self._rows = self.store.detection_views()
        self.table.setRowCount(len(self._rows))
        select_row = -1
        for i, v in enumerate(self._rows):
            items = [
                QTableWidgetItem(v.id),
                QTableWidgetItem(v.cls),
                QTableWidgetItem(self._conf_text(v)),
                QTableWidgetItem(self._sensor_text(v)),
                QTableWidgetItem(v.location_text),
                QTableWidgetItem(self._prio_text(v)),
            ]
            for c, item in enumerate(items):
                if c == 0:
                    item.setForeground(QColor(
                        MAGENTA if v.kind == "survivor" else AMBER))
                elif c == 5:
                    color = self._prio_color(v)
                    if color:
                        item.setForeground(QColor(color))
                self.table.setItem(i, c, item)
            if selected is not None and v.id == selected:
                select_row = i

        if select_row >= 0:
            self.table.selectRow(select_row)
        elif selected is None:
            self._render_detail(None)

    @staticmethod
    def _conf_text(v: DetectionView) -> str:
        # a hazard with no reported confidence shows N/A, never a fake 0%
        if v.confidence is None or v.confidence <= 0:
            return "N/A"
        return f"{v.confidence:.0%}"

    @staticmethod
    def _sensor_text(v: DetectionView) -> str:
        if v.kind == "survivor":
            return {"DUAL": "RGB+TH", "RGB ONLY": "RGB",
                    "THERMAL ONLY": "THERMAL"}.get(v.fusion_mode, "—")
        return "—"

    @staticmethod
    def _prio_text(v: DetectionView) -> str:
        if v.kind == "survivor":
            return v.priority or "P4"
        if v.severity is not None:
            return v.severity.label
        return "—"

    @staticmethod
    def _prio_color(v: DetectionView) -> str | None:
        if v.kind == "survivor":
            return PRIORITY_COLORS.get(v.priority or "P4")
        if v.severity is not None:
            return SEVERITY_COLORS.get(v.severity.label)
        return None

    def _on_select(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._rows):
            v = self._rows[row]
            self._render_detail(v)
            self.detection_selected.emit(v.id)

    def _render_detail(self, v: DetectionView | None) -> None:
        if v is None:
            self.detail.setText(
                "Select a detection record to see how it was fused and "
                "why it was prioritised.")
            return

        sev_html = ""
        if v.severity is not None:
            sev_html = (f"<span style='color:{SEVERITY_COLORS[v.severity.label]}'>"
                        f" · {v.severity.label}</span>")

        sensor_line = (
            f"RGB {self._pct(v.rgb_confidence)} · "
            f"THERMAL {self._pct(v.thermal_confidence)} · "
            f"<b>FUSED {self._pct(v.fused)}</b> ({v.fusion_mode})"
        )
        if v.fusion_mode == "THERMAL ONLY":
            sensor_line += ("<br><span style='color:#ffb63d'>"
                            "RGB CONFIRMATION: NOT AVAILABLE</span>")
        elif v.fusion_mode == "NOT REPORTED" and v.kind == "survivor":
            sensor_line += ("<br><span style='color:#5c7ba0'>"
                            "no sensor confidences reported</span>")

        prio_line = ""
        if v.kind == "survivor" and v.priority:
            score = self._priority_score(v)
            reasons = "".join(f"<br> &bull; {r}" for r in v.priority_reasons)
            color = PRIORITY_COLORS.get(v.priority, TXT_TEXT)
            score_txt = (f" (score {score:.0f})" if score is not None else "")
            prio_line = (
                f"<br><span style='color:{color}'><b>{v.priority}</b>"
                f"</span>{score_txt}"
                f"<span style='color:{TXT_MUTED}'> — why:{reasons}</span>"
            )

        self.detail.setText(
            f"<b style='color:{MAGENTA}'>{v.id}</b> "
            f"<span style='color:{TXT_TEXT}'>{v.cls}</span>{sev_html} "
            f"· conf <b>{self._conf_text(v)}</b>"
            f"<br>{sensor_line}"
            f"<br>geo <span style='color:{TXT_MUTED}'>{v.location_text}</span>"
            f"{prio_line}"
        )

    def _priority_score(self, v: DetectionView):
        for s in self.store.survivors:
            if s.id == v.id:
                return getattr(s, "priority_score", None)
        return None

    @staticmethod
    def _pct(value) -> str:
        return "N/A" if value is None else f"{value:.0%}"
