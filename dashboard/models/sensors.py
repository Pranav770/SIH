"""Sensor health model (Step 13)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Health(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    UNKNOWN = "unknown"

    @property
    def glyph(self) -> str:
        return {"healthy": "\u2713", "degraded": "\u26a0",
                "offline": "\u2715", "unknown": "\u00b7"}[self.value]


@dataclass
class SensorStatus:
    key: str
    name: str
    health: Health = Health.UNKNOWN
    detail: str = "not reported"
    last_rx: float | None = field(default=None, repr=False)

    @property
    def age_s(self) -> float | None:
        if self.last_rx is None:
            return None
        return time.monotonic() - self.last_rx

    @property
    def age_text(self) -> str:
        age = self.age_s
        if age is None:
            return "--"
        if age < 10:
            return f"{age:.1f}s"
        return f"{age:.0f}s"


SENSOR_KEYS = [
    ("rgb", "RGB CAMERA"),
    ("thermal", "THERMAL CAMERA"),
    ("imu", "IMU"),
    ("gps", "GPS"),
    ("lidar", "LIDAR"),
    ("flow", "OPTICAL FLOW"),
    ("baro", "BAROMETER"),
    ("telemetry", "TELEMETRY"),
]
