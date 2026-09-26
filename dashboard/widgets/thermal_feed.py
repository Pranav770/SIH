"""Thermal (FLIR) feed — the second half of the RGB+thermal sensor pair.

Shows the thermal stream with an honest provenance watermark (LIVE /
SIMULATION) and a clear NO SIGNAL overlay when frames stop arriving, so a
judge can always tell which sensor data they are looking at.
"""

from __future__ import annotations

import time

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel

HUD_WHITE = (235, 245, 255)   # BGR
HUD_AMBER = (61, 182, 255)    # BGR amber
HUD_NAVY = (16, 28, 48)       # BGR chip fill


class ThermalFeed(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 200)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #0a1120; color: #5c7ba0;")
        self.setText("THERMAL — AWAITING SENSOR")
        self._frame: np.ndarray | None = None
        self._last_frame_t: float | None = None
        self._source_label = "UNKNOWN"
        self._status: str | None = None

    # -- inputs (called from gcs wiring) ---------------------------------
    def update_frame(self, frame: np.ndarray) -> None:
        self._frame = frame
        self._last_frame_t = time.time()
        self._status = None
        self._render()

    def set_source_label(self, text: str) -> None:
        text = (text or "UNKNOWN").upper()
        if text != self._source_label:
            self._source_label = text
            self._render()

    def set_status(self, status: str | None) -> None:
        """Show an overlay (e.g. NO SIGNAL). None clears it."""
        status = status or None
        if status != self._status:
            self._status = status
            self._render()

    def age_s(self) -> float | None:
        if self._last_frame_t is None:
            return None
        return time.time() - self._last_frame_t

    # -- rendering --------------------------------------------------------
    def _render(self) -> None:
        if self._frame is None:
            self.setPixmap(QPixmap())
            self.setText(self._status or "THERMAL — AWAITING SENSOR")
            return

        frame = self._frame.copy()
        h, w = frame.shape[:2]

        # provenance watermark chip (top centre)
        chip = f"THERMAL · {self._source_label}"
        color = HUD_AMBER if self._source_label in ("SIMULATION", "SIM") \
            else HUD_WHITE
        (tw, th), _ = cv2.getTextSize(chip, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        x0 = (w - tw) // 2 - 8
        cv2.rectangle(frame, (x0, 6), (x0 + tw + 16, 6 + th + 10),
                      HUD_NAVY, -1)
        cv2.rectangle(frame, (x0, 6), (x0 + tw + 16, 6 + th + 10),
                      color, 1)
        cv2.putText(frame, chip, (x0 + 8, 6 + th + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

        # status overlay (dim the frame and print the reason)
        if self._status:
            dim = np.full_like(frame, 8)
            frame = cv2.addWeighted(frame, 0.35, dim, 0.65, 0)
            lines = self._status.split("\n")
            y = h // 2 - (len(lines) - 1) * 14
            for line in lines:
                (tw2, th2), _ = cv2.getTextSize(
                    line, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                cv2.putText(frame, line, ((w - tw2) // 2, y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 180, 255),
                            2, cv2.LINE_AA)
                y += th2 + 18

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        qimg = QImage(rgb.data, w, h, rgb.strides[0],
                      QImage.Format.Format_RGB888).copy()
        self.setText("")
        self.setPixmap(QPixmap.fromImage(qimg).scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()

    def mouseDoubleClickEvent(self, event):
        # keep parity with CameraFeed: double click toggles nothing here
        super().mouseDoubleClickEvent(event)
