"""In-app simulation engine — the demo data source (Step 16).

Runs as a worker thread and produces the *same record shapes* as the live
sources (telemetry dicts, map tuples, RGB/thermal frames), always tagged
``source="sim"`` so the store's mode-authority rules can accept or ignore
it.  Nothing it produces is ever mixed into LIVE mode.

Seven scripted scenarios cover the full SIH demo story: normal GPS,
GPS loss → GPS-denied navigation → recovery, thermal-only survivor
detection, hazard detection, communication loss with queue/resync,
multiple simultaneous detections and mission completion.
"""

from __future__ import annotations

import math
import queue
import random
import time

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

from utils import geo as geo_utils

# -- configuration --------------------------------------------------------
ROWS, COLS = 24, 36
CELL_M = 15.0
ORIGIN = (19.245812, 73.124581)      # demo disaster area (Nashik region)
FRAME_W, FRAME_H = 640, 360
BAND_STEP = 4                        # lawnmower row spacing (cells)
SCAN_RADIUS = 2.2                    # cells marked surveyed near the drone

SCENARIOS: dict[int, tuple[str, str]] = {
    0: ("FREE SEARCH", "Continuous mixed demo"),
    1: ("NORMAL GPS", "Scenario 1 · GPS nominal navigation"),
    2: ("GPS LOSS → DENIED", "Scenario 2 · GPS-denied nav & recovery"),
    3: ("THERMAL SURVIVOR", "Scenario 3 · Thermal-only detection"),
    4: ("HAZARD DETECTION", "Scenario 4 · Fire / flood / electrical"),
    5: ("COMMUNICATION LOSS", "Scenario 5 · Offline queue & resync"),
    6: ("MULTIPLE Detections", "Scenario 6 · Simultaneous detections"),
    7: ("MISSION COMPLETE", "Scenario 7 · Fast sweep to 100%"),
}


class SimulationEngine(QThread):
    telemetry_signal = Signal(dict)
    # grid, survivors, drone_pos, hazards, mission, extra
    map_signal = Signal(object, list, tuple, list, dict, dict)
    frame_signal = Signal(object)       # RGB
    thermal_signal = Signal(object)     # thermal

    def __init__(self, parent=None):
        super().__init__(parent)
        self._commands: queue.Queue = queue.Queue()
        self._active = False
        self._running = True

        self._rng = random.Random(2026)
        self._np_rng = np.random.default_rng(2026)

        # scenario state
        self.scenario = 0
        self._t0 = time.monotonic()
        self._events: list[tuple[float, str, dict]] = []
        self._fired: set[int] = set()
        self._gps_window: tuple[float, float] | None = None
        self._silent_window: tuple[float, float] | None = None
        self._speed_mult = 1.0

        # flight state
        self._reset_flight()
        self._base_rgb, self._base_thermal = self._build_bases()
        self._structures = self._build_structures()

    # ------------------------------------------------------------------
    # control API (main thread → worker via queue)
    # ------------------------------------------------------------------
    def submit(self, name: str, **kw) -> None:
        self._commands.put((name, kw))

    def set_active(self, active: bool) -> None:
        self._active = bool(active)

    def stop(self) -> None:
        self._running = False
        self.wait(3000)

    # ------------------------------------------------------------------
    # state reset
    # ------------------------------------------------------------------
    def _reset_flight(self) -> None:
        self.grid = np.zeros((ROWS, COLS), dtype=np.uint8)
        self.visited: set[tuple[int, int]] = set()
        self.visited_order: list[tuple[int, int]] = []
        self.bands = list(range(0, ROWS, BAND_STEP)) + [ROWS - 1]
        self._waypoints = self._build_path()
        self._wp_i = 0
        self._x, self._y = float(self._waypoints[0][0]), float(self._waypoints[0][1])
        self._heading = 0.0
        self.armed = False
        self.paused = False
        self.phase = "idle"
        self.mode = "HOLD"
        self.battery = 87.0
        self.survivors: list[dict] = []
        self.hazards: list[dict] = []
        self._s_count = 0
        self._h_count = 0
        self._takeoff_t: float | None = None
        self._home_timer = 0.0

    def _build_path(self) -> list[tuple[int, int]]:
        pts: list[tuple[int, int]] = []
        for i, r in enumerate(self.bands):
            cols = range(COLS) if i % 2 == 0 else range(COLS - 1, -1, -1)
            for c in cols:
                pts.append((c, r))
        return pts

    # ------------------------------------------------------------------
    # scenarios
    # ------------------------------------------------------------------
    def start_scenario(self, n: int) -> None:
        n = max(0, min(7, n))
        self.scenario = n
        self._reset_flight()
        self._fired.clear()
        self._t0 = time.monotonic()
        self._gps_window = None
        self._silent_window = None
        self._speed_mult = 1.0

        ev: list[tuple[float, str, dict]] = []
        if n == 0:
            ev = [(14, "surv", {}), (26, "haz", {"type": "fire"}),
                  (44, "surv", {"thermal_only": True}),
                  (56, "haz", {"type": "debris"}),
                  (74, "surv", {}), (86, "haz", {"type": "flood"})]
        elif n == 1:
            ev = [(16, "surv", {}), (30, "haz", {"type": "fire"}),
                  (52, "surv", {"thermal_only": True})]
        elif n == 2:
            self._gps_window = (10.0, 34.0)
            ev = [(44, "surv", {}), (56, "haz", {"type": "debris"})]
        elif n == 3:
            ev = [(8, "surv", {"thermal_only": True}),
                  (20, "surv", {}),
                  (34, "surv", {"thermal_only": True})]
        elif n == 4:
            ev = [(6, "haz", {"type": "fire"}),
                  (14, "haz", {"type": "flood"}),
                  (20, "haz", {"type": "electrical", "severity": 4}),
                  (28, "haz", {"type": "debris"}),
                  (36, "haz", {"type": "landslide"})]
        elif n == 5:
            self._silent_window = (8.0, 28.0)
            ev = [(34, "surv", {}), (44, "haz", {"type": "fire"}),
                  (58, "surv", {"thermal_only": True})]
        elif n == 6:
            ev = [(8, "surv", {"thermal_only": True}),
                  (9, "surv", {}),
                  (10, "surv", {}),
                  (11, "haz", {"type": "fire"}),
                  (12, "haz", {"type": "electrical", "severity": 4}),
                  (13, "haz", {"type": "flood"}),
                  (14, "haz", {"type": "chemical"})]
        elif n == 7:
            self._speed_mult = 15.0
        self._events = sorted(ev, key=lambda e: e[0])
        self.start_mission()

    # -- mission commands --------------------------------------------------
    def start_mission(self) -> None:
        if self.armed and self.phase in ("searching", "takeoff"):
            return
        # fresh sortie
        keep_surv = list(self.survivors) if self.scenario == 0 else []
        keep_haz = list(self.hazards) if self.scenario == 0 else []
        self._reset_flight()
        self.survivors = keep_surv
        self.hazards = keep_haz
        self.armed = True
        self.paused = False
        self.phase = "takeoff"
        self.mode = "AUTO"
        self._takeoff_t = time.monotonic()

    def pause(self) -> None:
        if self.armed:
            self.paused = True
            self.mode = "HOLD"
            self.phase = "paused"

    def resume(self) -> None:
        if self.armed and self.paused:
            self.paused = False
            self.mode = "AUTO"
            self.phase = "searching"

    def abort(self) -> None:
        if self.armed:
            self.phase = "aborted"
            self.mode = "RTL"
            self.paused = False
            self._wp_i = 0      # head home
            self._home_timer = time.monotonic()

    def rth(self) -> None:
        if self.armed:
            self.phase = "returning"
            self.mode = "RTL"
            self.paused = False
            self._wp_i = 0
            self._home_timer = time.monotonic()

    # ------------------------------------------------------------------
    # main loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        last = time.monotonic()
        tel_acc = map_acc = frame_acc = 0.0

        while self._running:
            try:
                while not self._commands.empty():
                    name, kw = self._commands.get_nowait()
                    getattr(self, name)(**kw)
            except Exception:
                pass

            now = time.monotonic()
            dt = min(0.2, now - last)
            last = now
            active = self._active

            t = now - self._t0
            self._fire_events(t)
            if active:
                self._update_flight(dt, t)

            silent = self._is_silent(t)
            if active and not silent:
                tel_acc += dt
                map_acc += dt
                frame_acc += dt
                if tel_acc >= 0.1:
                    tel_acc = 0.0
                    self.telemetry_signal.emit(self._telemetry(t))
                if map_acc >= 0.5:
                    map_acc = 0.0
                    self.map_signal.emit(*self._map_payload(t))
                if frame_acc >= 1.0 / 12:
                    frame_acc = 0.0
                    self.frame_signal.emit(self._render_rgb(t))
                    self.thermal_signal.emit(self._render_thermal(t))

            time.sleep(0.02)

    # ------------------------------------------------------------------
    # scenario machinery
    # ------------------------------------------------------------------
    def _is_silent(self, t: float) -> bool:
        w = self._silent_window
        return bool(w and w[0] <= t < w[1])

    def _gps_denied_now(self, t: float) -> bool:
        w = self._gps_window
        return bool(w and w[0] <= t < w[1])

    def _fire_events(self, t: float) -> None:
        for i, (et, kind, kw) in enumerate(self._events):
            if i in self._fired or t < et:
                continue
            self._fired.add(i)
            try:
                if kind == "surv":
                    self._spawn_survivor(**kw)
                elif kind == "haz":
                    self._spawn_hazard(**kw)
            except Exception as exc:      # never kill the sim thread
                print(f"[sim] scenario event {kind!r} failed: {exc}")

    def _random_visited(self) -> tuple[int, int]:
        if not self.visited_order:
            return (self._rng.randrange(3, COLS - 3),
                    self._rng.randrange(3, ROWS - 3))
        # prefer recently surveyed cells (detections lag the scan a little)
        # but allow the whole surveyed area so a long sortie produces
        # spatially spread-out records rather than one cluster
        window = self.visited_order[-600:]
        return self._rng.choice(window)

    def _spawn_survivor(self, thermal_only: bool = False) -> dict:
        gx, gy = self._random_visited()
        self._s_count += 1
        sid = f"S{self._s_count:02d}"
        conf = round(self._rng.uniform(0.82, 0.97), 3)
        lat, lon = geo_utils.grid_to_latlon(ORIGIN, CELL_M, gx, gy)
        sx, sy = self._cell_px(gx, gy)
        rec = {
            "id": sid, "grid_x": gx, "grid_y": gy, "confidence": conf,
            "timestamp": time.time(), "lat": lat, "lon": lon,
            "source": "sim",
        }
        if thermal_only:
            rec["thermal_conf"] = round(self._rng.uniform(0.90, 0.98), 3)
            rec["rgb_conf"] = None
            rec["rgb_visible"] = False
        else:
            rec["rgb_conf"] = round(self._rng.uniform(0.78, 0.92), 3)
            rec["thermal_conf"] = round(self._rng.uniform(0.86, 0.97), 3)
            rec["rgb_visible"] = True
            rec["bbox"] = [sx - 14, sy - 14, sx + 14, sy + 14]
        self.survivors.append(rec)
        return rec

    def _spawn_hazard(self, htype: str | None = None,
                      severity: int | None = None,
                      **kwargs) -> dict:
        # accepts {"type": ...} (wire format) or htype=... (direct calls)
        kind = htype or str(kwargs.get("type", "fire"))
        gx, gy = self._random_visited()
        self._h_count += 1
        hid = f"H{self._h_count:02d}"
        conf = round(self._rng.uniform(0.74, 0.96), 3)
        lat, lon = geo_utils.grid_to_latlon(ORIGIN, CELL_M, gx, gy)
        sx, sy = self._cell_px(gx, gy)
        rec = {
            "id": hid, "type": kind, "grid_x": gx, "grid_y": gy,
            "confidence": conf, "timestamp": time.time(),
            "lat": lat, "lon": lon, "source": "sim",
            "severity": severity,        # None → rule-based risk model
            "bbox": [sx - 26, sy - 26, sx + 26, sy + 26],
            "rgb_visible": htype not in (),
        }
        # hazard cells are marked on the map (value 4)
        if 0 <= gy < ROWS and 0 <= gx < COLS:
            self.grid[gy, gx] = 4
        self.hazards.append(rec)
        return rec

    # ------------------------------------------------------------------
    # flight dynamics
    # ------------------------------------------------------------------
    def _update_flight(self, dt: float, t: float) -> None:
        if self.phase == "takeoff" and self._takeoff_t and \
                time.monotonic() - self._takeoff_t > 3:
            self.phase = "searching"
            self.mode = "AUTO"

        if self.paused:
            return

        speed_cells = (8.0 / CELL_M) * self._speed_mult * dt   # 8 m/s nominal

        if self.phase in ("returning", "aborted", "landing"):
            self._fly_home(speed_cells, dt)
            return

        if self.phase in ("complete", "idle", "aborted"):
            return

        # advance along the serpentine path
        remaining = speed_cells
        while remaining > 0 and self._wp_i < len(self._waypoints):
            wx, wy = self._waypoints[self._wp_i]
            dx, dy = wx - self._x, wy - self._y
            dist = math.hypot(dx, dy)
            if dist <= 1e-6:
                self._wp_i += 1
                continue
            step = min(remaining, dist)
            self._x += dx / dist * step
            self._y += dy / dist * step
            self._heading = math.degrees(math.atan2(dx, dy)) % 360
            remaining -= step
            if math.hypot(wx - self._x, wy - self._y) < 1e-3:
                self._wp_i += 1

        self._mark_visited()

        if len(self.visited) >= ROWS * COLS and self.phase == "searching":
            if self.scenario == 0:
                self.start_mission()        # FREE SEARCH: fresh sweep loop
            else:
                self.phase = "complete"
                self.mode = "HOLD"
                self.armed = False

        # battery drain (visual only)
        self.battery = max(5.0, self.battery - 0.012 * dt)

    def _fly_home(self, speed: float, dt: float) -> None:
        hx, hy = float(self._waypoints[0][0]), float(self._waypoints[0][1])
        dx, dy = hx - self._x, hy - self._y
        dist = math.hypot(dx, dy)
        if dist < 0.05:
            if self.phase == "returning":
                self.phase = "landing"
                self._home_timer = time.monotonic()
            elif self.phase == "landing":
                if time.monotonic() - self._home_timer > 2.5:
                    self.phase = "complete"
                    self.mode = "HOLD"
                    self.armed = False
            elif self.phase == "aborted":
                self.mode = "HOLD"
                self.armed = False
            return
        step = min(speed * 2.0, dist)
        self._x += dx / dist * step
        self._y += dy / dist * step
        self._heading = math.degrees(math.atan2(dx, dy)) % 360

    def _mark_visited(self) -> None:
        gx, gy = int(round(self._x)), int(round(self._y))
        r = int(SCAN_RADIUS) + 1
        for yy in range(max(0, gy - r), min(ROWS, gy + r + 1)):
            for xx in range(max(0, gx - r), min(COLS, gx + r + 1)):
                if (xx - self._x) ** 2 + (yy - self._y) ** 2 <= SCAN_RADIUS ** 2:
                    if (xx, yy) not in self.visited:
                        self.visited.add((xx, yy))
                        self.visited_order.append((xx, yy))
                        if self.grid[yy, xx] == 0:
                            self.grid[yy, xx] = 2   # surveyed corridor

    # ------------------------------------------------------------------
    # payloads
    # ------------------------------------------------------------------
    @property
    def coverage(self) -> float:
        return 100.0 * len(self.visited) / (ROWS * COLS)

    def _cell_px(self, gx: int, gy: int) -> tuple[int, int]:
        sx, sy = FRAME_W / COLS, FRAME_H / ROWS
        return int(gx * sx + sx / 2), int(gy * sy + sy / 2)

    def _telemetry(self, t: float) -> dict:
        denied = self._gps_denied_now(t)
        lat, lon = geo_utils.grid_to_latlon(ORIGIN, CELL_M, self._x, self._y)
        rel_alt = 42.6 if self.armed else 0.0
        speed = 0.0 if (self.paused or self.phase in ("complete", "idle")) else 8.0
        climb = 0.1 if (self.armed and speed > 0) else 0.0
        if self.phase == "takeoff":
            climb = 2.4
        nav_sources = ["imu", "ekf"]
        if denied:
            nav_sources += ["vo", "of", "lidar"]

        data: dict = {
            "mode": self.mode,
            "armed": self.armed,
            "system_status": 4 if self.armed else 3,
            "autopilot": "sim",
            "source": "sim",
            "battery": int(self.battery),
            "voltage": int((14.0 + 2.8 * self.battery / 100.0) * 1000),
            "current": 1850,
            "heading": int(self._heading) % 360,
            "groundspeed": speed,
            "climb": climb,
            "alt": 50.0 + rel_alt,
            "relative_alt": rel_alt,
            "lat": lat, "lon": lon,
            "roll": math.sin(time.time() * 0.7) * 1.5,
            "pitch": math.cos(time.time() * 0.5) * 1.2,
            "yaw": math.radians(self._heading),
            "x": self._x * CELL_M,
            "y": self._y * CELL_M,
            "z": -rel_alt,
            "vx": speed * math.sin(math.radians(self._heading)),
            "vy": speed * math.cos(math.radians(self._heading)),
            "vz": -climb,
            "ekf_reported": True,
            "ekf_flags": (15 if not denied else 12),   # pos-aid bits drop
            "ekf_horiz_acc": 0.8 if not denied else 4.6,
            "ekf_vel_err": 0.12 if not denied else 0.45,
            "nav_sources": nav_sources,
            "gps_denied": denied,
        }
        if denied:
            data.update({"gps_fix": 0, "gps_satellites": 0,
                         "gps_hdop": None, "gps_accuracy_m": None})
        else:
            data.update({
                "gps_fix": 4,
                "gps_satellites": 16 + int(self._rng.random() * 3),
                "gps_hdop": round(0.7 + self._rng.random() * 0.3, 1),
                "gps_accuracy_m": round(0.7 + self._rng.random() * 0.5, 2),
            })
        if self._wp_i:
            data["wp_seq"] = min(self._wp_i, 255)
        return data

    def _map_payload(self, t: float):
        phase = self.phase
        mission = {
            "phase": phase,
            "progress": round(self.coverage, 1),
            "total_cells": ROWS * COLS,
            "scanned_cells": len(self.visited),
            "origin": list(ORIGIN),
            "cell_size_m": CELL_M,
        }
        denied = self._gps_denied_now(t)
        w = self._silent_window
        comm_state = "connected"
        if w and w[0] - 5 <= t < w[0]:
            comm_state = "degraded"     # mesh degrades just before the outage
        extra = {
            "ai": {
                "on_device": True,
                "model": "YOLO26n (edge)",
                "fps": round(23.5 + self._rng.random() * 2.0, 1),
                "latency_ms": int(38 + self._rng.random() * 8),
                "cpu_pct": int(34 + self._rng.random() * 10),
                "gpu_pct": int(64 + self._rng.random() * 8),
                "ram_used_gb": 4.8,
                "ram_total_gb": 8.0,
                "cloud_dependency": "NONE",
            },
            "comms": {
                "5G": {"state": comm_state,
                       "detail": "n78 · 42 ms" if comm_state == "connected"
                       else "no signal"},
                "WIFI": {"state": comm_state,
                         "detail": "AP-1" if comm_state == "connected"
                         else "no signal"},
                "MESH": {"state": comm_state,
                         "detail": "4 hops" if comm_state == "connected"
                         else "no peers"},
            },
        }
        drone = (int(round(self._x)), int(round(self._y)))
        return (self.grid, list(self.survivors), drone,
                list(self.hazards), mission, extra)

    # ------------------------------------------------------------------
    # frame rendering (synthetic top-down disaster scene)
    # ------------------------------------------------------------------
    def _build_bases(self) -> tuple[np.ndarray, np.ndarray]:
        w, h = FRAME_W, FRAME_H
        # RGB ground: vertical gradient + static noise
        grad = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        rgb = np.zeros((h, w, 3), np.float32)
        rgb[..., 0] = 18 + grad * 14        # B
        rgb[..., 1] = 26 + grad * 18        # G
        rgb[..., 2] = 30 + grad * 20        # R
        noise = self._np_rng.normal(0, 5, (h, w, 1)).astype(np.float32)
        rgb += noise
        # roads every 6 cells
        sy = h // 6
        for y in range(sy, h, sy):
            rgb[max(0, y - 2):y + 2, :] += np.array([10, 12, 14], np.float32)
        base_rgb = np.clip(rgb, 0, 255).astype(np.uint8)

        # thermal base: cool ambient, structures slightly cooler
        th = np.full((h, w), 42, np.float32)
        th += self._np_rng.normal(0, 3, (h, w)).astype(np.float32)
        for y in range(sy, h, sy):
            th[max(0, y - 2):y + 2, :] += 6
        base_th = np.clip(th, 0, 255).astype(np.uint8)
        return base_rgb, base_th

    def _build_structures(self) -> list[tuple[int, int, int, int]]:
        """Deterministic building footprints (x, y, w, h) in pixels."""
        rng = random.Random(7)
        structs = []
        for _ in range(12):
            w = rng.randint(30, 90)
            hgt = rng.randint(24, 70)
            x = rng.randint(4, FRAME_W - w - 4)
            y = rng.randint(4, FRAME_H - hgt - 4)
            structs.append((x, y, w, hgt))
        return structs

    def _draw_structures(self, img: np.ndarray, thermal: bool) -> None:
        for (x, y, w, h) in self._structures:
            if thermal:
                cv2.rectangle(img, (x, y), (x + w, y + h), (30,), -1)
            else:
                cv2.rectangle(img, (x, y), (x + w, y + h), (44, 52, 66), -1)
                cv2.rectangle(img, (x, y), (x + w, y + h), (70, 82, 100), 1)

    def _render_rgb(self, t: float) -> np.ndarray:
        img = self._base_rgb.copy()
        self._draw_structures(img, thermal=False)
        sx, sy = FRAME_W / COLS, FRAME_H / ROWS

        for s in self.survivors:
            if not s.get("rgb_visible", True):
                continue                       # occluded — RGB cannot see it
            px, py = self._cell_px(s["grid_x"], s["grid_y"])
            cv2.circle(img, (px, py), 9, (198, 186, 168), -1)
            cv2.circle(img, (px, py), 9, (90, 82, 70), 1)

        for hz in self.hazards:
            px, py = self._cell_px(hz["grid_x"], hz["grid_y"])
            kind = hz["type"]
            if kind == "fire":
                flick = 0.75 + 0.25 * math.sin(t * 9 + hz["grid_x"])
                r = int(30 * flick)
                cv2.circle(img, (px, py), r, (30, 90, 230), -1)
                cv2.circle(img, (px, py), int(r * 0.6), (60, 170, 255), -1)
            elif kind == "flood":
                cv2.ellipse(img, (px, py), (46, 30), 0, 0, 360,
                            (120, 70, 30), -1)
            elif kind == "electrical":
                pts = np.array([[px - 22, py + 10], [px - 8, py - 12],
                                 [px + 4, py + 8], [px + 18, py - 10]],
                                np.int32)
                cv2.polylines(img, [pts], False, (40, 240, 255), 2)
            elif kind == "chemical":
                cv2.circle(img, (px, py), 26, (150, 90, 170), -1)
            else:  # debris / structural / landslide / smoke
                for i in range(5):
                    ox = int((i - 2) * 11)
                    cv2.rectangle(img, (px + ox - 5, py - 6),
                                  (px + ox + 5, py + 6), (70, 96, 130), -1)

        # mild live noise so the feed reads as a camera
        roi = img[0:40, 0:120]
        roi += self._np_rng.integers(0, 18, roi.shape, dtype=np.uint8)
        return img

    def _render_thermal(self, t: float) -> np.ndarray:
        img = self._base_thermal.copy()
        self._draw_structures(img, thermal=True)

        def hot(px, py, r, val):
            cv2.circle(img, (px, py), r + 6, int(val * 0.55), -1)
            cv2.circle(img, (px, py), r, val, -1)

        for s in self.survivors:
            px, py = self._cell_px(s["grid_x"], s["grid_y"])
            hot(px, py, 11, 250)

        for hz in self.hazards:
            px, py = self._cell_px(hz["grid_x"], hz["grid_y"])
            kind = hz["type"]
            if kind == "fire":
                flick = 0.8 + 0.2 * math.sin(t * 11 + hz["grid_y"])
                hot(px, py, int(34 * flick), 255)
            elif kind == "flood":
                cv2.ellipse(img, (px, py), (46, 30), 0, 0, 360, (16,), -1)
            elif kind == "chemical":
                hot(px, py, 24, 150)
            elif kind == "electrical":
                hot(px, py, 16, 175)
            # debris/landslide: thermally neutral — sensors disagree, honest

        blur = cv2.GaussianBlur(img, (9, 9), 0)
        img = cv2.addWeighted(img, 0.55, blur, 0.45, 0)
        return cv2.applyColorMap(img, cv2.COLORMAP_TURBO)
