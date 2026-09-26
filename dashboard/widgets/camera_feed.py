import time
import numpy as np
import cv2
from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt, Signal as pyqtSignal
from PySide6.QtGui import QImage, QPixmap

HUD_CYAN = (255, 210, 77)   # BGR cyan
HUD_MAGENTA = (255, 88, 192)  # BGR magenta (targets)
HUD_NAVY = (16, 28, 48)     # BGR chip fill


class CameraFeed(QLabel):
    double_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #0a1120; color: #5c7ba0;")
        self.setText("NO VIDEO FEED")
        self._frame = None
        self._detections = []
        self._telemetry: dict = {}
        self._show_grid = False
        self._fps = 0.0
        self._frame_count = 0
        self._last_fps_time = time.time()
        self._last_frame_t: float | None = None
        self._source_label = "UNKNOWN"
        self._status: str | None = None

    def update_frame(self, frame: np.ndarray):
        self._frame = frame
        self._last_frame_t = time.time()
        self._frame_count += 1
        now = time.time()
        elapsed = now - self._last_fps_time
        if elapsed >= 1.0:
            self._fps = self._frame_count / elapsed
            self._frame_count = 0
            self._last_fps_time = now
        self._render()

    def set_source_label(self, text: str) -> None:
        """Provenance watermark: LIVE / SIMULATION / UNKNOWN."""
        text = (text or "UNKNOWN").upper()
        if text != self._source_label:
            self._source_label = text
            self._render()

    def set_status(self, status: str | None) -> None:
        """Overlay a stream status (e.g. NO SIGNAL); None clears it."""
        status = status or None
        if status != self._status:
            self._status = status
            self._render()

    def age_s(self) -> float | None:
        if self._last_frame_t is None:
            return None
        return time.time() - self._last_frame_t

    def set_detections(self, detections: list[dict]):
        self._detections = detections

    def update_telemetry(self, data: dict):
        self._telemetry.update(data)

    def toggle_grid(self, show: bool):
        self._show_grid = show
        if self._frame is not None:
            self._render()

    def _render(self):
        if self._frame is None:
            self.setPixmap(QPixmap())
            self.setText(self._status or "NO VIDEO FEED")
            return

        frame = self._frame.copy()
        h, w = frame.shape[:2]

        for det in self._detections:
            x1, y1, x2, y2 = det.get("bbox", [0, 0, 0, 0])
            label = det.get("label", "")
            color = det.get("color", HUD_MAGENTA)
            conf = det.get("confidence", 0.0)

            if x2 > x1 and y2 > y1:
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                text = f"{label} {conf:.0%}"
                (tw, th), _ = cv2.getTextSize(
                    text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                )
                cv2.rectangle(
                    frame, (x1, y1 - th - 8), (x1 + tw + 4, y1), color, -1
                )
                cv2.putText(
                    frame,
                    text,
                    (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1,
                )

        if self._show_grid:
            step_x = w // 8
            step_y = h // 6
            overlay = frame.copy()
            for x in range(0, w, step_x):
                cv2.line(overlay, (x, 0), (x, h), (255, 255, 255), 1)
            for y in range(0, h, step_y):
                cv2.line(overlay, (0, y), (w, y), (255, 255, 255), 1)
            cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)

            for i in range(8):
                for j in range(6):
                    cx = i * step_x + 4
                    cy = j * step_y + 14
                    label = f"{chr(65 + j)}-{i}"
                    cv2.putText(
                        frame,
                        label,
                        (cx, cy),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.35,
                        (200, 200, 200),
                        1,
                    )

        self._draw_hud(frame, w, h)

        # provenance watermark chip (top centre)
        chip = f"VIDEO · {self._source_label}"
        if self._source_label in ("SIMULATION", "SIM"):
            chip_color = (61, 182, 255)      # BGR amber
        elif self._source_label == "LIVE":
            chip_color = HUD_CYAN
        else:
            chip_color = (180, 180, 180)     # grey: unknown provenance
        (tw, th), _ = cv2.getTextSize(chip, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        x0 = (w - tw) // 2 - 8
        cv2.rectangle(frame, (x0, 6), (x0 + tw + 16, 6 + th + 10),
                      HUD_NAVY, -1)
        cv2.rectangle(frame, (x0, 6), (x0 + tw + 16, 6 + th + 10),
                      chip_color, 1)
        cv2.putText(frame, chip, (x0 + 8, 6 + th + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, chip_color, 1,
                    cv2.LINE_AA)

        # stream-status overlay (dim + reason) — a frozen last frame never
        # pretends to be live
        if self._status:
            dim = np.full_like(frame, 8)
            frame = cv2.addWeighted(frame, 0.35, dim, 0.65, 0)
            lines = self._status.split("\n")
            y = h // 2 - (len(lines) - 1) * 14
            for line in lines:
                (lw, lh), _ = cv2.getTextSize(
                    line, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                cv2.putText(frame, line, ((w - lw) // 2, y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 180, 255),
                            2, cv2.LINE_AA)
                y += lh + 18

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        q_img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)
        scaled = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)

    def _draw_chip(self, frame, x, y, text, align_right=False, width=None):
        """Small dark HUD data-chip with a cyan border and label."""
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        pad_x, pad_y = 8, 5
        cw, chh = tw + 2 * pad_x, th + 2 * pad_y
        if align_right:
            x = width - x - cw
        cv2.rectangle(frame, (x, y), (x + cw, y + chh), HUD_NAVY, -1)
        cv2.rectangle(frame, (x, y), (x + cw, y + chh), HUD_CYAN, 1)
        cv2.putText(
            frame,
            text,
            (x + pad_x, y + chh - pad_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            HUD_CYAN,
            1,
            cv2.LINE_AA,
        )

    def _draw_hud(self, frame, w, h):
        m, L = 20, 32

        cv2.line(frame, (m, m), (m + L, m), HUD_CYAN, 2)
        cv2.line(frame, (m, m), (m, m + L), HUD_CYAN, 2)
        cv2.line(frame, (w - m, m), (w - m - L, m), HUD_CYAN, 2)
        cv2.line(frame, (w - m, m), (w - m, m + L), HUD_CYAN, 2)
        cv2.line(frame, (m, h - m), (m + L, h - m), HUD_CYAN, 2)
        cv2.line(frame, (m, h - m), (m, h - m - L), HUD_CYAN, 2)
        cv2.line(frame, (w - m, h - m), (w - m - L, h - m), HUD_CYAN, 2)
        cv2.line(frame, (w - m, h - m), (w - m, h - m - L), HUD_CYAN, 2)

        cx, cy = w // 2, h // 2
        cv2.circle(frame, (cx, cy), 30, HUD_CYAN, 1)
        cv2.line(frame, (cx - 46, cy), (cx - 14, cy), HUD_CYAN, 1)
        cv2.line(frame, (cx + 14, cy), (cx + 46, cy), HUD_CYAN, 1)
        cv2.line(frame, (cx, cy - 46), (cx, cy - 14), HUD_CYAN, 1)
        cv2.line(frame, (cx, cy + 14), (cx, cy + 46), HUD_CYAN, 1)
        cv2.circle(frame, (cx, cy), 2, HUD_CYAN, -1)

        t = self._telemetry
        alt = t.get("alt")
        spd = t.get("groundspeed")
        hdg = t.get("heading")
        bat = t.get("battery")

        x0, y0 = 56, 14
        alt_txt = f"ALT {alt:06.1f} M" if alt is not None else "ALT ----- M"
        spd_txt = f"SPD {spd:05.1f} M/S" if spd is not None else "SPD --- M/S"
        hdg_txt = f"HDG {hdg:03.0f}" if hdg is not None else "HDG ---"
        self._draw_chip(frame, x0, y0, alt_txt)
        self._draw_chip(frame, x0, y0 + 34, spd_txt)

        self._draw_chip(frame, 56, 14, hdg_txt, align_right=True, width=w)

        if bat is not None:
            self._draw_chip(frame, 56, h - 44, f"BAT {bat}%", align_right=True, width=w)

        self._draw_chip(frame, 56, h - 34, f"FPS {self._fps:.0f}")

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()