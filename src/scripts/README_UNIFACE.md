# UniFace Dark Circle Analysis Module

This module replaces the old landmark-based analysis with a high-precision Face Parsing approach (BiSeNet via ONNX Runtime). It is designed to robustly track dark circle severity over years of selfies.

## 1. Prerequisites

### Hardware
- NVIDIA GPU (Recommended) for fast processing (~100ms/image). 
- CPU fallback is supported but slower (~1-2s/image).

### Software Requirements
Install the dependencies using the following command. Note that `onnxruntime-gpu` is required for GPU acceleration.

```bash
pip install onnxruntime-gpu opencv-python-headless numpy pandas tqdm matplotlib
```

*(If you don't have a GPU, use `onnxruntime` instead of `onnxruntime-gpu`)*

### Model File (Required)
You **MUST** download the BiSeNet face parsing model.
- **Filename**: `face_parsing.farl.lapa.int8.onnx` (or similar standard BiSeNet model)
- **Download Link Example**: [GitHub - Face Parsing ONNX](https://github.com/myown/model-repo/releases) (Please use a trusted source for `face_parsing.farl.lapa.int8.onnx`)
- **Place it in**: `src/scripts/models/` (create this folder)

## 2. Usage

### Basic Run
```bash
python src/scripts/analyze_darkcircle_uniface.py --model src/scripts/models/face_parsing.farl.lapa.int8.onnx
```

This will:
1. Scan default Photo directories (OneDrive, D:\WANGBIAO).
2. Process all images (resuming if interrupted).
3. Generate `results.csv`.
4. Create plots `dark_circle_trend_uniface.png` and `extremes_uniface.png`.
5. Export Top 10 Best/Worst images to `top_lightest/` and `top_darkest/`.

### Advanced Options
- `--dir "C:\MyPhotos" "D:\BackupPhotos"` : Specify custom scan directories.
- `--workers 4` : Number of parallel processes (Default: 4).
- `--debug` : Save overlay images to `debug_overlays/` to verify detection quality.
- `--out my_results.csv` : Custom output filename.

## 3. Outputs

| File | Description |
|------|-------------|
| `results.csv` | Full dataset with timestamps, scores (left/right/avg), and failure reasons. |
| `dark_circle_trend_uniface.png` | Scatter plot of raw scores + Smoothed 14-day trend line. |
| `extremes_uniface.png` | Side-by-side comparison of the Best vs Worst days. |
| `top_darkest/` | Folder containing copies of the 10 highest scoring (worst) images. |
| `top_lightest/` | Folder containing copies of the 10 lowest scoring (best) images. |

## 4. Troubleshooting
- **Model Load Failed**: Check if the `.onnx` file path is correct.
- **CUDA/GPU issues**: Ensure you have installed CUDA Toolkit compatible with your `onnxruntime-gpu` version. If it fails, the script falls back to CPU (slower).
- **No faces found**: Use `--debug` to check if images are being read correctly.
