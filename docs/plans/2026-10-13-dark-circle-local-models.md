# Local Dark Circle Models Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add selectable local ONNX/SAM3 dark-circle analysis without bundling environments or weights, then rebuild/install.

**Architecture:** External Python worker holds model; packaged backend orchestrates bounded local JSON requests. Shared segmentation-to-ROI scoring is model-independent. Settings are persisted in existing JSON API and histories isolated by profile.

**Tech Stack:** Python, OpenCV/NumPy, optional ONNX Runtime/Transformers in external Python, FastAPI, React/Electron.

---

### Task 1: Shared brow-distance ROI and scoring
Files: create src/services/face_brow_analysis.py; tests/test_face_brow_analysis.py.
1. Write tests for two eye/brow components, median edge gap, below-lid skin-only region and cheek exclusion; run `.venv-backend-runtime-gpu/Scripts/python.exe -m pytest tests/test_face_brow_analysis.py -q` expecting failure for missing implementation.
2. Implement build_brow_regions(parsing_map) and analyze_segmented_face(image_bgr, parsing_map, config=None), producing record fields and overlay. Reuse existing normalization/score definitions but no geometry fallback.
3. Run tests, add quality failure tests before implementing checks, rerun.

### Task 2: Settings and frontend (independent from ROI)
Files: src/core/user_config.py, src/backend/settings.py, src/services/automation_catalog.py, src/webapp/src/components/FaceHistory.jsx and new FaceAnalysisSettings.jsx, localized copy and frontend tests.
1. Add failing JSON validation/persistence and UI source/behavior tests.
2. Add method enum and four path/string fields, settings UI using existing state/update API; validate strings/existence as appropriate, no download/install action. Report sample overlays and provenance from backend report.
3. Run targeted Python/frontend tests and lint.

### Task 3: External worker and orchestration
Files: create src/scripts/face_model_worker.py, src/services/face_local_runtime.py, tests/test_face_local_runtime.py.
1. Write failing tests for local-only commands, profile isolation, missing inputs, worker failures and timeouts.
2. Implement JSON-lines subprocess with bounded requests. Worker loads CPU BiSeNet with correct normalization or local-only SAM3 and returns segmentation/analysis. Keep optional imports in worker only.
3. Test model adapters with synthetic contract fixtures; real local model smoke in user runtime, not repository.

### Task 4: Runtime/routes/history
Files: src/backend/face.py, src/backend/camera.py, src/scripts/analyze_face.py; tests/test_face_local_endpoint.py.
1. Test missing environment reporting and profile-specific database/report/overlay responses before route changes.
2. Route captured and historical photographs through configured runtime; serialize model access, keep live loop bounded or expose unavailable clearly; preserve old reports on errors. Export/report operate on selected profile; only serve manifested image assets.
3. Run regression face/cache/camera suites and inspect diffs for unsafe paths or blocking event-loop work.

### Task 5: Packaging and verification
Files: src/core/backend_runtime_packaging.py and packaging tests, version configuration/docs.
1. Verify worker/support sources bundled as code, forbidden packages/weights remain excluded; add failing resource tests first.
2. Run `.venv-backend-runtime-gpu/Scripts/python.exe -m pytest -q`, `npm --prefix src/webapp run check`. Run real ONNX and SAM3 on bounded sample locally and inspect overlay/score.
3. Review spec and code quality, address findings, update release version coherently. Run RUN.bat without forced timeout. Verify installed backend version/settings/report and no added model weights in package.

Task state: implementation and targeted model/ROI/settings tests complete; full verification and installed acceptance required. Added a separate optional SAM3 interpreter because ONNX and SAM3 may live in different existing environments. Review fixes cover total IPC deadline, model execution exclusion, immutable model settings during history jobs, profile-specific plots, and timestamp-matched overlays. Do not claim installation completion without installed runtime evidence.
