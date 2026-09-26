"""Emergency alert records (Step 9).

Alerts reference detections but never mutate or delete them — acknowledging
or clearing an alert only changes the alert's own state.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class AlertPriority(Enum):
    P1 = 1
    P2 = 2
    P3 = 3
    P4 = 4

    @property
    def label(self) -> str:
        return f"P{self.value}"

    @classmethod
    def from_priority_text(cls, text: str | None) -> "AlertPriority":
        if text:
            t = str(text).strip().upper()
            for p in cls:
                if t == p.label or t == str(p.value):
                    return p
        return cls.P3


@dataclass
class Alert:
    title: str
    priority: AlertPriority
    category: str                    # survivor / hazard / gps / comm / battery ...
    detail: str = ""
    lat: float | None = None
    lon: float | None = None
    location_text: str = ""
    confidence: float | None = None
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    acknowledged: bool = False
    cleared: bool = False
    source: str = "live"
    entity_id: str = ""
    dedupe_key: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    @property
    def age_text(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.created))

    @property
    def location(self) -> str:
        if self.location_text:
            return self.location_text
        if self.lat is not None and self.lon is not None:
            return f"{self.lat:.6f}, {self.lon:.6f}"
        return "UNKNOWN"
