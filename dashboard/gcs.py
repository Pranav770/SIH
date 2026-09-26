"""NIDAR GCS — main window.

Architecture
------------
All data flows into the single :class:`DashboardStore`, which enforces
mode authority (which source is believed per subsystem) and staleness:

    MAVLink thread ──ingest_telemetry(source="live")──┐
    UDP map thread ──ingest_map / ingest_frame(live)──┤
    sim engine ──────ingest_*(source="sim")───────────┼──► store ──► widgets
                                                      │   (authority   (ticks /
    mode switch ───── set_mode() ─────────────────────┘    filter)      signals)

Modes: LIVE (everything real) · SITL (telemetry real, perception+video
simulated) · SIMULATION (everything simulated).  No widget ever invents
data — unreported values render as N/A / UNKNOWN / UNAVAILABLE.
"""

from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from state.store import (
    FRAME_LOST_S,
    FRAME_STALE_S,
    MODE_LIVE,
    MODE_SIM,
    MODE_SITL,
    DashboardStore,
)
from state.sim import SCENARIOS, SimulationEngine
from threads.telemetry import DEFAULT_CONNECTION, TelemetryThread, mode_command
from threads.ffmpeg_receiver import FFmpegReceiverThread
from threads.map_receiver import MapReceiverThread
from threads.inference import InferenceThread
from widgets.camera_feed import CameraFeed
from widgets.map_canvas import MapCanvas
from widgets.status_bar import StatusBar
from widgets.survivor_list import SurvivorList
from widgets.hazard_panel import HazardPanel
from widgets.controls import Controls
from widgets.telemetry_popup import TelemetryPopup
from widgets.header_bar import HeaderBar
from widgets.nav_panel import NavPanel
from widgets.ai_panel import AIPanel
from widgets.thermal_feed import ThermalFeed
from widgets.fusion_bar import FusionBar
from widgets.comms_panel import CommsPanel
from widgets.sensor_panel import SensorPanel
from widgets.alerts_panel import AlertsPanel
from widgets.mission_panel import MissionPanel
from widgets.report_panel import ReportPanel
from widgets.model_panel import ModelPanel
from theme import APP_BG, GLOBAL_QSS, tab_qss
from utils.geo import latlon_to_grid
from utils.kml import load_kml

MODE_ARG = {"live": MODE_LIVE, "sitl": MODE_SITL,
            "sim": MODE_SIM, "simulation": MODE_SIM}

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL = os.path.join(_REPO_ROOT, "sih_model", "models", "best.onnx")


class MissionPlannerGCS(QMainWindow):
    def __init__(self, mode: str = MODE_LIVE,
                 mavlink: str = DEFAULT_CONNECTION,
                 model: str = DEFAULT_MODEL,
                 conf: float = 0.25,
                 demo_video: str | None = None):
        super().__init__()
        self.setWindowTitle("NIDAR Autonomous AirMouse GCS")
        self.setGeometry(50, 50, 1400, 850)
        self.setMinimumSize(1280, 700)

        self._mavlink = mavlink
        self._model_path = model
        self._conf = conf
        self._demo_video = demo_video
        self._paused = False
        self._link_ok = False
        self._link_ever_ok = False
        self._video_status = ""
        self.telemetry_thread: TelemetryThread | None = None
        self.video_thread: FFmpegReceiverThread | None = None
        self.map_thread: MapReceiverThread | None = None
        self.inference_thread: InferenceThread | None = None
        self.demo_video_thread: FFmpegReceiverThread | None = None

        # single source of truth ------------------------------------------
        self.store = DashboardStore(mode=mode, parent=self)

        central = QWidget()
        central.setStyleSheet(f"background-color: {APP_BG};")
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.header = HeaderBar()
        root_layout.addWidget(self.header)

        self.status_bar = StatusBar()
        root_layout.addWidget(self.status_bar)

        # -- body: left (camera) · center (map + alerts) · right (tabs) ----
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(4, 4, 4, 0)
        body_layout.setSpacing(4)

        # left: camera row (RGB + thermal) + fusion bar + survivor/hazard
        left_panel = QWidget()
        self.left_layout = QVBoxLayout(left_panel)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(4)

        self._cam_row = QHBoxLayout()
        self._cam_row.setSpacing(4)
        self.camera_feed = CameraFeed()
        self.thermal_feed = ThermalFeed()
        self._cam_row.addWidget(self.camera_feed, stretch=3)
        self._cam_row.addWidget(self.thermal_feed, stretch=1)
        self.left_layout.addLayout(self._cam_row, stretch=3)

        self.fusion_bar = FusionBar(self.store)
        self.left_layout.addWidget(self.fusion_bar)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(4)
        self.survivor_list = SurvivorList()
        self.hazard_panel = HazardPanel()
        bottom_row.addWidget(self.survivor_list, stretch=2)
        bottom_row.addWidget(self.hazard_panel, stretch=1)
        self.left_layout.addLayout(bottom_row, stretch=1)

        # center: tactical map + permanent priority alerts
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(4)

        self.map_canvas = MapCanvas()
        center_layout.addWidget(self.map_canvas, stretch=3)

        self.alerts_panel = AlertsPanel(self.store)
        center_layout.addWidget(self.alerts_panel, stretch=1)

        # right: slim tab column
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(tab_qss())
        self.tabs.setMinimumWidth(350)
        self.tabs.setMaximumWidth(440)

        self.nav_panel = NavPanel(self.store)
        self.ai_panel = AIPanel(self.store)
        self.model_panel = ModelPanel(self.store)
        self.mission_panel = MissionPanel(self.store)
        self.comms_panel = CommsPanel(self.store)
        self.sensor_panel = SensorPanel(self.store)
        self.report_panel = ReportPanel(self.store)

        self.tabs.addTab(self._tab(self.nav_panel), "NAV")
        self.tabs.addTab(self._tab(self.ai_panel), "AI")
        self.tabs.addTab(self._scroll_tab(self.model_panel), "MODEL")
        self.tabs.addTab(self._tab(self.mission_panel), "MISSION")
        self.tabs.addTab(self._tab(self._comms_tab()), "COMMS")
        self._report_index = self.tabs.addTab(self._tab(self.report_panel),
                                              "REPORT")

        body_layout.addWidget(left_panel, stretch=3)
        body_layout.addWidget(center_panel, stretch=2)
        body_layout.addWidget(self.tabs, stretch=2)

        root_layout.addWidget(body, stretch=1)

        self.controls = Controls()
        root_layout.addWidget(self.controls)

        self._root_layout = root_layout
        self._body = body
        self._is_fullscreen = False
        self._popup: TelemetryPopup | None = None

        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc.activated.connect(self._exit_fullscreen)

        # -- sources --------------------------------------------------------
        self.sim = SimulationEngine()
        self.map_thread = MapReceiverThread()
        self.inference_thread = InferenceThread(self._model_path, conf=self._conf)

        self._connect_static()
        self.map_thread.start()
        self.inference_thread.start()
        if self._demo_video:
            self._start_demo_video(self._demo_video)

        # initial per-mode setup (threads, chip, headers, first paint)
        self._on_mode_changed(self.store.mode)

    # ------------------------------------------------------------------
    # tab helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _tab(widget: QWidget) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(widget)
        return wrap

    @staticmethod
    def _scroll_tab(widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(widget)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        return scroll

    def _comms_tab(self) -> QWidget:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.comms_panel)
        lay.addWidget(self.sensor_panel)
        lay.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(inner)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        return scroll

    # ------------------------------------------------------------------
    # wiring: sources → store, store → widgets, widget → commands
    # ------------------------------------------------------------------
    def _connect_static(self) -> None:
        st = self.store

        # simulation engine → store (authority filter decides acceptance)
        self.sim.telemetry_signal.connect(
            lambda d: st.ingest_telemetry(d, source="sim"))
        self.sim.map_signal.connect(
            lambda *a: st.ingest_map(*a, source="sim"))
        self.sim.frame_signal.connect(
            lambda f: st.ingest_frame(f, source="sim", kind="rgb"))
        self.sim.thermal_signal.connect(
            lambda f: st.ingest_frame(f, source="sim", kind="thermal"))

        # UDP map receiver → store (rejected automatically outside LIVE)
        self.map_thread.map_signal.connect(self._on_map_packet)

        # store → frame consumers
        st.frame_available.connect(self.camera_feed.update_frame)
        st.thermal_available.connect(self.thermal_feed.update_frame)
        # local on-device inference taps the same authoritative RGB frames
        st.frame_available.connect(self._on_frame_for_inference)
        self.inference_thread.detections_signal.connect(self._on_edge_detections)
        self.inference_thread.status_signal.connect(self._on_inference_status)

        # store ticks → panels
        st.tick_fast.connect(self._refresh_fast)
        st.tick_slow.connect(self._refresh_slow)
        st.alerts_changed.connect(self.alerts_panel.refresh)
        st.detections_changed.connect(self._refresh_detections)
        st.mission_changed.connect(self.mission_panel.refresh)
        st.mode_changed.connect(self._on_mode_changed)

        # operator controls → vehicle / simulation
        self.controls.abort_signal.connect(self._on_abort)
        self.controls.pause_signal.connect(self._on_pause)
        self.controls.return_home_signal.connect(self._on_return_home)
        self.controls.start_mission_signal.connect(self._on_start)
        self.controls.load_area_signal.connect(self._on_load_area)

        # header mode switch
        self.header.mode_selected.connect(self._on_mode_selected)

        # regenerate the situation report immediately when its tab opens
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # demo scenarios (MISSION tab)
        self.mission_panel.scenario_selected.connect(self._on_scenario)

        # cross-panel selection (survivor row / AI record / hazard row /
        # map marker → fusion bar detail)
        self.survivor_list.survivor_selected.connect(
            self.fusion_bar.show_detection_id)
        self.ai_panel.detection_selected.connect(
            self.fusion_bar.show_detection_id)
        self.hazard_panel.hazard_selected.connect(
            self.fusion_bar.show_detection_id)
        self.map_canvas.detection_clicked.connect(self._on_map_detection)

        # fullscreen / telemetry popup
        self.camera_feed.double_clicked.connect(self._toggle_fullscreen)
        self.status_bar.telemetry_detail_clicked.connect(
            self._toggle_telemetry_popup)

    def _on_map_packet(self, grid, survivors, drone_pos, hazards, mission,
                       extra) -> None:
        self.store.ingest_map(grid, survivors, drone_pos, hazards, mission,
                              extra, source="live")

    def _on_tab_changed(self, index: int) -> None:
        if index == self._report_index:
            self.report_panel.refresh(force=True)

    # ------------------------------------------------------------------
    # local on-device inference (edge AI on the GCS host)
    # ------------------------------------------------------------------
    def _on_frame_for_inference(self, frame) -> None:
        if self.inference_thread is not None:
            self.inference_thread.submit_frame(frame)

    def _on_edge_detections(self, raw) -> None:
        self.store.ingest_edge_detections(raw, source="edge")

    def _on_inference_status(self, status: dict) -> None:
        self.ai_panel.set_local_inference(status)
        self.model_panel.set_inference_status(status)

    def _start_demo_video(self, url: str) -> None:
        """Loop a bundled/sample video through inference when no camera exists."""
        v = FFmpegReceiverThread(url)
        v.frame_signal.connect(self._on_demo_video_frame)
        v.status_signal.connect(lambda s: setattr(self, "_video_status", s))
        v.start()
        self.demo_video_thread = v

    def _on_demo_video_frame(self, frame) -> None:
        # demo frames use whatever the current mode's video authority is, so
        # they are accepted in SIM/SITL as well as LIVE
        self.store.ingest_frame(frame, source=self.store.video_authority,
                                kind="rgb")

    def _stop_demo_video(self) -> None:
        v = self.demo_video_thread
        if v is None:
            return
        self.demo_video_thread = None
        v.stop()
        v.deleteLater()

    # ------------------------------------------------------------------
    # mode management
    # ------------------------------------------------------------------
    def _on_mode_selected(self, mode: str) -> None:
        if mode == self.store.mode:
            self.header.set_mode(mode)
            return
        reply = QMessageBox.question(
            self,
            "Switch data mode",
            f"Switch to {mode} mode?\n\n"
            "Perception/telemetry state will be reset so no data bleeds "
            "between sources.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.store.set_mode(mode)        # emits mode_changed
        else:
            self.header.set_mode(self.store.mode)

    def _on_mode_changed(self, mode: str) -> None:
        """Apply thread/sim/UI changes for the store's current mode."""
        # simulation engine (SITL / SIMULATION): perception + video source
        if self.store.sim_active:
            if not self.sim.isRunning():
                self.sim.set_active(True)
                self.sim.start()
            else:
                self.sim.set_active(True)
        else:
            self.sim.set_active(False)

        # telemetry thread (LIVE / SITL — real vehicle link)
        if mode == MODE_SIM:
            self._stop_telemetry()
            self.controls.set_connection_status(
                None, "SIMULATION MODE — no vehicle link", text="SIM MODE")
        else:
            self._start_telemetry()

        # video thread (LIVE — real stream; sim frames elsewhere)
        if mode == MODE_LIVE:
            self._start_video()
        else:
            self._stop_video()
            self._video_status = ""

        # UI state
        self.header.set_mode(mode)
        self.mission_panel.set_sim_controls_visible(self.store.sim_active)
        self._paused = False
        self.controls.set_paused(False)
        self.map_canvas.update_map(None, [], (0, 0), [], {})
        self._refresh_fast()
        self._refresh_slow()

    # ------------------------------------------------------------------
    # thread lifecycle
    # ------------------------------------------------------------------
    def _start_telemetry(self) -> None:
        if self.telemetry_thread is not None:
            return
        self._link_ok = False
        self._link_ever_ok = False
        t = TelemetryThread(self._mavlink)
        t.telemetry_signal.connect(self._on_live_telemetry)
        t.connection_status.connect(self._on_link_status)
        t.command_result.connect(self.controls.show_command_result)
        t.start()
        self.telemetry_thread = t

    def _stop_telemetry(self) -> None:
        t = self.telemetry_thread
        if t is None:
            return
        self.telemetry_thread = None
        t.stop()
        t.deleteLater()

    def _on_live_telemetry(self, data: dict) -> None:
        if self.store.mode == MODE_SIM:
            return
        self.store.ingest_telemetry(data, source="live")

    def _on_link_status(self, ok: bool, detail: str) -> None:
        self.store.set_link_status(ok, detail)
        if ok:
            self._link_ever_ok = True
        self._link_ok = ok
        if self.store.mode == MODE_SIM:
            return
        # before the first heartbeat, "NO DATA" (amber) reads truer than
        # a red LINK LOST; after that a drop is a real loss
        chip_ok = ok if (ok or self._link_ever_ok) else None
        self.controls.set_connection_status(chip_ok, detail)

    def _start_video(self) -> None:
        if self.video_thread is not None:
            return
        v = FFmpegReceiverThread()
        v.frame_signal.connect(self._on_live_frame)
        v.status_signal.connect(self._on_video_status)
        v.start()
        self.video_thread = v

    def _stop_video(self) -> None:
        v = self.video_thread
        if v is None:
            return
        self.video_thread = None
        v.stop()
        v.deleteLater()

    def _on_live_frame(self, frame) -> None:
        if self.store.mode != MODE_LIVE:
            return
        self.store.ingest_frame(frame, source="live", kind="rgb")

    def _on_video_status(self, text: str) -> None:
        self._video_status = text

    # ------------------------------------------------------------------
    # refresh cycles (store ticks)
    # ------------------------------------------------------------------
    def _refresh_fast(self) -> None:
        st = self.store
        self.status_bar.update_telemetry(st.telemetry)
        self.status_bar.update_mission(
            st.mission.phase_text, st.mission.progress,
            st.mission.timer_text)
        self.status_bar.set_gps_state(st.nav.gps_denied)

        self.camera_feed.set_detections(st.camera_detections())
        self.camera_feed.update_telemetry(st.telemetry)

        self.survivor_list.update_survivors(st.survivors)
        self.hazard_panel.update_hazards(st.hazards)
        self._refresh_map()
        self._update_stream_status()
        self.fusion_bar.refresh()

        if self._popup is not None and self._popup.isVisible():
            self._popup.update_telemetry(st.telemetry)

    def _refresh_slow(self) -> None:
        self.nav_panel.refresh()
        self.ai_panel.refresh()
        self.comms_panel.refresh()
        self.sensor_panel.refresh()
        self.mission_panel.refresh()
        self.alerts_panel.refresh()
        self.report_panel.refresh()

    def _refresh_detections(self) -> None:
        st = self.store
        self.survivor_list.update_survivors(st.survivors)
        self.hazard_panel.update_hazards(st.hazards)
        self.ai_panel.refresh()
        self.fusion_bar.refresh()
        self.camera_feed.set_detections(st.camera_detections())
        self._refresh_map()

    def _refresh_map(self) -> None:
        if self.store.grid is None:
            return
        m = self.store.mission
        self.map_canvas.update_map(
            self.store.grid, self.store.survivors, self.store.drone_pos,
            self.store.hazards, {})
        self.map_canvas.update_extras(
            track=list(self.store.track),
            polygon=self._area_polygon_grid(),
            coverage_text=m.coverage.pct_text,
            area_name=m.area_name or "",
        )

    def _area_polygon_grid(self) -> list[tuple[int, int]] | None:
        """KML outline in grid coordinates — needs a geo origin; without
        one the polygon simply isn't drawn (no fabricated placement)."""
        m = self.store.mission
        if not m.area_polygon or not m.origin:
            return None
        try:
            return [latlon_to_grid(m.origin, m.cell_size_m, lat, lon)
                    for lat, lon in m.area_polygon]
        except Exception:
            return None

    def _update_stream_status(self) -> None:
        """Honest overlays for RGB + thermal (never a frozen frame that
        pretends to be live)."""
        age = self.store.age("video")
        if age is None:
            if self.store.mode == MODE_LIVE:
                detail = f"\n{self._video_status}" if self._video_status else ""
                self.camera_feed.set_status(
                    "NO VIDEO SIGNAL — LIVE STREAM" + detail)
            else:
                self.camera_feed.set_status(
                    "SIMULATION FEED\nmission/scenario not streaming yet")
        elif age > FRAME_LOST_S:
            self.camera_feed.set_status(
                f"VIDEO SIGNAL LOST\nlast frame {age:.0f}s ago")
        elif age > FRAME_STALE_S:
            self.camera_feed.set_status(
                f"VIDEO STALE — last frame {age:.0f}s ago")
        else:
            self.camera_feed.set_status(None)

        t_age = self.store.age("thermal")
        if t_age is None:
            if self.store.video_authority == "sim":
                self.thermal_feed.set_status(
                    "THERMAL — SIMULATION IDLE\nno frames yet")
            else:
                self.thermal_feed.set_status(
                    "THERMAL\nNO STREAM CONFIGURED — UNAVAILABLE")
        elif t_age > 5:
            self.thermal_feed.set_status(
                f"THERMAL STALE — last frame {t_age:.0f}s ago")
        else:
            self.thermal_feed.set_status(None)

        label = self.store.source_label("video")
        self.camera_feed.set_source_label(label)
        self.thermal_feed.set_source_label(label)

    # ------------------------------------------------------------------
    # operator commands → simulation / MAVLink
    # ------------------------------------------------------------------
    def _send_mav(self, name: str, modes: tuple[str, ...]) -> bool:
        if self.telemetry_thread is None or not self._link_ok:
            self.controls.show_command_result(
                name, False, "NOT SENT — NO TELEMETRY LINK")
            return False
        self.telemetry_thread.submit_command(name, mode_command(*modes))
        return True

    def _on_start(self) -> None:
        if self.store.sim_active:
            self.sim.submit("start_mission")
        if self.store.mode != MODE_SIM:
            self._send_mav("START", ("AUTO", "MISSION"))
        elif self.store.sim_active:
            self.controls.show_command_result(
                "START", True, "SENT TO SIMULATION")

    def _on_pause(self) -> None:
        self._paused = not self._paused
        self.controls.set_paused(self._paused)
        if self.store.sim_active:
            self.sim.submit("pause" if self._paused else "resume")
        if self.store.mode != MODE_SIM:
            if self._paused:
                self._send_mav("PAUSE", ("LOITER", "HOLD", "BRAKE"))
            else:
                self._send_mav("RESUME", ("AUTO", "MISSION"))
        elif self.store.sim_active:
            self.controls.show_command_result(
                "PAUSE" if self._paused else "RESUME", True,
                "SENT TO SIMULATION")

    def _on_return_home(self) -> None:
        if self.store.sim_active:
            self.sim.submit("rth")
        if self.store.mode != MODE_SIM:
            self._send_mav("RTH", ("RTL",))
        elif self.store.sim_active:
            self.controls.show_command_result(
                "RTH", True, "SENT TO SIMULATION")

    def _on_abort(self) -> None:
        # confirmation happens inside Controls._on_abort
        self._paused = False
        self.controls.set_paused(False)
        if self.store.sim_active:
            self.sim.submit("abort")
        if self.store.mode != MODE_SIM:
            self._send_mav("ABORT", ("RTL",))
        elif self.store.sim_active:
            self.controls.show_command_result(
                "ABORT", True, "SENT TO SIMULATION")

    def _on_load_area(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load disaster area outline", "",
            "KML / KMZ (*.kml *.kmz);;All files (*)")
        if not path:
            return
        try:
            kml = load_kml(path)
        except Exception as exc:
            QMessageBox.warning(self, "Area load failed", str(exc))
            return
        if not (kml.get("polygons") or kml.get("lines")):
            self.controls.show_command_result(
                "AREA", False, "NO POLYGON FOUND IN FILE")
            return
        self.store.set_area(kml)
        self.controls.show_command_result(
            "AREA", True, f"LOADED {kml.get('name', 'AREA')}")

    def _on_scenario(self, n: int) -> None:
        if not self.store.sim_active:
            self.controls.show_command_result(
                "SCENARIO", False, "SIMULATION OFF (LIVE MODE)")
            return
        self.store.reset_detections()
        self.sim.submit("start_scenario", n=n)
        name = SCENARIOS.get(n, (f"#{n}", ""))[0]
        self.controls.show_command_result(
            "SCENARIO", True, f"RUNNING #{n} {name}")

    def _on_map_detection(self, kind: str, ident: str) -> None:
        self.fusion_bar.show_detection_id(ident)
        if kind == "survivor":
            self.survivor_list.select_id(ident)
        else:
            self.hazard_panel.select_id(ident)

    # ------------------------------------------------------------------
    # fullscreen + telemetry popup (unchanged behaviour)
    # ------------------------------------------------------------------
    def _toggle_fullscreen(self):
        if self._is_fullscreen:
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self):
        self._is_fullscreen = True
        self.header.hide()
        self.status_bar.hide()
        self._body.hide()
        self.controls.hide()
        self.camera_feed.setParent(self)
        self._root_layout.addWidget(self.camera_feed)
        self.camera_feed.show()

    def _exit_fullscreen(self):
        if not self._is_fullscreen:
            return
        self._is_fullscreen = False
        self._root_layout.removeWidget(self.camera_feed)
        self.camera_feed.setParent(self._body)
        self._cam_row.insertWidget(0, self.camera_feed, stretch=3)
        self.camera_feed.show()
        self.header.show()
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
        self._popup.update_telemetry(self.store.telemetry)

        badge = {
            "mode": self.status_bar.mode_badge,
            "armed": self.status_bar.armed_badge,
            "battery": self.status_bar.battery_bar,
            "gps": self.status_bar.gps_badge,
            "heading": self.status_bar.heading_badge,
            "altitude": self.status_bar.alt_badge,
            "speed": self.status_bar.speed_badge,
            "vert": self.status_bar.vert_badge,
            "time": self.status_bar.time_badge,
        }.get(badge_name, self.status_bar.mode_badge)

        pos = badge.mapToGlobal(badge.rect().bottomLeft())
        self._popup.move(pos.x(), pos.y() + 4)
        self._popup.show()

    def _on_popup_closed(self):
        self._popup = None

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        self.header.stop()
        self._stop_telemetry()
        self._stop_video()
        self._stop_demo_video()
        if self.inference_thread is not None:
            self.inference_thread.stop()
            self.inference_thread = None
        if self.map_thread is not None:
            self.map_thread.stop()
            self.map_thread = None
        self.sim.stop()
        event.accept()


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="NIDAR GCS — autonomous disaster-response drone ground "
                    "control station")
    p.add_argument("--mode", choices=sorted(MODE_ARG), default=None,
                   help="data mode: live (all real) / sitl (telemetry real, "
                        "perception+video simulated) / sim (everything "
                        "simulated).  Default: live")
    p.add_argument("--mavlink", default=DEFAULT_CONNECTION,
                   help=f"pymavlink connection string "
                        f"(default: {DEFAULT_CONNECTION}; use "
                        f"'udpin:0.0.0.0:14551' if QGroundControl holds "
                        f"port 14550)")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help="path to the on-device model (best.onnx or best.pt). "
                        f"Default: {DEFAULT_MODEL}")
    p.add_argument("--conf", type=float, default=0.25,
                   help="detector confidence threshold (default 0.25)")
    p.add_argument("--demo", action="store_true",
                   help="one-flag demo: defaults to SIMULATION mode so the "
                        "built-in scenario + on-device AI run with no hardware")
    p.add_argument("--demo-video", default=None,
                   help="loop a video file/URL through inference when no "
                        "camera feed is available")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    if args.mode:
        mode = MODE_ARG[args.mode]
    else:
        mode = MODE_SIM if args.demo else MODE_LIVE
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(GLOBAL_QSS)
    gcs = MissionPlannerGCS(mode=mode, mavlink=args.mavlink,
                            model=args.model, conf=args.conf,
                            demo_video=args.demo_video)
    gcs.show()
    sys.exit(app.exec())
