# Dependency security refresh Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove all21 currently reported npm dependency audit findings without downgrading the current Electron/builder toolchain or weakening checks.

**Architecture:** Refresh vulnerable indirect dependencies within their existing compatible ranges. Keep electron-builder26.15.3, Electron42.11.14, @electron/get3.1.0 and global-agent3.0.0. Narrowly override roarr to3.3.0 only below the builder downloader's global-agent3.0.0, removing sprintf-js without changing proxy transport. Test the actual builder-resolved downloader with local HTTP/HTTPS proxy fixtures and ensure production roots stay unchanged. Do not use audit exemptions, forced downgrade, TLS bypass, deployment or installation.

**Rejected candidate:** Updating global-agent to4.1.3 produced audit0 but failed real HTTPS CONNECT tests with an explicit trusted CA: its agent forwarded TLS options only when `secureEndpoint` was set, whereas the exercised Node HTTPS agent supplied `protocol: 'https:'`. It also changed explicit-empty HTTPS proxy fallback. This candidate must not ship; retain the original transport and fix the logger dependency alone.

**Formatter boundary:** roarr3.3.0 removes the reported sprintf-js dependency, not every possible misuse of a printf API. A bounded child check found that an arbitrary oversized precision used as a format still raises RangeError in fast-printf. All14 actual global-agent3 logging calls use fixed message literals; external URLs, errors, headers and settings are context data. Enabled-logger regression tests pass hostile precision strings through that real context/URL path and through a fixed `%s` format. Do not describe this change as making arbitrary untrusted format strings safe.

**Tech Stack:** npm lockfile v3, Node tests, Electron Builder, pytest, existing CI/CodeQL.

---

### Task 1: Security regression and compatible dependency resolution

**Files:** `src/webapp/package.json`, `src/webapp/package-lock.json`, `src/webapp/src/utils/dependencySecurity.test.cjs`.

1. Record full audit21 (10moderate/11high), production-only0 and actual dependency parents. Add lockfile regression tests for every advisory security floor, scoped roarr3.3.0 and absence of sprintf-js, plus preserved production roots and current builder versions. Run before updates and record expected failures.
2. Add only `overrides: { "@electron/get@3.1.0": { "global-agent@3.0.0": { "roarr": "3.3.0" } } }` to package.json via apply_patch. Use targeted npm resolution of the vulnerable indirect packages to regenerate the lockfile; no force/audit-disable/unrelated tool major upgrades.
3. Ensure @humanfs/node>=0.16.8, xmldom>=0.8.15 within0.8, axios>=1.20, baseline>=2.11, brace-expansion safe patch in each major, browserslist>=4.28.7, fast-uri>=3.1.8, follow-redirects>=1.16.1, http-cache-semantics>4.2.0, joi>=18.2.9, js-yaml>=4.3.2, source-map-js>=1.2.2 and undici6>=6.28.1/7>=7.29.1. Verify actual resolved versions, not just manifest intent.
4. Run clean npm ci and full/production npm audit without suppressing findings. Inspect lock diff and npm ls for invalid dependencies. Detailed commit with red/green and resolution evidence.

### Task 2: Real downloader and serialization compatibility

**Files:** `src/webapp/src/utils/dependencyProxyCompatibility.test.cjs` and owned synthetic test fixtures only.

1. In fresh child processes resolve get3 through app-builder-lib rather than top-level get5. Assert the actual global-agent version/bootstrap state and request routing, not merely that initializeProxy returns (it swallows errors).
2. Exercise local HTTP and HTTPS CONNECT proxies, proxy authentication, NO_PROXY/direct access, repeat bootstrap, default TLS rejection and explicit test-CA success. Use only generated/synthetic credentials/certificates; no real proxy/API/camera/user data. Never disable certificate verification to make a test pass.
3. Preserve the existing explicit-empty HTTPS proxy fallback behavior. Exercise enabled logger output and formatting through the actual logger export; inspect the replacement formatter's response to the original oversized-precision vulnerability in a bounded child process.
4. Run plist parse/build roundtrip through the actual builder dependency to cover xmldom changes.
5. Coordinate tests against the old lock before Task1 updates; report precise expected failures. After updates run focused tests and lint. Commit only owned tests/fixtures with detailed evidence.

### Task 3: Integration, packaging and delivery

1. Run frontend check, Never Stop suite, actual Electron protocol/UI smokes, full Python/Ruff, audit and cache/packaging regressions. No test exclusion, increased timeout or security bypass.
2. Compile a temporary Windows unpacked/NSIS fixture using the existing config/icon/customNSIS checksum but a clearly synthetic backend resource; output only to a fresh temp directory. Never launch the artifact or installer. Check asar includes real production dependencies/entrypoints and excludes vulnerable build-only dependencies; do not call this full real-backend installation acceptance.
3. Independent spec then quality review. Create draft PR, wait for all necessary CI/CodeQL at exact head, ready/merge normally without bypass or force push.
4. Fetch actual remote main SHA, rerun its CI/CodeQL with manual entries if needed, verify all required jobs and clean root state. Run npm ci/audit on final main and disclose exact zero/nonzero results. Do not install/deploy the application.
