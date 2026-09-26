"""Detection schema (Step 6).

Every AI result the dashboard shows — survivor, hazard or raw detector
output — is normalised into a :class:`DetectionView` so the AI panel,
situation report and priority engine all consume one structure instead of
re-deriving fields per widget.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Severity(Enum):
    """Configurable hazard severity scale (Step 8)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {"low": 0, "medium": 1, "high": 2, "critical": 3}[self.value]

    @property
    def label(self) -> str:
        return self.value.upper()

    def upgrade(self, steps: int = 1) -> "Severity":
        r = min(3, self.rank + steps)
        return _BY_RANK[r]

    def downgrade(self, steps: int = 1) -> "Severity":
        r = max(0, self.rank - steps)
        return _BY_RANK[r]

    @classmethod
    def from_raw(cls, raw, default: "Severity | None" = None) -> "Severity | None":
        """Accept the historic int severity (1..4), a string, or None."""
        if isinstance(raw, cls):
            return raw
        if raw is None:
            return default
        if isinstance(raw, (int, float)):
            return {1: cls.LOW, 2: cls.MEDIUM, 3: cls.HIGH,
                    4: cls.CRITICAL}.get(int(raw), default)
        if isinstance(raw, str):
            v = raw.strip().lower()
            for sev in cls:
                if sev.value == v or sev.label == raw.strip().upper():
                    return sev
            # tolerate abbreviations from older senders
            alias = {"crit": cls.CRITICAL, "med": cls.MEDIUM}
            if v in alias:
                return alias[v]
        return default


_BY_RANK = {s.rank: s for s in Severity}


# Canonical class labels (Step 6 counter list)
CLASS_PERSON = "PERSON"
CLASS_SURVIVOR = "SURVIVOR"
HAZARD_CLASS = {
    "fire": "FIRE",
    "smoke": "SMOKE",
    "flood": "FLOOD",
    "structural": "DAMAGED STRUCTURE",
    "electrical": "ELECTRICAL LINE",
    "debris": "DEBRIS",
    "landslide": "LANDSLIDE",
    "chemical": "CHEMICAL LEAK",
}

ALL_CLASSES = [
    CLASS_PERSON, CLASS_SURVIVOR, "FIRE", "SMOKE", "FLOOD",
    "DAMAGED STRUCTURE", "ELECTRICAL LINE", "DEBRIS", "LANDSLIDE",
    "CHEMICAL LEAK",
]


def fused_confidence(rgb, thermal, fallback: float = 0.0) -> tuple[float, str]:
    """Documented sensor-fusion rule (Step 7).

    * both sensors reported  -> independent-evidence combination
      ``1 - (1 - rgb) * (1 - thermal)``
    * single sensor reported -> that sensor's confidence, mode labelled
      ``RGB ONLY`` / ``THERMAL ONLY`` (no invented agreement)
    * neither reported       -> caller's fallback, mode ``NOT REPORTED``
    """
    if rgb is not None and thermal is not None:
        return 1.0 - (1.0 - float(rgb)) * (1.0 - float(thermal)), "DUAL"
    if rgb is not None:
        return float(rgb), "RGB ONLY"
    if thermal is not None:
        return float(thermal), "THERMAL ONLY"
    return float(fallback), "NOT REPORTED"


@dataclass
class DetectionView:
    """Normalised record shared by AI panel / report / priority engine."""

    id: str
    cls: str                       # SURVIVOR / FIRE / ...
    confidence: float
    timestamp: float
    kind: str                      # "survivor" | "hazard" | "detection"
    lat: float | None = None
    lon: float | None = None
    grid_x: int = 0
    grid_y: int = 0
    severity: Severity | None = None
    source: str = "live"           # live | sim
    rgb_confidence: float | None = None
    thermal_confidence: float | None = None
    fused: float = 0.0
    fusion_mode: str = "NOT REPORTED"
    bbox: list | None = None
    priority: str | None = None    # survivor priority P1..P4
    priority_reasons: list = field(default_factory=list)
    status: str = ""               # hazard status (ACTIVE/ACK/...)
    age_s: float = 0.0

    @property
    def has_rgb(self) -> bool | None:
        return self.rgb_confidence is not None

    @property
    def has_thermal(self) -> bool | None:
        return self.thermal_confidence is not None

    @property
    def location_text(self) -> str:
        if self.lat is not None and self.lon is not None:
            return f"{self.lat:.6f}, {self.lon:.6f}"
        if self.grid_x or self.grid_y:
            return f"GRID {self.grid_x},{self.grid_y}"
        return "UNKNOWN"


def fresh_age(ts: float) -> float:
    if not ts:
        return 0.0
    return max(0.0, time.time() - ts)
