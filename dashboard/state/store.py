"""DashboardStore — the single source of truth (Step 17/18).

Every data source (live MAVLink thread, NIDAR map/video sockets, the
simulation engine) feeds the store through ``ingest_*`` methods.  The store

* enforces **mode authority** so live and simulated values never mix,
* timestamps every arrival for **staleness / heartbeat detection**,
* deduplicates detections and rejects out-of-order records,
* geo-tags survivors/hazards, assesses risk and rescue priority,
* owns alerts, mission/coverage state, sensor + communication health,
* coalesces UI updates into throttled ticks (250 ms / 1 s) so high-rate
  telemetry never triggers per-packet widget re-renders.

Widgets only ever *pull* from the store; threads only ever *push* into it.
"""

from __future__ import annotations

import time
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal

from models.telemetry import GPSStatus, EKFStatus
from models.nav import NavigationState, derive_navigation, PositionSource
from models.survivor import Survivor
from models.hazard import Hazard, coerce_hazard_type
from models.detection import Severity, DetectionView, fused_confidence
from models.alert import Alert, AlertPriority
from models.sensors import SensorStatus, Health, SENSOR_KEYS
from models.comms import CommunicationStatus, Link, LinkState, SyncQueue
from models.ai import AIInferenceStatus
from models.mission import MissionState, MissionPhase, SearchCoverage
from utils import geo as geo_utils
from utils.priority import assess_survivor_priority
from utils.risk import assess_hazard_severity
from utils.report import build_report, SituationReport

MODE_LIVE = "LIVE"
MODE_SITL = "SITL"
MODE_SIM = "SIMULATION"
ALL_MODES = (MODE_LIVE, MODE_SITL, MODE_SIM)

TELEMETRY_STALE_S = 3.0
TELEMETRY_LOST_S = 10.0
FRAME_STALE_S = 3.0
FRAME_LOST_S = 10.0
MAP_STALE_S = 5.0
MAP_LOST_S = 15.0
MAX_TRACK = 600
MAX_ALERTS = 200


class DashboardStore(QObject):
    tick_fast = Signal()          # ~4 Hz — telemetry-driven widgets
    tick_slow = Signal()          # 1 Hz  — health / clocks / ages
    alerts_changed = Signal()
    detections_changed = Signal()
    mission_changed = Signal()
    mode_changed = Signal(str)
    frame_available = Signal(object)     # RGB frame (authority-filtered)
    thermal_available = Signal(object)   # thermal frame

    def __init__(self, mode: str = MODE_LIVE, parent=None):
        super().__init__(parent)
        self.mode = mode if mode in ALL_MODES else MODE_LIVE

        # --- raw / derived state ----------------------------------------
        self.telemetry: dict = {}
        self.gps = GPSStatus()
        self.ekf = EKFStatus()
        self.nav = NavigationState()
        self.sensors: dict[str, SensorStatus] = {
            key: SensorStatus(key=key, name=name) for key, name in SENSOR_KEYS
        }
        self.comms = CommunicationStatus()
        self.ai = AIInferenceStatus()
        self.sync = SyncQueue()

        self.grid = None
        self.drone_pos: tuple[int, int] = (0, 0)
        self.track: deque = deque(maxlen=MAX_TRACK)
        self.survivors: list[Survivor] = []
        self.hazards: list[Hazard] = []
        self.extra_detections: list[DetectionView] = []
        self.alerts: list[Alert] = []
        self.mission = MissionState()
        self.thermal_linked = False      # thermal feed has produced a frame

        # --- provenance / freshness -------------------------------------
        self.last_rx: dict[str, float] = {}
        self._last_src: dict[str, str] = {}
        self._nav_hints: set[str] = set()
        self._explicit_denied: bool | None = None
        self._mission_packet_at: float | None = None
        self._gps_alert: Alert | None = None
        self._comm_alert: Alert | None = None
        self._telem_alert: Alert | None = None
        self._battery_alert: Alert | None = None
        self._gps_ticks = {"ok": 0, "denied": 0, "unknown": 0}
        self._offline = False
        self._link_ok: bool | None = None
        self._link_status: tuple[bool, str] | None = None
        self._last_sync_note = ""

        # --- timers -------------------------------------------------------
        self._fast = QTimer(self)
        self._fast.setInterval(250)
        self._fast.timeout.connect(self.tick_fast.emit)
        self._fast.start()

        self._slow = QTimer(self)
        self._slow.setInterval(1000)
        self._slow.timeout.connect(self._health_tick)
        self._slow.start()

    # ------------------------------------------------------------------
    # mode / authority
    # ------------------------------------------------------------------
    @property
    def telemetry_authority(self) -> str:
        return "sim" if self.mode == MODE_SIM else "live"

    @property
    def perception_authority(self) -> str:
        return "live" if self.mode == MODE_LIVE else "sim"

    @property
    def video_authority(self) -> str:
        return "live" if self.mode == MODE_LIVE else "sim"

    @property
    def sim_active(self) -> bool:
        return self.mode != MODE_LIVE

    @property
    def is_sim(self) -> bool:
        return self.mode == MODE_SIM

    def data_source_text(self) -> str:
        if self.mode == MODE_LIVE:
            return "DATA SOURCE: LIVE"
        if self.mode == MODE_SITL:
            return "DATA SOURCE: TELEMETRY LIVE · PERCEPTION SIM"
        return "DATA SOURCE: SIMULATION"

    def source_label(self, subsystem: str) -> str:
        """Per-subsystem provenance for panels/tooltips."""
        if subsystem == "telemetry":
            return "SIMULATION" if self.telemetry_authority == "sim" else "LIVE"
        if subsystem in ("perception", "video"):
            return "SIMULATION" if self.perception_authority == "sim" else "LIVE"
        return "LIVE"

    def set_mode(self, mode: str) -> None:
        if mode not in ALL_MODES or mode == self.mode:
            return
        self.mode = mode
        # reset mixed state so sources never bleed across modes
        self.survivors.clear()
        self.hazards.clear()
        self.extra_detections.clear()
        self.alerts.clear()
        self.track.clear()
        self.grid = None
        self.telemetry.clear()
        self.gps = GPSStatus()
        self.ekf = EKFStatus()
        self.nav = NavigationState()
        self._nav_hints.clear()
        self._explicit_denied = None
        self._gps_alert = self._comm_alert = self._telem_alert = None
        self._battery_alert = None
        self._gps_ticks = {"ok": 0, "denied": 0, "unknown": 0}
        self._mission_packet_at = None
        self.mission = MissionState()
        # keep loaded KML area across mode switches
        self.ai = AIInferenceStatus()
        for key in self.sensors:
            self.sensors[key].last_rx = None
            self.sensors[key].health = Health.UNKNOWN
            self.sensors[key].detail = "not reported"
        # a source that was authoritative before is no longer trustworthy
        for k in list(self.last_rx):
            if self._last_src.get(k) not in (None, self._authority_for(k)):
                self.last_rx.pop(k, None)
        self.mode_changed.emit(mode)
        self.alerts_changed.emit()
        self.detections_changed.emit()
        self.mission_changed.emit()
        self.tick_fast.emit()

    def _authority_for(self, subsystem: str) -> str:
        if subsystem == "telemetry":
            return self.telemetry_authority
        if subsystem in ("map", "video", "thermal"):
            return self.perception_authority
        return "live"

    def _accept(self, subsystem: str, source: str) -> bool:
        return source == self._authority_for(subsystem)

    def _rx(self, subsystem: str, source: str) -> None:
        self.last_rx[subsystem] = time.monotonic()
        self._last_src[subsystem] = source

    def age(self, subsystem: str) -> float | None:
        t = self.last_rx.get(subsystem)
        return None if t is None else time.monotonic() - t

    # ------------------------------------------------------------------
    # ingestion — telemetry (MAVLink / simulation)
    # ------------------------------------------------------------------
    def ingest_telemetry(self, data: dict, source: str = "live") -> None:
        if not data or not self._accept("telemetry", source):
            return
        self.telemetry.update(data)
        self._rx("telemetry", source)
        now = time.monotonic()

        gps_keys = ("gps_fix", "gps_satellites", "gps_hdop", "gps_accuracy_m")
        if any(k in data for k in gps_keys):
            if "gps_fix" in data:
                self.gps.fix_type = int(data["gps_fix"] or 0)
            if "gps_satellites" in data:
                self.gps.satellites = int(data["gps_satellites"])
            if "gps_hdop" in data:
                self.gps.hdop = data["gps_hdop"]
            if "gps_accuracy_m" in data:
                self.gps.accuracy_m = data["gps_accuracy_m"]
            self.gps.last_rx = now
            self.sensors["gps"].last_rx = now

        if "lat" in data:
            self.gps.lat = data.get("lat")
            self.gps.lon = data.get("lon")

        if "roll" in data or "pitch" in data:
            self.sensors["imu"].last_rx = now
        if "alt" in data or "climb" in data:
            self.sensors["baro"].last_rx = now
        if "mode" in data and not isinstance(data["mode"], str):
            data["mode"] = str(data["mode"])
        self.sensors["telemetry"].last_rx = now

        # EKF
        if data.get("ekf_reported"):
            self.ekf.reported = True
            self.ekf.flags = int(data.get("ekf_flags", 0) or 0)
            self.ekf.horiz_acc = data.get("ekf_horiz_acc")
            self.ekf.vel_err = data.get("ekf_vel_err")
            self.ekf.last_rx = now

        # nav hints (explicit backend/simulation reports)
        for hint in data.get("nav_sources", []) or []:
            self._nav_hints.add(str(hint).lower())
        if data.get("gps_denied") is not None:
            self._explicit_denied = bool(data["gps_denied"])

        if "wp_seq" in data:
            self.mission.wp_seq = int(data["wp_seq"])

        # vehicle global origin (GPS_GLOBAL_ORIGIN) is a real geographic
        # anchor — used when the companion does not send one
        if data.get("origin") and self.mission.origin is None:
            try:
                self.mission.origin = (float(data["origin"][0]),
                                       float(data["origin"][1]))
            except Exception:
                pass

        self._derive_phase_from_telemetry()

    def _derive_phase_from_telemetry(self) -> None:
        """Mission phase from real flight state when no companion mission
        packets are present (live SITL / hardware without the AI stack)."""
        if self._mission_packet_at and time.monotonic() - self._mission_packet_at < 10:
            return   # companion mission dict is authoritative
        mode = str(self.telemetry.get("mode", "") or "").upper()
        armed = bool(self.telemetry.get("armed"))
        if armed and "AUTO" in mode:
            if self.mission.phase in (MissionPhase.IDLE, MissionPhase.AREA_LOADED):
                self.mission.update("searching", self.mission.progress,
                                    self.mission.total_grid_cells,
                                    self.mission.scanned_cells)
                self.mission_changed.emit()
        elif armed and mode == "RTL":
            if self.mission.phase is MissionPhase.SCANNING:
                self.mission.update("returning", self.mission.progress,
                                    self.mission.total_grid_cells,
                                    self.mission.scanned_cells)
                self.mission_changed.emit()
        elif not armed and self.mission.started_at is not None and \
                self.mission.phase not in (MissionPhase.COMPLETE,
                                           MissionPhase.ABORTED):
            self.mission.update("complete", self.mission.progress,
                                self.mission.total_grid_cells,
                                self.mission.scanned_cells)
            self.mission_changed.emit()

    # ------------------------------------------------------------------
    # ingestion — perception (NIDAR map packets / simulation)
    # ------------------------------------------------------------------
    def ingest_map(self, grid, survivors_raw, drone_pos, hazards_raw,
                   mission: dict, extra: dict | None = None,
                   source: str = "live") -> None:
        if not self._accept("map", source):
            return
        extra = extra or {}
        self._rx("map", source)
        self._mission_packet_at = time.monotonic()
        self.grid = grid

        # --- drone track ------------------------------------------------
        if drone_pos is not None and len(drone_pos) >= 2:
            pos = (int(drone_pos[0]), int(drone_pos[1]))
            if not self.track or self.track[-1] != pos:
                self.track.append(pos)
            self.drone_pos = pos
            self._maybe_anchor_origin(pos)

        # --- mission ----------------------------------------------------
        if isinstance(mission, dict):
            self.mission.update(
                mission.get("phase", "idle"),
                float(mission.get("progress", 0) or 0),
                int(mission.get("total_cells", 0) or 0),
                int(mission.get("scanned_cells", 0) or 0),
            )
            if "origin" in mission and mission["origin"]:
                try:
                    o = mission["origin"]
                    lat0, lon0 = float(o[0]), float(o[1])
                    # reject the common (0,0) "no origin" sentinel
                    if abs(lat0) + abs(lon0) > 0.001:
                        self.mission.origin = (lat0, lon0)
                except Exception:
                    pass
            if "cell_size_m" in mission:
                try:
                    self.mission.cell_size_m = float(mission["cell_size_m"])
                except Exception:
                    pass

        # --- extension payloads -----------------------------------------
        if isinstance(extra.get("ai"), dict):
            self.ai.update_from(extra["ai"], source)
        comms = extra.get("comms")
        if isinstance(comms, dict):
            self._ingest_comms(comms, source)
        nav = extra.get("nav")
        if isinstance(nav, dict):
            if nav.get("gps_denied") is not None:
                self._explicit_denied = bool(nav["gps_denied"])
            for hint in nav.get("sources", []) or []:
                self._nav_hints.add(str(hint).lower())

        # --- hazards first (survivor priority needs them) ---------------
        new_hazards = self._merge_hazards(hazards_raw or [], source)
        new_survivors = self._merge_survivors(survivors_raw or [], source)
        self._merge_extra_detections(extra.get("detections"), source)

        # --- geo-tag -----------------------------------------------------
        self._geotag_all()

        # --- risk + priority ---------------------------------------------
        self._assess_hazards()
        for s in self.survivors:
            self._prioritize(s)

        # --- alerts for new records --------------------------------------
        for h in new_hazards:
            self._alert_for_hazard(h, source)
        for s in new_survivors:
            self._alert_for_survivor(s, source)

        # --- mission bookkeeping / coverage --------------------------------
        self.mission.survivors_found = len(self.survivors)
        self.mission.hazards_found = len(self.hazards)
        self._recompute_coverage()
        self._refresh_critical_count()

        self.mission_changed.emit()
        self.detections_changed.emit()

    def _maybe_anchor_origin(self, pos: tuple[int, int]) -> None:
        if self.mission.origin is not None:
            return
        lat, lon = self.telemetry.get("lat"), self.telemetry.get("lon")
        if lat is None or lon is None:
            return
        self.mission.origin = geo_utils.origin_from_anchor(
            float(lat), float(lon), pos[0], pos[1],
            self.mission.cell_size_m,
        )

    def _merge_survivors(self, raw: list, source: str) -> list[Survivor]:
        created: list[Survivor] = []
        by_id = {s.id: s for s in self.survivors}
        for i, item in enumerate(raw):
            if isinstance(item, Survivor):
                s = item
                sid = s.id
            else:
                try:
                    # id-less senders get a *stable* position-derived id so
                    # the same survivor is not re-created every packet
                    _gx, _gy = int(item.get("grid_x", 0)), int(item.get("grid_y", 0))
                    sid = str(item.get("id") or f"S@{_gx},{_gy}")
                except AttributeError:
                    continue
                s = Survivor(
                    id=sid,
                    grid_x=int(item.get("grid_x", 0)),
                    grid_y=int(item.get("grid_y", 0)),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                    timestamp=float(item.get("timestamp", time.time()) or time.time()),
                )
                s.lat = item.get("lat")
                s.lon = item.get("lon")
                s.rgb_confidence = item.get("rgb_conf", item.get("rgb_confidence"))
                s.thermal_confidence = item.get(
                    "thermal_conf", item.get("thermal_confidence"))
                bbox = item.get("bbox")
                if isinstance(bbox, (list, tuple)) and len(bbox) == 4 and \
                        (bbox[2] > bbox[0] or bbox[3] > bbox[1]):
                    s.bbox = list(bbox)
                s.source = item.get("source", source)
                if s.rgb_confidence is None and item.get("rgb") is not None:
                    s.rgb_confidence = 1.0 if item["rgb"] else 0.0
                if s.thermal_confidence is None and item.get("thermal") is not None:
                    s.thermal_confidence = 1.0 if item["thermal"] else 0.0
                s.recompute_fusion()

            existing = by_id.get(sid)
            if existing is None:
                self.survivors.append(s)
                by_id[sid] = s
                created.append(s)
            else:
                # dedupe / out-of-order handling
                if s.confidence > existing.confidence:
                    existing.confidence = s.confidence
                if s.timestamp >= existing.timestamp:
                    existing.timestamp = s.timestamp
                    if s.lat is not None:
                        existing.lat, existing.lon = s.lat, s.lon
                    if s.rgb_confidence is not None:
                        existing.rgb_confidence = s.rgb_confidence
                    if s.thermal_confidence is not None:
                        existing.thermal_confidence = s.thermal_confidence
                    if s.bbox:
                        existing.bbox = s.bbox
                    existing.recompute_fusion()
        return created

    def _merge_hazards(self, raw: list, source: str) -> list[Hazard]:
        created: list[Hazard] = []
        for i, item in enumerate(raw):
            if isinstance(item, Hazard):
                h = item
            else:
                try:
                    htype = coerce_hazard_type(item.get("type"))
                except AttributeError:
                    continue
                raw_sev = item.get("severity")
                h = Hazard(
                    type=htype,
                    grid_x=int(item.get("grid_x", 0)),
                    grid_y=int(item.get("grid_y", 0)),
                    severity=int(raw_sev) if isinstance(raw_sev, (int, float)) else 0,
                    timestamp=float(item.get("timestamp", time.time()) or time.time()),
                    # id-less hazards are keyed by type+position below
                    id=str(item.get("id") or ""),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                    lat=item.get("lat"),
                    lon=item.get("lon"),
                    source=item.get("source", source),
                )
                h.severity_level = Severity.from_raw(raw_sev) if raw_sev is not None \
                    else None
                status = item.get("status")
                if status:
                    h.status = str(status)

            key = h.id or f"{h.type.value}:{h.grid_x},{h.grid_y}"
            existing = next(
                (x for x in self.hazards
                 if (x.id and x.id == key) or
                 (not x.id and x.type is h.type and x.grid_x == h.grid_x
                  and x.grid_y == h.grid_y)),
                None,
            )
            if existing is None:
                if not h.id:
                    h.id = key
                self.hazards.append(h)
                created.append(h)
            else:
                if h.confidence > existing.confidence:
                    existing.confidence = h.confidence
                if h.timestamp >= existing.timestamp:
                    existing.timestamp = h.timestamp
                    if h.lat is not None:
                        existing.lat, existing.lon = h.lat, h.lon
                    if h.severity_level is not None:
                        existing.severity_level = h.severity_level
        return created

    def ingest_edge_detections(self, raw, source: str = "edge") -> None:
        """Local on-device detector output.

        Edge inference runs *downstream* of whichever frame source is
        authoritative, so results are merged directly instead of re-checking
        mode authority (which only distinguishes live vs sim).
        """
        if raw:
            self._merge_extra_detections(raw, source)

    def _merge_extra_detections(self, raw, source: str) -> None:
        if not raw:
            return
        by_id = {d.id: d for d in self.extra_detections}
        changed = False
        for i, item in enumerate(raw):
            try:
                did = str(item.get("id") or f"D{i + 1:02d}")
            except AttributeError:
                continue
            view = DetectionView(
                id=did,
                cls=str(item.get("class") or item.get("cls") or "UNKNOWN"),
                confidence=float(item.get("confidence", 0.0) or 0.0),
                timestamp=float(item.get("timestamp", time.time()) or time.time()),
                kind="detection",
                lat=item.get("lat"),
                lon=item.get("lon"),
                grid_x=int(item.get("grid_x", 0) or 0),
                grid_y=int(item.get("grid_y", 0) or 0),
                severity=Severity.from_raw(item.get("severity")),
                source=item.get("source", source),
                rgb_confidence=item.get("rgb_conf"),
                thermal_confidence=item.get("thermal_conf"),
                bbox=item.get("bbox"),
                status=str(item.get("status") or ""),
            )
            view.fused, view.fusion_mode = _fuse(view)
            if did in by_id:
                old = by_id[did]
                if view.timestamp >= old.timestamp:
                    idx = self.extra_detections.index(old)
                    self.extra_detections[idx] = view
                    by_id[did] = view
                    changed = True
            else:
                self.extra_detections.append(view)
                by_id[did] = view
                changed = True
        if changed:
            self.detections_changed.emit()

    # ------------------------------------------------------------------
    # ingestion — video
    # ------------------------------------------------------------------
    def ingest_frame(self, frame, source: str = "live", kind: str = "rgb") -> None:
        if frame is None or not self._accept("video", source):
            return
        key = "thermal" if kind == "thermal" else "video"
        self._rx(key, source)
        if kind == "thermal":
            self.thermal_linked = True
            self.sensors["thermal"].last_rx = time.monotonic()
            self.thermal_available.emit(frame)
        else:
            self.sensors["rgb"].last_rx = time.monotonic()
            self.frame_available.emit(frame)

    # ------------------------------------------------------------------
    # geo-tagging / risk / priority helpers
    # ------------------------------------------------------------------
    def _geotag_all(self) -> None:
        origin = self.mission.origin
        cell = self.mission.cell_size_m
        for s in self.survivors:
            if s.lat is None and origin is not None:
                s.lat, s.lon = geo_utils.grid_to_latlon(origin, cell,
                                                        s.grid_x, s.grid_y)
        for h in self.hazards:
            if h.lat is None and origin is not None:
                h.lat, h.lon = geo_utils.grid_to_latlon(origin, cell,
                                                        h.grid_x, h.grid_y)
        for d in self.extra_detections:
            if d.lat is None and origin is not None and (d.grid_x or d.grid_y):
                d.lat, d.lon = geo_utils.grid_to_latlon(origin, cell,
                                                        d.grid_x, d.grid_y)

    def _assess_hazards(self) -> None:
        for h in self.hazards:
            if h.severity_level is not None:
                continue    # backend-provided severity always wins
            nearest = None
            nd = float("inf")
            for s in self.survivors:
                d = ((s.grid_x - h.grid_x) ** 2 +
                     (s.grid_y - h.grid_y) ** 2) ** 0.5 * self.mission.cell_size_m
                if d < nd:
                    nd, nearest = d, s
            sev, reasons = assess_hazard_severity(
                h.type,
                h.confidence,
                survivor_near_m=nd if nearest is not None else None,
            )
            h.severity_level = sev
            h.risk_reasons = reasons
            h.severity = sev.rank + 1   # keep legacy int in sync

    def _prioritize(self, s: Survivor) -> None:
        result = assess_survivor_priority(
            s, self.hazards, self.drone_pos, self.mission.cell_size_m)
        changed = result.label != s.priority or result.score != s.priority_score
        s.priority = result.label
        s.priority_score = result.score
        s.priority_reasons = result.reasons
        if changed:
            for a in self.alerts:
                if a.entity_id == s.id and a.category == "survivor" \
                        and not a.acknowledged:
                    a.priority = AlertPriority.from_priority_text(s.priority)

    # ------------------------------------------------------------------
    # coverage (Step 5)
    # ------------------------------------------------------------------
    def _recompute_coverage(self) -> None:
        cov = self.mission.coverage
        cell = self.mission.cell_size_m
        total_cells = self.mission.total_grid_cells
        scanned = self.mission.scanned_cells

        # geometry-derived totals (KML area + origin) when available
        poly_area = 0.0
        if self.mission.area_polygon:
            poly_area = geo_utils.polygon_area_m2(self.mission.area_polygon)

        if total_cells > 0 and scanned >= 0:
            cov.pct = min(100.0, 100.0 * scanned / total_cells)
            cov.cells_total = total_cells
            cov.cells_scanned = scanned
            cov.method = "packet"
        elif self.grid is not None:
            cov.cells_total = int(self.grid.size)
            cov.cells_scanned = int((self.grid != 0).sum())
            if cov.cells_total:
                cov.pct = min(100.0, 100.0 * cov.cells_scanned / cov.cells_total)
                cov.method = "geometry"
        else:
            cov.method = "none"

        if poly_area > 0:
            cov.area_total_m2 = poly_area
        elif cov.cells_total:
            cov.area_total_m2 = cov.cells_total * cell * cell
        cov.area_searched_m2 = cov.area_total_m2 * cov.pct / 100.0

        # keep the legacy field in sync (status bar progress)
        self.mission.progress = cov.pct

    # ------------------------------------------------------------------
    # alerts (Step 9)
    # ------------------------------------------------------------------
    def raise_alert(self, *, title: str, priority, category: str, detail: str = "",
                    lat=None, lon=None, location_text: str = "",
                    confidence=None, key: str = "", entity_id: str = "",
                    source: str = "live") -> Alert:
        if isinstance(priority, int):
            priority = AlertPriority(priority)
        existing = None
        for a in reversed(self.alerts):
            if key and a.dedupe_key == key:
                existing = a
                break
        if existing is not None and not existing.acknowledged:
            existing.updated = time.time()
            existing.detail = detail or existing.detail
            if priority.value < existing.priority.value:
                existing.priority = priority
            self.alerts_changed.emit()
            return existing
        if existing is not None:
            # same event re-occurring after acknowledgement → new record
            key = f"{key}#{int(time.time())}"

        alert = Alert(
            title=title, priority=priority, category=category, detail=detail,
            lat=lat, lon=lon, location_text=location_text,
            confidence=confidence, source=source, entity_id=entity_id,
            dedupe_key=key or title,
        )
        self.alerts.append(alert)
        if len(self.alerts) > MAX_ALERTS:
            for i, a in enumerate(list(self.alerts)):
                if a.cleared:
                    del self.alerts[i]
                    break
            else:
                del self.alerts[0]
        self.alerts_changed.emit()
        self._refresh_critical_count()

        if self._link_ok is False and self._offline:
            self.sync.enqueue("alert", {
                "title": title, "priority": alert.priority.label,
                "category": category, "location": alert.location,
                "source": source, "entity_id": entity_id,
            })
        return alert

    def _alert_for_survivor(self, s: Survivor, source: str) -> None:
        self.raise_alert(
            title=f"SURVIVOR DETECTED {s.id}",
            priority=AlertPriority.from_priority_text(s.priority),
            category="survivor",
            detail=f"Confidence {s.confidence:.1%} · {s.fusion_mode} · "
                   f"{s.priority_reasons[-1] if s.priority_reasons else ''}".strip(),
            lat=s.lat, lon=s.lon, location_text=s.location_text,
            confidence=s.confidence, key=f"surv:{s.id}",
            entity_id=s.id, source=source,
        )

    def _alert_for_hazard(self, h: Hazard, source: str) -> None:
        sev = h.effective_severity
        if sev is Severity.LOW or sev is Severity.MEDIUM:
            return
        self.raise_alert(
            title=h.class_label,
            priority=AlertPriority.P1 if sev is Severity.CRITICAL
            else AlertPriority.P2,
            category="hazard",
            detail=f"{sev.label} · confidence "
                   f"{h.confidence:.0%}" if h.confidence else sev.label,
            lat=h.lat, lon=h.lon, location_text=h.location_text,
            confidence=h.confidence or None,
            key=f"haz:{h.id}", entity_id=h.id, source=source,
        )

    def acknowledge_alert(self, alert_id: str) -> None:
        for a in self.alerts:
            if a.id == alert_id:
                a.acknowledged = True
                if a.category == "hazard":
                    for h in self.hazards:
                        if h.id == a.entity_id:
                            h.status = "ACK"
                self.alerts_changed.emit()
                self.detections_changed.emit()
                break

    def acknowledge_all(self) -> None:
        changed = False
        for a in self.alerts:
            if not a.acknowledged:
                a.acknowledged = True
                changed = True
                if a.category == "hazard":
                    for h in self.hazards:
                        if h.id == a.entity_id:
                            h.status = "ACK"
        if changed:
            self.alerts_changed.emit()
            self.detections_changed.emit()

    def clear_alert(self, alert_id: str) -> None:
        for a in self.alerts:
            if a.id == alert_id:
                a.cleared = True
                self.alerts_changed.emit()
                self._refresh_critical_count()
                break

    @property
    def active_alerts(self) -> list[Alert]:
        return [a for a in self.alerts if not a.cleared]

    @property
    def unacknowledged(self) -> list[Alert]:
        return [a for a in self.active_alerts if not a.acknowledged]

    @property
    def critical_alert_count(self) -> int:
        return sum(1 for a in self.active_alerts
                   if a.priority is AlertPriority.P1 and not a.acknowledged)

    def _refresh_critical_count(self) -> None:
        self.mission.critical_alerts = self.critical_alert_count

    # ------------------------------------------------------------------
    # KML area (Step 5)
    # ------------------------------------------------------------------
    def set_area(self, kml: dict) -> None:
        polys = kml.get("polygons") or []
        if polys:
            # largest polygon by point count as the search boundary
            poly = max(polys, key=len)
            self.mission.area_polygon = poly
        elif kml.get("lines"):
            self.mission.area_polygon = list(kml["lines"][0])
        else:
            return
        self.mission.area_name = kml.get("name", "AREA")
        if self.mission.phase is MissionPhase.IDLE:
            self.mission.update("area_loaded", 0)
        # NOTE: the KML outline is *not* used as a geo origin — an area
        # centroid says nothing about the grid's (0,0).  Coordinates come
        # from the companion's mission origin, GPS_GLOBAL_ORIGIN or the
        # drone co-registration anchor; until one exists the UI shows
        # GEO: PENDING rather than a made-up position.
        self._recompute_coverage()
        self.mission_changed.emit()

    # ------------------------------------------------------------------
    # communication health (Step 11)
    # ------------------------------------------------------------------
    def _ingest_comms(self, data: dict, source: str) -> None:
        for name, value in data.items():
            link = self.comms.ensure(str(name).upper())
            if isinstance(value, dict):
                state = str(value.get("state", "unknown")).lower()
                link.detail = str(value.get("detail", ""))
            else:
                state = str(value).lower()
                link.detail = ""
            try:
                link.state = LinkState(state)
            except ValueError:
                link.state = LinkState.UNKNOWN
            link.last_rx = time.monotonic()

    def _link_from_age(self, subsystem: str, never_text: str = "awaiting data",
                       stale=TELEMETRY_STALE_S, lost=TELEMETRY_LOST_S) -> Link:
        age = self.age(subsystem)
        if age is None:
            # before the first packet the thread-level status decides how
            # this reads (e.g. "PORT IN USE" instead of a fake "LINK OK")
            detail = never_text
            state = LinkState.UNKNOWN
            if subsystem == "telemetry" and self._link_status is not None \
                    and not self._link_status[0]:
                detail = self._link_status[1]
                state = LinkState.DISCONNECTED
            return Link(name=subsystem, state=state, detail=detail,
                        last_rx=None)
        state = (LinkState.CONNECTED if age <= stale else
                 LinkState.DEGRADED if age <= lost else LinkState.DISCONNECTED)
        return Link(name=subsystem, state=state,
                    detail=f"last data {age:.1f} s ago", last_rx=None)

    def set_link_status(self, ok: bool, detail: str) -> None:
        """Thread-level MAVLink status (bind/heartbeat/silence detail)."""
        self._link_status = (bool(ok), str(detail))
        if not ok and self.age("telemetry") is None:
            self.comms.ensure("TELEMETRY").detail = str(detail)
            self.tick_slow.emit()   # reflect immediately in slow widgets

    def _update_comms(self) -> None:
        telemetry_link = self._link_from_age("telemetry")
        telemetry_link.name = "TELEMETRY"
        gs_link = self._link_from_age("map", stale=MAP_STALE_S, lost=MAP_LOST_S)
        gs_link.name = "GROUND STATION"

        # companion/sim-reported links (5G / Wi-Fi / Mesh): their reported
        # state wins until it goes stale (no packet ⇒ cannot claim health)
        now = time.monotonic()
        for link in list(self.comms.links.values()):
            if link.name in ("TELEMETRY", "GROUND STATION"):
                continue
            if link.last_rx is not None and now - link.last_rx > 15 and \
                    link.state in (LinkState.CONNECTED, LinkState.DEGRADED):
                link.state = LinkState.DISCONNECTED
                link.detail = f"stale {now - link.last_rx:.0f}s"

        links = {l.name: l for l in self.comms.links.values()}
        links["TELEMETRY"] = telemetry_link
        links["GROUND STATION"] = gs_link
        self.comms.links = links

        offline = (telemetry_link.state is LinkState.DISCONNECTED or
                   gs_link.state is LinkState.DISCONNECTED)
        self._link_ok = (telemetry_link.state is LinkState.CONNECTED and
                         gs_link.state is LinkState.CONNECTED)

        # flush queued records *before* reporting the transition so the
        # "link restored — SYNCED n RECORDS" message carries a real count
        if not offline and not self.sync.empty:
            n = self.sync.flush()
            self.comms.last_sync = time.time()
            self._last_sync_note = f"SYNCED {n} RECORDS"
        elif self.comms.last_sync is None:
            self.comms.last_sync = time.time()

        if offline != self._offline:
            self._offline = offline
            self._handle_offline_transition(offline)

        self.comms.storage_ok = self.sync.storage_ok
        self.comms.offline = offline

    def _autonomy_status_text(self) -> str:
        """Honest autonomy indicators: only claim what still has evidence,
        otherwise 'last known' / 'not reported'."""
        parts = []
        if self.ai.reported and self.ai.on_device and not self.ai.stale:
            parts.append("ON-DEVICE AI: ACTIVE")
        elif self.ai.reported:
            parts.append("ON-DEVICE AI: LAST KNOWN")
        else:
            parts.append("ON-DEVICE AI: NOT REPORTED")
        parts.append("LOCAL DATA STORAGE: "
                     + ("ACTIVE" if self.sync.storage_ok else "UNAVAILABLE"))
        if self.nav.reported:
            parts.append(f"NAVIGATION: {self.nav.label}")
        else:
            parts.append("NAVIGATION: LAST KNOWN")
        parts.append("ALERT QUEUE: ACTIVE" if self.sync.storage_ok
                     else "ALERT QUEUE: UNAVAILABLE")
        return " · ".join(parts)

    @property
    def autonomy_text(self) -> str:
        """Honest autonomy indicators for the offline banner / comms panel."""
        return self._autonomy_status_text()

    def _handle_offline_transition(self, offline: bool) -> None:
        if offline:
            telem = self.comms.links.get("TELEMETRY")
            gs = self.comms.links.get("GROUND STATION")
            down = [n for n, l in (("TELEMETRY", telem), ("GROUND STATION", gs))
                    if l is not None and l.state is LinkState.DISCONNECTED]
            self._comm_alert = self.raise_alert(
                title="COMMUNICATION LOST" if len(down) == 2
                else f"{down[0] if down else 'LINK'} LINK LOST",
                priority=AlertPriority.P1,
                category="comm",
                detail="Autonomous operation continues onboard. "
                       + self._autonomy_status_text(),
                key="comm:lost", source=self.telemetry_authority,
            )
        else:
            if self._comm_alert is not None:
                synced = self._last_sync_note or "records synced"
                self._comm_alert.detail = f"Link restored — {synced}"
                self._comm_alert.acknowledged = True
                self._comm_alert = None
            self.comms.last_sync = time.time()
            self.alerts_changed.emit()

    # ------------------------------------------------------------------
    # sensor health (Step 13)
    # ------------------------------------------------------------------
    def _update_sensors(self) -> None:
        def set_state(key, health, detail):
            s = self.sensors[key]
            s.health = health
            s.detail = detail

        # RGB — detail reflects the actual provenance, never a fixed label
        rgb_src = "sim" if self.video_authority == "sim" else "live"
        age = self.age("video")
        if age is None:
            set_state("rgb", Health.OFFLINE,
                      "no video signal" if self.mode == MODE_LIVE
                      else "no frames")
        elif age <= FRAME_STALE_S:
            set_state("rgb", Health.HEALTHY, f"{rgb_src} · {age:.1f}s")
        elif age <= FRAME_LOST_S:
            set_state("rgb", Health.DEGRADED, f"stale {age:.0f}s")
        else:
            set_state("rgb", Health.OFFLINE, f"lost {age:.0f}s")

        # Thermal
        if self.sensors["thermal"].last_rx is None:
            if self.mode == MODE_LIVE:
                set_state("thermal", Health.UNKNOWN, "no stream configured")
            else:
                set_state("thermal", Health.OFFLINE, "no frames")
        else:
            t_age = time.monotonic() - self.sensors["thermal"].last_rx
            if t_age <= 5:
                set_state("thermal", Health.HEALTHY, f"{rgb_src} · {t_age:.1f}s")
            else:
                set_state("thermal", Health.OFFLINE, f"lost {t_age:.0f}s")

        # IMU
        i_age = time.monotonic() - self.sensors["imu"].last_rx \
            if self.sensors["imu"].last_rx else None
        if i_age is None:
            set_state("imu", Health.UNKNOWN, "not reported")
        elif i_age <= 2:
            set_state("imu", Health.HEALTHY, f"ATTITUDE · {i_age:.1f}s")
        elif i_age <= 10:
            set_state("imu", Health.DEGRADED, f"stale {i_age:.0f}s")
        else:
            set_state("imu", Health.OFFLINE, f"lost {i_age:.0f}s")

        # GPS
        st = self.gps.state
        detail = f"{self.gps.fix_label} · {self.gps.age_text}"
        if st == "OK":
            set_state("gps", Health.HEALTHY, detail)
        elif st == "STALE":
            set_state("gps", Health.DEGRADED, detail)
        elif st == "LOST":
            set_state("gps", Health.OFFLINE, detail)
        else:
            set_state("gps", Health.UNKNOWN, "no GPS data")

        # LiDAR / optical flow — only healthy when actually reported
        for key, src in (("lidar", PositionSource.LIDAR),
                         ("flow", PositionSource.OPTICAL_FLOW)):
            hint = src.value in self._nav_hints
            if hint:
                set_state(key, Health.HEALTHY, "reported by nav stack")
            else:
                set_state(key, Health.UNKNOWN, "not reported")

        # Barometer (VFR_HUD altitude source)
        b_age = time.monotonic() - self.sensors["baro"].last_rx \
            if self.sensors["baro"].last_rx else None
        if b_age is None:
            set_state("baro", Health.UNKNOWN, "not reported")
        elif b_age <= 2:
            set_state("baro", Health.HEALTHY, f"VFR_HUD · {b_age:.1f}s")
        elif b_age <= 10:
            set_state("baro", Health.DEGRADED, f"stale {b_age:.0f}s")
        else:
            set_state("baro", Health.OFFLINE, f"lost {b_age:.0f}s")

        # Telemetry link
        link = self.comms.links.get("TELEMETRY")
        if link is None:
            set_state("telemetry", Health.UNKNOWN, "not connected")
        elif link.state is LinkState.CONNECTED:
            set_state("telemetry", Health.HEALTHY, link.detail)
        elif link.state is LinkState.DEGRADED:
            set_state("telemetry", Health.DEGRADED, link.detail)
        elif link.state is LinkState.DISCONNECTED:
            set_state("telemetry", Health.OFFLINE, link.detail)
        else:
            set_state("telemetry", Health.UNKNOWN, link.detail)

    # ------------------------------------------------------------------
    # health tick (1 Hz)
    # ------------------------------------------------------------------
    def _health_tick(self) -> None:
        # navigation state (also used for GPS-denied banner/alerts)
        explicit = self._explicit_denied
        hints = sorted(self._nav_hints)
        self.nav = derive_navigation(self.gps, self.ekf, hints, explicit)

        # GPS availability statistics for the situation report
        if self.gps.last_rx is None:
            self._gps_ticks["unknown"] += 1
        elif self.nav.gps_denied:
            self._gps_ticks["denied"] += 1
        else:
            self._gps_ticks["ok"] += 1

        # communication first: link state determines whether alerts raised
        # below are queued for synchronisation
        self._update_comms()

        # GPS lost / recovered transitions (only while telemetry is alive —
        # a link outage must never be displayed as GPS loss)
        telem_age = self.age("telemetry")
        telemetry_fresh = (telem_age is not None and
                           telem_age <= TELEMETRY_LOST_S)
        if self.nav.gps_denied and self.gps.last_rx is not None \
                and telemetry_fresh:
            if self._gps_alert is None:
                self._gps_alert = self.raise_alert(
                    title="GPS LOST — GPS-DENIED NAVIGATION ACTIVE",
                    priority=AlertPriority.P1,
                    category="gps",
                    detail=f"Position source: {self.nav.label} · "
                           f"{self.nav.reason}",
                    key="gps:lost", source=self.telemetry_authority,
                )
        elif self._gps_alert is not None and not self.nav.gps_denied:
            self._gps_alert.detail = "GPS fix restored — " + \
                (self.nav.label or "GPS active")
            self._gps_alert.acknowledged = True
            self._gps_alert = None
            self.alerts_changed.emit()

        # telemetry heartbeat alert
        age_t = self.age("telemetry")
        if age_t is not None and age_t > TELEMETRY_STALE_S:
            if self._telem_alert is None:
                self._telem_alert = self.raise_alert(
                    title="TELEMETRY STALE",
                    priority=AlertPriority.P2 if age_t < TELEMETRY_LOST_S
                    else AlertPriority.P1,
                    category="telemetry",
                    detail=f"No telemetry for {age_t:.1f} s",
                    key="telem:stale", source=self.telemetry_authority,
                )
            else:
                self._telem_alert.detail = f"No telemetry for {age_t:.1f} s"
        elif self._telem_alert is not None:
            self._telem_alert.acknowledged = True
            self._telem_alert = None
            self.alerts_changed.emit()

        # low battery
        bat = self.telemetry.get("battery")
        if isinstance(bat, (int, float)) and 0 <= bat < 20:
            if self._battery_alert is None:
                self._battery_alert = self.raise_alert(
                    title="LOW BATTERY",
                    priority=AlertPriority.P2,
                    category="battery",
                    detail=f"Battery {bat:.0f}% — plan recovery",
                    key="bat:low", source=self.telemetry_authority,
                )
        elif self._battery_alert is not None and \
                (not isinstance(bat, (int, float)) or bat >= 25):
            self._battery_alert.acknowledged = True
            self._battery_alert = None
            self.alerts_changed.emit()

        self._update_sensors()
        self._refresh_critical_count()
        self.tick_slow.emit()

    # ------------------------------------------------------------------
    # scenario / demo support
    # ------------------------------------------------------------------
    def reset_detections(self) -> None:
        """Fresh detection/alert state for a new demo scenario — keeps the
        loaded KML area and geo origin."""
        self.survivors.clear()
        self.hazards.clear()
        self.extra_detections.clear()
        self.alerts.clear()
        self.track.clear()
        self._gps_alert = self._comm_alert = self._telem_alert = None
        self._battery_alert = None
        self._gps_ticks = {"ok": 0, "denied": 0, "unknown": 0}
        self._explicit_denied = None
        self._nav_hints.clear()
        keep = (self.mission.area_name, self.mission.area_polygon,
                self.mission.origin, self.mission.cell_size_m)
        self.mission = MissionState()
        (self.mission.area_name, self.mission.area_polygon,
         self.mission.origin, self.mission.cell_size_m) = keep
        if self.mission.area_name:
            self.mission.update("area_loaded", 0)
        self.alerts_changed.emit()
        self.detections_changed.emit()
        self.mission_changed.emit()

    # ------------------------------------------------------------------
    # reporting / views
    # ------------------------------------------------------------------
    @property
    def gps_stats(self) -> tuple[float, float]:
        total = self._gps_ticks["ok"] + self._gps_ticks["denied"]
        if total <= 0:
            return 0.0, 0.0
        return (100.0 * self._gps_ticks["ok"] / total,
                100.0 * self._gps_ticks["denied"] / total)

    @property
    def communication_summary(self) -> str:
        if self.comms.offline:
            return "LOST"
        states = [l.state for n, l in self.comms.links.items()
                  if n in ("TELEMETRY", "GROUND STATION")]
        if LinkState.DEGRADED in states:
            return "INTERMITTENT"
        if all(s is LinkState.UNKNOWN for s in states) and states:
            return "UNKNOWN"
        return "CONNECTED" if states else "UNKNOWN"

    def ai_line(self) -> str:
        if not self.ai.reported:
            return "NOT REPORTED"
        dev = "ON-DEVICE" if self.ai.on_device else \
            ("OFFLOADED" if self.ai.on_device is False else "UNKNOWN")
        fps = AIInferenceStatus.fmt(self.ai.fps, digits=0)
        lat = AIInferenceStatus.fmt(self.ai.latency_ms, " ms")
        return f"{dev} · {self.ai.model or 'model N/A'} · {fps} fps · {lat}"

    def detection_views(self) -> list[DetectionView]:
        """All detections (survivors + hazards + raw) in one list."""
        views: list[DetectionView] = []
        for s in self.survivors:
            v = DetectionView(
                id=s.id, cls="SURVIVOR", confidence=s.confidence,
                timestamp=s.timestamp, kind="survivor",
                lat=s.lat, lon=s.lon, grid_x=s.grid_x, grid_y=s.grid_y,
                severity=s.severity, source=s.source,
                rgb_confidence=s.rgb_confidence,
                thermal_confidence=s.thermal_confidence,
                fused=s.fused_confidence, fusion_mode=s.fusion_mode,
                bbox=s.bbox, priority=s.priority,
                priority_reasons=s.priority_reasons, age_s=s.age_s,
            )
            views.append(v)
        for h in self.hazards:
            views.append(DetectionView(
                id=h.id, cls=h.class_label, confidence=h.confidence,
                timestamp=h.timestamp, kind="hazard",
                lat=h.lat, lon=h.lon, grid_x=h.grid_x, grid_y=h.grid_y,
                severity=h.effective_severity, source=h.source,
                fused=h.confidence, fusion_mode="NOT REPORTED",
                status=h.status, age_s=h.age_s,
            ))
        views.extend(self.extra_detections)
        views.sort(key=lambda v: v.timestamp, reverse=True)
        return views

    def class_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for v in self.detection_views():
            counts[v.cls] = counts.get(v.cls, 0) + 1
        return counts

    def camera_detections(self) -> list[dict]:
        """BBox overlays for the camera HUD — only real bboxes, never
        fabricated ones."""
        out = []
        for v in self.detection_views():
            if not v.bbox:
                continue
            x1, y1, x2, y2 = v.bbox
            if x2 <= x1 or y2 <= y1:
                continue
            out.append({
                "label": v.id if v.kind == "survivor" else v.cls,
                "confidence": v.confidence,
                "bbox": list(v.bbox),
                "color": (255, 88, 192) if v.kind == "survivor" else (60, 180, 255),
            })
        return out

    def build_report(self) -> SituationReport:
        ok, denied = self.gps_stats
        return build_report(
            mission_id=f"{self.mission.name} "
                       f"{'#01' if self.mission.started_at else ''}".strip(),
            coverage_text=self.mission.coverage.searched_text,
            coverage_pct=self.mission.coverage.pct_text,
            survivors=self.survivors,
            hazards=self.hazards,
            critical_alerts=self.critical_alert_count,
            alerts=self.active_alerts,
            gps_normal_pct=ok,
            gps_denied_pct=denied,
            communication=self.communication_summary,
            pending_records=self.sync.pending,
            ai_line=self.ai_line(),
            data_sources=self.data_source_text().replace("DATA SOURCE: ", ""),
        )


def _fuse(view: DetectionView) -> tuple[float, str]:
    return fused_confidence(view.rgb_confidence, view.thermal_confidence,
                            view.confidence)
