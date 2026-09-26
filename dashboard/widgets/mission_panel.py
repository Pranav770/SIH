"""Mission progress panel (Step 14): phase, timer, coverage, stage
checklist and honest result counts.

Coverage numbers come from :class:`models.mission.SearchCoverage`
(packet-reported or geometry-derived — method is shown so nobody mistakes
it for a GPS measurement).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal as pyqtSignal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QProgressBar,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from models.mission import MissionPhase
from state.sim import SCENARIOS
from theme import (
    AMBER,
    BORDER,
    CYAN,
    FONT,
    GREEN,
    INSET_BG,
    MAGENTA,
    RED,
    TXT_BRIGHT,
    TXT_DIM,
    TXT_MUTED,
    TXT_TEXT,
    input_qss,
    small_button_qss,
)

_PHASE_COLORS = {
    MissionPhase.IDLE: TXT_DIM,
    MissionPhase.AREA_LOADED: CYAN,
    MissionPhase.TAKEOFF: GREEN,
    MissionPhase.SCANNING: GREEN,
    MissionPhase.RETURNING: AMBER,
    MissionPhase.LANDING: AMBER,
    MissionPhase.COMPLETE: CYAN,
    MissionPhase.ABORTED: RED,
}

_STATE_ICONS = {"done": ("✓", GREEN), "active": ("▸", AMBER),
                "pending": ("○", TXT_DIM)}


class MissionPanel(QWidget):
    scenario_selected = pyqtSignal(int)     # scenario number 0..7

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # -- phase + timer --------------------------------------------------
        top = QGridLayout()
        self.phase = QLabel("IDLE")
        self.phase.setFont(QFont(FONT, 13, QFont.Weight.Bold))
        self.phase.setStyleSheet(f"color: {TXT_BRIGHT};")
        top.addWidget(QLabel("PHASE"), 0, 0)
        top.addWidget(self.phase, 0, 1)
        self.timer = QLabel("--:--:--")
        self.timer.setFont(QFont(FONT, 13, QFont.Weight.Bold))
        self.timer.setStyleSheet(f"color: {CYAN};")
        self.timer.setAlignment(Qt.AlignmentFlag.AlignRight)
        top.addWidget(QLabel("ELAPSED"), 0, 2)
        top.addWidget(self.timer, 0, 3)
        for col, label in ((0, "PHASE"), (2, "ELAPSED")):
            k = top.itemAtPosition(0, col)
            if k is not None and k.widget():
                k.widget().setStyleSheet(f"color: {TXT_MUTED};")
                k.widget().setFont(QFont(FONT, 7))
        lay.addLayout(top)

        # -- demo scenarios (shown in SITL / SIMULATION modes) -------------
        srow = QHBoxLayout()
        srow.setSpacing(4)
        slbl = QLabel("SCENARIO")
        slbl.setStyleSheet(f"color: {TXT_MUTED};")
        slbl.setFont(QFont(FONT, 7))
        srow.addWidget(slbl)
        self.scenario_combo = QComboBox()
        self.scenario_combo.setStyleSheet(input_qss())
        self.scenario_combo.setFont(QFont(FONT, 8))
        for n in sorted(SCENARIOS):
            name, desc = SCENARIOS[n]
            label = name if n == 0 else f"{n} · {name}"
            self.scenario_combo.addItem(label, userData=n)
            self.scenario_combo.setItemData(
                self.scenario_combo.count() - 1, desc,
                Qt.ItemDataRole.ToolTipRole)
        self.scenario_combo.currentIndexChanged.connect(
            self._on_scenario_changed)
        srow.addWidget(self.scenario_combo, stretch=1)
        self.btn_run_scenario = QPushButton("RUN")
        self.btn_run_scenario.setStyleSheet(small_button_qss(AMBER))
        self.btn_run_scenario.setFont(QFont(FONT, 8, QFont.Weight.Bold))
        self.btn_run_scenario.clicked.connect(self._on_run_scenario)
        srow.addWidget(self.btn_run_scenario)
        lay.addLayout(srow)

        self.scenario_desc = QLabel(SCENARIOS[0][1])
        self.scenario_desc.setStyleSheet(f"color: {TXT_DIM}; font-style: italic;")
        self.scenario_desc.setFont(QFont(FONT, 7))
        self.scenario_desc.setWordWrap(True)
        lay.addWidget(self.scenario_desc)

        # -- coverage --------------------------------------------------------
        clabel = QLabel("SEARCH COVERAGE")
        clabel.setStyleSheet(f"color: {TXT_MUTED};")
        clabel.setFont(QFont(FONT, 7))
        lay.addWidget(clabel)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFixedHeight(16)
        self.bar.setTextVisible(True)
        self.bar.setFormat("%p%")
        self.bar.setStyleSheet(
            f"QProgressBar {{ background-color: {INSET_BG}; "
            f"border: 1px solid {BORDER}; border-radius: 2px; "
            f"color: {TXT_BRIGHT}; text-align: center; font-weight: bold; }}"
            f"QProgressBar::chunk {{ background-color: {GREEN}; "
            f"border-radius: 1px; }}")
        lay.addWidget(self.bar)

        self.cov_detail = QLabel("0 / 0 cells · method: none")
        self.cov_detail.setStyleSheet(f"color: {TXT_DIM};")
        self.cov_detail.setFont(QFont(FONT, 7))
        lay.addWidget(self.cov_detail)

        # -- counts ----------------------------------------------------------
        cg = QGridLayout()
        cg.setHorizontalSpacing(8)
        self._counts: dict[str, QLabel] = {}
        for i, (key, label, color) in enumerate((
            ("survivors", "SURVIVORS", MAGENTA),
            ("hazards", "HAZARDS", AMBER),
            ("critical", "CRIT ALERTS", RED),
            ("wp", "WAYPOINT", CYAN),
        )):
            k = QLabel(label)
            k.setStyleSheet(f"color: {TXT_MUTED};")
            k.setFont(QFont(FONT, 7))
            v = QLabel("—")
            v.setStyleSheet(f"color: {color}; font-weight: bold;")
            v.setFont(QFont(FONT, 11, QFont.Weight.Bold))
            r, c = divmod(i, 2)
            cg.addWidget(k, r, c * 2)
            cg.addWidget(v, r, c * 2 + 1)
            self._counts[key] = v
        lay.addLayout(cg)

        # -- area ------------------------------------------------------------
        self.area = QLabel("NO AREA LOADED")
        self.area.setStyleSheet(
            f"background-color: {INSET_BG}; color: {TXT_MUTED}; "
            f"border: 1px solid {BORDER}; border-radius: 2px; padding: 3px;")
        self.area.setFont(QFont(FONT, 8, QFont.Weight.Bold))
        self.area.setWordWrap(True)
        lay.addWidget(self.area)

        # -- stage checklist --------------------------------------------------
        shead = QLabel("PIPELINE CHECKLIST")
        shead.setStyleSheet(f"color: {CYAN}; font-weight: bold;")
        shead.setFont(QFont(FONT, 9))
        lay.addWidget(shead)

        self._stages: list[tuple[QLabel, QLabel]] = []
        for _ in range(6):
            icon = QLabel("○")
            icon.setFixedWidth(16)
            icon.setStyleSheet(f"color: {TXT_DIM};")
            icon.setFont(QFont(FONT, 9, QFont.Weight.Bold))
            text = QLabel("—")
            text.setStyleSheet(f"color: {TXT_MUTED};")
            text.setFont(QFont(FONT, 8))
            row = QGridLayout()
            row.setHorizontalSpacing(6)
            row.addWidget(icon, 0, 0)
            row.addWidget(text, 0, 1)
            lay.addLayout(row)
            self._stages.append((icon, text))

        lay.addStretch()

    # ------------------------------------------------------------------
    def _on_scenario_changed(self, index: int) -> None:
        n = self.scenario_combo.itemData(index)
        if n is not None and n in SCENARIOS:
            self.scenario_desc.setText(SCENARIOS[n][1])

    def _on_run_scenario(self) -> None:
        n = self.scenario_combo.currentData()
        if n is not None:
            self.scenario_selected.emit(int(n))

    def set_sim_controls_visible(self, visible: bool) -> None:
        """Scenario launcher only makes sense with the simulation engine."""
        self.scenario_combo.setVisible(visible)
        self.btn_run_scenario.setVisible(visible)
        self.scenario_desc.setVisible(visible)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        m = self.store.mission

        self.phase.setText(m.phase_text.upper())
        self.phase.setStyleSheet(
            f"color: {_PHASE_COLORS.get(m.phase, TXT_BRIGHT)}; "
            f"font-weight: bold;")
        self.timer.setText(m.timer_text)

        cov = m.coverage
        pct = int(round(max(0.0, min(100.0, cov.pct))))
        self.bar.setValue(pct)
        total_ha = cov.area_total_m2 / 10_000.0
        self.cov_detail.setText(
            f"{cov.cells_scanned} / {cov.cells_total} cells · "
            f"searched {cov.searched_text} of {total_ha:.2f} ha · "
            f"method: {cov.method}")
        if cov.method == "none":
            self.cov_detail.setStyleSheet(f"color: {TXT_DIM};")
        else:
            self.cov_detail.setStyleSheet(f"color: {TXT_MUTED};")

        self._counts["survivors"].setText(str(len(self.store.survivors)))
        self._counts["hazards"].setText(str(len(self.store.hazards)))
        crit = self.store.critical_alert_count
        self._counts["critical"].setText(str(crit))
        wp = m.wp_seq
        self._counts["wp"].setText(
            str(wp) if wp is not None else "N/A")

        self.area.setText(
            f"AREA: {m.area_name or 'none loaded'} · grid "
            f"{m.cell_size_m:.0f} m/cell"
            + (f" · origin {m.origin[0]:.4f},{m.origin[1]:.4f}"
               if m.origin else " · GEO PENDING"))

        stages = m.stage_states(
            has_area=m.area_name is not None,
            detections_seen=bool(self.store.survivors or self.store.hazards),
        )
        for (icon, text), (label, state) in zip(self._stages, stages):
            glyph, color = _STATE_ICONS.get(state, ("○", TXT_DIM))
            icon.setText(glyph)
            icon.setStyleSheet(f"color: {color}; font-weight: bold;")
            text.setText(label)
            text.setStyleSheet(
                f"color: {TXT_TEXT if state == 'active' else TXT_MUTED};"
                + (" font-weight: bold;" if state == "active" else ""))
