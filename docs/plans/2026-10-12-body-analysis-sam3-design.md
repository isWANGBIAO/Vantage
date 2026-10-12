# Body Analysis with Optional Local SAM3 — Design

## Goal and scope

Replace the top-level dark-circle history navigation item with **Body Analysis**.
Its three subpages are Dark Circles, Leg Hair, and Scalp. Keep the existing
dark-circle pipeline and report unchanged. The two hair subpages show locally
generated SAM3 reports, including reviewable masks and quality flags.

This is a local-first feature. Only a small, sanitized report runner and the
Vantage integration are tracked. Photographs, reports, model weights, local
configuration, API keys, and exploratory online-model scripts are not tracked.

## Selected approach

The main Vantage package ships the report runner source but **not** PyTorch,
Transformers, SAM3 weights, or a separate Python installation. A dedicated
optional environment under the configured user-data directory owns those
dependencies. The UI detects missing prerequisites and offers an explicit
install action; it never installs packages, downloads weights, or uploads
photographs silently. If weights are absent, the UI asks the user to select a
local checkpoint directory instead of attempting an authenticated download.

Alternatives rejected: bundling the GPU stack and weights would greatly expand
the installer and couple the desktop runtime to one CUDA environment; displaying
only a pre-existing HTML report would not satisfy automatic analysis.

## Data and execution flow

1. The Body Analysis settings keep the leg-photo directory, scalp-photo
   directory, local checkpoint directory, optional Python environment state,
   and enabled flag in Vantage's existing user-data JSON configuration. No
   machine-specific path is a source-code default. On this computer only,
   existing photo/model locations may be seeded into that local JSON during
   setup after the user confirms them.
2. At backend startup, a non-blocking worker checks configured directories.
   It fingerprints supported image files and the runner/model version, compares
   them with the last successful manifest, and schedules work only for changed
   input. Initial analysis includes all configured images. Repeated launches
   with unchanged inputs reuse the last complete report.
3. The worker runs the sanitized script in the optional environment as a
   child process. Source images are read only. New output is written to a
   staging directory in user data; the previous report remains visible until
   validation succeeds and the new report is atomically published. No private
   path or raw image content enters logs or API error text.
4. The UI shows readiness, install/setup guidance, job progress, failure and
   retry, then the latest successful report. Reports expose source capture time,
   segmentation masks/overlays, per-image quality warnings, and time trends.
   A missing detection is `null`, never zero. Unreviewed or rejected scalp
   candidate measurements remain inspectable but cannot enter trend charts.
5. Only generated report assets beneath the selected report directory are
   served through a restricted endpoint. HTML, if displayed in an iframe, is
   sandboxed without same-origin privileges. The existing dark-circle tab is
   mounted only while visible so its live-camera polling does not run under a
   hidden subpage. Old `#face-history` links continue to open Dark Circles.

## Safety and interpretation

The shipped runner is extracted from the local prototype rather than copied
wholesale. It has no credential reads, online image requests, user-specific
paths, recursive deletion of a caller-supplied output directory, or implicit
package downloads. The optional install action is explicit and isolated from
the main backend environment. Analyze only configured directories; never scan
the repository or arbitrary user folders.

Leg-hair line counts and pixel-normalized density are image-processing proxies,
not biological hair counts or physical density. Scalp hair-region/texture and
visible-scalp candidates are likewise photo proxies. Lighting, angle, hair
length, crop, and segmentation failures limit comparability. The UI must not
claim a trend from rejected or unverified measurements.

## Verification and delivery

- Tests for configuration validation, startup single-flight/incremental
  scheduling, missing dependencies, local-only process invocation, atomic
  publication, report path traversal protection, and rejected-metric exclusion.
- Frontend tests for navigation/hash compatibility, hidden dark-circle polling,
  install/setup states, report display, and localization; run lint, tests, and
  build.
- Run the full Python suite and an isolated local runner smoke test without
  private images in committed fixtures. On this machine, perform a real local
  analysis and inspect masks before accepting any time trend.
- Verify the packaged installer size and installed runtime separately. Do not
  claim that a source-level test proves the installed UI or optional GPU setup.
