# Trained model artifacts

Drop the exported model files here:

| File | Size | Purpose |
|------|------|---------|
| `best.onnx` | ~9.3 MB (ONNX Opset 18, slimmed) | **Primary** — onnxruntime edge inference |
| `best.pt`   | ~4.4 MB (FP16 PyTorch)             | Optional — Ultralytics fallback |

The dashboard loads `sih_model/models/best.onnx` by default:

```bash
.venv/bin/python dashboard/gcs.py --model sih_model/models/best.onnx
```

If the files are absent the dashboard still runs — the AI/MODEL tabs simply
report `EDGE AI UNAVAILABLE · model not found`, never a fabricated result.
