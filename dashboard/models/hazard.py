from dataclasses import dataclass, field
from enum import Enum
import time

from models.detection import Severity, HAZARD_CLASS


class HazardType(Enum):
    FIRE = "fire"
    FLOOD = "flood"
    DEBRIS = "debris"
    ELECTRICAL = "electrical"
    STRUCTURAL = "structural"
    LANDSLIDE = "landslide"
    CHEMICAL = "chemical"
    SMOKE = "smoke"


# Tolerate the short codes used by theme.HAZARD_COLORS / older senders.
_HAZARD_ALIASES = {
    "FIRE": HazardType.FIRE,
    "FLOOD": HazardType.FLOOD,
    "DEBRIS": HazardType.DEBRIS,
    "ELEC": HazardType.ELECTRICAL,
    "ELECTRICAL": HazardType.ELECTRICAL,
    "POWER": HazardType.ELECTRICAL,
    "STRUCT": HazardType.STRUCTURAL,
    "STRUCTURAL": HazardType.STRUCTURAL,
    "DAMAGE": HazardType.STRUCTURAL,
    "LANDSL": HazardType.LANDSLIDE,
    "LANDSLIDE": HazardType.LANDSLIDE,
    "CHEM": HazardType.CHEMICAL,
    "CHEMICAL": HazardType.CHEMICAL,
    "LEAK": HazardType.CHEMICAL,
    "SMOKE": HazardType.SMOKE,
}


def coerce_hazard_type(raw, default: HazardType = HazardType.DEBRIS) -> HazardType:
    """Accept ``HazardType``, ``"fire"``, ``"FIRE"``, ``"ELEC"`` …"""
    if isinstance(raw, HazardType):
        return raw
    if raw is None:
        return default
    text = str(raw).strip().upper()
    if text in _HAZARD_ALIASES:
        return _HAZARD_ALIASES[text]
    try:
        return HazardType(text.lower())
    except ValueError:
        return default


@dataclass
class Hazard:
    type: HazardType
    grid_x: int
    grid_y: int
    severity: int                 # historic 1..4 raw value (kept for compat)
    timestamp: float = field(default_factory=time.time)
    # extended schema -----------------------------------------------------
    id: str = ""
    confidence: float = 0.0
    lat: float | None = None
    lon: float | None = None
    severity_level: Severity | None = None   # normalised LOW..CRITICAL
    status: str = "ACTIVE"                   # ACTIVE / ACK / CLEARED
    source: str = "live"
    risk_reasons: list = field(default_factory=list)

    @property
    def age_s(self) -> float:
        return max(0.0, time.time() - self.timestamp) if self.timestamp else 0.0

    @property
    def effective_severity(self) -> Severity:
        if self.severity_level is not None:
            return self.severity_level
        return Severity.from_raw(self.severity, Severity.MEDIUM)

    @property
    def class_label(self) -> str:
        return HAZARD_CLASS.get(self.type.value, self.type.value.upper())

    @property
    def location_text(self) -> str:
        if self.lat is not None and self.lon is not None:
            return f"{self.lat:.6f}, {self.lon:.6f}"
        return f"GRID {self.grid_x},{self.grid_y}"
