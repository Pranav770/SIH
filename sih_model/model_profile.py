"""Static model profile + dashboard label mapping.

Kept separate from ``sih_model/inference.py`` (the engine, authored by the
model team) so the analytical MODEL tab can present the Judges' "Key
Highlights" without modifying the canonical inference code.
"""

from __future__ import annotations

# Master 7-class ontology (authoritative — bound to the trained output head)
CLASS_DESCRIPTIONS = {
    "person": "Human search & rescue (SAR) target",
    "fire": "Structural / wildfire emergency",
    "smoke": "Early fire indicator",
    "floodwater": "Natural disaster inundation",
    "structural_damage": "Infrastructure collapse / damage",
    "landslide": "Terrain & geological hazard",
    "exposed_wire": "Electrical hazard / utility infrastructure",
}

# model class name -> dashboard ontology label (models/detection.py)
DASHBOARD_CLASS_MAP = {
    "person": "PERSON",
    "fire": "FIRE",
    "smoke": "SMOKE",
    "floodwater": "FLOOD",
    "structural_damage": "DAMAGED STRUCTURE",
    "landslide": "LANDSLIDE",
    "exposed_wire": "ELECTRICAL LINE",
}

DEFAULT_MODEL = "sih_model/models/best.onnx"

MODEL_PROFILE = {
    "architecture": "YOLOv26 Nano (YOLO26n) — anchorless dual-head detector",
    "parameters": "2,506,530 params (~2.51M; 2.38M fused)",
    "layers": "260 layers (120 when fused for inference)",
    "compute": "5.9 GFLOPs (5.3 GFLOPs fused @ 640x640)",
    "input": "(1, 3, 640, 640) BCHW",
    "output": "(1, 11, 8400) — 4 box coords + 7 class logits",
    "pt_fp16": "4.4 MB (FP16 PyTorch)",
    "onnx": "9.3 MB (ONNX Opset 18, slimmed via onnxslim)",
    "target": ("Qualcomm Hexagon NPU via Qualcomm AI Engine Direct (QAIRT) / "
               "ONNX Runtime QNN EP — Dragonwing RB3 Gen 2 (QCS6490) & "
               "Snapdragon 8/X Series"),
    "cloud_dependency": "NONE",
}

# peak augmented benchmark (v4-full-best.pt), high -> low
MAP_TABLE = [
    ("structural_damage", 0.918, "Post-earthquake structural safety mapping"),
    ("smoke",             0.825, "Early aerial wildfire-origin detection"),
    ("exposed_wire",      0.795, "Electrocution prevention for ground teams"),
    ("fire",              0.718, "Active flame tracking (RGB + thermal)"),
    ("floodwater",        0.620, "Flood contour / inundation extraction"),
    ("landslide",         0.530, "Soil slips, blocked mountain routes"),
    ("person",            0.426, "Survivor detection under aerial viewing angles"),
]

LATENCY_TABLE = [
    ("Pre-processing",        0.2),
    ("NPU / GPU inference",   1.7),
    ("Post-processing (NMS)", 1.4),
]
END_TO_END = "~3.3 ms  ·  ~300+ FPS (NVIDIA Tesla T4 / Qualcomm NPU)"

DATASET_TABLE = [
    (0, "person",            "VisDrone, Humans-in-Floods", 117378, 30366),
    (1, "fire",              "Smoke-Fire-YOLO, FlameVision", 11789, 2896),
    (2, "smoke",             "Smoke-Fire-YOLO",              9489, 2363),
    (3, "floodwater",        "FloodNet (mask contours)",     1560, 400),
    (4, "structural_damage", "RescueNet, SARD, Earthquake",  5973, 1451),
    (5, "landslide",         "Landslide Image Dataset",       175, 37),
    (6, "exposed_wire",      "TTPLA (JSON)",                  535, 99),
]
DATASET_SUMMARY = ("20,996 train / 5,228 val images  ·  146,899 train / "
                   "37,612 val boxes  ·  8 public datasets  ·  "
                   "5 annotation formats")

TRAINING = {
    "phase1": "Head warm-up — 15 epochs, backbone frozen (freeze=10), AdamW lr0=0.001",
    "phase2": "Multi-scale fine-tune — 40 epochs, fully unfrozen, AdamW lr0=0.0001, warmup 3.0",
    "augment": "mosaic 1.0, multi_scale 0.5, close_mosaic 10 (copy_paste/mixup disabled)",
    "hardware": "NVIDIA Tesla T4 — 5.61 h (phase 2)",
}

ROADMAP = ("SAHI (Slicing Aided Hyper Inference) + patch-attention heads for "
           "<30 px human targets at high flight altitudes")
