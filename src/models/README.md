# Bundled Model Assets

## YuNet face detector

- File: `face_detection_yunet_2023mar.onnx`
- Upstream: <https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet>
- License: MIT; see `LICENSE.face_detection_yunet.txt`
- SHA-256: `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`

Vantage loads this ONNX model with OpenCV `FaceDetectorYN`. The five returned
landmarks are used only for a coarse camera-facing head-pose check. They do not
measure eye direction and must not be described as gaze tracking.

## YOLOX person detector

- File: `object_detection_yolox_2022nov_int8bq.onnx`
- Upstream: <https://github.com/opencv/opencv_zoo/tree/main/models/object_detection_yolox>
- License: Apache-2.0; see `LICENSE.object_detection_yolox.txt`
- SHA-256: `dcaae0aaa2fea4167f89235ee340eb869d3707b25712218d4c7ce921ac90e2ba`

Vantage loads this block-quantized ONNX model through OpenCV DNN and uses only
COCO class `0` (`person`) at a `0.50` confidence threshold. It supplements the
face signal for seated presence without adding PyTorch, Ultralytics, or a
separate ONNX Runtime dependency.
