# Dependency security refresh evidence

## Scope and resolution

The starting full npm audit reported21 findings:10moderate and11high. Production-only audit reported0. These findings were in development, build and download dependencies; this is not evidence of21 independently exploitable application defects.

| Reported package or chain | Resolved version / action |
| --- | --- |
| @humanfs/node | 0.16.8 |
| @xmldom/xmldom | 0.8.15 |
| axios | 1.20.0 |
| baseline-browser-mapping | 2.11.30 |
| brace-expansion | 1.1.21,2.1.7,5.0.12; all nested copies checked |
| browserslist | 4.29.4 |
| fast-uri | 3.1.9 |
| follow-redirects | 1.16.1 |
| http-cache-semantics | 4.3.0 |
| joi | 18.3.0 |
| js-yaml | 4.3.2 |
| source-map-js | 1.2.2 |
| undici | 6.29.1,7.30.1 |
| sprintf-js,roarr,global-agent,@electron/get,app-builder-lib,dmg-builder,electron-builder-squirrel-windows,electron-builder | Remove sprintf-js via precisely scoped roarr3.3.0 override; preserve global-agent3.0.0, downloader3.1.0 and builder26.15.3. These eight reported entries include parent-chain findings. |

All production lockfile entries and direct development tool versions remain unchanged. Electron stays42.11.14. No audit exemption, forced downgrade or TLS validation bypass was added.

The rejected global-agent4.1.3 candidate reached audit0 but failed real HTTPS CONNECT requests with a configured trusted CA and changed explicit-empty HTTPS proxy fallback. It is not the shipped solution. The accepted override only changes the logger below the original proxy transport.

## Regression evidence

- Original lock:16expected security-test failures and1preservation pass. The final17security tests pass.
- Transport-preserving version/scope checks also failed against the rejected candidate before passing with the accepted solution.
-11real builder-resolved compatibility tests pass: authenticated HTTP proxy, HTTPS CONNECT with explicit trusted CA, rejection of untrusted TLS, NO_PROXY, direct requests, unset/empty HTTPS fallback, repeat bootstrap, enabled logger and actual plist XML roundtrip.
- Tests use only synthetic loopback credentials/certificates and bounded child processes. They assert bootstrap state because the downloader can swallow initialization errors.
- The actual14global-agent logging calls use fixed message literals. Hostile precision strings pass as URL/context data and fixed-format arguments in the enabled logger test. A separate bounded probe found that fast-printf still raises RangeError when an arbitrary oversized precision is itself used as the format. This work does not claim arbitrary untrusted format strings are safe.

## Local integration results

| Check | Result |
| --- | --- |
| Independent clean npm ci and npm ls --all | Pass; no invalid, missing or extraneous dependencies |
| Full npm audit / npm audit --omit=dev | 0 /0 findings |
| Frontend lint, production build | Pass |
| Frontend tests, final run | 677passed |
| Never Stop tests | 174passed |
| Electron production protocol smoke | Pass |
| Electron unified UI smoke | 8primary pages;0renderer errors |
| Packaging helper safety tests | 6passed; also wired into frontend CI |
| Ruff | Pass |
| Python tests | 2098passed,101subtests passed,16platform skips; one existing anyio deprecation warning |

## Windows packaging boundary

The standalone command `node src/webapp/scripts/smoke-dependency-packaging.cjs` compiled Windows x64 unpacked and NSIS artifacts with the unchanged builder, Electron, app identity, V icon, real CLI files, NSIS include and custom binary checksum. It used a complete temporary config file, not a config object merged with production resource arrays. Output, caches and temporary files stayed in an owned temporary directory and were removed after completion.

The final compile exited0; the NSIS executable was110,988,848bytes with an MZ header. Archive checks verified production main/preload/dist/index/icon bytes, Never Stop and ssh2 presence, exact CLI resources, and exclusion of roarr,sprintf-js,global-agent,electron-builder and app-builder-lib from app.asar.

The backend resource was deliberately synthetic, signing was disabled for the disposable worker, and no installer or application artifact was launched. This validates the affected downloader/packager chain, not full real-backend installation acceptance. No production deployment, application installation or security-setting change was performed.

Remote PR and exact-main CI evidence must be recorded in the PR after those runs finish; local results do not substitute for that gate.
