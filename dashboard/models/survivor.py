from dataclasses import dataclass, field
import time

from models.detection import fused_confidence, Severity


@dataclass
class Survivor:
    """A detected survivor (geo-tagged when a coordinate frame is known).

    ``grid_x/grid_y`` are the companion-computer occupancy-grid cells;
    ``lat/lon`` are attached by the store when a mission origin exists
    (packet-provided coordinates always win).
    """

    id: str
    grid_x: int
    grid_y: int
    confidence: float
    timestamp: float = field(default_factory=time.time)
    pixel_x: float = 0.0
    pixel_y: float = 0.0
    # geo-tag (Step 5) — None until an origin is available
    lat: float | None = None
    lon: float | None = None
    # sensor fusion (Step 7)
    rgb_confidence: float | None = None
    thermal_confidence: float | None = None
    fused_confidence: float = 0.0
    fusion_mode: str = "NOT REPORTED"
    bbox: list | None = None
    # rescue priority (Step 10) — filled by the store's priority engine
    priority: str = "P4"
    priority_score: float = 0.0
    priority_reasons: list = field(default_factory=list)
    severity: Severity | None = None
    # provenance
    source: str = "live"

    @property
    def age_s(self) -> float:
        return max(0.0, time.time() - self.timestamp) if self.timestamp else 0.0

    @property
    def rgb_ok(self) -> bool | None:
        """True / False / None (not reported)."""
        return None if self.rgb_confidence is None else self.rgb_confidence > 0

    @property
    def thermal_ok(self) -> bool | None:
        return None if self.thermal_confidence is None else self.thermal_confidence > 0

    @property
    def thermal_only(self) -> bool:
        return self.thermal_confidence is not None and self.rgb_confidence is None

    @property
    def location_text(self) -> str:
        if self.lat is not None and self.lon is not None:
            return f"{self.lat:.6f}, {self.lon:.6f}"
        return f"GRID {self.grid_x},{self.grid_y}"

    def recompute_fusion(self) -> None:
        self.fused_confidence, self.fusion_mode = fused_confidence(
            self.rgb_confidence, self.thermal_confidence, self.confidence
        )
