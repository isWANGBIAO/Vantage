from src.scripts.run_packaging_builds import resolve_build_worker_count


def test_resolve_build_worker_count_uses_available_commands_not_more_processes():
    assert resolve_build_worker_count(None, command_count=2, cpu_count=32) == 2
    assert resolve_build_worker_count(32, command_count=2, cpu_count=32) == 2
    assert resolve_build_worker_count(1, command_count=2, cpu_count=32) == 1


def test_resolve_build_worker_count_handles_invalid_or_empty_inputs():
    assert resolve_build_worker_count(0, command_count=2, cpu_count=32) == 2
    assert resolve_build_worker_count(-5, command_count=2, cpu_count=32) == 2
    assert resolve_build_worker_count(None, command_count=0, cpu_count=32) == 1
    resolved_from_current_machine = resolve_build_worker_count(None, command_count=2, cpu_count=None)
    assert 1 <= resolved_from_current_machine <= 2
