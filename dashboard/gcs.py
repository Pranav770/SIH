import sys
import numpy as np
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QSplitter,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut

from threads.telemetry import TelemetryThread
from threads.ffmpeg_receiver import FFmpegReceiverThread
from threads.video_receiver import VideoReceiverThread
from threads.map_receiver import MapReceiverThread
from widgets.camera_feed import CameraFeed
from widgets.map_canvas import MapCanvas
from widgets.status_bar import StatusBar
from widgets.survivor_list import SurvivorList
from widgets.hazard_panel import HazardPanel
from widgets.controls import Controls
from widgets.telemetry_popup import TelemetryPopup
from models.mission import MissionState
from models.survivor import Survivor


class MissionPlannerGCS(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NIDAR Autonomous AirMouse GCS")
        self.setGeometry(50, 50, 1400, 850)
        self.setMinimumSize(1100, 700)

        self.mission = MissionState()
        self._all_survivors: list[Survivor] = []

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.status_bar = StatusBar()
        root_layout.addWidget(self.status_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(4, 4, 4, 0)
        body_layout.setSpacing(4)

        left_panel = QWidget()
        self.left_layout = left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self.camera_feed = CameraFeed()
        left_layout.addWidget(self.camera_feed, stretch=3)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(4)
        self.survivor_list = SurvivorList()
        self.hazard_panel = HazardPanel()
        bottom_row.addWidget(self.survivor_list, stretch=2)
        bottom_row.addWidget(self.hazard_panel, stretch=1)
        left_layout.addLayout(bottom_row, stretch=1)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        self.map_canvas = MapCanvas()
        right_layout.addWidget(self.map_canvas, stretch=3)

        right_bottom = QHBoxLayout()
        right_bottom.setSpacing(4)
        right_layout.addLayout(right_bottom, stretch=1)

        body_layout.addWidget(left_panel, stretch=3)
        body_layout.addWidget(right_panel, stretch=2)

        root_layout.addWidget(body, stretch=1)

        self.controls = Controls()
        root_layout.addWidget(self.controls)

        self._root_layout = root_layout
        self._body = body
        self._is_fullscreen = False
        self._popup: TelemetryPopup | None = None

        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc.activated.connect(self._exit_fullscreen)

        self._setup_threads()
        self._connect_signals()

    def _setup_threads(self):
        self.telemetry_thread = TelemetryThread()
        self.video_thread = FFmpegReceiverThread()
        self.map_thread = MapReceiverThread()

        self.telemetry_thread.start()
        self.video_thread.start()
        self.map_thread.start()

    def _connect_signals(self):
        self.telemetry_thread.telemetry_signal.connect(
            self.status_bar.update_telemetry
        )
        self.telemetry_thread.telemetry_signal.connect(
            self._on_telemetry_update
        )
        self.telemetry_thread.connection_status.connect(
            self.controls.set_connection_status
        )

        self.video_thread.frame_signal.connect(self.camera_feed.update_frame)

        self.map_thread.map_signal.connect(self._on_map_update)

        self.controls.abort_signal.connect(self._on_abort)
        self.controls.pause_signal.connect(self._on_pause)
        self.controls.return_home_signal.connect(self._on_return_home)
        self.camera_feed.double_clicked.connect(self._toggle_fullscreen)
        self.status_bar.telemetry_detail_clicked.connect(self._toggle_telemetry_popup)

    def _on_map_update(
        self,
        grid: np.ndarray,
        survivors: list,
        drone_pos: tuple,
        hazards: list,
        mission: dict,
    ):
        self.mission.update(
            mission.get("phase", "idle"),
            mission.get("progress", 0),
            mission.get("total_cells", 0),
            mission.get("scanned_cells", 0),
        )
        self.status_bar.update_mission(
            self.mission.phase_text, self.mission.progress
        )

        self._all_survivors = survivors
        self.map_canvas.update_map(grid, survivors, drone_pos, hazards, mission)
        self.survivor_list.update_survivors(survivors)
        self.hazard_panel.update_hazards(hazards)

        detections = []
        for s in survivors:
            detections.append(
                {
                    "label": s.id,
                    "confidence": s.confidence,
                    "color": (0, 0, 255),
                    "bbox": [0, 0, 0, 0],
                }
            )
        self.camera_feed.set_detections(detections)

    def _on_abort(self):
        print("EMERGENCY ABORT TRIGGERED")
        self.status_bar.update_mission("Aborted", self.mission.progress)

    def _on_pause(self):
        print("MISSION PAUSED")

    def _on_return_home(self):
        print("RETURN HOME TRIGGERED")

    def _toggle_fullscreen(self):
        if self._is_fullscreen:
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self):
        self._is_fullscreen = True
        self.status_bar.hide()
        self._body.hide()
        self.controls.hide()
        self.camera_feed.setParent(self)
        self._root_layout.addWidget(self.camera_feed)
        self.camera_feed.show()

    def _exit_fullscreen(self):
        self._is_fullscreen = False
        self._root_layout.removeWidget(self.camera_feed)
        self.camera_feed.setParent(self._body)
        self.left_layout.insertWidget(0, self.camera_feed, stretch=3)
        self.camera_feed.show()
        self.status_bar.show()
        self._body.show()
        self.controls.show()

    def _toggle_telemetry_popup(self, badge_name: str):
        if self._popup is not None and self._popup.isVisible():
            self._popup.close()
            self._popup = None
            return

        self._popup = TelemetryPopup()
        self._popup.closed.connect(self._on_popup_closed)
        self._popup.update_telemetry(self.status_bar._telemetry_data)

        badge = {
            "mode": self.status_bar.mode_badge,
            "armed": self.status_bar.armed_badge,
            "battery": self.status_bar.battery_bar,
            "gps": self.status_bar.gps_badge,
            "heading": self.status_bar.heading_badge,
            "altitude": self.status_bar.alt_badge,
            "speed": self.status_bar.speed_badge,
        }.get(badge_name, self.status_bar.mode_badge)

        pos = badge.mapToGlobal(badge.rect().bottomLeft())
        self._popup.move(pos.x(), pos.y() + 4)
        self._popup.show()

    def _on_telemetry_update(self, data: dict):
        if self._popup is not None and self._popup.isVisible():
            self._popup.update_telemetry(data)

    def _on_popup_closed(self):
        self._popup = None

    def closeEvent(self, event):
        self.telemetry_thread.stop()
        self.video_thread.stop()
        self.map_thread.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    gcs = MissionPlannerGCS()
    gcs.show()
    sys.exit(app.exec())
