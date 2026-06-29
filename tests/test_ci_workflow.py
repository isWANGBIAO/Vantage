from pathlib import Path


def test_python_ci_step_isolates_vantage_runtime_dirs():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    python_step_start = workflow.index("- name: Run Python tests")
    frontend_job_start = workflow.index("  frontend:")
    python_step = workflow[python_step_start:frontend_job_start]

    required_env_vars = {
        "VANTAGE_DATA_DIR",
        "VANTAGE_CONFIG_DIR",
        "VANTAGE_HISTORY_DIR",
        "VANTAGE_LOG_DIR",
        "VANTAGE_PLOT_DIR",
        "VANTAGE_CACHE_DIR",
        "VANTAGE_RUNTIME_DIR",
        "VANTAGE_MIGRATION_DIR",
    }

    missing = [name for name in sorted(required_env_vars) if name not in python_step]
    assert not missing, f"Python CI step should isolate Vantage runtime dirs: {missing}"
