# README Badge Wall Design

## Goal

Give the public Vantage README a complete, polished badge wall while ensuring
that every badge is backed by current repository configuration or live GitHub
data.

## Layout

Place three centered rows directly below the `# Vantage` heading:

1. Project health: CI, CodeQL, latest release, release downloads, and license.
2. Supported stack: Windows, macOS, Python 3.11, Node.js 22, FastAPI, React,
   and Electron.
3. Repository activity: last commit, contributors, open issues, open pull
   requests, stars, and forks.

Use a consistent `flat-square` Shields.io style. Each badge links to the most
relevant GitHub page or upstream technology page. Dynamic project claims must
come from GitHub Actions or GitHub repository metadata; stack badges may be
static only when the declared support or version is present in tracked files.

## Truthfulness Rules

- CI and CodeQL badges point to the existing workflow files and the `master`
  branch.
- Release, download, license, and activity badges use live GitHub metadata.
- Python and Node.js versions match README requirements and CI setup files.
- React and Electron are present in `src/webapp/package.json`; FastAPI is
  present in the tracked Python requirements.
- No coverage, quality score, compliance, or readiness badge is added unless a
  real automated measurement exists.
- `AGENTS.md` records these rules so future edits preserve the contract.

## Validation

Validate tracked-source evidence, HTTP availability of every image and target
URL, consistency of badge styling, README placement, and a clean Markdown/git
diff. Existing Python and frontend tests/build establish that the starting
branch remains healthy; badge changes themselves are verified with a focused
link/source audit.
