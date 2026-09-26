"""
SIH Model Inference Pipeline
=============================
Authoritative inference wrapper for SIH 7-class aerial computer vision models (ONNX & PyTorch).
Supports ONNX Runtime and Ultralytics backends with zero-copy OpenCV frame processing.

Master 7-Class Ontology:
  0: person
  1: fire
  2: smoke
  3: floodwater
  4: structural_damage
  5: landslide
  6: exposed_wire
"""

import os
import cv2
import numpy as np
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SIHInference")

CLASS_NAMES = {
    0: "person",
    1: "fire",
    2: "smoke",
    3: "floodwater",
    4: "structural_damage",
    5: "landslide",
    6: "exposed_wire"
}

# Color palette for UI annotation (BGR format)
CLASS_COLORS = {
    0: (255, 128, 0),    # person: Bright Blue
    1: (0, 0, 255),      # fire: Red
    2: (128, 128, 128),  # smoke: Gray
    3: (255, 255, 0),    # floodwater: Cyan
    4: (0, 165, 255),    # structural_damage: Orange
    5: (42, 42, 165),    # landslide: Brown
    6: (0, 255, 255)     # exposed_wire: Yellow
}


class SIHInferenceEngine:
    def __init__(self, model_path: str = None, conf_thresh: float = 0.25, iou_thresh: float = 0.45):
        self.conf_thresh = conf_thresh
        self.iou_thresh = iou_thresh
        self.model_path = model_path
        self.backend = None
        self.session = None
        self.yolo_model = None

        if self.model_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            default_onnx = os.path.join(base_dir, "models", "best.onnx")
            default_pt = os.path.join(base_dir, "models", "best.pt")

            if os.path.exists(default_onnx):
                self.model_path = default_onnx
            elif os.path.exists(default_pt):
                self.model_path = default_pt
            else:
                raise FileNotFoundError("No model found in sih_model/models/. Please specify model_path.")

        self._init_backend()

    def _init_backend(self):
        logger.info(f"Initializing inference backend for: {self.model_path}")
        ext = os.path.splitext(self.model_path)[1].lower()

        if ext == ".onnx":
            try:
                import onnxruntime as ort
                providers = ort.get_available_providers()
                logger.info(f"Available ONNX Providers: {providers}")
                self.session = ort.InferenceSession(self.model_path, providers=providers)
                self.backend = "onnxruntime"
                self.input_name = self.session.get_inputs()[0].name
                logger.info("Successfully initialized ONNXRuntime backend.")
                return
            except ImportError:
                logger.warning("onnxruntime not installed. Falling back to ultralytics backend.")

        # Fallback / PyTorch backend via Ultralytics
        try:
            from ultralytics import YOLO
            self.yolo_model = YOLO(self.model_path)
            self.backend = "ultralytics"
            logger.info("Successfully initialized Ultralytics backend.")
        except ImportError as e:
            raise RuntimeError(
                "Neither onnxruntime nor ultralytics is available. "
                "Install using `pip install onnxruntime ultralytics`"
            ) from e

    def predict(self, frame: np.ndarray):
        """
        Run object detection on an BGR OpenCV frame.
        Returns list of detection dicts:
        [{"class_id": 1, "class_name": "fire", "confidence": 0.88, "bbox": [x1, y1, x2, y2]}]
        """
        if frame is None or frame.size == 0:
            return []

        if self.backend == "ultralytics":
            return self._predict_ultralytics(frame)
        elif self.backend == "onnxruntime":
            return self._predict_onnxruntime(frame)

        return []

    def _predict_ultralytics(self, frame: np.ndarray):
        results = self.yolo_model.predict(
            source=frame,
            conf=self.conf_thresh,
            iou=self.iou_thresh,
            verbose=False
        )
        detections = []
        if not results or len(results) == 0:
            return detections

        boxes = results[0].boxes
        if boxes is None:
            return detections

        for box in boxes:
            cls_id = int(box.cls[0].cpu().item())
            conf = float(box.conf[0].cpu().item())
            xyxy = box.xyxy[0].cpu().numpy().astype(int).tolist()

            detections.append({
                "class_id": cls_id,
                "class_name": CLASS_NAMES.get(cls_id, f"unknown_{cls_id}"),
                "confidence": round(conf, 4),
                "bbox": xyxy
            })

        return detections

    def _predict_onnxruntime(self, frame: np.ndarray):
        # ONNX preprocessing
        h_orig, w_orig = frame.shape[:2]
        img_resized = cv2.resize(frame, (640, 640))
        img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
        img_norm = img_rgb.astype(np.float32) / 255.0
        img_transposed = np.transpose(img_norm, (2, 0, 1))
        input_tensor = np.expand_dims(img_transposed, axis=0)

        outputs = self.session.run(None, {self.input_name: input_tensor})
        raw_output = outputs[0]  # Shape: (1, 11, 8400) or (1, 8400, 11)

        # Transpose if shape is (1, 11, 8400)
        if raw_output.shape[1] < raw_output.shape[2]:
            raw_output = np.transpose(raw_output, (0, 2, 1))

        predictions = raw_output[0]  # Shape: (8400, 11) -> 4 bbox coords + 7 class confidences

        boxes = []
        confidences = []
        class_ids = []

        x_factor = w_orig / 640.0
        y_factor = h_orig / 640.0

        for pred in predictions:
            cx, cy, w, h = pred[0:4]
            scores = pred[4:]
            class_id = int(np.argmax(scores))
            conf = float(scores[class_id])

            if conf >= self.conf_thresh:
                x1 = int((cx - 0.5 * w) * x_factor)
                y1 = int((cy - 0.5 * h) * y_factor)
                x2 = int((cx + 0.5 * w) * x_factor)
                y2 = int((cy + 0.5 * h) * y_factor)

                boxes.append([x1, y1, x2 - x1, y2 - y1])
                confidences.append(conf)
                class_ids.append(class_id)

        indices = cv2.dnn.NMSBoxes(boxes, confidences, self.conf_thresh, self.iou_thresh)

        detections = []
        if len(indices) > 0:
            for i in indices.flatten():
                x1, y1, w, h = boxes[i]
                cls_id = class_ids[i]
                detections.append({
                    "class_id": cls_id,
                    "class_name": CLASS_NAMES.get(cls_id, f"unknown_{cls_id}"),
                    "confidence": round(confidences[i], 4),
                    "bbox": [max(0, x1), max(0, y1), min(w_orig, x1 + w), min(h_orig, y1 + h)]
                })

        return detections

    def draw_detections(self, frame: np.ndarray, detections: list) -> np.ndarray:
        """
        Draw bounding boxes and class labels on an OpenCV frame.
        """
        annotated_frame = frame.copy()
        for det in detections:
            cls_id = det["class_id"]
            label = f"{det['class_name']} {det['confidence']:.2f}"
            x1, y1, x2, y2 = det["bbox"]
            color = CLASS_COLORS.get(cls_id, (0, 255, 0))

            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)

            (w_txt, h_txt), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(annotated_frame, (x1, y1 - 20), (x1 + w_txt + 10, y1), color, -1)
            cv2.putText(annotated_frame, label, (x1 + 5, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        return annotated_frame
