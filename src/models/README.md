# Bundled Model Assets

## YuNet face detector

- File: `face_detection_yunet_2023mar.onnx`
- Upstream: <https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet>
- License: MIT; see `LICENSE.face_detection_yunet.txt`
- SHA-256: `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`

Vantage loads this ONNX model with OpenCV `FaceDetectorYN`. Live presence uses
a `0.50` confidence threshold and accepts only the largest face whose clipped
box occupies at least `0.5%` of the frame. It does not require frontal landmark
geometry, so a sufficiently visible turned face can still maintain presence.

Historical camera-facing analysis keeps the stricter `0.75` confidence
threshold and five-landmark head-pose check. The landmarks do not measure eye
direction and must not be described as gaze tracking.
