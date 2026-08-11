from __future__ import annotations

import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
from typing import Iterable, Mapping, Sequence


BACKEND_ENVIRONMENT_STATE_NAME = ".vantage-backend-runtime-state.json"
BACKEND_ENVIRONMENT_STATE_SCHEMA_VERSION = 1
LEGACY_REQUIREMENTS_STAMP_NAME = ".requirements-backend-runtime-gpu.sha256"


def canonicalize_distribution_name(name: str) -> str:
    normalized = re.sub(r"[-_.]+", "-", str(name).strip()).lower()
    if not normalized:
        raise ValueError("distribution name must not be empty")
    return normalized


def normalize_distribution_closure(
    distributions: Iterable[str | Sequence[str] | Mapping[str, object]],
) -> list[str]:
    normalized: dict[str, str] = {}
    for distribution in distributions:
        if isinstance(distribution, str):
            name, separator, version = distribution.partition("==")
            if not separator:
                raise ValueError(
                    f"distribution entry must use exact name==version syntax: {distribution}"
                )
        elif isinstance(distribution, Mapping):
            name = str(distribution.get("name", ""))
            version = str(distribution.get("version", ""))
        else:
            if len(distribution) != 2:
                raise ValueError("distribution tuple must contain name and version")
            name, version = str(distribution[0]), str(distribution[1])

        canonical_name = canonicalize_distribution_name(name)
        exact_version = str(version).strip()
        if not exact_version:
            raise ValueError(f"distribution version must not be empty: {canonical_name}")
        previous = normalized.get(canonical_name)
        if previous is not None and previous != exact_version:
            raise ValueError(
                f"conflicting versions for {canonical_name}: {previous} and {exact_version}"
            )
        normalized[canonical_name] = exact_version

    return [f"{name}=={normalized[name]}" for name in sorted(normalized)]


def installed_distribution_closure() -> list[str]:
    return normalize_distribution_closure(
        {
            "name": distribution.metadata.get("Name") or distribution.name,
            "version": distribution.version,
        }
        for distribution in metadata.distributions()
    )


def current_python_identity() -> dict[str, str]:
    return {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "cache_tag": str(getattr(sys.implementation, "cache_tag", "")),
    }


def current_platform_identity() -> dict[str, str]:
    return {
        "sys_platform": sys.platform,
        "system": platform.system(),
        "machine": platform.machine(),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_requirements_sha256(
    core_requirements: str | Path,
    requirements: str | Path,
) -> str:
    inputs = [
        {
            "role": "core",
            "sha256": _sha256_file(Path(core_requirements).resolve()),
        },
        {
            "role": "overlay",
            "sha256": _sha256_file(Path(requirements).resolve()),
        },
    ]
    payload = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_backend_environment_state(
    core_requirements: str | Path,
    requirements: str | Path,
    *,
    python_identity: Mapping[str, object] | None = None,
    platform_identity: Mapping[str, object] | None = None,
    distributions: Iterable[str | Sequence[str] | Mapping[str, object]] | None = None,
) -> dict[str, object]:
    resolved_python_identity = dict(python_identity or current_python_identity())
    resolved_platform_identity = dict(platform_identity or current_platform_identity())
    resolved_distributions = normalize_distribution_closure(
        installed_distribution_closure() if distributions is None else distributions
    )
    return {
        "schema_version": BACKEND_ENVIRONMENT_STATE_SCHEMA_VERSION,
        "requirements_sha256": compute_requirements_sha256(
            core_requirements,
            requirements,
        ),
        "python": resolved_python_identity,
        "platform": resolved_platform_identity,
        "distributions": resolved_distributions,
    }


def backend_environment_state_path(venv: str | Path) -> Path:
    return Path(venv) / BACKEND_ENVIRONMENT_STATE_NAME


def load_backend_environment_state(venv: str | Path) -> dict[str, object] | None:
    state_path = backend_environment_state_path(venv)
    if not state_path.is_file():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return state if isinstance(state, dict) else None


def write_backend_environment_state(
    venv: str | Path,
    state: Mapping[str, object],
) -> Path:
    state_path = backend_environment_state_path(venv)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(state), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=state_path.parent,
            prefix=f".{state_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, state_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return state_path


def environment_state_validation_error(
    state: Mapping[str, object] | None,
    *,
    requirements_sha256: str,
    python_identity: Mapping[str, object],
    platform_identity: Mapping[str, object],
    distributions: Iterable[str | Sequence[str] | Mapping[str, object]],
) -> str | None:
    if not isinstance(state, Mapping):
        return "backend environment state is missing or invalid"
    if state.get("schema_version") != BACKEND_ENVIRONMENT_STATE_SCHEMA_VERSION:
        return "backend environment state schema is unsupported"
    if state.get("requirements_sha256") != requirements_sha256:
        return "backend environment requirements do not match"
    if state.get("python") != dict(python_identity):
        return "backend environment Python identity does not match"
    if state.get("platform") != dict(platform_identity):
        return "backend environment platform identity does not match"
    try:
        expected_closure = normalize_distribution_closure(distributions)
        stored_closure = normalize_distribution_closure(state.get("distributions", []))
    except (TypeError, ValueError):
        return "backend environment distribution closure is invalid"
    if stored_closure != expected_closure:
        return "backend environment distribution closure does not match"
    return None
