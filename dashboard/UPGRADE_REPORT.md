# Autonomous Disaster-Response GCS — Upgrade Report

**Scope of this report (13 points, as agreed):** what already existed, what was
missing, the files touched, the telemetry source map, how GPS-denied and
offline operation are represented, geo-tagging, rescue-priority logic, how to
run and demo the pipeline, what is hardware-dependent, and the verification /
honesty guarantees.

The dashboard is a **single PySide6 application** at `dashboard/gcs.py`. No
dependencies were added (the pinned environment is `pyside6`, `numpy`,
`opencv-python`, `pymavlink`, Python 3.13). Nothing was rebuilt: the existing
glass-cockpit navy/cyan theme (`dashboard/theme.py`), layout, branding, flight
controls and wire protocol were preserved and extended.

---

## 1. Existing features (audit — before any change)

| Subsystem | What already worked |
|---|---|
| Entry point | `dashboard/gcs.py` — `MissionPlannerGCS(QMainWindow)` builds header, status bar, camera, map, lists, controls, telemetry popup, fullscreen (double-click camera, ESC to exit). |
| Theme | `dashboard/theme.py` — colour constants + QSS helpers for the navy/cyan glass look. |
| Camera | `widgets/camera_feed.py` — RGB frame display with HUD/watermark, `update_frame`, `set_detections`. |
| Map | `widgets/map_canvas.py` — grid rendering, drone marker, hit-testing. |
| Detections | `widgets/survivor_list.py`, `widgets/hazard_panel.py` — record tables. |
| Status / controls | `widgets/status_bar.py`, `widgets/controls.py`, `widgets/header_bar.py`, `widgets/telemetry_popup.py`. |
| Threads | `threads/telemetry.py` (MAVLink), `threads/video_receiver.py`, `threads/map_receiver.py` (UDP). |
| Models / utils | mission, survivor, hazard models; protocol decoder. |
| Test | root `dashboard/test_telemetry.py` (kept untouched). |

## 2. Gaps that blocked the full judge-visible pipeline

1. No single source of truth — widgets read raw dicts and could disagree; no
   provenance, no staleness, no mode authority.
2. No on-device-AI status surface; no sensor-health or comms/link panel.
3. No unified RGB + thermal view or **fusion** with honest single-sensor labels.
4. No geo-tagging of detections (grid → lat/lon) and no KML area import.
5. Alerts existed only implicitly — no priority, acknowledgement, or queueing.
6. No explainable rescue priority (P1–P4) with reasons.
7. No offline/comm-loss semantics (what still works, what is stale, what is queued).
8. No situation report (JSON / CSV / print).
9. No repeatable demo scenarios or typed telemetry models.

## 3. Files added / changed

**New — state & engine**
- `state/store.py` — `DashboardStore`: the single ingestion point, mode
  authority, staleness, geo-tagging, risk, priority, alerts, comms/sensor
  health, coverage, situation report.
- `state/sim.py` — `SimulationEngine(QThread)` + 7 labelled scenarios + free
  search; emits telemetry / map / RGB / thermal tagged `source="sim"`.
- `state/__init__.py`.

**New — typed models** (`models/`): `telemetry.py`, `nav.py`, `detection.py`,
`alert.py`, `sensors.py`, `comms.py`, `ai.py`, `survivor.py`, `hazard.py`,
`mission.py` (extended).

**New — utilities** (`utils/`): `paths.py` (`DATA_DIR`, `EXPORT_DIR`),
`geo.py` (`latlon_to_grid`), `kml.py` (`load_kml`), `risk.py`, `priority.py`,
`report.py`, `protocol.py` (extended).

**New — widgets** (`widgets/`): `nav_panel.py`, `ai_panel.py`,
`thermal_feed.py`, `fusion_bar.py`, `comms_panel.py`, `sensor_panel.py`,
`alerts_panel.py`, `mission_panel.py`, `report_panel.py`.

**Upgraded — widgets**: `header_bar.py` (mode switch + data-source badge),
`status_bar.py` (VERT / TIME / GPS-lost / drone-ID badges),
`controls.py` (real command dispatch, tri-state link, PAUSE toggle, ABORT
confirm), `camera_feed.py`, `map_canvas.py` (track, KML polygon,
priority-coloured survivors, severity-filled hazards, tooltips, click routing),
`survivor_list.py`, `hazard_panel.py`, `telemetry_popup.py`, `mission_panel.py`.

**Upgraded — threads**: `telemetry.py` (configurable connection, typed
telemetry, command queue, `mode_command`), `ffmpeg_receiver.py`,
`map_receiver.py` (status signals, raw-dict pass-through).

**Entry / theme / tests**: `gcs.py` (full wiring), `theme.py` (extended),
`tests/smoke_test.py` (15 checks). Removed: `New_Dash/` (work consolidated
under git-tracked `dashboard/`).

## 4. Telemetry / data source map

Every value is ingested through `DashboardStore` and carries its origin.
Mode authority decides which source is *believed* per subsystem:

| Panel / value | Source | Authority rule |
|---|---|---|
| Header data-source badge, STATUS bar | `store.data_source_text()` | mode-driven |
| STATUS bar (mode, armed, battery, GPS, HDG, ALT, SPD, VERT, TIME) | `threads/telemetry.py` (MAVLink) / `state/sim.py` | LIVE & SITL = live; SIM = sim |
| NAV panel (fix, sats, HDOP, EKF, position sources) | MAVLink `GPS_RAW_INT` / `EKF_STATUS_REPORT` / `ATTITUDE` (+ simplified in sim) | same as telemetry |
| AI panel (state, model, FPS, latency, CPU/GPU) | companion `extra.ai` / sim | LIVE = live; else sim |
| Camera RGB + thermal, fusion bar | `FFmpegReceiverThread` (LIVE) / `state/sim.py` (SITL, SIM) | video authority |
| Map (grid, track, KML, coverage) | `MapReceiverThread` (UDP 5556) / sim | perception authority |
| Survivors / hazards, alerts, comms health, sensor health | store-derived | from the above |
| Situation report | `store.build_report()` | derived, always current |

Authority is enforced in one place (`store._accept` via `_authority_for`), so a
scribe cannot show simulated data in LIVE mode or real data in SIMULATION mode.

## 5. GPS-denied representation

- `models/nav.py::derive_navigation` distinguishes **GPS-denied** (fix lost
  while data is fresh) from **GPS stale** (no data) — a stale receiver is *not*
  reported as denied.
- Under denial the GPS source shows `STANDBY`/`UNKNOWN` (never `ACTIVE`), the
  banner reads `GPS-DENIED NAVIGATION: ACTIVE`, and the fallback sources
  (EKF/IMU/VO/optical-flow/LiDAR) are shown as active when the vehicle reports
  them. The denied reason is exclusive — it is never overwritten by
  "GPS 3D, 0.0 s ago".
- STATUS bar recolours to a red **GPS LOST** badge; the receiver truth stays in
  the telemetry tooltip and NAV panel.
- Scenario 2 (`GPS LOSS → DENIED`) exercises this; LIVE/SITL can reproduce it
  with ArduPilot `param set SIM_GPS_DISABLE 1/0`.

## 6. Offline / communication-loss representation

- Offline = **TELEMETRY** or **GROUND STATION** link DISCONNECTED, derived from
  age (telemetry `3 s`/`10 s`, ground station `5 s`/`15 s`).
- A red banner shows `COMMUNICATION LOST — AUTONOMOUS OPERATION` with the
  autonomy detail line (e.g. `ON-DEVICE AI: LAST KNOWN · LOCAL DATA STORAGE:
  ACTIVE · NAVIGATION: IMU · ALERT QUEUE: ACTIVE`).
- The COMMS tab shows LINK HEALTH (TELEMETRY / GROUND STATION / 5G / WIFI /
  MESH) and the **OFFLINE SYNC QUEUE**: queued alerts and a "buffered locally"
  note. The queue is flushed on reconnect with `Link restored — SYNCED n RECORDS`.
- Alerts raised while offline are queued, not lost. Scenario 5
  (`COMMUNICATION LOSS`) demonstrates loss → queue → resync.

## 7. Geo-tagging

- Grid cells are converted to lat/lon through a **single origin chain**:
  companion packet origin (rejecting the `(0,0)` sentinel) → MAVLink
  `GPS_GLOBAL_ORIGIN` → drone co-registration anchor. A KML centroid is *not*
  used (an outline says nothing about the grid origin); until an origin exists
  the UI shows `GEO: PENDING` rather than a fabricated position.
- `utils/geo.py::latlon_to_grid` maps lat/lon back to grid cell for the KML
  outline overlay and map hit-testing.
- Every survivor/hazard row shows Grid, Geo (lat/lon) and priority.
- `utils/kml.py::load_kml` reads a KML/KMZ outline; `store.set_area` stores it
  and recomputes coverage.

## 8. Rescue-priority logic (explainable P1–P4)

`utils/priority.py` is a transparent rule engine (not a black box). Score
components (max 100): survivor detected **40**, detector confidence **25**,
nearby hazard severity **0–15**, hazard-zone exposure **0–10**, accessibility
**0–10**. Bands: **≥78 P1 · ≥62 P2 · ≥46 P3 · else P4**. Each survivor keeps
the human-readable reasons that produced the score, shown in the AI tab detail
card and in the situation report. **A backend-provided hazard severity always
wins over the risk-model estimate**.

## 9. Situation report

`report_panel.py` + `utils/report.py::build_report` produce a live preview with
**JSON / CSV / print** export (default folder `~/SIH_Reports`). Every field is
derived from actual store state, so an unmeasured value appears as `N/A` /
`NOT REPORTED` in the export too. The preview force-refreshes when its tab is
opened.

## 10. How to run

```bash
# from the repository root
.venv/bin/python dashboard/gcs.py                 # LIVE (all real sources)
.venv/bin/python dashboard/gcs.py --mode sitl     # telemetry live, perception+video sim
.venv/bin/python dashboard/gcs.py --mode sim      # everything simulated (no hardware)

# if QGroundControl already holds UDP 14550:
.venv/bin/python dashboard/gcs.py --mode sitl --mavlink udpin:0.0.0.0:14551
```

Use the **LIVE / SITL / SIMULATION** switch in the header to change mode
(confirmation dialog; state is reset so sources never bleed across modes).

## 11. Demo script (what a judge should see)

Start in **`--mode sim`**, open the **MISSION** tab, pick a scenario and press
**RUN**, then **START MISSION**. Suggested order:

1. **FREE SEARCH** — continuous mixed feed; watch the map track, coverage and
   detections build up.
2. **NORMAL GPS** — NAV panel: GPS + EKF + IMU nominal.
3. **GPS LOSS → DENIED** — NAV banner flips to `GPS-DENIED NAVIGATION: ACTIVE`,
   status bar shows red `GPS LOST`, fallback sources activate, then recovery.
4. **THERMAL SURVIVOR** — fusion bar labels the detection `THERMAL ONLY` and
   states that no cross-sensor agreement is claimed.
5. **HAZARD DETECTION** — severity-filled hazard markers, risk model, alerts.
6. **COMMUNICATION LOSS** — red autonomy banner, links DISCONNECTED, sync queue
   fills, resync message on restore.
7. **MULTIPLE Detections** — several simultaneous survivors/hazards; P1–P4
   explainable prioritisation; the PRIORITY ALERTS panel and ACK/CLEAR.
8. **MISSION COMPLETE** — fast sweep to 100 % coverage.
9. Open **REPORT**, review, then **JSON / CSV / PRINT**.
10. Click a survivor in the list, on the map, or in the AI records to cross-highlight the fusion bar.

No-hardware path: everything above works in `--mode sim`.

## 12. Hardware-dependent leftovers (honest limitations)

- **LIVE video** expects an FFmpeg-readable stream (`tcp://drone.local:8554` by
  default) and the `ffmpeg` binary; without them the camera shows
  `NO VIDEO SIGNAL` and the sensor row shows the reason.
- **LIVE thermal** has no configured stream; it is reported as
  `NO STREAM CONFIGURED — UNAVAILABLE` (never invented).
- **Live perception uplink** expects the companion to send UDP map packets on
  port 5556; with no sender the map stays in its waiting state.
- **Vehicle commands** (START / PAUSE / RTH / ABORT) require a live MAVLink
  link; otherwise the feedback reads `NOT SENT — NO TELEMETRY LINK`.
- **GPS-denied in SITL/LIVE** depends on the autopilot (`SIM_GPS_DISABLE`);
  simulated `gps_denied` is intentionally ignored when telemetry authority is
  live.
- True coverage quality, obstacle avoidance and delivery actions depend on the
  vehicle/companion payload, not the GCS.

## 13. Verification & honesty guarantees

- `QT_QPA_PLATFORM=offscreen .venv/bin/python dashboard/tests/smoke_test.py`
  runs **15 checks**: imports, mode authority, simulated pipeline, map/coverage,
  geo-tagging, risk, alerts + acknowledgement, frames/sensor health, AI status,
  nav, report (text/JSON/CSV), GPS-denied vs stale derivation, headless widget
  rendering, and full-window wiring. Result: **SMOKE TEST PASSED**.
- `python -m compileall dashboard` compiles clean.
- **No fake data rule:** unreported values render `N/A` / `UNKNOWN` /
  `UNAVAILABLE` / `STALE` / `DEGRADED`; simulation data is labelled `SIM`;
  a hazard's single detector score is labelled `DETECTOR`, not `FUSED`.
- **Staleness:** frame thresholds `3 s`/`10 s`, map `5 s`/`15 s`; stale frames
  are overlaid rather than silently shown as live.
- Manual multi-mode run confirms clean thread lifecycles (telemetry/video start
  and stop on mode change; no orphaned threads on close).
