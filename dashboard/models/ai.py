"""On-device AI / edge inference status (Step 12).

Values are ``None`` when nothing reported them — the UI must render
``N/A`` / ``NOT REPORTED`` instead of inventing measurements.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class AIInferenceStatus:
    on_device: bool | None = None
    model: str | None = None
    fps: float | None = None
    latency_ms: float | None = None
    cpu_pct: float | None = None
    gpu_pct: float | None = None
    ram_used_gb: float | None = None
    ram_total_gb: float | None = None
    cloud_dependency: str | None = None
    source: str = "unknown"          # live | sim | unknown
    last_rx: float | None = field(default=None, repr=False)

    @property
    def reported(self) -> bool:
        return self.last_rx is not None or self.model is not None

    @property
    def age_s(self) -> float | None:
        if self.last_rx is None:
            return None
        return time.monotonic() - self.last_rx

    @property
    def stale(self) -> bool:
        return self.age_s is None or self.age_s > 5.0

    @staticmethod
    def fmt(value, suffix: str = "", digits: int = 0) -> str:
        if value is None:
            return "N/A"
        if isinstance(value, float):
            return f"{value:.{digits}f}{suffix}"
        return f"{value}{suffix}"

    def update_from(self, data: dict, source: str) -> None:
        """Merge a raw ``ai`` dict (map-packet extra or simulation)."""
        for key in ("on_device", "model", "fps", "latency_ms", "cpu_pct",
                    "gpu_pct", "ram_used_gb", "ram_total_gb",
                    "cloud_dependency"):
            if key in data and data[key] is not None:
                setattr(self, key, data[key])
        if "cloud_dependency" in data and data["cloud_dependency"] is None:
            self.cloud_dependency = None
        self.source = source
        self.last_rx = time.monotonic()
