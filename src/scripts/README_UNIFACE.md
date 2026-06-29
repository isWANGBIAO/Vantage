# Optional Face Parsing Model

Vantage can use an ONNX face parsing model for higher-quality face-history
analysis. The public repository does not include model weights.

## Local Model Placement

Place a licensed model here for local experiments:

```text
src/scripts/models/face_parsing.farl.lapa.int8.onnx
```

This path is ignored by Git. Do not commit model weights unless their source and
redistribution license are documented.

## Running The Script

```powershell
python src/scripts/analyze_darkcircle_uniface.py --model src/scripts/models/face_parsing.farl.lapa.int8.onnx
```

If the model is unavailable or ONNX Runtime cannot load it, the analysis code
falls back to a conservative non-model path.

## Privacy

Use local images only. Do not commit photos, screenshots, image paths, generated
face reports, or private health records.
