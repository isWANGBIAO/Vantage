"""Project task summaries and source-control activity."""

import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.core.config import Config

from . import source_paths as _source_paths

router = APIRouter()

PROJECT_ACTIVITY_SNAPSHOT_NAME = "project_activity.json"

def _get_project_progress_root():
    configured_root = Path(Config.get_project_root())
    if (configured_root / "Prompt_Project_Management.md").exists():
        return configured_root

    current_dir = Path(os.path.dirname(os.path.abspath(_source_paths.SERVER_FILE)))
    return current_dir.parent

def _find_git_root(start_dir):
    current = Path(start_dir).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None

def _decode_process_output(value):
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("gbk", errors="replace")

def _load_project_activity_snapshot(project_root):
    snapshot_path = Path(project_root) / PROJECT_ACTIVITY_SNAPSHOT_NAME
    if not snapshot_path.exists():
        return []

    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Project activity snapshot parsing error: {exc}")
        return []

    commits = payload.get("commits", [])
    if not isinstance(commits, list):
        return []

    normalized_commits = []
    for commit in commits:
        if not isinstance(commit, dict):
            continue
        commit_hash = str(commit.get("hash", "")).strip()
        date_text = str(commit.get("date", "")).strip()
        message = str(commit.get("message", "")).strip()
        if commit_hash and date_text and message:
            normalized_commits.append({"hash": commit_hash, "date": date_text, "message": message})
    return normalized_commits

def _load_recent_git_commits(project_root, days=14):
    git_root = _find_git_root(project_root) or _find_git_root(Path.cwd())
    if git_root is None:
        return []

    recent_commits = []
    try:
        time_limit = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        git_cmd = ["git", "log", f'--since="{time_limit}"', "--pretty=format:%h|%ad|%s", "--date=short"]
        proc = subprocess.run(git_cmd, capture_output=True, cwd=git_root)

        if proc.returncode != 0 or not proc.stdout:
            return []

        out_text = _decode_process_output(proc.stdout)
        for line in out_text.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                recent_commits.append({
                    "hash": parts[0],
                    "date": parts[1],
                    "message": parts[2],
                })
    except Exception as e:
        print(f"Git log parsing error: {e}")

    return recent_commits

@router.get("/api/v1/projects/progress")
async def get_project_progress():
    """Parse Prompt_Project_Management.md and git logs to return project momentum."""
    try:
        project_root = _get_project_progress_root()
        md_file = project_root / "Prompt_Project_Management.md"

        completed_tasks = []
        pending_tasks = []
        current_project = "General"

        if md_file.exists():
            with open(md_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines:
                    line = line.strip()
                    # Detect Headers as project groups
                    if line.startswith("## ") or line.startswith("### ") or line.startswith("#### "):
                        cleaned_header = re.sub(r'^#+\s*', '', line)
                        if cleaned_header and "任务" in cleaned_header or "项目" in cleaned_header:
                             current_project = cleaned_header

                    # Detect completed tasks
                    elif line.startswith("- [X]") or line.startswith("- [x]"):
                        task_desc = line[5:].strip()
                        completed_tasks.append({"project": current_project, "task": task_desc, "status": "completed"})

                    # Detect pending tasks
                    elif line.startswith("- [ ]"):
                         task_desc = line[5:].strip()
                         pending_tasks.append({"project": current_project, "task": task_desc, "status": "pending"})

        # Calculate stats
        total_tasks = len(completed_tasks) + len(pending_tasks)
        completion_rate = (len(completed_tasks) / total_tasks) if total_tasks > 0 else 0

        # Git commits (last 14 days). Packaged builds fall back to a bundled snapshot.
        recent_commits = _load_recent_git_commits(project_root)
        if not recent_commits:
            recent_commits = _load_project_activity_snapshot(project_root)

        return {
            "tasks": {
                "completed": completed_tasks,
                "pending": pending_tasks
            },
            "commits": recent_commits,
            "stats": {
                "total_tasks": total_tasks,
                "completed_tasks": len(completed_tasks),
                "completion_rate": completion_rate
            }
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})
