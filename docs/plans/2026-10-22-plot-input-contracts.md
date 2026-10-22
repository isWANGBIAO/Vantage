# Plot input integrity repair

Scope: issues #53, #67, #72, #117, #118, #119 and #120. Depends on
the finance and data-input repairs in PRs #144 and #151.

## Design and sequence

1. Reproduce row-order dependent time averages, undated body measurements,
   missing heart-rate interpolation, malformed Mi exports, stale filename
   assumptions and next-day food association with synthetic inputs.
2. Share the strict duration parser, normalize and sort real dates before
   calculations, and keep missing observations as explicit chart gaps.
3. Discover exports by schema/type, isolate invalid records with basename and
   CSV row diagnostics, and deduplicate overlapping exports by observation time.
4. Join health outcomes by calendar date rather than exploded food row order.
5. Independently review, add visible skipped-measurement warnings, then run the
   full Python suite and frontend lint/tests/build. Render a real ECharts SVG
   to verify missing heart-rate observations do not become connecting lines.

## Evidence

- Initial eight parser/statistic regressions failed before implementation.
- Independent review identified missing diagnostics for #67 and #118; both
  additional regressions failed before the follow-up changes and then passed.
- Full Python: 1870 passed, 16 skipped, 98 subtests before the diagnostic-only
  follow-up; focused plotting suite after follow-up: 25 passed.
- Frontend: 611 passed, lint/build passed. Real ECharts SVG regression passed.
- Inputs are synthetic; no personal exports, API calls or model inference.

Issue closure remains conditional on the integrated main commit and CI.
