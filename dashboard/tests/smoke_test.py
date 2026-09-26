"""Headless pipeline smoke test — no display, no hardware, no sockets.

Verifies: imports, mode authority, simulation → store ingestion,
geo-tagging, risk/priority, alerts, coverage, report generation,
and the GPS-denied derivation.  Run:

    QT_QPA_PLATFORM=offscreen python tests/smoke_test.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


def main() -> int:
    app = QApplication([])

    # -- imports ---------------------------------------------------------
    from state.store import DashboardStore, MODE_SIM, MODE_LIVE
    from state.sim import SimulationEngine, SCENARIOS
    from models.nav import derive_navigation, PositionSource, SourceState
    from utils.report import build_report  # noqa: F401
    from utils.kml import load_kml  # noqa: F401
    from utils.priority import assess_survivor_priority  # noqa: F401
    print("[1] imports OK")

    # -- mode authority --------------------------------------------------
    store = DashboardStore(mode=MODE_LIVE)
    store.ingest_telemetry({"gps_fix": 3, "gps_satellites": 9}, source="sim")
    assert not store.telemetry, "SIM telemetry must be ignored in LIVE mode"
    store.ingest_telemetry({"gps_fix": 3, "gps_satellites": 9}, source="live")
    assert store.gps.satellites == 9
    store.set_mode(MODE_SIM)
    assert not store.telemetry, "mode switch must clear live state"
    store.ingest_telemetry({"gps_fix": 3, "gps_satellites": 9}, source="live")
    assert not store.telemetry, "LIVE telemetry must be ignored in SIM mode"
    print("[2] mode authority OK")

    # -- simulated pipeline ---------------------------------------------
    store.set_mode(MODE_SIM)
    sim = SimulationEngine()
    sim.telemetry_signal.connect(
        lambda d: store.ingest_telemetry(d, source="sim"))
    sim.map_signal.connect(
        lambda *a: store.ingest_map(*a, source="sim"))
    sim.frame_signal.connect(
        lambda f: store.ingest_frame(f, source="sim", kind="rgb"))
    sim.thermal_signal.connect(
        lambda f: store.ingest_frame(f, source="sim", kind="thermal"))
    sim.set_active(True)
    sim.start_scenario(6)          # multiple simultaneous detections
    sim.start()

    deadline = time.time() + 17
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    sim.stop()

    assert store.telemetry.get("mode") in ("AUTO", "HOLD"), store.telemetry.get("mode")
    assert store.gps.satellites, "no GPS from sim"
    assert store.age("telemetry") is not None and store.age("telemetry") < 2
    print(f"[3] telemetry OK  mode={store.telemetry.get('mode')} "
          f"bat={store.telemetry.get('battery')}% "
          f"fix={store.gps.fix_label} sats={store.survivors and 'n/a' or store.gps.satellites}")

    assert store.grid is not None, "no map data"
    assert len(store.survivors) >= 1, "no survivors"
    assert len(store.hazards) >= 1, "no hazards"
    assert store.mission.coverage.pct > 0, "no coverage"
    print(f"[4] map OK  coverage={store.mission.coverage.pct_text} "
          f"scanned={store.mission.coverage.cells_scanned}/"
          f"{store.mission.coverage.cells_total} "
          f"({store.mission.coverage.method}) survivors={len(store.survivors)} "
          f"hazards={len(store.hazards)}")

    # geo-tagging
    s0 = store.survivors[0]
    assert s0.lat is not None and s0.lon is not None, "geo-tag missing"
    assert 19.0 < s0.lat < 19.5 and 73.0 < s0.lon < 73.3, (s0.lat, s0.lon)
    print(f"[5] geo-tag OK  {s0.id} -> {s0.location_text} "
          f"priority={s0.priority} score={s0.priority_score:.0f}")

    # risk model
    for h in store.hazards:
        assert h.effective_severity is not None
        assert h.risk_reasons or h.severity_level is not None
    print(f"[6] risk OK  " + ", ".join(
        f"{h.id}:{h.type.value}={h.effective_severity.label}" for h in store.hazards))

    # alerts
    assert store.active_alerts, "no alerts raised"
    p1 = [a for a in store.active_alerts if a.priority.label == "P1"]
    print(f"[7] alerts OK  {len(store.active_alerts)} active "
          f"({len(p1)} P1): " + "; ".join(a.title for a in store.active_alerts[:4]))
    # acknowledge without deleting detection
    aid = store.active_alerts[0].id
    store.acknowledge_alert(aid)
    assert any(a.id == aid and a.acknowledged for a in store.alerts)
    print("[8] alert ack OK (detection records untouched)")

    # frames + sensor health
    assert store.age("video") is not None, "no RGB frames"
    assert store.age("thermal") is not None, "no thermal frames"
    assert store.sensors["rgb"].health.value == "healthy"
    assert store.sensors["thermal"].health.value == "healthy"
    print(f"[9] video OK  rgb={store.sensors['rgb'].detail} "
          f"thermal={store.sensors['thermal'].detail}")

    # AI status
    assert store.ai.reported and store.ai.on_device is True
    print(f"[10] ai OK  {store.ai_line()}")

    # nav state (GPS nominal)
    assert not store.nav.gps_denied
    print(f"[11] nav OK  label={store.nav.label} banner={store.nav.banner}")

    # report
    rep = store.build_report()
    text = rep.to_text()
    assert "DISASTER SITUATION REPORT" in text
    assert rep.survivors_detected >= 1
    assert rep.recommendations
    rep.to_json(); rep.to_csv()
    print("[12] report OK\n" + "\n".join("     " + l for l in text.splitlines()[:14]))

    # GPS-denied derivation (unit-level)
    from models.telemetry import GPSStatus, EKFStatus
    g = GPSStatus(fix_type=0, satellites=0, last_rx=time.monotonic())
    n = derive_navigation(g, EKFStatus(), ["ekf", "imu", "vo", "of", "lidar"], None)
    assert n.gps_denied and n.banner.startswith("GPS-DENIED")
    g2 = GPSStatus(fix_type=4, satellites=16, last_rx=time.monotonic() - 30)
    n2 = derive_navigation(g2, EKFStatus(), [], None)
    assert not n2.gps_denied, "stale GPS must not be reported as GPS-denied"
    print(f"[13] gps-denied derivation OK  '{n.label}' vs stale '{n2.label}'")

    # -- widget rendering (headless) -------------------------------------
    from widgets.nav_panel import NavPanel
    from widgets.ai_panel import AIPanel
    from widgets.fusion_bar import FusionBar
    from widgets.comms_panel import CommsPanel
    from widgets.sensor_panel import SensorPanel
    from widgets.alerts_panel import AlertsPanel
    from widgets.mission_panel import MissionPanel
    from widgets.report_panel import ReportPanel
    from widgets.model_panel import ModelPanel
    from widgets.camera_feed import CameraFeed
    from widgets.thermal_feed import ThermalFeed
    from widgets.map_canvas import MapCanvas
    from widgets.survivor_list import SurvivorList
    from widgets.hazard_panel import HazardPanel
    from widgets.controls import Controls
    from widgets.status_bar import StatusBar
    from widgets.header_bar import HeaderBar
    from widgets.telemetry_popup import TelemetryPopup

    panels = [NavPanel(store), AIPanel(store), FusionBar(store),
              CommsPanel(store), SensorPanel(store), AlertsPanel(store),
              MissionPanel(store), ReportPanel(store), ModelPanel(store)]
    for p in panels:
        p.refresh()
    panels[-1].set_inference_status({"available": True, "backend": "onnxruntime",
                                     "model": "best.onnx", "fps": 8.0,
                                     "latency_ms": 1.7, "detections": 3})

    survivor_list = SurvivorList()
    survivor_list.update_survivors(store.survivors)
    survivor_list.select_id(store.survivors[0].id)
    hazard_panel = HazardPanel()
    hazard_panel.update_hazards(store.hazards)
    hazard_panel.select_id(store.hazards[0].id)

    cam = CameraFeed()
    cam.set_source_label(store.source_label("video"))
    cam.set_status("VIDEO STALE — test")
    cam.set_detections(store.camera_detections())
    cam.update_telemetry(store.telemetry)
    therm = ThermalFeed()
    therm.set_source_label(store.source_label("video"))
    therm.set_status("THERMAL STALE — test")

    canvas = MapCanvas()
    canvas.update_map(store.grid, store.survivors, store.drone_pos,
                      store.hazards, {})
    canvas.update_extras(track=list(store.track), polygon=None,
                         coverage_text=store.mission.coverage.pct_text,
                         area_name="")
    canvas.resize(640, 480)
    canvas.grab()                     # force a paint pass

    status = StatusBar()
    status.update_telemetry(store.telemetry)
    status.update_mission(store.mission.phase_text, store.mission.progress,
                          store.mission.timer_text)
    status.set_gps_state(False)
    header = HeaderBar()
    header.set_mode(store.mode)
    controls = Controls()
    controls.set_connection_status(None, "test", text="SIM MODE")
    controls.show_command_result("TEST", True, "ok")
    controls.set_paused(True)
    popup = TelemetryPopup()
    popup.update_telemetry(store.telemetry)
    popup.close()
    print(f"[14] widget rendering OK  ({len(panels)} panels + tables + "
          f"camera/map/status/controls)")

    # -- full window wiring (SIM) ---------------------------------------
    from gcs import MissionPlannerGCS
    win = MissionPlannerGCS(mode=MODE_SIM)
    win.show()
    try:
        win._on_scenario(6)
        win._on_start()
        end = time.time() + 12
        while time.time() < end and not win.store.survivors:
            app.processEvents()
            time.sleep(0.02)
        win.store._health_tick()
        app.processEvents()
        assert win.store.grid is not None
        assert len(win.store.survivors) >= 1
        assert win.mission_panel.scenario_combo.isHidden() is False
        win.tabs.setCurrentIndex(4)
        app.processEvents()
        print("[15] full window wiring OK  "
              f"mode={win.store.mode} survivors={len(win.store.survivors)} "
              f"alerts={len(win.store.active_alerts)}")
    finally:
        win.close()
        app.processEvents()

    # -- on-device inference engine: decode + NMS (no real weights) ------
    import numpy as _np
    _root = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from sih_model.inference import (SIHInferenceEngine, CLASS_NAMES,
                                     DASHBOARD_CLASS_MAP)

    class _In:
        name = "images"

    class _Sess:
        def __init__(self, pred):
            self.pred = pred

        def get_inputs(self):
            return [_In()]

        def run(self, _out, _feed):
            return [self.pred]

    nc = len(CLASS_NAMES)
    pred = _np.zeros((1, 4 + nc, 8400), dtype=_np.float32)
    pred[0, 0, 0], pred[0, 1, 0], pred[0, 2, 0], pred[0, 3, 0] = 320, 320, 40, 40
    pred[0, 4 + 4, 0] = 0.90          # structural_damage
    pred[0, 0, 1], pred[0, 1, 1], pred[0, 2, 1], pred[0, 3, 1] = 322, 318, 42, 42
    pred[0, 4 + 4, 1] = 0.60          # overlapping duplicate -> NMS drops
    eng = object.__new__(SIHInferenceEngine)
    eng.model_path, eng.conf, eng.iou, eng.imgsz = "fake.onnx", 0.25, 0.45, 640
    eng.backend, eng.available, eng.reason = "onnxruntime", True, ""
    eng._session, eng._model, eng._requested_backend = _Sess(pred), None, "auto"
    dets = eng.infer(_np.zeros((640, 640, 3), dtype=_np.uint8))
    assert len(dets) == 1, f"NMS should collapse the duplicate: {len(dets)}"
    assert dets[0].label == "structural_damage"
    assert DASHBOARD_CLASS_MAP["structural_damage"] == "DAMAGED STRUCTURE"
    print(f"[16] inference decode/NMS OK  {dets[0].label} "
          f"{dets[0].confidence:.2f} -> {dets[0].dash_class}")

    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
