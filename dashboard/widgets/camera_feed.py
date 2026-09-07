import time
import numpy as np
import cv2
from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt, Signal as pyqtSignal
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QFont


class CameraFeed(QLabel):
    double_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #1a1a1a; color: #888;")
        self.setText("No Video Feed")
        self._frame = None
        self._detections = []
        self._show_grid = False
        self._fps = 0.0
        self._frame_count = 0
        self._last_fps_time = time.time()

    def update_frame(self, frame: np.ndarray):
        self._frame = frame
        self._frame_count += 1
        now = time.time()
        elapsed = now - self._last_fps_time
        if elapsed >= 1.0:
            self._fps = self._frame_count / elapsed
            self._frame_count = 0
            self._last_fps_time = now
        self._render()

    def set_detections(self, detections: list[dict]):
        self._detections = detections

    def toggle_grid(self, show: bool):
        self._show_grid = show
        if self._frame is not None:
            self._render()

    def _render(self):
        if self._frame is None:
            return

        frame = self._frame.copy()
        h, w = frame.shape[:2]

        for det in self._detections:
            x1, y1, x2, y2 = det.get("bbox", [0, 0, 0, 0])
            label = det.get("label", "")
            color = det.get("color", (0, 0, 255))
            conf = det.get("confidence", 0.0)

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

        fps_text = f"FPS: {self._fps:.0f}"
        cv2.putText(
            frame,
            fps_text,
            (w - 90, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )

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

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()
