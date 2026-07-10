# Truthful README Badge Wall Implementation Plan

**Goal:** Add a complete, polished, and evidence-backed badge wall to Vantage and preserve its truthfulness contract in `AGENTS.md`.

**Architecture:** Use three centered HTML badge rows under the README title. Live repository state comes from GitHub Actions and Shields.io GitHub endpoints, while supported-stack badges mirror versions or platforms declared in tracked files. Repository guidance prevents future maintainers from adding unsupported claims.

**Tech Stack:** Markdown/HTML, GitHub Actions status badges, Shields.io GitHub metadata badges.

---

### Task 1: Add the badge wall and repository policy

**Files:**
- Modify: `README.md:1`
- Modify: `AGENTS.md`

**Step 1: Confirm all badge claims have tracked evidence**

Run:

```powershell
rg -n -g "README.md" -g "*.yml" -g "requirements*.txt" -g "package.json" 'name: CI|name: CodeQL|Python 3.11|Node.js 22|Windows and macOS|fastapi==|"react"|"electron"' .
```

Expected: existing CI/CodeQL workflows, platform support, Python 3.11, Node.js
22, FastAPI 0.139.0, React 19.2.7, and Electron 42.6.0 are all present.

**Step 2: Add three centered badge rows below the title**

Add these badge groups with consistent `flat-square` styling:

- Health: CI, CodeQL, Release, Downloads, License.
- Stack: Windows, macOS, Python 3.11, Node.js 22, FastAPI 0.139.0,
  React 19.2.7, Electron 42.6.0.
- Activity: Last Commit, Contributors, Issues, Pull Requests, Stars, Forks.

Use GitHub-backed dynamic endpoints for health and activity. Link each badge to
the relevant workflow, release, license, repository page, or upstream project.

**Step 3: Add badge truthfulness guidance to `AGENTS.md`**

Require live status badges to reference real automation/metadata, static stack
badges to match tracked configuration, removal of stale badges, and an explicit
ban on fabricated passing, coverage, quality, security, compliance, version,
download, and support claims.

**Step 4: Inspect the diff**

Run:

```powershell
git diff -- README.md AGENTS.md
git diff --check
```

Expected: only the approved badge wall and policy are added, with no whitespace
errors.

**Step 5: Commit**

```powershell
git add README.md AGENTS.md
git commit -m "docs: add truthful project badge wall"
```

### Task 2: Validate badge sources and public rendering

**Files:**
- Verify: `README.md`
- Verify: `AGENTS.md`

**Step 1: Parse every badge image and target URL**

Run a PowerShell validation script that extracts every `<a href>` and `<img
src>` from the badge block, requires HTTPS, and checks for duplicate or missing
links.

Expected: 18 unique badge images and 18 corresponding target links.

**Step 2: Check public HTTP responses**

Request every badge image and target URL with redirects enabled.

Expected: every URL returns a successful 2xx response after redirects and every
badge image has an SVG content type.

**Step 3: Recheck live GitHub state**

Run:

```powershell
gh api "repos/isWANGBIAO/Vantage/actions/workflows/ci.yml/runs?branch=main&event=push&per_page=1"
gh api "repos/isWANGBIAO/Vantage/actions/workflows/codeql.yml/runs?branch=main&per_page=1"
gh api repos/isWANGBIAO/Vantage/releases/latest
```

Expected: CI and CodeQL latest runs are completed successfully and the latest
release is the version displayed by the release badge.

**Step 4: Run final repository checks**

```powershell
python -m pytest -q
npm --prefix src/webapp test
npm --prefix src/webapp run build
git diff --check HEAD~1 HEAD
git status --short --branch
```

Expected: Python tests, frontend tests, and frontend build pass; the branch is
clean and contains only intentional commits.
