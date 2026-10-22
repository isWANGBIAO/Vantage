# Camera preview live-state validation

## Confirmed cause and scope

The real camera and backend remained healthy: an in-memory loopback probe received three JPEG frames in138ms. An isolated Electron production-protocol probe observed3840x2160 decoded pixels and `img.complete === true` throughout twelve observations while the stream continued. No private pixels were stored or emitted by these diagnostics.

The old lifecycle treated every completed image as a broken stream before checking decoded dimensions. The repair prioritizes valid dimensions and only interprets completion without usable pixels as failure. Explicit image errors, attempt/session guards, retry bounds and privacy cleanup remain unchanged. Device-online status is not used as evidence that preview pixels are visible.

## Red/green evidence

- Before the production change, two focused assertions failed with `waiting !== live`.
- The isolated production UI regression reproduced the stale recovery overlay using synthetic4K JPEG parts without Content-Length, matching the backend framing. It failed on the old implementation while the picture was decoded.
- After the fix, all5lifecycle tests and678frontend tests passed, with lint and production build passing.
- Full Electron UI smoke passed all8primary pages with0renderer errors, including continuous decoded-complete4K preview without overlay/retry churn, abrupt TCP disconnection recovery, and privacy hide/show cleanup.
- Never Stop174tests, production protocol smoke and6packaging-helper safety tests passed.
- Independent review identified a timing-sensitive test assertion; the revised test waits for actual Live/no-overlay state before checking stability across multiple500ms lifecycle observations. This is not an increased timeout or a weakened expected result.

## Boundaries and delivery

The change does not alter camera settings, model/provider configuration or backend capture. DOM image attributes alone cannot detect every graceful EOF or stalled transport that retains its final decoded frame; this repair does not claim universal liveness detection. Actual abrupt disconnection recovery remains tested.

Prepare patch version1.0.91 with the existing release metadata tool. Installation acceptance must separately verify the generated package, installed build identity, service readiness and unchanged settings. This document records source-test evidence, not an unperformed installation or remote CI result. No remote push or merge is part of the current request.
