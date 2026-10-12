# CPU-only runtime policy

## Approved scope

Prevent Vantage's background image analysis and Electron UI from implicitly using
GPU acceleration. Preserve UI layout, camera capture, close-to-tray behavior and
model provider settings. Do not change system drivers or global environment.

## Design

Use a process-local Python bootstrap that forces
`OPENCV_OPENCL_RUNTIME=disabled` before OpenCV initialization, including packaged
runtime hooks, development server, CLI and standalone face-analysis processes.
Child processes inherit the same policy. A main-thread OpenCV toggle alone is
insufficient; selecting an OpenCL CPU device still initializes the runtime.

Apply Electron's official `app.disableHardwareAcceleration()` synchronously,
before readiness or window creation. This changes rendering implementation, not
the React interface. No new user setting or GPU opt-in is introduced.

## Verification and limits

Use test-first entry-point/order and environment-inheritance checks, existing
Python tests in the packaging environment, frontend lint/tests/build, and review.
Do not run CUDA coexistence reproductions or stop the installed application.
Source verification does not establish a new installed-package acceptance result
or repair the underlying NVIDIA driver fault.

## References

- https://www.electronjs.org/docs/latest/api/app#appdisablehardwareacceleration
- https://github.com/opencv/opencv/blob/4.14.0/modules/core/src/ocl.cpp
