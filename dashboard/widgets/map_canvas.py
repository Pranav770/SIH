"""Tactical map canvas: grid, drone, survivors, hazards plus mission
context (flight track, KML area polygon, coverage caption).

Marker colours carry meaning — survivor fill shows rescue priority
(P1..P4), hazard fill shows effective severity (backend severity wins
over the risk model) — and clicking a marker reports its id so linked
panels (fusion bar / lists) can show the detail.
"""

import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPointF, Signal as pyqtSignal
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

from theme import HAZARD_COLORS

CELL_COLORS = {
    0: QColor(18, 30, 52),   # empty / unscanned (night navy)
    1: QColor(82, 96, 120),  # wall (concrete)
    2: QColor(22, 58, 92),   # corridor (steel blue)
    3: QColor(18, 62, 55),   # room (teal)
    4: QColor(122, 34, 20),  # hazard (dark red)
}

CELL_LABELS = {
    0: "",
    1: "Wall",
    2: "Corridor",
    3: "Room",
    4: "Hazard",
}

PRIORITY_FILL = {
    "P1": QColor(255, 90, 90),
    "P2": QColor(255, 138, 61),
    "P3": QColor(77, 210, 255),
    "P4": QColor(255, 88, 192),
}

SEVERITY_FILL = [                     # by Severity.rank 0..3
    QColor(46, 230, 168),             # LOW
    QColor(255, 182, 61),             # MEDIUM
    QColor(255, 138, 61),             # HIGH
    QColor(255, 90, 90),              # CRITICAL
]

_TYPE_SHORT = {
    "fire": "FIRE", "flood": "FLOOD", "debris": "DEBR",
    "electrical": "ELEC", "structural": "STRU", "landslide": "LAND",
    "chemical": "CHEM", "smoke": "SMOK",
}

# theme HAZARD_COLORS keys are the short codes
_TYPE_COLOR_KEY = {
    "fire": "FIRE", "flood": "FLOOD", "debris": "DEBRIS",
    "electrical": "ELEC", "structural": "STRUCT", "landslide": "LANDSL",
    "chemical": "CHEM", "smoke": "SMOKE",
}


class MapCanvas(QWidget):
    # (kind: "survivor"|"hazard", id)
    detection_clicked = pyqtSignal(str, str)

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
        self._press_pos = QPointF()
        self._cell_size = 20
        self._show_grid = True
        # mission context (set via update_extras)
        self._track: list[tuple[int, int]] = []
        self._polygon: list[tuple[int, int]] | None = None
        self._coverage_text = ""
        self._area_name = ""
        # marker hit-testing: (kind, id, local center, tooltip)
        self._hits: list[tuple[str, str, QPointF, str]] = []
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

    def update_extras(self, track=None, polygon=None, coverage_text: str = "",
                      area_name: str | None = None) -> None:
        """Flight track (grid coords), KML area polygon (grid coords) and
        the coverage caption drawn over the map."""
        if track is not None:
            self._track = list(track)
        if polygon is not None:
            self._polygon = list(polygon) if polygon else None
        self._coverage_text = coverage_text or ""
        if area_name is not None:
            self._area_name = area_name
        self.update()

    def toggle_grid_lines(self, show: bool):
        self._show_grid = show
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), QColor(9, 17, 32))

        if self._grid is None:
            painter.setPen(QColor(143, 179, 217))
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
                color = CELL_COLORS.get(cell_val, QColor(122, 148, 180))
                x = c * cs
                y = r * cs
                painter.fillRect(x, y, cs, cs, color)
                if self._show_grid:
                    painter.setPen(QPen(QColor(29, 58, 95), 0.5))
                    painter.drawRect(x, y, cs, cs)

        # KML / area polygon outline (grid frame requires a geo origin)
        if self._polygon and len(self._polygon) >= 3:
            pts = [QPointF(gx * cs + cs // 2, gy * cs + cs // 2)
                   for gx, gy in self._polygon]
            painter.setPen(QPen(QColor(46, 230, 168, 220), 2,
                                Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(QPolygonF(pts))

        # flight track (recent drone positions)
        if len(self._track) >= 2:
            painter.setPen(QPen(QColor(77, 210, 255, 130), 1.5))
            painter.drawPolyline(QPolygonF(
                [QPointF(gx * cs + cs // 2, gy * cs + cs // 2)
                 for gx, gy in self._track]))

        self._hits = []

        for s in self._survivors:
            sx = s.grid_x * cs + cs // 2
            sy = s.grid_y * cs + cs // 2
            fill = PRIORITY_FILL.get(getattr(s, "priority", None),
                                     QColor(255, 88, 192))
            painter.setPen(QPen(fill.lighter(130), 2))
            painter.setBrush(QBrush(QColor(fill.red(), fill.green(),
                                           fill.blue(), 170)))
            painter.drawEllipse(QPointF(sx, sy), cs * 0.4, cs * 0.4)
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.setFont(QFont("monospace", 7, QFont.Weight.Bold))
            painter.drawText(int(sx - 5), int(sy + 3), s.id)
            tip = self._survivor_tip(s)
            self._hits.append(("survivor", s.id, QPointF(sx, sy), tip))

        dx = self._drone_pos[0] * cs + cs // 2
        dy = self._drone_pos[1] * cs + cs // 2
        arrow_size = cs * 0.6
        painter.setPen(QPen(QColor(77, 210, 255), 2))
        painter.setBrush(QBrush(QColor(77, 210, 255, 190)))
        arrow = QPolygonF(
            [
                QPointF(dx, dy - arrow_size),
                QPointF(dx - arrow_size * 0.5, dy + arrow_size * 0.5),
                QPointF(dx + arrow_size * 0.5, dy + arrow_size * 0.5),
            ]
        )
        painter.drawPolygon(arrow)
        painter.setPen(QPen(QColor(77, 210, 255)))
        painter.setFont(QFont("monospace", 7, QFont.Weight.Bold))
        painter.drawText(int(dx + arrow_size), int(dy + 3), "Drone")

        for h in self._hazards:
            hx = h.grid_x * cs + cs // 2
            hy = h.grid_y * cs + cs // 2
            sev = h.effective_severity
            fill = SEVERITY_FILL[sev.rank]
            type_color = QColor(HAZARD_COLORS.get(
                _TYPE_COLOR_KEY.get(h.type.value, ""), "#9fb6cd"))
            painter.setPen(QPen(type_color, 2))
            painter.setBrush(QBrush(QColor(fill.red(), fill.green(),
                                           fill.blue(), 165)))
            painter.drawRect(
                int(hx - cs * 0.4),
                int(hy - cs * 0.4),
                int(cs * 0.8),
                int(cs * 0.8),
            )
            short = _TYPE_SHORT.get(h.type.value, h.type.value[:4].upper())
            painter.setPen(QPen(type_color))
            painter.setFont(QFont("monospace", 6, QFont.Weight.Bold))
            painter.drawText(int(hx - cs * 0.45), int(hy + cs * 0.75),
                             short)
            self._hits.append(("hazard", h.id,
                               QPointF(hx, hy), self._hazard_tip(h)))

        painter.restore()

        self._draw_axes(painter)
        self._draw_caption(painter)
        painter.end()

    # ------------------------------------------------------------------
    @staticmethod
    def _survivor_tip(s) -> str:
        prio = getattr(s, "priority", None) or "P4"
        geo = (f"{s.lat:.6f}, {s.lon:.6f}"
               if getattr(s, "lat", None) is not None
               else f"grid {s.grid_x},{s.grid_y}")
        return (f"{s.id} · survivor · conf {s.confidence:.0%} · "
                f"{prio}\n{geo}")

    @staticmethod
    def _hazard_tip(h) -> str:
        sev = h.effective_severity
        return (f"{h.id} · {h.type.value} · {sev.label} · "
                f"status {h.status}\ngrid {h.grid_x},{h.grid_y}")

    def _draw_caption(self, painter: QPainter):
        """Area / coverage caption in screen space (bottom-left, so it never
        collides with drone/survivor markers near the origin)."""
        parts = []
        if self._area_name:
            parts.append(f"AREA {self._area_name}")
        if self._coverage_text:
            parts.append(f"COVERAGE {self._coverage_text}")
        if not parts:
            return
        painter.setPen(QPen(QColor(143, 179, 217)))
        painter.setFont(QFont("monospace", 8, QFont.Weight.Bold))
        painter.drawText(8, self.height() - 8, "  ·  ".join(parts))

    def _draw_axes(self, painter: QPainter):
        if self._grid is None:
            return
        rows, cols = self._grid.shape
        cs = self._cell_size * self._zoom

        painter.setPen(QPen(QColor(143, 179, 217)))
        painter.setFont(QFont("monospace", 7))

        for c in range(0, cols, max(1, cols // 10)):
            x = self._offset.x() + c * cs
            painter.drawText(
                int(x), int(self._offset.y() - 4), str(c)
            )

        for r in range(0, rows, max(1, rows // 10)):
            y = self._offset.y() + r * cs
            painter.drawText(int(self._offset.x() - 20), int(y + 4), str(r))

    # ------------------------------------------------------------------
    def _to_screen(self, local: QPointF) -> QPointF:
        return QPointF(local.x() * self._zoom + self._offset.x(),
                       local.y() * self._zoom + self._offset.y())

    def _hit_test(self, pos) -> tuple[str, str, str] | None:
        radius = self._cell_size * 0.55 * self._zoom + 4
        best = None
        best_d = None
        for kind, ident, local, tip in self._hits:
            scr = self._to_screen(local)
            d = ((scr.x() - pos.x()) ** 2 + (scr.y() - pos.y()) ** 2) ** 0.5
            if d <= radius and (best_d is None or d < best_d):
                best, best_d = (kind, ident, tip), d
        return best

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
            self._press_pos = event.position()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            delta = event.position() - self._drag_start
            self._offset += QPointF(delta.x(), delta.y())
            self._drag_start = event.position()
            self.update()
        else:
            hit = self._hit_test(event.position())
            self.setToolTip(hit[2] if hit else "")

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            # a click (not a drag) on a marker reports its id
            dx = event.position().x() - self._press_pos.x()
            dy = event.position().y() - self._press_pos.y()
            if abs(dx) + abs(dy) < 6:
                hit = self._hit_test(event.position())
                if hit:
                    self.detection_clicked.emit(hit[0], hit[1])
