# NIDAR AirMouse — Autonomous AI Drone for Disaster Response

> **Smart India Hackathon 2026 · Problem Statement ID 26177**
> *A deployable AI-powered autonomous drone that aids search-and-rescue operations by detecting people and hazards, thereby improving responder safety and reducing victim discovery time.*
> Organization: Qualcomm Inc · Category: Hardware · Theme: Robotics & Drones

NIDAR AirMouse is a two-part system: an **on-device AI perception stack** that turns RGB + thermal imagery into geo-tagged survivors and hazards, and a **ground-control dashboard** that fuses drone telemetry, AI detections, navigation health and communications into one live common operating picture for emergency responders.

The design goal is simple: **the drone keeps working when the network doesn't.** All inference happens on the aircraft (edge NPU), detections are geo-tagged locally, alerts are queued offline, and the operator dashboard never fabricates a value it doesn't actually have.

---

## Table of Contents

- [Solution Overview](#solution-overview)
- [System Architecture](#system-architecture)
- [Repository Layout](#repository-layout)
- [On-Device AI Perception (`sih_model/`)](#on-device-ai-perception-sih_model)
- [Ground Control Dashboard (`dashboard/`)](#ground-control-dashboard-dashboard)
- [Running the Project](#running-the-project)
- [End-to-End Demo Flow](#end-to-end-demo-flow)
- [Problem Statement → Implementation Mapping](#problem-statement--implementation-mapping)
- [Tech Stack](#tech-stack)
- [Hardware & Deployment Notes](#hardware--deployment-notes)
- [Testing](#testing)
- [Prior Art & References](#prior-art--references)
- [Team](#team)

---

## Solution Overview

| Capability | How it is delivered |
|---|---|
| Detects survivors | Person/survivor class from the on-device detector, geo-tagged and prioritised |
| Detects hazards | Fire, smoke, floodwater, structural damage, landslide, exposed wiring (extensible to debris / chemical) |
| Works without cloud | INT8/NCNN model runs on the Qualcomm NPU; no inference network dependency |
| Multi-sensor fusion | RGB + thermal confidence fusion with explicit single-sensor labelling |
| Navigation awareness | GPS + EKF/IMU/visual-odometry/optical-flow/LiDAR position-source view, GPS-denied fallback |
| Geo-tagged mapping | Grid ↔ WGS84 anchoring, KML search-area import, live survivor/hazard markers, coverage % |
| Prioritised alerting | Explainable P1–P4 rescue priority with human-readable reasons |
| Offline resilience | Link-health model, local store, queued alerts, automatic resync |
| Command centre | Real-time PySide6 dashboard (RGB, thermal, map, AI, nav, comms, report) |

---

## System Architecture

```
                         ┌────────────────────────── AIRCRAFT (edge) ──────────────────────────┐
                         │  RGB camera ─┐                                                       │
                         │  Thermal    ─┼─► Sensor fusion ─► On-device AI (YOLO26n → ONNX/NCNN  │
                         │  IMU / GPS  ─┘                        on Qualcomm NPU)                │
                         │                                        │                             │
                         │  ArduPilot / PX4  ◄── MAVLink ─────────┤  detections + frame meta     │
                         │  (autonomous nav, GPS / GPS-denied)    │  geo-tagged to WGS84         │
                         └────────────────────────────────────────┼─────────────────────────────┘
                                                                  │
                     ┌───────────── MAVLink telemetry ────────────┼──── perception uplink (UDP) ──┐
                     │                                            │                               │
                     ▼                                            ▼                               │
            ┌──────────────────────────────────────────────────────────────────────────────┐       │
            │                     NIDAR AirMouse GCS (PySide6 dashboard)                     │◄──────┘
            │  Status bar · Map · RGB+Thermal+Fusion · AI · Hazards · Alerts · Priority ·    │
            │  Nav (GPS/GPS-denied) · Comms/Offline · Mission · Situation Report             │
            └──────────────────────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
                                   Emergency response team
```

- **Telemetry** arrives over MAVLink (`pymavlink`) — live vehicle state, GPS/EKF, mode/arm status.
- **Perception** arrives as UDP packets from the companion computer (or the built-in simulation engine).
- **Everything flows through one store** (`dashboard/state/store.py`) which enforces data-source authority, staleness and provenance, so simulated, live and stale data can never be confused.

---

## Repository Layout

```
SIH/
├── dashboard/                  # Ground-control dashboard (PySide6)
│   ├── gcs.py                  # Main window / wiring
│   ├── theme.py                # Navy/cyan glass-cockpit theme
│   ├── models/                 # Typed data models (telemetry, nav, detection, alert, …)
│   ├── state/
│   │   ├── store.py            # Single source of truth (ingest, authority, staleness, risk, report)
│   │   └── sim.py              # 7 built-in demo scenarios + simulation engine
│   ├── threads/                # MAVLink, FFmpeg video, UDP map receivers
│   ├── utils/                  # geo, kml, protocol, risk, priority, report, paths
│   ├── widgets/                # All panels (nav, ai, fusion, thermal, comms, alerts, mission, report…)
│   ├── tests/smoke_test.py     # Headless 15-check pipeline test
│   └── UPGRADE_REPORT.md       # Deep-dive audit & implementation report
├── sih_model/                  # On-device AI: training + edge deployment notebooks
│   ├── training_nb/
│   │   ├── baseline_onnx_production/final_github_sih_nb.ipynb
│   │   └── best_performing_nb/peak_performance notebook.ipynb
│   └── qualcomm_edge_deployment/pipeline_qualcomm_verification.ipynb
├── pyproject.toml              # Python dependencies (uv)
└── README.md
```

---

## On-Device AI Perception (`sih_model/`)

The perception stack is a **YOLO26n** detector trained in two phases and exported for the Qualcomm NPU. Training runs are published as notebooks so the whole pipeline is reproducible.

### 7-Class Ontology

| ID | Class | Source dataset |
|----|-------|----------------|
| 0 | `person` | VisDrone (pedestrian/person) |
| 1 | `fire` | Smoke-Fire, FlameVision |
| 2 | `smoke` | Smoke-Fire |
| 3 | `floodwater` | RescueNet |
| 4 | `structural_damage` | FloodNet, SARD |
| 5 | `landslide` | Landslide dataset |
| 6 | `exposed_wire` | TTPLA (transmission-line wires) |

Annotations from every source are remapped into this single ontology; segmentation masks, COCO/JSON and pixel-index datasets are converted to YOLO format with a bounding-box sanity filter (minimum size, maximum area, coordinate clamping).

### Two-Phase Training (`training_nb/`)

1. **Phase 1 — head warm-up:** backbone frozen (`freeze=10`), AdamW, 15 epochs — adapts the detection head to the 7 classes quickly.
2. **Phase 2 — full fine-tune:** all layers unfrozen, lower LR, **multi-scale** input for robustness to varying drone altitude/distance, 40 epochs; mosaic enabled, copy-paste/mix-up disabled to avoid hallucinated boxes.
3. **Extract best weights** → `best.pt`.

### Edge Export & Qualcomm Deployment

- **ONNX export** with `simplify=True` at 640×640 (the dashboard's model input size).
- **NCNN conversion** for lightweight edge inference: `onnxsim` → `onnx2ncnn` → `ncnnoptimize`.
- **Qualcomm AI Hub** verification (`qai_hub`): model payload integrity, target-device compilation/verification on a Snapdragon device profile, and on-device inference validation — the deployment path that keeps inference local.

> The dashboard's AI panel surfaces exactly these facts: on-device state, model name, inference FPS, latency, CPU/GPU/RAM and cloud dependency — and shows `N/A` when the companion does not report them.

---

## Ground Control Dashboard (`dashboard/`)

A real-time PySide6 operator console. It is **not decorative** — every value is bound to a real source and carries its provenance.

### What the operator sees

- **Top status bar** — mode, armed, battery %, voltage, GPS fix/sats, heading, AGL altitude, ground speed, vertical speed, mission timer, drone ID.
- **Central map** — drone position + heading, flight-path track, KML search boundary, coverage %, survivor markers, severity-coded hazard markers, click-through to details.
- **RGB + Thermal feeds + Sensor Fusion bar** — per-sensor confidence, fused confidence (`1−(1−rgb)(1−thermal)`), and explicit `DUAL` / `RGB ONLY` / `THERMAL ONLY` labelling (no fake agreement).
- **NAV panel** — GPS fix/sats/HDOP/accuracy/age, EKF/INS state, and active position sources (GPS, EKF, IMU, Visual Odometry, Optical Flow, LiDAR, Visual SLAM) with a **GPS-DENIED NAVIGATION: ACTIVE** banner and fallback chain.
- **AI Perception panel** — on-device status, FPS/latency/CPU/GPU, per-class counters and individual detection records.
- **Hazard Intelligence** — type, effective severity, location, age, status.
- **Emergency Alerts** — prioritised (P1–P4), with location/severity, acknowledge/clear that never deletes the detection.
- **Rescue Priority** — explainable P1–P4 with the reasons that produced the score.
- **Comms / Sensors + Offline** — 5G / Wi-Fi / telemetry / mesh / ground-station link health, sync queue, and an **autonomous operation** banner when the link drops.
- **Mission panel** — phase checklist, coverage, survivor/hazard counts, KML area, scenario launcher.
- **Situation report** — auto-generated summary, exportable to JSON / CSV / print.

A detailed audit, feature matrix and source map live in [`dashboard/UPGRADE_REPORT.md`](dashboard/UPGRADE_REPORT.md).

### Data-source modes

The header switches the whole system between three modes, and authority is enforced in the store so sources never bleed into each other:

| Mode | Telemetry | Perception + video |
|------|-----------|--------------------|
| **LIVE** | real MAVLink | real (companion/FFmpeg) |
| **SITL** | real MAVLink (ArduPilot SITL) | simulated locally |
| **SIMULATION** | simulated | simulated |

Every panel is tagged `DATA SOURCE: LIVE` / `SIMULATION` / `TELEMETRY LIVE · PERCEPTION SIM`.

---

## Running the Project

### Prerequisites

- Python **3.13+**
- [`uv`](https://docs.astral.sh/uv/) (or plain `pip`)
- For live video: `ffmpeg`

### Install

```bash
uv sync                 # creates /.venv from pyproject.toml + uv.lock
# or: python -m venv .venv && .venv/bin/pip install -e .
```

### Run the dashboard

```bash
.venv/bin/python dashboard/gcs.py                 # LIVE (all real sources)
.venv/bin/python dashboard/gcs.py --mode sitl     # telemetry live, perception+video sim
.venv/bin/python dashboard/gcs.py --mode sim      # fully simulated (no hardware)
```

### Run against ArduPilot SITL

`sim_vehicle.py` needs MAVProxy; the SITL binary can be driven directly:

```bash
cd /path/to/ardupilot
./build/sitl/bin/arducopter -w \
  --defaults Tools/autotest/default_params/copter.parm \
  --model + --home 19.2458,73.1246,0,0 \
  --serial0 udpclient:127.0.0.1:14550 --speedup 1 -I0

# in another terminal
.venv/bin/python dashboard/gcs.py --mode sitl
```

If QGroundControl already holds UDP `14550`, run the dashboard on `--mavlink udpin:0.0.0.0:14551`.

### Run the AI training / deployment notebooks

Open the notebooks in `sih_model/` in Jupyter or Kaggle (they install `ultralytics`, `ncnn`, `qai_hub` themselves). A GPU is recommended for training; the Qualcomm AI Hub step requires an API token (see [Security](#security-note)).

---

## End-to-End Demo Flow

1. **Load KML disaster area** → search boundary drawn on the map.
2. **Start autonomous mission** → drone takes off, begins mapping.
3. **Live telemetry** flows into the status bar / NAV panel.
4. **RGB + thermal** feeds stream into the dashboard.
5. **Survivor detected** → automatically geo-tagged (grid → WGS84).
6. **Hazard detected** → classified and severity-scored.
7. **Risk / priority** generated (P1–P4) with reasons.
8. **Markers + alert** appear on the live map and alert panel.
9. **GPS loss** → dashboard flips to GPS-denied navigation with fallback sources.
10. **Network loss** → autonomous-operation banner, queued alerts, local storage.
11. **Link restored** → queued data syncs (`SYNCED n RECORDS`).
12. **Situation report** generated and exported.

The **MISSION tab scenario launcher** drives seven scripted scenarios for a repeatable, hardware-free demo:

| # | Scenario | Demonstrates |
|---|----------|--------------|
| 1 | Normal GPS | nominal navigation |
| 2 | GPS loss → denied | GPS-denied fallback & recovery |
| 3 | Thermal survivor | thermal-only detection (no RGB agreement claimed) |
| 4 | Hazard detection | fire / flood / electrical hazard intel |
| 5 | Communication loss | offline queue & resync |
| 6 | Multiple detections | simultaneous survivors + hazards, P1–P4 |
| 7 | Mission complete | fast sweep to 100 % coverage |

---

## Problem Statement → Implementation Mapping

| PSID 26177 requirement | Where it lives |
|---|---|
| Autonomous navigation (GPS + GPS-denied, SLAM/VO/optical flow/obstacle avoidance) | NAV panel + `models/nav.py` position-source & GPS-denied derivation; fallback sources reported only when the vehicle advertises them |
| On-device AI inference (people + hazards, no cloud) | `sih_model/` YOLO26n → ONNX/NCNN → Qualcomm NPU; AI panel shows on-device/FPS/latency/cloud-dependency |
| Multi-sensor fusion (RGB, thermal, IMU, GPS) | RGB/thermal feeds + fusion bar (`store.detection_views`), fusion labels; IMU/GPS in NAV & sensor health |
| Hazard classification | 7 hazard classes in the model; `models/hazard.py` + risk model; severity-coded markers |
| Geo-tagged mapping (survivors, hazards, safe routes) | `utils/geo.py` grid↔WGS84 anchoring, KML import, live map with markers & coverage |
| Emergency alerting + prioritised recommendations | `alerts_panel.py`, `utils/priority.py` explainable P1–P4, `utils/report.py` recommendations |
| Offline resilience (5G/Wi-Fi optional) | link-health model, autonomous-operation banner, local store + sync queue |
| Command-centre dashboard | the entire `dashboard/` application |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Flight control | ArduPilot / PX4 over MAVLink (SITL for simulation) |
| On-device AI | YOLO26n (Ultralytics) → ONNX → NCNN → Qualcomm AI Hub (Snapdragon NPU) |
| Dashboard | Python 3.13, PySide6 (Qt6), NumPy, OpenCV, pymavlink, pyserial |
| Video | FFmpeg (RTSP/TCP) → raw frames |
| Perception uplink | UDP (default port 5556) |
| Packaging | `uv` / `pyproject.toml` |

---

## Hardware & Deployment Notes

- **Aircraft:** multirotor with a companion computer; RGB + thermal cameras; GNSS + IMU (+ optional optical-flow / LiDAR).
- **Compute:** Snapdragon-class edge SoC executing the quantised detector via the Qualcomm NPU path.
- **Remaining hardware-dependent items:** live thermal stream wiring, companion perception uplink (UDP 5556), live video endpoint, and autopilot-side GPS-denied behaviour all depend on the physical stack. The dashboard reports `UNAVAILABLE` / `UNKNOWN` / `STALE` rather than inventing values when a source is absent.

---

## Testing

```bash
# headless pipeline test (no display, no hardware, no sockets)
QT_QPA_PLATFORM=offscreen .venv/bin/python dashboard/tests/smoke_test.py
```

Covers: mode authority, simulated pipeline, map/coverage, geo-tagging, risk,
alerts + acknowledgement, frames/sensor health, AI status, navigation,
situation report (text/JSON/CSV), GPS-denied vs stale derivation, headless
widget rendering and full-window wiring. Validated end-to-end against real
ArduPilot SITL (link, telemetry, arm/takeoff, mode commands, live GPS loss &
recovery).

---

## Prior Art & References

Past Smart India Hackathon projects and research that informed this design:

- **Hale — Autonomous Search & Rescue Drone** (SIH winner) — [alwinjoseph7/Project-Links](https://github.com/alwinjoseph7/Project-Links)
- **CodeRescue** (SIH 2020, AR disaster response) — [udbhav-chugh/Smart_India_Hackathon_CodeRescue](https://github.com/udbhav-chugh/Smart_India_Hackathon_CodeRescue)
- **Dronecharya** (SIH 2022, drone ambulance) — [manvi-singhal/Dronecharya](https://github.com/manvi-singhal/Dronecharya)
- **Team Aero Rescue, IIIT Nagpur** — winners, SIH 2025 Hardware Edition (PSID 25047, disaster-response drone)
- Research: *Drones4Good* (ICCVW 2023), *MedDrone Rescue* (ICMLAS 2025), *FlexiDrone* (ICAISS 2025)

---

## Security Note

Do **not** commit cloud credentials. The Qualcomm AI Hub token previously
hardcoded in `sih_model/qualcomm_edge_deployment/pipeline_qualcomm_verification.ipynb`
has been replaced with an environment-variable placeholder — set your own:

```bash
export QAI_HUB_API_TOKEN="<your-token>"
# notebook cell:  !qai-hub configure --api_token $QAI_HUB_API_TOKEN
```

Revoke/rotate any token that was ever committed.

---

## Team

Built for **Smart India Hackathon 2026**, Problem Statement ID **26177** (Qualcomm Inc · Hardware · Robotics & Drones).

---

> **Design principle:** the dashboard must never mislead — missing data shows as
> `N/A` / `UNKNOWN` / `UNAVAILABLE` / `STALE`, and simulated data is always
> labelled `SIMULATION`.
