"""SIH on-device inference engine (YOLO26n → ONNX / Ultralytics).

Single entry point used by the dashboard and by judges' quick tests.

    from sih_model.inference import SIHInferenceEngine
    engine = SIHInferenceEngine()                 # defaults to models/best.onnx
    dets = engine.infer(frame_bgr)                # -> [Detection, ...]

The 7-class ontology is anchored to the trained model's output head and is
the single source of truth for the dashboard label map and README:

    0 person            1 fire              2 smoke
    3 floodwater        4 structural_damage 5 landslide
    6 exposed_wire

Backends:
  * ``onnx``  — onnxruntime (primary, lightweight edge path)
  * ``ultralytics`` — optional PyTorch fallback (``pip install ultralytics``)
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------------------
# Master 7-class ontology (authoritative — bound to the trained output head)
# ---------------------------------------------------------------------------
CLASS_NAMES = [
    "person",             # 0  Human search & rescue target
    "fire",               # 1  Structural / wildfire emergency
    "smoke",              # 2  Early fire indicator
    "floodwater",         # 3  Natural disaster inundation
    "structural_damage",  # 4  Infrastructure collapse / damage
    "landslide",          # 5  Terrain & geological hazard
    "exposed_wire",       # 6  Electrical hazard / utility infrastructure
]

CLASS_DESCRIPTIONS = {
    "person": "Human search & rescue (SAR) target",
    "fire": "Structural / wildfire emergency",
    "smoke": "Early fire indicator",
    "floodwater": "Natural disaster inundation",
    "structural_damage": "Infrastructure collapse / damage",
    "landslide": "Terrain & geological hazard",
    "exposed_wire": "Electrical hazard / utility infrastructure",
}

# model label -> dashboard class label (models/detection.py ontology)
DASHBOARD_CLASS_MAP = {
    "person": "PERSON",
    "fire": "FIRE",
    "smoke": "SMOKE",
    "floodwater": "FLOOD",
    "structural_damage": "DAMAGED STRUCTURE",
    "landslide": "LANDSLIDE",
    "exposed_wire": "ELECTRICAL LINE",
}

DEFAULT_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "models", "best.onnx")

# ---------------------------------------------------------------------------
# Static model profile (Judges' "Key Highlights" — shown in the MODEL tab)
# ---------------------------------------------------------------------------
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

# peak augmented benchmark (v4-full-best.pt), sorted high -> low
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
    ("Pre-processing",          0.2),
    ("NPU / GPU inference",     1.7),
    ("Post-processing (NMS)",   1.4),
]
END_TO_END = "~3.3 ms  ·  ~300+ FPS (NVIDIA Tesla T4 / Qualcomm NPU)"

# unified dataset benchmark
DATASET_TABLE = [
    # id, name, sources, train boxes, val boxes
    (0, "person",            "VisDrone, Humans-in-Floods", 117378, 30366),
    (1, "fire",              "Smoke-Fire-YOLO, FlameVision", 11789, 2896),
    (2, "smoke",             "Smoke-Fire-YOLO",              9489, 2363),
    (3, "floodwater",        "FloodNet (mask contours)",     1560, 400),
    (4, "structural_damage", "RescueNet, SARD, Earthquake",  5973, 1451),
    (5, "landslide",         "Landslide Image Dataset",       175, 37),
    (6, "exposed_wire",      "TTPLA (JSON)",                  535, 99),
]
DATASET_SUMMARY = "20,996 train / 5,228 val images  ·  146,899 train / 37,612 val boxes  ·  8 public datasets  ·  5 annotation formats"

TRAINING = {
    "phase1": "Head warm-up — 15 epochs, backbone frozen (freeze=10), AdamW lr0=0.001",
    "phase2": "Multi-scale fine-tune — 40 epochs, fully unfrozen, AdamW lr0=0.0001, warmup 3.0",
    "augment": "mosaic 1.0, multi_scale 0.5, close_mosaic 10 (copy_paste/mixup disabled)",
    "hardware": "NVIDIA Tesla T4 — 5.61 h (phase 2)",
}

ROADMAP = ("SAHI (Slicing Aided Hyper Inference) + patch-attention heads for "
           "<30 px human targets at high flight altitudes")


@dataclass
class Detection:
    cls_id: int
    label: str
    confidence: float
    bbox: tuple[float, float, float, float]   # x1, y1, x2, y2 (pixels)
    dash_class: str = ""                       # dashboard ontology label

    def to_dict(self, stable_id: str, frame_size=None, source="edge") -> dict:
        x1, y1, x2, y2 = self.bbox
        return {
            "id": stable_id,
            "class": self.dash_class or DASHBOARD_CLASS_MAP.get(self.label, self.label.upper()),
            "confidence": round(float(self.confidence), 4),
            "bbox": [int(x1), int(y1), int(x2), int(y2)],
            "source": source,
        }


# ---------------------------------------------------------------------------
def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thres: float) -> list[int]:
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_r = (boxes[rest, 2] - boxes[rest, 0]) * (boxes[rest, 3] - boxes[rest, 1])
        union = area_i + area_r - inter + 1e-9
        iou = inter / union
        order = rest[iou <= iou_thres]
    return keep


class SIHInferenceEngine:
    """Backend-agnostic detector wrapper (ONNX primary, Ultralytics fallback)."""

    def __init__(self, model_path: str | None = None, backend: str = "auto",
                 conf: float = 0.25, iou: float = 0.45, imgsz: int = 640):
        self.model_path = model_path or DEFAULT_MODEL
        self.conf = float(conf)
        self.iou = float(iou)
        self.imgsz = int(imgsz)
        self.backend = "none"
        self.available = False
        self.reason = ""
        self._session = None
        self._model = None
        self._requested_backend = backend
        self._load()

    # -- loading --------------------------------------------------------
    def _load(self) -> None:
        if not os.path.exists(self.model_path):
            self.reason = f"model not found: {self.model_path}"
            return
        ext = os.path.splitext(self.model_path)[1].lower()
        if self._requested_backend != "auto":
            order = [self._requested_backend]
        elif ext == ".onnx":
            order = ["onnx"]
        elif ext in (".pt", ".torchscript", ""):
            order = ["ultralytics", "onnx"]
        else:
            order = ["onnx", "ultralytics"]
        reasons: list[str] = []
        for backend in order:
            try:
                if backend == "onnx" and ext in (".onnx", ".ort"):
                    import onnxruntime as ort          # noqa: F401
                    so = ort.SessionOptions()
                    so.log_severity_level = 3
                    self._session = ort.InferenceSession(
                        self.model_path, so,
                        providers=["CPUExecutionProvider"])
                    self.backend = "onnxruntime"
                    self.available = True
                    return
                if backend == "ultralytics":
                    from ultralytics import YOLO          # noqa: F401
                    self._model = YOLO(self.model_path)
                    self.backend = "ultralytics"
                    self.available = True
                    return
            except Exception as exc:                       # noqa: BLE001
                reasons.append(f"{backend}: {exc}")
        self.reason = "; ".join(reasons) if reasons else \
            f"no backend could load {self.model_path}"

    @property
    def class_names(self) -> list[str]:
        if self._model is not None:
            names = getattr(self._model, "names", None)
            if isinstance(names, dict):
                return [names[i] for i in sorted(names)]
            if names:
                return list(names)
        return list(CLASS_NAMES)

    # -- inference ------------------------------------------------------
    def infer(self, frame_bgr) -> list[Detection]:
        if not self.available or frame_bgr is None:
            return []
        try:
            if self.backend == "ultralytics":
                return self._infer_ultralytics(frame_bgr)
            return self._infer_onnx(frame_bgr)
        except Exception:                                  # noqa: BLE001
            return []

    def _infer_ultralytics(self, frame) -> list[Detection]:
        r = self._model.predict(frame, imgsz=self.imgsz, conf=self.conf,
                                iou=self.iou, verbose=False)[0]
        names = self.class_names
        out: list[Detection] = []
        for b in r.boxes:
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
            cid = int(b.cls[0])
            label = names[cid] if cid < len(names) else str(cid)
            out.append(Detection(cid, label, float(b.conf[0]), (x1, y1, x2, y2),
                                 DASHBOARD_CLASS_MAP.get(label, label.upper())))
        return out

    def _infer_onnx(self, frame) -> list[Detection]:
        import cv2
        h0, w0 = frame.shape[:2]
        img, ratio, (padx, pady) = _letterbox(frame, self.imgsz)
        blob = img[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        inputs = self._session.get_inputs()
        outputs = self._session.run(None, {inputs[0].name: blob})
        pred = outputs[0]
        names = self.class_names
        nc = len(names)

        dets: list[Detection] = []
        # NMS-included export: (1, N, 6) -> x1,y1,x2,y2,conf,cls
        if pred.ndim == 3 and pred.shape[2] == 6:
            for row in pred[0]:
                x1, y1, x2, y2, cf, cid = row.tolist()
                cid = int(cid)
                label = names[cid] if cid < len(names) else str(cid)
                dets.append(Detection(cid, label, cf, (x1, y1, x2, y2),
                                      DASHBOARD_CLASS_MAP.get(label, label.upper())))
            return dets

        if pred.ndim == 3:
            pred = pred[0]
        if pred.shape[0] == 4 + nc:            # (11, 8400) -> (8400, 11)
            pred = pred.T
        boxes_xywh = pred[:, :4]
        scores = pred[:, 4:4 + nc]
        cls_ids = scores.argmax(1)
        confs = scores[np.arange(len(cls_ids)), cls_ids]
        keep = confs >= self.conf
        boxes_xywh, cls_ids, confs = boxes_xywh[keep], cls_ids[keep], confs[keep]
        if len(confs) == 0:
            return []

        # xywh (letterboxed) -> xyxy (original image)
        cx, cy, w, h = boxes_xywh.T
        x1 = (cx - w / 2 - padx) / ratio
        y1 = (cy - h / 2 - pady) / ratio
        x2 = (cx + w / 2 - padx) / ratio
        y2 = (cy + h / 2 - pady) / ratio
        boxes = np.stack([x1, y1, x2, y2], axis=1)

        for c in np.unique(cls_ids):
            m = cls_ids == c
            for i in _nms(boxes[m], confs[m], self.iou):
                idx = int(np.where(m)[0][i])
                label = names[int(c)] if int(c) < len(names) else str(int(c))
                dets.append(Detection(int(c), label, float(confs[idx]),
                                      tuple(boxes[idx].tolist()),
                                      DASHBOARD_CLASS_MAP.get(label, label.upper())))
        return dets

    # -- provenance label ----------------------------------------------
    def status_text(self) -> str:
        if self.available:
            return f"EDGE AI READY · {self.backend} · {os.path.basename(self.model_path)}"
        return f"EDGE AI UNAVAILABLE · {self.reason}"


def _letterbox(img, new_shape: int = 640, color=(114, 114, 114)):
    import cv2
    h, w = img.shape[:2]
    r = min(new_shape / h, new_shape / w)
    nw, nh = int(round(w * r)), int(round(h * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    dw, dh = new_shape - nw, new_shape - nh
    top, left = dh // 2, dw // 2
    padded = cv2.copyMakeBorder(resized, top, dh - top, left, dw - left,
                                cv2.BORDER_CONSTANT, value=color)
    return padded, r, (left, top)


# ---------------------------------------------------------------------------
def _main(argv=None) -> int:
    p = argparse.ArgumentParser(description="SIH YOLO26n inference (quick test)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--source", required=True, help="image or video path")
    p.add_argument("--out", default="sih_inference_out.jpg")
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--imgsz", type=int, default=640)
    args = p.parse_args(argv)

    engine = SIHInferenceEngine(args.model, conf=args.conf, imgsz=args.imgsz)
    print(engine.status_text())
    if not engine.available:
        return 1

    import cv2
    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        print(f"cannot open source: {args.source}")
        return 1
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print("no frame read")
        return 1
    dets = engine.infer(frame)
    for d in dets:
        print(f"  {d.label:18} {d.confidence:.3f}  {tuple(round(v) for v in d.bbox)}")
    for d in dets:
        x1, y1, x2, y2 = (int(v) for v in d.bbox)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 255), 2)
        cv2.putText(frame, f"{d.label} {d.confidence:.2f}", (x1, max(12, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)
    cv2.imwrite(args.out, frame)
    print(f"{len(dets)} detections -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
