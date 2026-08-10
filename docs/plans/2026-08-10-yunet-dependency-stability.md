# YuNet and Dependency Stability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reject observed empty-workstation YuNet hallucinations, integrate the current frontend and Python dependency groups, and ship a synchronized Vantage 1.0.67 release.

**Architecture:** Keep the existing YuNet-only, one-hertz presence pipeline and change only its normalized foreground boundary from 0.5% to 1.0%. Bring the two Dependabot groups into the same feature branch, repair the Electron/Node contract test and README together, validate OpenCV 4.14 against presence behavior, then merge, tag, release, build, install, and probe the packaged runtime from the same commit.

**Tech Stack:** Python 3.11/3.13, OpenCV YuNet ONNX, pytest, Electron 42.8, React 19.2.8, Node 24.18, npm, GitHub Actions, PowerShell, electron-builder.

---

### Task 1: Raise the foreground boundary with TDD

**Files:**
- Modify: `tests/test_person_detection.py:168-205`
- Modify: `tests/test_person_detection_model_config.py:25`
- Modify: `src/services/person_detection.py:19-21,264-291`

**Step 1: Write the failing boundary tests**

Change the synthetic 640x480 boundary rows to exercise 1.0% exactly:

```python
def test_foreground_area_threshold_includes_exact_boundary(self):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    accepted = _FakeFaceDetector(np.vstack([_face_row(width=64, height=48)]))
    rejected = _FakeFaceDetector(np.vstack([_face_row(width=63, height=48)]))

    self.assertEqual(
        person_detection.detect_foreground_presence_face_boxes(
            frame, model=accepted
        ),
        [(10, 20, 74, 68)],
    )
    self.assertEqual(
        person_detection.detect_foreground_presence_face_boxes(
            frame, model=rejected
        ),
        [],
    )
```

Add an explicit regression representing the observed upper empty-scene area:

```python
def test_observed_empty_scene_sized_detection_is_not_foreground(self):
    detector = _FakeFaceDetector(
        np.vstack([_face_row(width=40, height=50, confidence=0.62)])
    )
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    self.assertEqual(
        person_detection.detect_foreground_presence_face_boxes(
            frame, model=detector
        ),
        [],
    )
```

Update `test_person_detection_model_config.py` to expect `0.01`.

**Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_person_detection.py tests/test_person_detection_model_config.py -q
```

Expected: failures show the old `0.005` constant still accepts the 0.65% and just-below-1.0% rows.

**Step 3: Implement the minimal boundary change**

Set:

```python
PRESENCE_MIN_FACE_AREA_RATIO = 0.01
```

Update the function docstring to say 1.0%. Do not change confidence, frontal geometry, selection, timing, or error semantics.

**Step 4: Run focused presence tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_person_detection.py tests/test_person_detection_model_config.py tests/test_take_photo.py tests/test_face_live_endpoint.py tests/test_sedentary_monitor.py -q
```

Expected: all pass, including moderate-confidence non-frontal presence and the one-second/one-minute photo contract.

**Step 5: Commit**

```powershell
git add src/services/person_detection.py tests/test_person_detection.py tests/test_person_detection_model_config.py
git commit -m "fix: reject sub-foreground YuNet detections" -m "Raise the normalized foreground face boundary to 1.0% while preserving 0.50 confidence, non-frontal presence, largest-face selection, one-hertz sampling, and absence timing contracts."
```

### Task 2: Align current YuNet documentation

**Files:**
- Modify: `src/models/README.md:9-14`
- Modify: `docs/plans/2026-07-15-yunet-only-foreground-presence-design.md:3-5`

**Step 1: Update current model documentation**

Change the model README boundary from 0.5% to 1.0%. Add a status note to the 2026-07-15 design that its 0.5% boundary was refined by `2026-08-10-yunet-dependency-stability-design.md`; keep the old evidence intact as historical context.

**Step 2: Verify stale current references**

Run:

```powershell
rg -n "0\.5%|0\.005" src/services/person_detection.py src/models/README.md tests/test_person_detection_model_config.py
```

Expected: no matches.

**Step 3: Commit**

```powershell
git add src/models/README.md docs/plans/2026-07-15-yunet-only-foreground-presence-design.md
git commit -m "docs: record refined YuNet foreground boundary" -m "Point the original YuNet-only design to the approved 1.0% refinement and keep the model documentation consistent with runtime behavior."
```

### Task 3: Repair and integrate the frontend dependency contract

**Files:**
- Modify: `tests/test_ci_workflow.py:27-70`
- Modify: `README.md:14-17`
- Modify via Dependabot commit: `src/webapp/package.json`
- Modify via Dependabot commit: `src/webapp/package-lock.json`

**Step 1: Write the failing Electron contract**

Change `expected_electron_version` to `42.8.0`, make the workflow failure message interpolate that variable, and update README assertions to 42.8.0.

**Step 2: Run the contract and verify RED**

Run:

```powershell
python -m pytest tests/test_ci_workflow.py::test_frontend_workflows_pin_electron_node_runtime -q
```

Expected: FAIL because the package and lockfile still contain Electron 42.6.1.

**Step 3: Integrate the reviewed Dependabot frontend commit**

Run:

```powershell
git cherry-pick --no-commit c73b603b7e004644b01a2573e01d05ddfb6a0a66
```

This updates React, React DOM, their type packages, and Electron only. Update the Electron README badge to 42.8.0; keep Node 24.18.0 because Electron 42.8.0 embeds the same Node line.

**Step 4: Verify frontend and contract tests**

Run:

```powershell
python -m pytest tests/test_ci_workflow.py -q
npm --prefix src/webapp ci
npm --prefix src/webapp test -- --run
npm --prefix src/webapp run lint
npm --prefix src/webapp run build
```

Expected: all pass; the Electron contract no longer fails Python 3.11 or 3.13 CI.

**Step 5: Commit**

```powershell
git add README.md tests/test_ci_workflow.py src/webapp/package.json src/webapp/package-lock.json
git commit -m "build: update frontend dependency contract" -m "Integrate the current React and Electron dependency group, align the Electron 42.8.0 package, lockfile, badge, and CI contract, and retain Node 24.18.0."
```

### Task 4: Integrate and validate the Python dependency group

**Files:**
- Modify via Dependabot commit: `requirements.txt`
- Modify via Dependabot commit: `requirements-ci.txt`
- Modify via Dependabot commit: `requirements-backend-runtime-gpu.txt`

**Step 1: Integrate the reviewed Dependabot Python commit**

Run:

```powershell
git cherry-pick --no-commit df230300949cba8b1966cbb56168a7af03816bf8
```

Confirm the diff contains only the 16 declared dependency updates and specifically pins OpenCV 4.14.0.94 consistently in source, CI, and packaged-runtime requirements.

**Step 2: Install the updated CI dependencies in an isolated verification venv**

Create a temporary local verification environment rather than mutating the machine-wide Python environment:

```powershell
py -3.11 -m venv .venv-ci-verify
.\.venv-ci-verify\Scripts\python.exe -m pip install --upgrade pip
.\.venv-ci-verify\Scripts\python.exe -m pip install -r requirements-ci.txt
```

**Step 3: Verify OpenCV and the presence suite**

Run:

```powershell
.\.venv-ci-verify\Scripts\python.exe -c "import cv2; assert cv2.__version__ == '4.14.0'"
.\.venv-ci-verify\Scripts\python.exe -m pytest tests/test_person_detection.py tests/test_person_detection_model_config.py tests/test_take_photo.py tests/test_face_live_endpoint.py tests/test_runtime_model_prewarm.py tests/test_backend_runtime_packaging.py tests/test_verify_backend_runtime.py -q
```

Expected: all pass under OpenCV 4.14.

**Step 4: Run the local private numeric probe**

Without copying, modifying, or committing any image, run the two known empty-scene files through `detect_foreground_presence_face_boxes` using Unicode-safe `numpy.fromfile` plus `cv2.imdecode`.

Expected: both return `[]` with the 1.0% boundary.

**Step 5: Commit**

```powershell
git add requirements.txt requirements-ci.txt requirements-backend-runtime-gpu.txt
git commit -m "build: update Python dependency group" -m "Integrate 16 reviewed Python dependency updates, including OpenCV 4.14.0.94 across development, CI, and packaged-runtime manifests."
```

### Task 5: Prepare release 1.0.67

**Files:**
- Modify: `src/webapp/package.json:4`
- Modify: `src/webapp/package-lock.json:3,9`
- Modify: `README.md:108-119`

**Step 1: Write the failing release metadata expectation**

Run the existing release metadata test before the version bump to establish that the current source still describes 1.0.66. Then update the package and lockfile together:

```powershell
npm --prefix src/webapp version 1.0.67 --no-git-tag-version
```

Update README tag examples to `v1.0.67`.

**Step 2: Verify release metadata**

Run:

```powershell
python -m pytest tests/test_ci_workflow.py::test_release_metadata_matches_package_version -q
```

Expected: PASS with package, lockfile, README, and release workflow consistent.

**Step 3: Commit**

```powershell
git add src/webapp/package.json src/webapp/package-lock.json README.md
git commit -m "release: prepare Vantage 1.0.67" -m "Align package metadata and release documentation for the integrated YuNet and dependency stability release."
```

### Task 6: Run complete local verification

**Files:**
- No tracked changes expected.

**Step 1: Run all source tests and builds**

```powershell
python -m pytest -q
npm --prefix src/webapp test -- --run
npm --prefix src/webapp run lint
npm --prefix src/webapp run build
```

**Step 2: Run focused regression groups again**

```powershell
python -m pytest tests/test_person_detection.py tests/test_take_photo.py tests/test_face_live_endpoint.py tests/test_sedentary_monitor.py tests/test_renderer_camera_frame.py tests/test_server_startup_idempotence.py -q
python -m pytest tests/test_runtime_model_prewarm.py tests/test_backend_runtime_packaging.py tests/test_verify_backend_runtime.py tests/test_ci_workflow.py -q
```

**Step 3: Audit the branch**

```powershell
git status --short
git diff main...HEAD --check
git log --oneline main..HEAD
```

Expected: clean worktree, no whitespace errors, detailed commits only in scope.

### Task 7: Review, publish, and merge the integrated PR

**Files:**
- No additional files unless review finds a tested defect.

**Step 1: Perform specification and code-quality review**

Use `superpowers:requesting-code-review`. Resolve only evidence-backed findings; for any code change, return to a failing test first.

**Step 2: Push and create a ready PR**

```powershell
git push -u origin fix/yunet-dependency-contracts
gh pr create --base main --head fix/yunet-dependency-contracts --title "fix: stabilize YuNet presence and dependency updates" --body-file <prepared-public-pr-body>
```

The PR body must summarize the 1.0% evidence without private paths or images, list dependency versions, and include exact verification results.

**Step 3: Wait for required CI**

Poll rather than using a fixed sleep:

```powershell
gh pr checks <number> --watch
```

Required: Python 3.11, Python 3.13, frontend tests/build, Python CodeQL, and JavaScript/TypeScript CodeQL all pass. A first Python 3.13 cache miss may spend approximately 18 minutes compiling winsdk; distinguish active compilation from failure.

**Step 4: Merge normally and close superseded PRs**

```powershell
gh pr merge <number> --merge --delete-branch
gh pr close 23 --comment "Superseded by the integrated, tested 1.0.67 dependency release."
gh pr close 25 --comment "Superseded by the integrated, tested 1.0.67 dependency release."
```

Do not close #23 or #25 until the integrated PR is merged.

### Task 8: Tag, release, build, install, and probe 1.0.67

**Files:**
- No tracked changes expected after merge.

**Step 1: Synchronize local main and tag the merge**

```powershell
git -C D:\WANGBIAO\code\Vantage fetch --prune origin
git -C D:\WANGBIAO\code\Vantage pull --ff-only origin main
git -C D:\WANGBIAO\code\Vantage tag -a v1.0.67 -m "Vantage 1.0.67"
git -C D:\WANGBIAO\code\Vantage push origin v1.0.67
```

Verify the tag targets the merged `main` commit.

**Step 2: Wait for and verify the Release workflow**

Use `gh run watch` for the tag-triggered release. Confirm the release contains the installer, blockmap, and `SHA256SUMS.txt`, and independently recalculate SHA-256 values after downloading the assets.

**Step 3: Run the full Windows packaged flow**

From synchronized `main`, run `RUN.bat` without a short timeout or forced termination and let build, install, and launch finish naturally.

**Step 4: Probe the installed application**

After two minutes of stable startup, verify:

- installed UI and `/api/status` report version 1.0.67 and the merged commit;
- `/api/health/sedentary` and `/api/aqi` retain their response contracts;
- the packaged runtime manifest contains YuNet and OpenCV 4.14 but no YOLOX;
- no coordinates, private image paths, or new exceptions appear in logs;
- the two private empty-scene frames return no foreground box under the packaged Python runtime.

**Step 5: Report final synchronization**

Record the merged PR, merge commit, tag, release workflow, asset hashes, installed version/commit, source test counts, and any remaining manual camera observation that cannot be fabricated while the workstation is unattended.
