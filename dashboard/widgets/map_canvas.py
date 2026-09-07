import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QBrush,
    QFont,
    QPolygonF,
    QWheelEvent,
    QMouseEvent,
)

CELL_COLORS = {
    0: QColor(245, 245, 245),
    1: QColor(60, 60, 60),
    2: QColor(173, 216, 230),
    3: QColor(144, 238, 144),
    4: QColor(255, 140, 0),
}

CELL_LABELS = {
    0: "",
    1: "Wall",
    2: "Corridor",
    3: "Room",
    4: "Hazard",
}


class MapCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self._grid = None
        self._survivors = []
        self._drone_pos = (0, 0)
        self._hazards = []
        self._zoom = 1.0
        self._offset = QPointF(0, 0)
        self._dragging = False
        self._drag_start = QPointF()
        self._cell_size = 20
        self._show_grid = True
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def update_map(
        self,
        grid: np.ndarray,
        survivors: list,
        drone_pos: tuple[int, int],
        hazards: list,
        mission: dict,
    ):
        self._grid = grid
        self._survivors = survivors
        self._drone_pos = drone_pos
        self._hazards = hazards
        self.update()

    def toggle_grid_lines(self, show: bool):
        self._show_grid = show
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), QColor(30, 30, 30))

        if self._grid is None:
            painter.setPen(QColor(150, 150, 150))
            painter.setFont(QFont("monospace", 12))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "Waiting for map data..."
            )
            painter.end()
            return

        painter.save()
        painter.translate(self._offset)
        painter.scale(self._zoom, self._zoom)

        rows, cols = self._grid.shape
        cs = self._cell_size

        for r in range(rows):
            for c in range(cols):
                cell_val = int(self._grid[r, c])
                color = CELL_COLORS.get(cell_val, QColor(200, 200, 200))
                x = c * cs
                y = r * cs
                painter.fillRect(x, y, cs, cs, color)
                if self._show_grid:
                    painter.setPen(QPen(QColor(180, 180, 180), 0.5))
                    painter.drawRect(x, y, cs, cs)

        for s in self._survivors:
            sx = s.grid_x * cs + cs // 2
            sy = s.grid_y * cs + cs // 2
            painter.setPen(QPen(QColor(255, 0, 0), 2))
            painter.setBrush(QBrush(QColor(255, 50, 50, 180)))
            painter.drawEllipse(QPointF(sx, sy), cs * 0.4, cs * 0.4)
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.setFont(QFont("sans-serif", 7, QFont.Weight.Bold))
            painter.drawText(
                int(sx - 5),
                int(sy + 3),
                s.id,
            )

        dx = self._drone_pos[0] * cs + cs // 2
        dy = self._drone_pos[1] * cs + cs // 2
        arrow_size = cs * 0.6
        painter.setPen(QPen(QColor(0, 200, 0), 2))
        painter.setBrush(QBrush(QColor(0, 220, 0, 200)))
        arrow = QPolygonF(
            [
                QPointF(dx, dy - arrow_size),
                QPointF(dx - arrow_size * 0.5, dy + arrow_size * 0.5),
                QPointF(dx + arrow_size * 0.5, dy + arrow_size * 0.5),
            ]
        )
        painter.drawPolygon(arrow)
        painter.setPen(QPen(QColor(0, 255, 0)))
        painter.setFont(QFont("sans-serif", 7, QFont.Weight.Bold))
        painter.drawText(int(dx + arrow_size), int(dy + 3), "Drone")

        for h in self._hazards:
            hx = h.grid_x * cs + cs // 2
            hy = h.grid_y * cs + cs // 2
            severity_color = QColor(255, 100, 0, 150)
            if h.severity >= 3:
                severity_color = QColor(255, 0, 0, 180)
            painter.setPen(QPen(severity_color, 2))
            painter.setBrush(QBrush(severity_color))
            painter.drawRect(
                int(hx - cs * 0.4),
                int(hy - cs * 0.4),
                int(cs * 0.8),
                int(cs * 0.8),
            )

        painter.restore()

        self._draw_axes(painter)
        painter.end()

    def _draw_axes(self, painter: QPainter):
        if self._grid is None:
            return
        rows, cols = self._grid.shape
        cs = self._cell_size * self._zoom

        painter.setPen(QPen(QColor(180, 180, 180)))
        painter.setFont(QFont("monospace", 7))

        for c in range(0, cols, max(1, cols // 10)):
            x = self._offset.x() + c * cs
            painter.drawText(
                int(x), int(self._offset.y() - 4), str(c)
            )

        for r in range(0, rows, max(1, rows // 10)):
            y = self._offset.y() + r * cs
            painter.drawText(int(self._offset.x() - 20), int(y + 4), str(r))

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        if delta > 0:
            self._zoom *= 1.15
        else:
            self._zoom /= 1.15
        self._zoom = max(0.2, min(5.0, self._zoom))
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.position()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            delta = event.position() - self._drag_start
            self._offset += QPointF(delta.x(), delta.y())
            self._drag_start = event.position()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
