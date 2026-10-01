# 6. Edge AI Compute & Offline Resilient Architecture

---

## Hardware Acceleration

* **Radxa Dragon Q6A (Qualcomm QCS6490)** with Hexagon AI Engine enables onboard AI inference without cloud dependency.
* YOLOv26n model is deployed through **Qualcomm QNN Context Binary** for optimized NPU execution.

## AI Pipeline

* RGB/Thermal frames → YOLOv26n (FPN+PAN + NMS-free head) → Human/Hazard detection → Geo-tagging.
* AI inference runs parallel with **2.5D SLAM and autonomous navigation**, maintaining real-time operation.

## Network-Adaptive Operation

* **Connected Mode:** Priority alerts (survivor/hazard coordinates) are transmitted immediately; GeoJSON, telemetry and maps are synchronized to GCS.
* **Disconnected Mode:** Detection results and maps are stored locally; autonomy continues without network dependency. Data is synchronized after link recovery.

## Why This Architecture

* Reduces latency by eliminating cloud inference.
* Minimizes bandwidth by transmitting sparse GeoJSON/key-value map data instead of heavy point clouds.

---

## System Data Flow

```
        Camera + Sensors
               │
               ▼
       YOLOv26n (QNN/NPU)
               │
               ▼
   Human + Hazard Detection
               │
               ▼
      GeoJSON + 2.5D SLAM
               │
        ┌──────┴──────┐
        ▼             ▼
 ┌─────────────┐ ┌───────────────┐
 │ 5G Available│ │  No Network   │
 └─────────────┘ └───────────────┘
        │             │
        ▼             ▼
    GCS Sync     Local Storage ──► Sync Later
```

---

## Cloud vs Edge Pipeline

```
Cloud AI Pipeline:
Drone → Network → Cloud → Result
(high latency, network dependent)

Edge AI Pipeline:
Drone → Q6A NPU → Result
(low latency, autonomous)
```

| | Cloud AI Pipeline | Edge AI Pipeline |
|---|---|---|
| **Path** | Drone → Network → Cloud → Result | Drone → Q6A NPU → Result |
| **Latency** | High (RTT + upload of heavy frames) | Low (on-device inference) |
| **Network dependency** | Hard dependency — no link, no detections | None for inference; link only gates sync |
| **Autonomy** | Paused on link loss | Continuous mapping through link loss |

---

## Demo Simulation Sequence

| # | Observed Behaviour |
|---|---|
| 1 | **Frame input** — live RGB/thermal feed enters the pipeline |
| 2 | **Detection bounding boxes** — human + hazard classes drawn on-frame |
| 3 | **GPS/SLAM point generation** — detections geo-tagged onto the map |
| 4 | **Network cut simulation** — link indicator drops to disconnected |
| 5 | **Continued autonomous mapping** — drone keeps detecting, geo-tagging and mapping |
| 6 | **Data upload after reconnection** — queued detections/maps sync to GCS |

---

## Design Decisions

* **Engineering decision:** inference lives on the NPU, so the autonomy loop never waits on a radio link.
* **Bandwidth decision:** we uplink sparse GeoJSON/key-value map data, not raw video or point clouds.
* **Resilience decision:** disconnect is a degraded comms state, not a mission abort — local store + resync makes the link opportunistic rather than mandatory.
