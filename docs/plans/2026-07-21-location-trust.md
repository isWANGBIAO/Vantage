# Generic Trusted Location Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Replace hardcoded and blindly trusted locations with a metadata-based local trust gate that returns location unavailable instead of reporting or embedding an untrusted city.

**Architecture:** Normalize WinRT, browser, and explicit configuration inputs into `LocationSample` values and resolve them through one stateful `LocationTrustResolver`. AQI and EXIF request purpose-specific decisions; rejected samples never fall back to a hardcoded city or stale coordinate.

**Tech Stack:** Python 3.11 dataclasses and FastAPI, WinRT `winsdk`, React 19 browser geolocation, Node test runner, pytest.

---

### Task 1: Add the platform-independent location trust resolver

**Files:**
- Create: `src/services/location_trust.py`
- Create: `tests/test_location_trust.py`

**Step 1: Write failing unit tests**

Add focused tests for:

```python
def test_default_and_ip_sources_are_rejected_even_with_small_accuracy(): ...
def test_satellite_and_wifi_samples_are_trusted_for_aqi_and_exif(): ...
def test_cellular_is_only_trusted_for_aqi(): ...
def test_browser_requires_high_accuracy(): ...
def test_invalid_remote_stale_and_future_samples_are_unknown(): ...
def test_implausible_short_interval_jump_is_rejected(): ...
def test_long_gap_allows_a_new_trusted_baseline(): ...
```

Use an injectable `now` and independent resolver instances so tests do not depend on wall-clock or module globals.

**Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_location_trust.py -q
```

Expected: collection fails because `src.services.location_trust` does not exist.

**Step 3: Implement the minimal resolver**

Create:

```python
class LocationPurpose(str, Enum):
    AQI = "aqi"
    EXIF = "exif"

class LocationStatus(str, Enum):
    TRUSTED = "trusted"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class LocationSample:
    latitude: float
    longitude: float
    accuracy_m: float
    captured_at: datetime
    source: str
    is_remote_source: bool = False

@dataclass(frozen=True)
class LocationDecision:
    status: LocationStatus
    sample: LocationSample | None
    reason: str
```

Implement `LocationTrustResolver.resolve(sample, purpose, *, now=None)` with named constants:

- maximum age: 120 seconds
- future clock skew: 30 seconds
- continuity window: 300 seconds
- maximum plausible speed: 350 m/s
- EXIF accuracy: 1,000 m
- AQI accuracy: 5,000 m for metadata-rich sources
- browser accuracy: 1,000 m for both purposes

Accept explicit `configured`, `satellite`, and `wi_fi`; accept `cellular` only for AQI; reject `ip_address`, `default`, `unknown`, `obfuscated`, remote, invalid, stale, and future samples. Store the last accepted sample only for continuity checking; never return it as a fallback.

**Step 4: Verify GREEN**

```powershell
python -m pytest tests/test_location_trust.py -q
```

Expected: all resolver tests pass.

**Step 5: Commit**

```powershell
git add src/services/location_trust.py tests/test_location_trust.py
git commit -m "feat: add metadata-based location trust resolver" -m "Validate source, accuracy, freshness, remote status, and short-interval movement before AQI or EXIF can consume a coordinate. Keep the resolver city-independent and fail closed when evidence is insufficient."
```

### Task 2: Feed WinRT metadata into the resolver

**Files:**
- Modify: `src/manager/get_location.py`
- Modify: `tests/test_get_location_save_image.py`

**Step 1: Write failing integration tests**

Add fake WinRT positions that prove:

- a current Wi-Fi sample returns its coordinates for EXIF;
- a current Windows `DEFAULT` sample returns `(None, None)`;
- a remote or stale WinRT sample returns `(None, None)`;
- an explicit `VANTAGE_STATIC_*` pair remains an accepted opt-in override;
- missing WinRT metadata fails closed rather than assuming trust.

Patch a dedicated resolver per test so continuity state cannot leak.

**Step 2: Verify RED**

```powershell
python -m pytest tests/test_get_location_save_image.py -q
```

Expected: new metadata trust assertions fail because `get_location()` still returns raw coordinates.

**Step 3: Implement the WinRT adapter**

- Add a helper that converts `Geocoordinate` metadata into `LocationSample`.
- Map WinRT enum names to normalized lowercase source names.
- Add `get_trusted_location(purpose=LocationPurpose.EXIF, resolver=None)`.
- Preserve `get_location()` as the existing EXIF-compatible tuple wrapper.
- Build explicit configured coordinates as a fresh `configured` sample.
- Log only source, accuracy, and decision reason; do not print raw coordinates.
- Convert API errors and rejected samples to `(None, None)` without interrupting capture.

**Step 4: Verify GREEN and nearby capture contracts**

```powershell
python -m pytest tests/test_get_location_save_image.py tests/test_screenshot_capture.py tests/test_take_photo.py -q
```

Expected: all tests pass.

**Step 5: Commit**

```powershell
git add src/manager/get_location.py tests/test_get_location_save_image.py
git commit -m "fix: validate Windows location metadata before EXIF" -m "Reject default, remote, stale, and incomplete WinRT positions while preserving explicit static overrides. Keep image capture available when coordinates are unavailable and avoid logging raw coordinates."
```

### Task 3: Remove the AQI city fallback and validate browser samples

**Files:**
- Modify: `src/server.py`
- Create: `tests/test_aqi_location_trust.py`
- Modify: `tests/test_backend_path_resolution.py`

**Step 1: Write failing endpoint tests**

Cover these behaviors:

```python
def test_aqi_without_trusted_location_is_unavailable_and_does_not_call_upstream(): ...
def test_aqi_rejects_browser_coordinates_without_accuracy_and_timestamp(): ...
def test_aqi_rejects_low_accuracy_browser_coordinates(): ...
def test_aqi_uses_a_fresh_high_accuracy_browser_sample(): ...
def test_aqi_can_use_a_trusted_backend_location_when_browser_data_is_missing(): ...
def test_aqi_upstream_timeout_preserves_unavailable_response_contract(): ...
```

Assert unavailable payloads keep `aqi`, `city`, `level`, `color`, `status`, `lat`, and `lon`, with coordinates set to `None`. Assert `requests.get` is never called for rejected locations.

**Step 2: Verify RED**

```powershell
python -m pytest tests/test_aqi_location_trust.py tests/test_backend_path_resolution.py -q
```

Expected: hardcoded SJTU fallback and raw lat/lon acceptance cause failures.

**Step 3: Implement endpoint trust handling**

- Extend `/api/aqi` with optional `accuracy` and `timestamp_ms` query fields.
- Normalize a complete browser request into a `browser` `LocationSample`.
- Resolve it for AQI; if absent or rejected, attempt a current trusted backend AQI location.
- If neither is trusted, return `status="unavailable"`, `city="Location unavailable"`, and null coordinates without calling Open-Meteo.
- Remove all SJTU coordinates and comments.
- Preserve the existing success and upstream-error response keys.

**Step 4: Verify GREEN**

```powershell
python -m pytest tests/test_aqi_location_trust.py tests/test_backend_path_resolution.py -q
```

Expected: all AQI tests pass.

**Step 5: Commit**

```powershell
git add src/server.py tests/test_aqi_location_trust.py tests/test_backend_path_resolution.py
git commit -m "fix: fail closed when AQI location is untrusted" -m "Remove the Shanghai fallback, require browser accuracy and timestamp metadata, and skip Open-Meteo requests when neither browser nor backend can provide a trusted current position."
```

### Task 4: Send browser accuracy and timestamp

**Files:**
- Create: `src/webapp/src/utils/locationSample.js`
- Create: `src/webapp/src/utils/locationSample.test.js`
- Modify: `src/webapp/src/components/Dashboard.jsx`
- Modify: `src/webapp/src/components/Dashboard.test.js`

**Step 1: Write failing frontend tests**

Test a pure helper that:

- produces `lat`, `lon`, `accuracy`, and `timestamp_ms` for a complete browser position;
- rejects non-finite coordinates, non-positive accuracy, and invalid timestamps;
- URL-encodes the accepted values without adding a city or IP-derived fallback.

Update the Dashboard contract test to require `accuracy` and `timestamp` forwarding.

**Step 2: Verify RED**

```powershell
npm --prefix src/webapp test -- --run src/utils/locationSample.test.js src/components/Dashboard.test.js
```

Expected: helper module is missing and Dashboard does not forward metadata.

**Step 3: Implement the minimal frontend adapter**

- Add `buildBrowserLocationQuery(position)` as a pure helper.
- Change Dashboard to pass the complete `position` object into `fetchAqiBackend`.
- Call `/api/aqi` without query parameters when the helper rejects the sample.
- Keep the existing permission and hidden-dashboard policy unchanged.

**Step 4: Verify GREEN**

```powershell
npm --prefix src/webapp test -- --run
```

Expected: all frontend tests pass.

**Step 5: Commit**

```powershell
git add src/webapp/src/utils/locationSample.js src/webapp/src/utils/locationSample.test.js src/webapp/src/components/Dashboard.jsx src/webapp/src/components/Dashboard.test.js
git commit -m "feat: forward browser location confidence metadata" -m "Send accuracy and capture time with Dashboard coordinates so the backend can distinguish high-confidence browser fixes from coarse IP or proxy-derived positions."
```

### Task 5: Document the policy and verify release contracts

**Files:**
- Modify: `.env.example`
- Modify: `README.md` only if the existing configuration section documents location behavior
- Modify: runtime packaging tests only if the new service is not already included by package discovery

**Step 1: Add or update contract tests before production packaging changes**

If packaging does not discover `src/services/location_trust.py`, first add a failing assertion to the appropriate runtime packaging test. Do not add packaging code when discovery already works.

**Step 2: Update public configuration documentation**

Explain that static coordinates are explicit opt-in overrides. State that the default behavior uses trustworthy platform metadata and returns unavailable instead of guessing a city.

**Step 3: Run targeted verification**

```powershell
python -m pytest tests/test_location_trust.py tests/test_get_location_save_image.py tests/test_aqi_location_trust.py tests/test_backend_path_resolution.py tests/test_screenshot_capture.py tests/test_take_photo.py tests/test_backend_runtime_packaging.py tests/test_verify_backend_runtime.py -q
npm --prefix src/webapp test -- --run
npm --prefix src/webapp run lint
npm --prefix src/webapp run build
```

**Step 4: Run full verification**

```powershell
python -m pytest -q
```

Expected: all Python and frontend checks pass with no tracked build artifacts.

**Step 5: Commit**

```powershell
git add .env.example README.md tests src/core/backend_runtime_packaging.py
git commit -m "docs: explain fail-closed location behavior" -m "Document explicit location overrides and the default privacy-preserving behavior while keeping runtime packaging coverage aligned with the new trust service."
```

### Task 6: Final review and installed-flow verification

**Files:**
- Review all changes since the design commit.

**Step 1: Request final spec and quality review**

Compare the branch with `main` and resolve every critical or important issue.

**Step 2: Run `RUN.bat` naturally**

```powershell
RUN.bat
```

Do not impose a short timeout. Confirm the packaged app installs and launches.

**Step 3: Verify the installed application**

- `/api/status` remains healthy.
- `/api/health/sedentary` remains healthy.
- `/api/aqi` without a trustworthy location returns unavailable and never identifies SJTU.
- runtime manifest and package contain `location_trust.py` as required.
- no private coordinates, runtime logs, screenshots, or generated diagnostics are tracked.

**Step 4: Commit any review-only corrections with a detailed message**

Do not create an empty commit.
