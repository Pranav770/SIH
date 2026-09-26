"""Mission state, search coverage and KML area (Steps 14 / 5)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from models.survivor import Survivor
from models.hazard import Hazard, HazardType


class MissionPhase(Enum):
    IDLE = "idle"
    AREA_LOADED = "area_loaded"
    TAKEOFF = "takeoff"
    SCANNING = "scanning"       # covers SEARCHING + MAPPING from the brief
    RETURNING = "returning"
    LANDING = "landing"
    COMPLETE = "complete"
    ABORTED = "aborted"


# Tolerated incoming phase strings (companion + simulation).
_PHASE_ALIASES = {
    "idle": MissionPhase.IDLE,
    "area_loaded": MissionPhase.AREA_LOADED,
    "loaded": MissionPhase.AREA_LOADED,
    "takeoff": MissionPhase.TAKEOFF,
    "searching": MissionPhase.SCANNING,
    "scan": MissionPhase.SCANNING,
    "mapping": MissionPhase.SCANNING,
    "returning": MissionPhase.RETURNING,
    "rtl": MissionPhase.RETURNING,
    "landing": MissionPhase.LANDING,
    "complete": MissionPhase.COMPLETE,
    "completed": MissionPhase.COMPLETE,
    "aborted": MissionPhase.ABORTED,
    "abort": MissionPhase.ABORTED,
    "pause": MissionPhase.IDLE,
    "paused": MissionPhase.IDLE,
}


@dataclass
class SearchCoverage:
    """Coverage derived from mission/search geometry (never hard-coded)."""

    pct: float = 0.0                     # 0..100
    cells_total: int = 0
    cells_scanned: int = 0
    area_total_m2: float = 0.0
    area_searched_m2: float = 0.0
    method: str = "none"                 # packet | geometry | none

    @property
    def pct_text(self) -> str:
        return f"{self.pct:.0f}%"

    @property
    def searched_text(self) -> str:
        return _area_text(self.area_searched_m2)

    @property
    def remaining_text(self) -> str:
        return _area_text(max(0.0, self.area_total_m2 - self.area_searched_m2))


def _area_text(m2: float) -> str:
    if m2 <= 0:
        return "N/A"
    if m2 >= 1_000_000:
        return f"{m2 / 1_000_000:.2f} km²"
    return f"{m2 / 10_000:.2f} ha"


class MissionState:
    def __init__(self):
        self.phase = MissionPhase.IDLE
        self.progress = 0.0
        self.total_grid_cells = 0
        self.scanned_cells = 0
        self.survivors_found = 0
        self.hazards_found = 0
        # extension --------------------------------------------------------
        self.name = "DISASTER SEARCH"
        self.started_at: float | None = None
        self.wp_seq: int | None = None          # current waypoint (MAVLink)
        self.coverage = SearchCoverage()
        self.area_name: str | None = None       # loaded KML
        self.area_polygon: list | None = None   # [(lat, lon), ...]
        self.cell_size_m: float = 10.0          # config: metres per grid cell
        self.origin: tuple[float, float] | None = None   # (lat, lon)

    # -- compat -----------------------------------------------------------
    @property
    def phase_text(self) -> str:
        labels = {
            MissionPhase.IDLE: "Idle",
            MissionPhase.AREA_LOADED: "Area Loaded",
            MissionPhase.TAKEOFF: "Takeoff",
            MissionPhase.SCANNING: "Searching",
            MissionPhase.RETURNING: "Returning Home",
            MissionPhase.LANDING: "Landing",
            MissionPhase.COMPLETE: "Mission Complete",
            MissionPhase.ABORTED: "Mission Aborted",
        }
        return labels.get(self.phase, "Unknown")

    def update(self, phase: str, progress: float, total: int = 0,
               scanned: int = 0) -> None:
        resolved = _PHASE_ALIASES.get(str(phase).lower().strip(),
                                      MissionPhase.IDLE)
        if resolved is not self.phase:
            if (self.phase in (MissionPhase.IDLE, MissionPhase.AREA_LOADED)
                    and resolved not in (MissionPhase.IDLE,
                                         MissionPhase.AREA_LOADED)
                    and self.started_at is None):
                self.started_at = time.time()
            self.phase = resolved
        self.progress = progress
        self.total_grid_cells = total
        self.scanned_cells = scanned

    # -- derived ----------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.phase in (MissionPhase.TAKEOFF, MissionPhase.SCANNING,
                              MissionPhase.RETURNING, MissionPhase.LANDING)

    @property
    def timer_text(self) -> str:
        if self.started_at is None:
            return "--:--:--"
        delta = int(time.time() - self.started_at)
        h, rem = divmod(max(0, delta), 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    @property
    def critical_alerts(self) -> int:
        """Set by the store (alerts own the count)."""
        return getattr(self, "_critical_alerts", 0)

    @critical_alerts.setter
    def critical_alerts(self, value: int) -> None:
        self._critical_alerts = value

    def stage_states(self, has_area: bool,
                     detections_seen: bool) -> list[tuple[str, str]]:
        """Checklist rendering: (label, state) ∈ pending / active / done."""
        p = self.phase
        flying = p not in (MissionPhase.IDLE, MissionPhase.AREA_LOADED)
        searching = p is MissionPhase.SCANNING

        def st(cond_done: bool, cond_active: bool = False) -> str:
            if cond_active:
                return "active"
            return "done" if cond_done else "pending"

        return [
            ("Area loaded", st(has_area)),
            ("Takeoff", st(flying)),
            ("Path planning", st(self.started_at is not None)),
            ("Autonomous navigation",
             st(p in (MissionPhase.RETURNING, MissionPhase.LANDING,
                      MissionPhase.COMPLETE), cond_active=searching)),
            ("Mapping", st(self.scanned_cells > 0)),
            ("AI search in progress",
             st(detections_seen and not searching, cond_active=searching)),
        ]
