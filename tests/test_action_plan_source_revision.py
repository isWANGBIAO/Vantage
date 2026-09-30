import asyncio
import json
import os
from unittest.mock import patch

from src.backend import action_plans as _backend_action_plans


def _revision():
    return asyncio.run(_backend_action_plans.get_action_plan_source_revision())


def test_revision_tracks_content_even_if_size_and_timestamp_are_unchanged(tmp_path):
    source = tmp_path / "Time.xlsx"
    source.write_bytes(b"first")
    original_stat = source.stat()
    with patch.object(_backend_action_plans.DataLoader, "resolve_data_path", return_value=source):
        first = _revision()
        assert first.status_code == 200
        assert first.headers["cache-control"] == "no-store"
        assert first.body == _revision().body
        source.write_bytes(b"other")
        os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        assert first.body != _revision().body
        assert set(json.loads(first.body)) == {"revision"}


def test_missing_source_returns_retryable_error_without_private_path(tmp_path):
    source = tmp_path / "private" / "Time.xlsx"
    with patch.object(_backend_action_plans.DataLoader, "resolve_data_path", return_value=source):
        result = _revision()
    assert result.status_code == 503
    assert str(tmp_path) not in result.body.decode()
    assert "revision" not in json.loads(result.body)


def test_unreadable_source_returns_retryable_error():
    with patch.object(_backend_action_plans, "_compute_action_plan_source_revision", side_effect=PermissionError("private")):
        result = _revision()
    assert result.status_code == 503
    assert b"private" not in result.body


def test_source_modified_during_hash_is_rejected(tmp_path):
    source = tmp_path / "Time.xlsx"
    source.write_bytes(b"initial")
    before = source.stat()
    source.write_bytes(b"changed content")
    after = source.stat()
    snapshot = tmp_path / "snapshot.xlsx"
    snapshot.write_bytes(b"initial")
    with patch.object(_backend_action_plans.DataLoader, "_safe_copy_excel", return_value=snapshot), patch.object(_backend_action_plans.DataLoader, "resolve_data_path", return_value=source), patch.object(
        _backend_action_plans.Path, "stat", side_effect=[before, after]
    ):
        result = _revision()
    assert result.status_code == 503


def test_locked_workbook_uses_snapshot_and_removes_it(tmp_path):
    source = tmp_path / "Time.xlsx"
    source.write_bytes(b"workbook")
    snapshot = tmp_path / "snapshot.xlsx"
    snapshot.write_bytes(b"workbook")
    original_open = _backend_action_plans.Path.open

    def locked_open(path, *args, **kwargs):
        if path == source:
            raise PermissionError("Workbook open in Excel")
        return original_open(path, *args, **kwargs)

    def resolve(name, *args, **kwargs):
        target = tmp_path / name
        if target.exists() or name in _backend_action_plans.ACTION_PLAN_CONTENT_FILES:
            return target
        raise FileNotFoundError(name)

    with patch.object(_backend_action_plans.DataLoader, "resolve_data_path", side_effect=resolve), patch.object(
        _backend_action_plans.DataLoader, "_safe_copy_excel", return_value=snapshot
    ) as copy, patch.object(_backend_action_plans.Path, "open", locked_open):
        result = _revision()
    assert result.status_code == 200
    assert copy.call_count >= 1
    assert copy.call_args_list[0].args == (source,)
    assert not snapshot.exists()


def test_revision_covers_every_source_the_action_plan_reads(tmp_path):
    """只覆盖 Time.xlsx 会漏掉资产负债表和各个 Prompt 的修改。"""
    for name in ("Time.xlsx", "Balance Sheet.xlsx", "Prompt_Goals.md", "Prompt_Inventory.md"):
        (tmp_path / name).write_bytes(b"original")

    def resolve(name, *args, **kwargs):
        target = tmp_path / name
        if target.exists():
            return target
        raise FileNotFoundError(name)

    with patch.object(_backend_action_plans.DataLoader, "resolve_data_path", side_effect=resolve), patch.object(
        _backend_action_plans.DataLoader, "_safe_copy_excel", side_effect=lambda p: _snapshot(p, tmp_path)
    ):
        baseline = _revision().body

        for name in ("Balance Sheet.xlsx", "Prompt_Goals.md", "Prompt_Inventory.md"):
            original = (tmp_path / name).read_bytes()
            (tmp_path / name).write_bytes(b"edited")
            assert _revision().body != baseline, f"{name} 的修改没有改变指纹"
            (tmp_path / name).write_bytes(original)
            assert _revision().body == baseline, f"{name} 恢复后指纹应还原"


def test_revision_ignores_files_that_do_not_exist(tmp_path):
    """可选 Prompt 不存在时不应让接口失败。"""
    (tmp_path / "Time.xlsx").write_bytes(b"workbook")

    def resolve(name, *args, **kwargs):
        target = tmp_path / name
        if target.exists():
            return target
        raise FileNotFoundError(name)

    with patch.object(_backend_action_plans.DataLoader, "resolve_data_path", side_effect=resolve), patch.object(
        _backend_action_plans.DataLoader, "_safe_copy_excel", side_effect=lambda p: _snapshot(p, tmp_path)
    ):
        first = _revision()
        assert first.status_code == 200

        # Creating a previously missing prompt must still change the fingerprint.
        (tmp_path / "Prompt_Goals.md").write_bytes(b"new goals")
        assert _revision().body != first.body


def _snapshot(path, tmp_path):
    """Stand-in for the locked-file snapshot helper."""
    target = tmp_path / f"snap-{path.name}"
    target.write_bytes(path.read_bytes())
    return target


def test_copy_failure_returns_retryable_error():
    with patch.object(_backend_action_plans, "_compute_action_plan_source_revision", side_effect=_backend_action_plans.subprocess.CalledProcessError(1, "copy")):
        assert _revision().status_code == 503
