# Camera Warmup Design

## Goal

Keep Vantage camera colors visually stable after startup and automatic black-frame recovery without applying software color filters or permanently locking camera controls.

## Design

After every successful camera open, Vantage enters a two-second warmup window. Frames are still read so the camera driver can settle automatic exposure and white balance, but they are not published to `state.latest_frame` until the warmup window completes. If an older valid frame exists during a reconnect, the UI keeps showing it; on first startup, the existing unavailable/loading state remains until the first warmed frame arrives.

The warmup uses monotonic time so system clock changes cannot shorten or extend it. Pure-black frame recovery remains active during warmup. A camera that keeps returning blank frames is reopened rather than accepted merely because the warmup elapsed.

## Non-goals

- No CSS or OpenCV color correction.
- No fixed exposure, white balance, hue, saturation, or contrast values.
- No new user-facing camera controls.
- No change to capture resolution or backend selection.

## Verification

- Unit tests cover the warmup deadline and publication decision.
- Existing black-frame recovery and renderer-camera tests remain green.
- The packaged app is rebuilt with `RUN.bat` and its live MJPEG frame is checked after warmup.
