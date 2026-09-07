from dataclasses import dataclass, field
import time


@dataclass
class Survivor:
    id: str
    grid_x: int
    grid_y: int
    confidence: float
    timestamp: float = field(default_factory=time.time)
    pixel_x: float = 0.0
    pixel_y: float = 0.0
