"""Local YOLO inference thread (on-device AI on the GCS host).

Wraps the canonical :class:`sih_model.inference.SIHInferenceEngine` (authored
by the model team) and feeds detections into the dashboard pipeline.

Frame policy: a single-slot queue — if inference cannot keep up, the oldest
frame is dropped rather than queued, so latency never grows unbounded and the
UI never blocks.
"""

from __future__ import annotations

import os
import queue
import sys
import time

from PySide6.QtCore import QThread, Signal

# make the repo root importable so we can use sih_model.*
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from sih_model.inference import SIHInferenceEngine  # noqa: E402
from sih_model.model_profile import DASHBOARD_CLASS_MAP  # noqa: E402


class InferenceThread(QThread):
    detections_signal = Signal(list)    # list[dict] -> store.ingest_edge_detections
    status_signal = Signal(dict)        # engine stats for the AI / MODEL tabs

    def __init__(self, model_path: str, conf: float = 0.25, iou: float = 0.45,
                 target_fps: float = 8.0, parent=None):
        super().__init__(parent)
        self.model_path = model_path
        self.target_fps = max(1.0, float(target_fps))
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._running = True

        self.engine: SIHInferenceEngine | None = None
        self.available = False
        self.reason = ""
        self.backend = "none"
        try:
            self.engine = SIHInferenceEngine(model_path, conf_thresh=conf,
                                             iou_thresh=iou)
            self.available = True
            self.backend = self.engine.backend or "unknown"
        except Exception as exc:                             # noqa: BLE001
            self.reason = str(exc)

        self._latency_ms = 0.0
        self._fps = 0.0
        self._frames = 0
        self._det_total = 0

    # ------------------------------------------------------------------
    def submit_frame(self, frame) -> None:
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            pass

    def stop(self) -> None:
        self._running = False
        self.wait(4000)

    # ------------------------------------------------------------------
    def run(self) -> None:
        self._emit_status()
        last = time.perf_counter()
        while self._running:
            try:
                frame = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if not self.available:
                continue

            t0 = time.perf_counter()
            raw = self.engine.predict(frame)
            self._latency_ms = (time.perf_counter() - t0) * 1000.0
            self._frames += 1
            self._det_total += len(raw)

            payload = []
            for d in raw:
                x1, y1, x2, y2 = (int(v) for v in d.get("bbox", [0, 0, 0, 0]))
                cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                cid = int(d.get("class_id", -1))
                name = str(d.get("class_name", "unknown"))
                # stable-ish id so a stationary object keeps one record
                sid = f"Y{cid}-{int(cx // 64)}-{int(cy // 64)}"
                payload.append({
                    "id": sid,
                    "class": DASHBOARD_CLASS_MAP.get(name, name.upper()),
                    "confidence": round(float(d.get("confidence", 0.0)), 4),
                    "bbox": [x1, y1, x2, y2],
                    "source": "edge",
                })
            if payload:
                self.detections_signal.emit(payload)

            now = time.perf_counter()
            if now - last >= 0.5:
                self._fps = self._frames / max(0.5, now - last)
                self._frames = 0
                last = now
                self._emit_status()

            spent = time.perf_counter() - t0
            budget = 1.0 / self.target_fps
            if spent < budget:
                time.sleep(budget - spent)

    def _emit_status(self) -> None:
        self.status_signal.emit({
            "available": self.available,
            "backend": self.backend,
            "reason": self.reason,
            "model": os.path.basename(self.model_path),
            "fps": self._fps,
            "latency_ms": self._latency_ms,
            "detections": self._det_total,
        })
