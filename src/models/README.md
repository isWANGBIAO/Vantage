# Bundled Model Assets

## YuNet face detector

- File: `face_detection_yunet_2023mar.onnx`
- Upstream: <https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet>
- License: MIT; see `LICENSE.face_detection_yunet.txt`
- SHA-256: `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`

Vantage loads this ONNX model with OpenCV `FaceDetectorYN`. The five returned
landmarks are used only for a coarse camera-facing head-pose check. They do not
measure eye direction and must not be described as gaze tracking.
