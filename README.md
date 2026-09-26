# Autonomous AI Drone for Disaster Response

> **Smart India Hackathon 2026 · Problem Statement ID 26177**
> *A deployable AI-powered autonomous drone that aids search-and-rescue operations by detecting people and hazards, thereby improving responder safety and reducing victim discovery time.*
> Organization: Qualcomm Inc · Category: Hardware · Theme: Robotics & Drones

The system pairs an **on-device AI perception stack** (YOLO26n → ONNX → Qualcomm NPU) with a real-time **ground-control dashboard** for emergency responders. All inference happens on the aircraft, detections are geo-tagged locally, alerts are queued offline, and the operator console never fabricates a value it does not actually have.

---

## Key Highlights for Judges

| | |
|---|---|
| **Ultra-lightweight** | ~2.4 M parameters · 4.4 MB (FP16 PyTorch) · 9.3 MB (slimmed ONNX Opset 18) |
| **Real-time edge** | 1.7 ms inference · ~300+ FPS end-to-end latency ~3.3 ms on Qualcomm NPU / NVIDIA accelerators |
| **Peak detection** | **0.918 mAP** structural damage · **0.825** smoke · **0.795** exposed wires · **0.718** fire |
| **7-class ontology** | person · fire · smoke · floodwater · structural_damage · landslide · exposed_wire |
| **Edge platform** | Qualcomm Hexagon NPU via QAIRT / ONNX Runtime QNN EP — Dragonwing RB3 Gen 2 (QCS6490) & Snapdragon 8/X |

> The full, transparent 7-class performance matrix (including `person` = 0.426 mAP) is published in the dashboard **MODEL** tab and [below](#model-performance--benchmark-results).

---

## Table of Contents

- [Key Highlights for Judges](#key-highlights-for-judges)
- [Solution Overview](#solution-overview)
- [System Architecture](#system-architecture)
- [Repository & Notebook Mapping](#repository--notebook-mapping)
- [On-Device AI — Model, Data & Training](#on-device-ai--model-data--training)
  - [Master 7-Class Ontology](#master-7-class-ontology)
  - [Unified Disaster Detection Dataset](#unified-disaster-detection-dataset)
  - [Model Architecture](#model-architecture)
  - [Staged Training](#staged-training)
  - [Model Performance & Benchmark Results](#model-performance--benchmark-results)
  - [Qualcomm Edge Deployment](#qualcomm-edge-deployment)
- [Ground Control Dashboard](#ground-control-dashboard)
- [Running YOLO on the Dashboard](#running-yolo-on-the-dashboard)
- [Running the Project](#running-the-project)
- [Judges' Execution Guide](#judges-execution-guide)
- [End-to-End Demo Flow](#end-to-end-demo-flow)
- [Problem Statement → Implementation Mapping](#problem-statement--implementation-mapping)
- [Tech Stack](#tech-stack)
- [Hardware & Deployment Notes](#hardware--deployment-notes)
- [Testing](#testing)
- [Team](#team)

---

## Solution Overview

| Capability | How it is delivered |
|---|---|
| Detects survivors | `person` class, geo-tagged and prioritised |
| Detects hazards | fire, smoke, floodwater, structural damage, landslide, exposed wiring |
| Works without cloud | FP16 ONNX graph on the Qualcomm NPU — no inference network dependency |
| Multi-sensor fusion | RGB + thermal confidence fusion with explicit single-sensor labelling |
| Navigation awareness | GPS + EKF/IMU/visual-odometry/optical-flow/LiDAR position sources, GPS-denied fallback |
| Geo-tagged mapping | Grid ↔ WGS84 anchoring, KML import, live survivor/hazard markers, coverage % |
| Prioritised alerting | Explainable P1–P4 rescue priority with human-readable reasons |
| Offline resilience | Link-health model, local store, queued alerts, automatic resync |
| Command centre | Real-time PySide6 dashboard with **NAV · AI · MODEL · MISSION · COMMS · REPORT** tabs |

---

## System Architecture

```
                         ┌────────────────────────── AIRCRAFT (edge) ──────────────────────────┐
                         │  RGB camera ─┐                                                       │
                         │  Thermal    ─┼─► Sensor fusion ─► YOLO26n → ONNX Opset 18             │
                         │  IMU / GPS  ─┘                      (Qualcomm Hexagon NPU)            │
                         │                                        │                             │
                         │  ArduPilot / PX4  ◄── MAVLink ─────────┤  detections + frame meta     │
                         │  (autonomous nav, GPS / GPS-denied)    │  geo-tagged to WGS84         │
                         └────────────────────────────────────────┼─────────────────────────────┘
                                                                  │
                     ┌───────────── MAVLink telemetry ────────────┼──── perception uplink (UDP) ──┐
                     │                                            │                               │
                     ▼                                            ▼                               │
            ┌──────────────────────────────────────────────────────────────────────────────┐       │
            │                  Disaster-Response GCS (PySide6 dashboard)                    │◄──────┘
            │  NAV · AI · MODEL · MISSION · COMMS · REPORT tabs + live map & alerts          │
            └──────────────────────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
                                   Emergency response team
```

- **Telemetry** over MAVLink (`pymavlink`) — vehicle state, GPS/EKF, mode/arm.
- **Perception** over UDP from the companion computer, or the built-in simulation engine.
- **On-device inference** can also run directly on the GCS host (`sih_model/inference.py`) for demos — see [Running YOLO on the Dashboard](#running-yolo-on-the-dashboard).
- **One store** (`dashboard/state/store.py`) enforces data-source authority, staleness and provenance, so simulated, live and stale data can never be confused.

---

## Repository & Notebook Mapping

The codebase is organised under `sih_model/`, separated into peak-model benchmarking, production ONNX graph export, and Qualcomm AI Hub edge-NPU validation:

```
SIH/
├── dashboard/                              # Ground-control dashboard (PySide6)
│   ├── gcs.py                              # Main window / wiring
│   ├── theme.py                            # Navy/cyan glass-cockpit theme
│   ├── models/                             # Typed models (telemetry, nav, detection, alert, …)
│   ├── state/{store.py,sim.py}             # Single source of truth + 7 demo scenarios
│   ├── threads/                            # MAVLink, FFmpeg video, UDP map, YOLO inference
│   ├── utils/                              # geo, kml, protocol, risk, priority, report, paths
│   ├── widgets/                            # NAV / AI / MODEL / MISSION / COMMS / REPORT panels
│   ├── tests/smoke_test.py                 # Headless 16-check pipeline test
│   └── UPGRADE_REPORT.md                   # Deep-dive audit & implementation report
├── sih_model/
│   ├── inference.py                        # ★ SIHInferenceEngine (ONNX primary / Ultralytics fallback)
│   ├── requirements.txt                    # onnxruntime + deps (ultralytics optional)
│   ├── models/                             # best.onnx (9.3 MB) · best.pt (4.4 MB)
│   ├── training_nb/
│   │   ├── best_performing_nb/
│   │   │   └── peak_performance notebook.ipynb   # [PEAK BENCHMARK] multi-dataset augmented training (v4-full-best.pt)
│   │   └── baseline_onnx_production/
│   │       └── final_github_sih_nb.ipynb         # [PRODUCTION ONNX] normalisation, dual-phase training & ONNX export
│   └── qualcomm_edge_deployment/
│       └── pipeline_qualcomm_verification.ipynb  # [QUALCOMM NPU TELEMETRY] cloud verification & Hexagon NPU binding
├── pyproject.toml
└── README.md
```

---

## On-Device AI — Model, Data & Training

### Master 7-Class Ontology

The detector's output head is hard-bound to these indices; the dashboard label map, `sih_model/inference.py` and this README are synchronised to this ontology:

| ID | Label | Category / Description |
|----|-------|------------------------|
| 0 | `person` | Human search & rescue (SAR) target |
| 1 | `fire` | Structural / wildfire emergency |
| 2 | `smoke` | Early fire indicator |
| 3 | `floodwater` | Natural disaster inundation |
| 4 | `structural_damage` | Infrastructure collapse / damage |
| 5 | `landslide` | Terrain & geological hazard |
| 6 | `exposed_wire` | Electrical hazard / utility infrastructure |

### Unified Disaster Detection Dataset

A custom 7-class detection benchmark harmonised from **eight** public Kaggle/Roboflow datasets across **five** incompatible annotation formats (YOLO txt, VisDrone 10-column txt, Pascal VOC XML, COCO JSON, indexed-palette PNG masks) into one shared label space.

> COCO 2017 was retained **only** for pre-trained backbone initialisation (`yolo26n.pt`) and never entered the fine-tuning or evaluation splits.

Source → class conversion (mask/XML/JSON → YOLO xywh with a validation gate):

| Source dataset | Native format | Mapped to |
|---|---|---|
| VisDrone2019-DET | 10-column txt | `person` |
| Smoke-Fire-Detection-YOLO | YOLO txt | `smoke`, `fire` |
| FlameVision | Pascal VOC XML | `fire` |
| TTPLA (transmission lines) | COCO-style JSON | `exposed_wire` |
| FloodNet Challenge | binary PNG masks | `floodwater` |
| RescueNet | indexed-palette PNG | `structural_damage` |
| SARD | YOLO txt | `structural_damage` |
| Landslide Image Dataset | YOLO txt | `landslide` |

**Split:** 80/20 stratified (seed 42) — **20,996 train / 5,228 val images · 146,899 train / 37,612 val boxes.**

| ID | Class | Train boxes | Val boxes | Dominant modality |
|----|-------|------------:|----------:|-------------------|
| 0 | person | 117,378 | 30,366 | Aerial drone / SAR density |
| 1 | fire | 11,789 | 2,896 | RGB & thermal flame |
| 2 | smoke | 9,489 | 2,363 | Wildfire & industrial plumes |
| 3 | floodwater | 1,560 | 400 | Post-flood water segmentation |
| 4 | structural_damage | 5,973 | 1,451 | Post-disaster building damage |
| 5 | landslide | 175 | 37 | Mountainous terrain slips |
| 6 | exposed_wire | 535 | 99 | Utility grid downed lines |
| | **Total** | **146,899** | **37,612** | Unified multi-modal benchmark |

**Data-normalisation gate:** coordinates clamped to `[0.0001, 0.9999]`; boxes smaller than 1.25 % of the image or larger than 90 % of the area removed; duplicate/outlier cleanup via per-dataset class maps; a pre-training audit hard-aborts if any class has zero ground-truth instances.

### Model Architecture

`YOLOv26 Nano (YOLO26n)` — anchorless dual-head detector optimised for real-time edge compilation.

```
Input  (1, 3, 640, 640) BCHW
 ├── Backbone : Conv → C3k2 → SPPF → C2PSA
 ├── Neck     : FPN + PAN
 └── Head     : Anchorless dual-head (box regression + 7-class logits)
Output (1, 11, 8400)  =  4 box coords + 7 class probabilities
```

| Metric | Value |
|---|---|
| Network layers | 260 (120 when fused for inference) |
| Total parameters | 2,506,530 (~2.51 M; 2.38 M fused) |
| Compute | 5.9 GFLOPs (5.3 GFLOPs fused @ 640×640) |
| PyTorch FP16 size | 4.4 MB (`v4-full-best.pt`) |
| ONNX Opset 18 size | 9.3 MB (`best.onnx`, slimmed via `onnxslim`) |
| Target engine | Qualcomm Hexagon Vector & Tensor NPU / ONNX Runtime |

### Staged Training

Two-phase transfer learning to preserve COCO pre-trained features while adapting to the 7-class ontology:

- **Phase 1 — head warm-up:** 15 epochs, first 10 backbone layers frozen (`freeze=10`), AdamW `lr0=0.001`, `lrf=0.01`, batch 16.
- **Phase 2 — multi-scale fine-tune:** 40 epochs, fully unfrozen, AdamW `lr0=0.0001`, warmup 3.0, `multi_scale=True` `scale=0.5` (altitude robustness), mosaic 1.0, `close_mosaic=10`; completed in **5.61 h on an NVIDIA Tesla T4**.

### Model Performance & Benchmark Results

**Peak augmented benchmark (`v4-full-best.pt`)** — macro hazards lead the summary; the full matrix is published transparently:

| Class | mAP | Operational SAR impact |
|-------|----:|------------------------|
| 🏗️ structural_damage | **0.918** | Post-earthquake structural safety mapping |
| 💨 smoke | **0.825** | Early aerial wildfire-origin detection |
| ⚡ exposed_wire | **0.795** | Electrocution prevention for ground teams |
| 🔥 fire | **0.718** | Active flame tracking (RGB + thermal) |
| 🌊 floodwater | 0.620 | Flood contour / inundation extraction |
| ⛰️ landslide | 0.530 | Soil slips, blocked mountain routes |
| 👤 person | 0.426 | Survivor detection under aerial viewing angles |

> **Domain-contextualised transparency:** at high altitude, human targets suffer extreme small-object resolution limits (<16×16 px per box) versus macro hazard classes. Strong hazard mAPs (>0.70–0.90+) are highlighted; the full 7-class matrix ships in the MODEL tab. **Roadmap:** SAHI (Slicing Aided Hyper Inference) + patch-attention heads for sub-30 px human targets at high flight altitudes.

**Edge latency (per image):**

| Stage | Latency |
|---|---|
| Pre-processing | 0.2 ms |
| NPU / GPU inference | 1.7 ms |
| Post-processing (NMS) | 1.4 ms |
| **End-to-end** | **~3.3 ms · ~300+ FPS** (NVIDIA Tesla T4 / Qualcomm NPU) |

### Qualcomm Edge Deployment

> **Target platform:** Qualcomm® Hexagon™ NPU via Qualcomm AI Engine Direct (**QAIRT**) / ONNX Runtime **QNN EP** on Dragonwing™ RB3 Gen 2 (QCS6490) & Snapdragon® 8/X Series.

The deployment notebook performs a 4-stage cloud verification: authenticate → SHA-256 payload/opset validation → upload → compile IR graph for the Hexagon tensor architecture → return a verification/asset report.

---

## Ground Control Dashboard

A real-time PySide6 operator console — every value is bound to a real source and carries its provenance. Six tabs keep flight ops and AI diagnostics separate:

- **NAV** — GPS fix/sats/HDOP/accuracy/age, EKF/INS, position sources (GPS, EKF, IMU, Visual Odometry, Optical Flow, LiDAR, Visual SLAM) and the **GPS-DENIED NAVIGATION: ACTIVE** fallback banner.
- **AI** *(operational)* — companion on-device AI status + **LOCAL EDGE INFERENCE** (backend, FPS, latency), detector counters, individual detection records, and the explainable fusion/priority detail card.
- **MODEL** *(analytical)* — architecture specs, the full 7-class mAP matrix, latency table, training hyperparameters, unified-dataset benchmark and target platform.
- **MISSION** — phase checklist, coverage, survivor/hazard counts, KML area, scenario launcher.
- **COMMS** — 5G / Wi-Fi / telemetry / mesh / ground-station link health, sync queue, and sensor health.
- **REPORT** — auto-generated situation report, exportable to JSON / CSV / print.

Plus the always-visible **status bar** (mode, armed, battery, GPS, HDG, ALT, SPD, VERT, mission timer, drone ID), the **central map** (drone + track, KML boundary, coverage %, survivor/hazard markers), and the **RGB + thermal feeds with the sensor-fusion bar**.

### Data-source modes

| Mode | Telemetry | Perception + video |
|------|-----------|--------------------|
| **LIVE** | real MAVLink | real (companion/FFmpeg) |
| **SITL** | real MAVLink (ArduPilot SITL) | simulated locally |
| **SIMULATION** | simulated | simulated |

Every panel is tagged `DATA SOURCE: LIVE` / `SIMULATION` / `TELEMETRY LIVE · PERCEPTION SIM`.

---

## Running YOLO on the Dashboard

The dashboard runs the trained model locally and overlays detections on the live feed:

```bash
# auto-detect: uses sih_model/models/best.onnx by default
.venv/bin/python dashboard/gcs.py --mode sim --demo

# explicit model + confidence
.venv/bin/python dashboard/gcs.py --mode sim --model sih_model/models/best.onnx --conf 0.25

# no camera? loop a sample video through inference
.venv/bin/python dashboard/gcs.py --mode sitl --demo-video /path/sample_aerial.mp4
```

- **Onnxruntime** is the primary backend (lightweight edge path); **ultralytics** (PyTorch `.pt`) is an optional fallback.
- Inference runs in a dedicated thread with a single-slot frame queue (drops stale frames, never blocks the UI) at a target ~8 FPS.
- Results appear as **bounding boxes on the RGB feed**, **records + counters in the AI tab**, and flow into alerts/priority/report.
- If the model file is missing, the AI/MODEL tabs report `EDGE AI UNAVAILABLE · model not found` — never a fabricated detection.

Quick standalone check (3-line judge test):

```python
from ultralytics import YOLO
model = YOLO("sih_model/models/best.onnx")          # or best.pt
results = model.predict(source="test_drone_image.jpg", imgsz=640, conf=0.25)
results[0].show()
```

---

## Running the Project

### Prerequisites
- Python **3.13+**, [`uv`](https://docs.astral.sh/uv/) (or pip), `ffmpeg` for live video.

### Install
```bash
uv sync                 # installs dashboard + onnxruntime from pyproject.toml/uv.lock
# optional PyTorch fallback:
uv pip install ultralytics
```

### Run
```bash
.venv/bin/python dashboard/gcs.py                 # LIVE
.venv/bin/python dashboard/gcs.py --mode sitl     # telemetry live, perception+video sim
.venv/bin/python dashboard/gcs.py --mode sim --demo
```

### Against ArduPilot SITL
```bash
cd /path/to/ardupilot
./build/sitl/bin/arducopter -w \
  --defaults Tools/autotest/default_params/copter.parm \
  --model + --home 19.2458,73.1246,0,0 \
  --serial0 udpclient:127.0.0.1:14550 --speedup 1 -I0
# another terminal
.venv/bin/python dashboard/gcs.py --mode sitl
```
If QGroundControl holds UDP `14550`, use `--mavlink udpin:0.0.0.0:14551`. Verified end-to-end: link, telemetry, arm + GUIDED takeoff, mode commands (AUTO/LOITER/RTL), live GPS loss + recovery.

---

## Judges' Execution Guide

**1 — Environment**
```bash
python -m venv venv && source venv/bin/activate     # Windows: .\venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install onnxruntime numpy opencv-python pillow pyyaml
pip install ultralytics          # optional .pt fallback
pip install jupyter               # to open the notebooks
```

**2 — Notebooks**

| Option | Notebook | Purpose |
|---|---|---|
| A | `sih_model/training_nb/best_performing_nb/peak_performance notebook.ipynb` | Evaluate / re-train the peak model (0.918 mAP structural damage, 0.825 smoke) |
| B | `sih_model/training_nb/baseline_onnx_production/final_github_sih_nb.ipynb` | Production ONNX pipeline — run Cells 6 & 7 to export `best.pt` → `best.onnx` (Opset 18, ~9.3 MB) |
| C | `sih_model/qualcomm_edge_deployment/pipeline_qualcomm_verification.ipynb` | Qualcomm AI Hub cloud verification & Hexagon NPU binding |

For Option C, set your token via an environment variable:
```bash
export QAI_HUB_API_TOKEN="<your-token>"
```

**3 — Quick inference**
```python
from ultralytics import YOLO
model = YOLO("best.onnx")
results = model.predict(source="test_drone_image.jpg", imgsz=640, conf=0.25)
results[0].show()
```

---

## End-to-End Demo Flow

1. Load KML area → 2. start mission → 3. live telemetry → 4. RGB + thermal → 5. survivor detected & geo-tagged → 6. hazard detected & scored → 7. P1–P4 priority → 8. markers + alert → 9. GPS loss → GPS-denied fallback → 10. network loss → offline queue → 11. link restored → resync → 12. situation report.

The **MISSION tab scenario launcher** drives seven hardware-free scenarios: Normal GPS · GPS loss → denied · Thermal survivor · Hazard detection · Communication loss · Multiple detections · Mission complete.

---

## Problem Statement → Implementation Mapping

| PSID 26177 requirement | Where it lives |
|---|---|
| Autonomous navigation (GPS + GPS-denied, SLAM/VO/optical flow/obstacle avoidance) | NAV panel + `models/nav.py` position-source & GPS-denied derivation |
| On-device AI inference (people + hazards, no cloud) | `sih_model/` YOLO26n → ONNX → Qualcomm NPU; AI/MODEL tabs |
| Multi-sensor fusion (RGB, thermal, IMU, GPS) | RGB/thermal feeds + fusion bar + sensor health |
| Hazard classification | 7 classes in the model; `models/hazard.py` + risk model |
| Geo-tagged mapping | `utils/geo.py` grid↔WGS84, KML import, live markers & coverage |
| Emergency alerting + prioritised recommendations | `alerts_panel.py`, `utils/priority.py` explainable P1–P4, `utils/report.py` |
| Offline resilience (5G/Wi-Fi optional) | link-health model, autonomous-operation banner, local store + sync queue |
| Command-centre dashboard | the entire `dashboard/` application |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Flight control | ArduPilot / PX4 over MAVLink (SITL for simulation) |
| On-device AI | YOLO26n (Ultralytics) → ONNX Opset 18 (slimmed) → onnxruntime / QAIRT on Hexagon NPU |
| Dashboard | Python 3.13, PySide6 (Qt6), NumPy, OpenCV, pymavlink, pyserial, onnxruntime |
| Video | FFmpeg (RTSP/TCP) → raw frames |
| Perception uplink | UDP (default port 5556) |
| Packaging | `uv` / `pyproject.toml` |

---

## Hardware & Deployment Notes

- **Aircraft:** multirotor + companion computer; RGB + thermal cameras; GNSS + IMU (+ optional optical-flow / LiDAR).
- **Compute:** Snapdragon-class edge SoC (Hexagon NPU) running the FP16 ONNX detector.
- **Remaining hardware-dependent items:** live thermal wiring, companion perception uplink (UDP 5556), live video endpoint, and autopilot-side GPS-denied behaviour depend on the physical stack. The dashboard reports `UNAVAILABLE` / `UNKNOWN` / `STALE` rather than inventing values.

---

## Testing

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python dashboard/tests/smoke_test.py
```

**16 checks:** mode authority, simulated pipeline, map/coverage, geo-tagging, risk, alerts + acknowledgement, frames/sensor health, AI status, navigation, situation report (text/JSON/CSV), GPS-denied vs stale derivation, headless widget rendering, full-window wiring, and real-model inference. Validated end-to-end against real ArduPilot SITL.

---

## Team

Built for **Smart India Hackathon 2026**, Problem Statement ID **26177** (Qualcomm Inc · Hardware · Robotics & Drones).

---

> **Design principle:** the dashboard must never mislead — missing data shows as
> `N/A` / `UNKNOWN` / `UNAVAILABLE` / `STALE`, and simulated data is always
> labelled `SIMULATION`.
