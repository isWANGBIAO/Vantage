# CPU runtime policy verification — 2026-10-07

## Delivered source changes

- One shared process-local helper forces `OPENCV_OPENCL_RUNTIME=disabled` before
  native imports, overriding inherited enabling values. It does not modify the
  system environment or driver.
- Thirteen Python startup/consumer boundaries cover the development server,
  packaged launcher and runtime hook, CLI/MCP, standalone face analysis, face
  detection, camera, location photos, photo selection and screenshots.
- Standalone photo-selection startup retains repository import-path support.
- Electron synchronously disables hardware acceleration before loading other
  startup dependencies. Layout, Canvas charts, provider settings, tray and
  close-window behavior are unchanged.
- Independent review found no critical or important blocking issue.

## Verification actually performed

- Test-first Python policy/order checks: 20 failures before implementation,
  then 20 passing; direct-script compatibility extension detected one failure
  before its fix; final policy suite: **24 passed**.
- Test-first Electron startup contract: 19 passing / 1 failing before the fix,
  then **20 passed**, covering development/packaged startup for all three OS
  platform identifiers without launching Electron.
- Final full Python run in `.venv-backend-runtime-gpu`:
  **1681 passed, 16 skipped, 70 subtests passed, 7 warnings**. The warnings are
  SciencePlots use of deprecated Matplotlib style APIs.
- Frontend tests: **526 passed**. Frontend lint and production build passed.
- Packaging-environment `pip check`: no broken requirements.
- Actual OpenCV 4.14.0 check: the policy overrides an inherited runtime DLL
  value before importing OpenCV; `haveOpenCL()` returned false in both the main
  thread and a worker. No camera, detector workload or CUDA probe was run.
- JavaScript syntax and whitespace checks passed.

Reproduction commands for source checks, from repository root:

```powershell
$env:OPENCV_OPENCL_RUNTIME = 'disabled'
.venv-backend-runtime-gpu/Scripts/python.exe -m pytest -q
.venv-backend-runtime-gpu/Scripts/python.exe -m pip check
npm --prefix src/webapp run lint
npm --prefix src/webapp test
npm --prefix src/webapp run build
node --check src/webapp/main.cjs
git diff --check
```

## Boundaries and non-claims

The installed application was not stopped, replaced or rebuilt. This is source
verification, not acceptance of a new installer or a new CUDA coexistence test.
It removes Vantage-side implicit acceleration triggers; it does not repair or
fully explain the underlying NVIDIA driver's initialization/cleanup failure.
Chromium can retain a software-rendering process named `gpu-process` even when
hardware acceleration is disabled. Experimental explicit-CUDA scripts and the
separate Never Stop subproject are outside this change.

The branch is retained locally; no merge or remote push is part of this delivery.

## Official references

- https://www.electronjs.org/docs/latest/api/app#appdisablehardwareacceleration
- https://github.com/electron/electron/blob/v42.8.0/shell/browser/api/electron_api_app.cc
- https://github.com/opencv/opencv/blob/4.14.0/modules/core/src/ocl.cpp
