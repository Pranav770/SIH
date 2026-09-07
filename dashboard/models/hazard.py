from dataclasses import dataclass, field
from enum import Enum
import time


class HazardType(Enum):
    FIRE = "fire"
    FLOOD = "flood"
    DEBRIS = "debris"
    ELECTRICAL = "electrical"
    STRUCTURAL = "structural"
    LANDSLIDE = "landslide"
    CHEMICAL = "chemical"
    SMOKE = "smoke"


@dataclass
class Hazard:
    type: HazardType
    grid_x: int
    grid_y: int
    severity: int
    timestamp: float = field(default_factory=time.time)
