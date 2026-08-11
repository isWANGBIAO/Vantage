import json
import os
import select
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path


def _ensure_project_root_on_sys_path(
    script_path: str | Path | None = None,
    path_list: list[str] | None = None,
) -> Path:
    current_script = Path(script_path or __file__).resolve()
    project_root = current_script.parents[2]
    resolved_path_list = path_list if path_list is not None else sys.path
    project_root_str = str(project_root)
    if project_root_str not in resolved_path_list:
        resolved_path_list.insert(0, project_root_str)
    return project_root


_ensure_project_root_on_sys_path()

from src.core.config import Config
from src.utils.sensitive_data import RedactingPipeLog, build_log_path_prefixes
from src.utils.subprocess_safety import (
    bind_current_process_to_windows_kill_on_close_job,
    terminate_process_tree,
)


SUPERVISE_ARG = "--supervise"
OWN_TARGET_ARG = "--own-target"
SUPERVISOR_READY_SIGNAL = b"READY\n"
SUPERVISOR_ERROR_SIGNAL = b"ERROR\n"
OWNER_BOUND_SIGNAL = b"OWNER_READY\n"
OWNER_ERROR_SIGNAL = b"OWNER_ERROR\n"
OWNER_TARGET_READY_PREFIX = b"TARGET_READY "
SUPERVISOR_READY_TIMEOUT_SECONDS = 15.0
OWNER_STOP_TIMEOUT_SECONDS = 5.0
OWNER_PAYLOAD_LIMIT_BYTES = 4 * 1024 * 1024
_WINDOWS_PEEK_NAMED_PIPE = None


def _resolve_npm_executable() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def _build_frontend_command(mode: str, npm_executable: str | None = None) -> list[str]:
    resolved_npm = npm_executable or _resolve_npm_executable()
    if mode == "production":
        return [resolved_npm, "run", "electron:start"]
    if mode == "development":
        return [resolved_npm, "run", "electron:dev"]
    raise ValueError(f"Unsupported frontend launch mode: {mode}")


def _build_frontend_env(mode: str, base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ)
    env.update(Config.build_runtime_environment())
    if mode == "production":
        env["NODE_ENV"] = "production"
    else:
        env.pop("NODE_ENV", None)
    return env


def _get_creationflags() -> int:
    if os.name != "nt":
        return 0

    flags = 0
    for flag_name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= getattr(subprocess, flag_name, 0)
    return flags


def _get_start_new_session() -> bool:
    return os.name != "nt"


def _prepare_frontend_runtime_logs(
    logs_dir: Path,
    mode: str,
    launched_at: datetime,
) -> dict[str, Path]:
    runtime_dir = logs_dir / "frontend"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    timestamp = launched_at.strftime("%Y%m%d_%H%M%S")

    stdout_log = runtime_dir / f"frontend-{mode}-out-{timestamp}.log"
    stderr_log = runtime_dir / f"frontend-{mode}-err-{timestamp}.log"
    stdout_pointer = logs_dir / f"frontend_{mode}.out.latest.log"
    stderr_pointer = logs_dir / f"frontend_{mode}.err.latest.log"

    for pointer_path, log_path in (
        (stdout_pointer, stdout_log),
        (stderr_pointer, stderr_log),
    ):
        try:
            pointer_path.write_text(str(log_path.resolve()), encoding="utf-8")
        except OSError:
            pass

    return {
        "stdout_log": stdout_log,
        "stderr_log": stderr_log,
        "stdout_pointer": stdout_pointer,
        "stderr_pointer": stderr_pointer,
    }


class _OwnedFrontendLifecycle:
    def __init__(self, *, windows_job=None) -> None:
        self._windows_job = windows_job
        self._target = None
        self._lock = threading.RLock()
        self.stop_requested = threading.Event()

    def attach_target(self, process: subprocess.Popen) -> None:
        with self._lock:
            self._target = process
            should_stop = self.stop_requested.is_set()
        if should_stop:
            self.stop_for_control_loss()

    def detach_target(self, process: subprocess.Popen) -> None:
        with self._lock:
            if self._target is process:
                self._target = None

    def stop_target_tree(self) -> None:
        self.stop_requested.set()
        with self._lock:
            process = self._target
        if process is not None:
            terminate_process_tree(process)

    def stop_for_control_loss(self) -> None:
        self.stop_requested.set()
        if self._windows_job is not None:
            # The owner belongs to this Job too. Terminating it atomically stops
            # the owner and every target descendant after the control lease dies.
            self._windows_job.terminate()
            return
        self.stop_target_tree()


def _stop_target_process(process: subprocess.Popen) -> None:
    terminate_process_tree(process)
    if process.poll() is None:
        try:
            process.wait(timeout=OWNER_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=OWNER_STOP_TIMEOUT_SECONDS)


def _run_owned_frontend_target(
    *,
    mode: str,
    command: list[str],
    env: dict[str, str],
    webapp_dir: Path,
    runtime_logs: dict[str, Path],
    path_prefixes: dict[str, str],
    launched_at: datetime,
    lifecycle: _OwnedFrontendLifecycle,
    notify_ready=lambda _pid: None,
) -> int:
    """Run one isolated frontend target while preserving redacted logs."""

    timestamp = launched_at.isoformat()
    with RedactingPipeLog(
        runtime_logs["stdout_log"],
        path_prefixes=path_prefixes,
    ) as stdout_log, RedactingPipeLog(
        runtime_logs["stderr_log"],
        path_prefixes=path_prefixes,
    ) as stderr_log:
        header = f"\n=== Frontend launch {mode} {timestamp} ===\n"
        stdout_log.write_record(header)
        stderr_log.write_record(header)
        process = None
        try:
            if lifecycle.stop_requested.is_set():
                raise RuntimeError("frontend lifecycle control was lost")
            with stdout_log.capture_subprocess_output(
                stream_name="frontend-stdout"
            ) as stdout_handle, stderr_log.capture_subprocess_output(
                stream_name="frontend-stderr"
            ) as stderr_handle:
                process = subprocess.Popen(
                    command,
                    cwd=webapp_dir,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    creationflags=0,
                    start_new_session=os.name != "nt",
                    close_fds=True,
                )
                lifecycle.attach_target(process)
                notify_ready(process.pid)
                returncode = process.wait()
                # A command may exit while a pipe-inheriting descendant remains.
                # Its isolated group/Job is still owned and must not outlive us.
                _stop_target_process(process)
                return returncode
        except Exception as exc:
            if process is not None:
                _stop_target_process(process)
            stderr_log.write_record(f"Frontend process failed: {exc}\n")
            return 1
        finally:
            if process is not None:
                lifecycle.detach_target(process)


def _serialize_owner_payload(
    *,
    mode: str,
    command: list[str],
    env: dict[str, str],
    webapp_dir: Path,
    runtime_logs: dict[str, Path],
    path_prefixes: dict[str, str],
    launched_at: datetime,
) -> bytes:
    payload = {
        "schemaVersion": 1,
        "mode": mode,
        "command": [str(part) for part in command],
        "env": {str(key): str(value) for key, value in env.items()},
        "webappDir": str(webapp_dir),
        "runtimeLogs": {
            str(key): str(value) for key, value in runtime_logs.items()
        },
        "pathPrefixes": {
            str(key): str(value) for key, value in path_prefixes.items()
        },
        "launchedAt": launched_at.isoformat(),
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode(
        "utf-8"
    )
    if len(encoded) + 1 > OWNER_PAYLOAD_LIMIT_BYTES:
        raise RuntimeError("frontend owner payload is too large")
    return encoded + b"\n"


def _parse_owner_payload(raw_payload: bytes) -> dict[str, object]:
    if not raw_payload or not raw_payload.endswith(b"\n"):
        raise RuntimeError("invalid frontend owner payload")
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("invalid frontend owner payload") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise RuntimeError("invalid frontend owner payload")
    if payload.get("mode") not in {"production", "development"}:
        raise RuntimeError("invalid frontend owner payload")
    command = payload.get("command")
    env = payload.get("env")
    runtime_logs = payload.get("runtimeLogs")
    path_prefixes = payload.get("pathPrefixes")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(part, str) and part for part in command)
        or not isinstance(env, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in env.items()
        )
        or not isinstance(payload.get("webappDir"), str)
        or not isinstance(runtime_logs, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in runtime_logs.items()
        )
        or not {"stdout_log", "stderr_log"}.issubset(runtime_logs)
        or not isinstance(path_prefixes, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in path_prefixes.items()
        )
        or not isinstance(payload.get("launchedAt"), str)
    ):
        raise RuntimeError("invalid frontend owner payload")
    try:
        launched_at = datetime.fromisoformat(payload["launchedAt"])
    except ValueError as exc:
        raise RuntimeError("invalid frontend owner payload") from exc
    return {
        "mode": payload["mode"],
        "command": command,
        "env": env,
        "webapp_dir": Path(payload["webappDir"]),
        "runtime_logs": {
            key: Path(value) for key, value in runtime_logs.items()
        },
        "path_prefixes": path_prefixes,
        "launched_at": launched_at,
    }


def _write_control_signal(stream, value: bytes) -> None:
    stream.write(value)
    stream.flush()


def _control_pipe_was_lost(control_stream) -> bool:
    try:
        descriptor = control_stream.fileno()
    except (AttributeError, OSError, ValueError):
        return True

    if os.name != "nt":
        try:
            readable, _writable, _exceptional = select.select(
                [descriptor], [], [], 0
            )
            if not readable:
                return False
            os.read(descriptor, 1)
            return True
        except (OSError, ValueError):
            return True

    import ctypes
    import msvcrt
    from ctypes import wintypes

    global _WINDOWS_PEEK_NAMED_PIPE
    if _WINDOWS_PEEK_NAMED_PIPE is None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        peek_named_pipe = kernel32.PeekNamedPipe
        peek_named_pipe.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        peek_named_pipe.restype = wintypes.BOOL
        _WINDOWS_PEEK_NAMED_PIPE = peek_named_pipe
    available = wintypes.DWORD()
    try:
        pipe_handle = wintypes.HANDLE(msvcrt.get_osfhandle(descriptor))
    except OSError:
        return True
    if not _WINDOWS_PEEK_NAMED_PIPE(
        pipe_handle,
        None,
        0,
        None,
        ctypes.byref(available),
        None,
    ):
        return True
    if available.value == 0:
        return False
    try:
        return os.read(descriptor, 1) != b""
    except OSError:
        return True


def _monitor_supervisor_control(
    control_stream,
    lifecycle,
    monitor_finished: threading.Event,
) -> None:
    while not monitor_finished.wait(0.05):
        # No post-start messages are valid. EOF is the supervisor lease ending;
        # any unexpected byte also fails closed.
        if _control_pipe_was_lost(control_stream):
            lifecycle.stop_for_control_loss()
            return


def _run_frontend_owner(*, control_stream=None, signal_stream=None) -> int:
    control_stream = control_stream or sys.stdin.buffer
    signal_stream = signal_stream or sys.stdout.buffer
    try:
        windows_job = bind_current_process_to_windows_kill_on_close_job()
    except Exception:
        try:
            _write_control_signal(signal_stream, OWNER_ERROR_SIGNAL)
        except (BrokenPipeError, OSError, ValueError):
            pass
        return 1

    lifecycle = _OwnedFrontendLifecycle(windows_job=windows_job)

    def stop_for_signal(_signum, _frame):
        lifecycle.stop_for_control_loss()
        raise SystemExit(1)

    for signal_name in ("SIGTERM", "SIGINT"):
        resolved_signal = getattr(signal, signal_name, None)
        if resolved_signal is not None:
            signal.signal(resolved_signal, stop_for_signal)

    try:
        _write_control_signal(signal_stream, OWNER_BOUND_SIGNAL)
        raw_payload = control_stream.readline(OWNER_PAYLOAD_LIMIT_BYTES + 1)
        if len(raw_payload) > OWNER_PAYLOAD_LIMIT_BYTES:
            raise RuntimeError("invalid frontend owner payload")
        payload = _parse_owner_payload(raw_payload)
        monitor_finished = threading.Event()
        control_monitor = threading.Thread(
            target=_monitor_supervisor_control,
            args=(control_stream, lifecycle, monitor_finished),
            name="vantage-frontend-owner-control",
            daemon=False,
        )
        control_monitor.start()
        try:
            return _run_owned_frontend_target(
                **payload,
                lifecycle=lifecycle,
                notify_ready=lambda pid: _write_control_signal(
                    signal_stream,
                    OWNER_TARGET_READY_PREFIX + str(pid).encode("ascii") + b"\n",
                ),
            )
        finally:
            monitor_finished.set()
            control_monitor.join(timeout=1)
    except Exception:
        lifecycle.stop_target_tree()
        try:
            _write_control_signal(signal_stream, OWNER_ERROR_SIGNAL)
        except (BrokenPipeError, OSError, ValueError):
            pass
        return 1


def _owner_creationflags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _parse_target_ready_signal(value: bytes) -> int | None:
    if not value.startswith(OWNER_TARGET_READY_PREFIX) or not value.endswith(b"\n"):
        return None
    raw_pid = value[len(OWNER_TARGET_READY_PREFIX) : -1]
    if not raw_pid.isdigit():
        return None
    pid = int(raw_pid)
    return pid if pid > 0 else None


def _terminate_frontend_owner(
    process: subprocess.Popen,
    *,
    target_pid: int | None,
) -> None:
    if process.stdin is not None:
        try:
            process.stdin.close()
        except (OSError, ValueError):
            pass
    try:
        process.wait(timeout=OWNER_STOP_TIMEOUT_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass

    if os.name != "nt" and target_pid is not None:
        try:
            os.killpg(target_pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    terminate_process_tree(process)
    try:
        process.wait(timeout=OWNER_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=OWNER_STOP_TIMEOUT_SECONDS)


def _close_owner_pipes(process: subprocess.Popen) -> None:
    for pipe_name in ("stdin", "stdout"):
        pipe = getattr(process, pipe_name, None)
        if pipe is not None:
            try:
                pipe.close()
            except (OSError, ValueError):
                pass


def _run_frontend_supervisor(
    *,
    mode: str,
    command: list[str],
    env: dict[str, str],
    webapp_dir: Path,
    runtime_logs: dict[str, Path],
    path_prefixes: dict[str, str],
    launched_at: datetime,
    notify_ready=lambda: None,
) -> int:
    """Broker one owned frontend target and keep its control lease open."""

    owner = None
    target_pid = None
    try:
        payload = _serialize_owner_payload(
            mode=mode,
            command=command,
            env=env,
            webapp_dir=webapp_dir,
            runtime_logs=runtime_logs,
            path_prefixes=path_prefixes,
            launched_at=launched_at,
        )
        owner = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), OWN_TARGET_ARG],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=_owner_creationflags(),
            start_new_session=os.name != "nt",
            close_fds=True,
        )
        assert owner.stdin is not None
        assert owner.stdout is not None
        if owner.stdout.readline() != OWNER_BOUND_SIGNAL:
            raise RuntimeError("frontend owner failed before binding lifecycle")
        owner.stdin.write(payload)
        owner.stdin.flush()
        target_pid = _parse_target_ready_signal(owner.stdout.readline())
        if target_pid is None:
            raise RuntimeError("frontend owner failed before target readiness")
        notify_ready()
        return owner.wait()
    except Exception:
        if owner is not None:
            _terminate_frontend_owner(owner, target_pid=target_pid)
        return 1
    finally:
        if owner is not None:
            _close_owner_pipes(owner)


def _supervise_frontend(mode: str) -> int:
    project_root = Config.get_project_root()
    webapp_dir = project_root / "src" / "webapp"
    runtime_paths = Config.get_runtime_paths()
    launched_at = datetime.now()
    runtime_logs = _prepare_frontend_runtime_logs(
        runtime_paths["log_dir"],
        mode,
        launched_at,
    )
    ready_sent = False

    def notify_ready():
        nonlocal ready_sent
        sys.stdout.buffer.write(SUPERVISOR_READY_SIGNAL)
        sys.stdout.buffer.flush()
        ready_sent = True

    returncode = _run_frontend_supervisor(
        mode=mode,
        command=_build_frontend_command(mode),
        env=_build_frontend_env(mode),
        webapp_dir=webapp_dir,
        runtime_logs=runtime_logs,
        path_prefixes=build_log_path_prefixes(
            project_root=project_root,
            runtime_paths=runtime_paths,
        ),
        launched_at=launched_at,
        notify_ready=notify_ready,
    )
    if not ready_sent:
        try:
            sys.stdout.buffer.write(SUPERVISOR_ERROR_SIGNAL)
            sys.stdout.buffer.flush()
        except (BrokenPipeError, OSError):
            pass
    return returncode


def _wait_for_supervisor_signal(
    process,
    *,
    timeout_seconds=SUPERVISOR_READY_TIMEOUT_SECONDS,
):
    result = []

    def read_signal():
        try:
            result.append(process.stdout.readline())
        except (OSError, ValueError):
            result.append(b"")

    reader = threading.Thread(
        target=read_signal,
        name="vantage-frontend-ready",
        daemon=True,
    )
    reader.start()
    reader.join(timeout=max(0.0, float(timeout_seconds)))
    if reader.is_alive():
        terminate_process_tree(process)
        process.wait(timeout=5)
        reader.join(timeout=1)
        return b""
    return result[0] if result else b""


def _launch_frontend_supervisor(mode: str) -> int:
    project_root = Config.get_project_root()
    command = [sys.executable, str(Path(__file__).resolve()), SUPERVISE_ARG, mode]
    process = subprocess.Popen(
        command,
        cwd=project_root,
        env=_build_frontend_env(mode),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=_get_creationflags(),
        start_new_session=_get_start_new_session(),
        close_fds=True,
    )
    signal = _wait_for_supervisor_signal(process)
    if process.stdout is not None:
        process.stdout.close()
    if signal == SUPERVISOR_READY_SIGNAL:
        print(f"Frontend supervisor launched: mode={mode}, pid={process.pid}")
        return 0

    try:
        returncode = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        terminate_process_tree(process)
        returncode = process.wait(timeout=5)
    print(
        "Frontend supervisor failed before the application started; "
        "see the frontend error log.",
        file=sys.stderr,
    )
    return returncode or 1


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if args and args[0] == OWN_TARGET_ARG:
        return _run_frontend_owner()
    if args and args[0] == SUPERVISE_ARG:
        mode = args[1] if len(args) > 1 else "production"
        return _supervise_frontend(mode)
    mode = args[0] if args else "production"
    _build_frontend_command(mode)
    return _launch_frontend_supervisor(mode)


if __name__ == "__main__":
    raise SystemExit(main())
