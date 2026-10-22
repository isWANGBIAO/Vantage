# Electron scrolling regression: rendering policy

## Evidence and decision

The browser frontend is smooth while the same production UI in Electron is not.
The desktop entry point unconditionally calls `app.disableHardwareAcceleration()`.
An isolated Electron 42.11.14 comparison, using the same page and viewport with
WebGL disabled in both modes, measured approximately 7 scrolling frames/second
with software composition and 60 frames/second with normal GPU composition.
These are local diagnostic measurements, not a cross-device performance promise.

The previous CPU-runtime validation did not establish that hardware composition
caused the historical driver incident. Blanket software rendering is therefore
too broad. The user approved restoring normal composition, retaining the Python
OpenCL policy, disabling unneeded webpage WebGL, and rebuilding/reinstalling.

## Scope

- Remove the unconditional Electron hardware-acceleration opt-out.
- Set `webPreferences.webgl: false` on the main window. This blocks page WebGL
  contexts, not the graphics driver initialization needed by the compositor.
- Record the actual GPU feature status in the local Electron startup log.
- Preserve the existing backend OpenCL policy, configuration JSON, layout,
  protocol security, tray and window-close behavior.
- Replace the test that enforces blanket software rendering with tests for the
  new policy; retain production UI and protocol smoke coverage.

No browser-engine migration, driver changes, global GPU preference, private data,
or unrelated camera-stream fix belongs to this change. GitHub issue #132 concerns
MJPEG reconnection rather than this scrolling regression. Existing graphics
driver stability remains an observation boundary; WebGL blocking is not proof
that all historic driver coexistence issues are resolved.

## Verification

Use a failing startup-policy test before implementation, then run frontend
lint/tests/build, protocol/UI smoke checks and the backend OpenCL policy tests.
Run the full Windows build/install flow to completion. Verify the installed build,
local GPU status, backend readiness, configuration preservation and user-visible
scrolling separately. Headless smoke success alone does not establish smoothness.

## References

- https://www.electronjs.org/docs/latest/api/app#appdisablehardwareacceleration
- https://www.electronjs.org/docs/latest/api/structures/web-preferences
