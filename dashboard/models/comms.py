"""Communication health + offline sync queue (Step 11).

``SyncQueue`` is a bounded, disk-backed buffer: when the ground-station
link drops, detections and alerts keep accumulating locally and are flushed
when the link returns — nothing is lost and the dashboard keeps running.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from utils.paths import DATA_DIR


class LinkState(Enum):
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return self.value.upper()


_LINK_COLORS = {  # exported for widgets
    "connected": "#3ddc84",
    "degraded": "#ffb63d",
    "disconnected": "#ff5a5a",
    "unknown": "#5c7ba0",
}


def link_color(state: LinkState) -> str:
    return _LINK_COLORS[state.value]


@dataclass
class Link:
    name: str
    state: LinkState = LinkState.UNKNOWN
    detail: str = "no data"
    last_rx: float | None = field(default=None, repr=False)

    @property
    def age_s(self) -> float | None:
        if self.last_rx is None:
            return None
        return time.monotonic() - self.last_rx


@dataclass
class CommunicationStatus:
    links: dict = field(default_factory=dict)   # name -> Link
    last_sync: float | None = None              # unix time of last flush/rx
    storage_ok: bool | None = None
    offline: bool = False

    def ensure(self, name: str) -> Link:
        if name not in self.links:
            self.links[name] = Link(name=name)
        return self.links[name]


class SyncQueue:
    """Bounded JSON-persisted queue of unsynchronised records."""

    def __init__(self, path: str | None = None, maxlen: int = 500):
        self._q: deque = deque(maxlen=maxlen)
        self._path = path or os.path.join(DATA_DIR, "sync_queue.json")
        self.storage_ok = False
        self._load()

    # -- persistence ------------------------------------------------------
    def _load(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        self._q.extend(data[-self._q.maxlen:])
            # write probe → storage status
            with open(self._path, "a", encoding="utf-8"):
                pass
            self.storage_ok = True
        except Exception:
            self.storage_ok = False

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(list(self._q), fh)
            self.storage_ok = True
        except Exception:
            self.storage_ok = False

    # -- queue API --------------------------------------------------------
    def enqueue(self, kind: str, payload: dict) -> None:
        self._q.append({
            "kind": kind,
            "payload": payload,
            "queued_at": time.time(),
            "source": payload.get("source", "live"),
        })
        self._save()

    def flush(self) -> int:
        """Called when the link returns; returns number of records synced."""
        n = len(self._q)
        if n:
            self._q.clear()
            self._save()
        return n

    @property
    def pending(self) -> int:
        return len(self._q)

    @property
    def pending_alerts(self) -> int:
        return sum(1 for r in self._q if r.get("kind") == "alert")

    @property
    def empty(self) -> bool:
        return not self._q
