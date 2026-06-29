# Face Analysis Algorithm Notes

This document describes the public, privacy-safe shape of Vantage face-history
analysis. It does not include private photo paths, health records, or model
weights.

## Purpose

The face-history workflow estimates visual trends from local images. It is a
personal analytics feature, not a medical diagnostic tool.

## Inputs

- Local images selected by the user or discovered through configured media
  directories.
- Optional timestamps from filenames or file metadata.
- Optional face parsing model weights supplied by the user.

Do not commit real photos, screenshots, image exports, or derived private reports
to Git.

## Model Boundary

The preferred parser can use an ONNX face parsing model at:

```text
src/scripts/models/face_parsing.farl.lapa.int8.onnx
```

The public repository does not ship this model. Users must provide a licensed
model themselves if they want model-backed segmentation. When the model is
missing or cannot be loaded, the runtime uses a conservative fallback path.

## Processing Outline

1. Locate local images from configured folders.
2. Detect or approximate face regions.
3. Estimate under-eye and skin-region features.
4. Aggregate per-image metrics into trend data.
5. Render local reports and charts.

## Privacy Notes

- Keep source images local.
- Avoid sharing generated reports that include identifiable faces.
- Strip or avoid GPS EXIF metadata when sharing images.
- Use synthetic fixtures for tests and public demos.

## Limitations

- Lighting, camera angle, focus, occlusion, skin tone, and image compression can
  strongly affect scores.
- Fallback mode is less precise than a licensed segmentation model.
- Scores are trend signals only and should not be treated as medical evidence.
