from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any


def _ensure_project_root_on_sys_path(script_path: str | Path | None = None) -> Path:
    current_script = Path(script_path or __file__).resolve()
    project_root = current_script.parents[2]
    project_root_text = str(project_root)
    if project_root_text not in sys.path:
        sys.path.insert(0, project_root_text)
    return project_root


_ensure_project_root_on_sys_path()

from src.core.backend_runtime_lock import (
    DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS,
    backend_runtime_lock,
)
from src.utils.subprocess_safety import (
    bind_current_process_to_windows_kill_on_close_job,
    terminate_process_tree,
)


_INTERNAL_LEASE_OWNER_FLAG = "--internal-lease-owner"
_INTERNAL_READY_FD_OPTION = "--internal-ready-fd"
_INTERNAL_READY_HANDLE_OPTION = "--internal-ready-handle"
_INTERNAL_CONTINUE_FD_OPTION = "--internal-continue-fd"
_INTERNAL_CONTINUE_HANDLE_OPTION = "--internal-continue-handle"
_LEASE_OWNER_STARTUP_GRACE_SECONDS = 5.0
_LEASE_OWNER_STOP_TIMEOUT_SECONDS = 5.0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one backend-runtime consumer while holding its lifecycle lock.",
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        _INTERNAL_LEASE_OWNER_FLAG,
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(_INTERNAL_READY_FD_OPTION, type=int, help=argparse.SUPPRESS)
    parser.add_argument(
        _INTERNAL_READY_HANDLE_OPTION,
        type=int,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(_INTERNAL_CONTINUE_FD_OPTION, type=int, help=argparse.SUPPRESS)
    parser.add_argument(
        _INTERNAL_CONTINUE_HANDLE_OPTION,
        type=int,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def build_backend_runtime_lease_owner_command(
    *,
    project_root: str | Path,
    timeout_seconds: float,
    ready_option: str,
    ready_value: int,
    continue_option: str,
    continue_value: int,
    command: list[str],
    bootstrap_python: str | Path = sys.executable,
    lock_runner: str | Path = __file__,
) -> list[str]:
    return [
        str(bootstrap_python),
        str(Path(lock_runner).resolve()),
        "--project-root",
        str(Path(project_root).resolve()),
        "--timeout-seconds",
        str(timeout_seconds),
        _INTERNAL_LEASE_OWNER_FLAG,
        ready_option,
        str(ready_value),
        continue_option,
        str(continue_value),
        "--",
        *command,
    ]


def _clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("VANTAGE_BACKEND_RUNTIME_LOCK_HELD", None)
    return environment


def _inherited_pipe_descriptor(
    *,
    descriptor: int | None,
    handle: int | None,
    flags: int,
    label: str,
) -> int:
    if descriptor is not None:
        if handle is not None:
            raise ValueError(f"lease owner received two {label} transports")
        return descriptor
    if handle is None:
        raise ValueError(f"lease owner did not receive a {label} transport")
    if os.name != "nt":
        raise ValueError(f"Windows {label} handle is invalid on this platform")

    import msvcrt

    return msvcrt.open_osfhandle(handle, flags | int(getattr(os, "O_BINARY", 0)))


def _notify_supervisor_ready(args: argparse.Namespace) -> int:
    descriptor = _inherited_pipe_descriptor(
        descriptor=args.internal_ready_fd,
        handle=args.internal_ready_handle,
        flags=os.O_WRONLY,
        label="ready-signal",
    )
    try:
        os.write(descriptor, b"1")
    except OSError:
        # The outer supervisor may have died. Its acknowledgement channel is
        # not the lease: keep owning the real file lock and launch safely.
        pass
    return descriptor


def _notify_supervisor_result(descriptor: int, returncode: int) -> None:
    try:
        try:
            os.write(descriptor, f"{int(returncode)}\n".encode("ascii"))
        except OSError:
            # The outer launcher may have died. Tree cleanup and the real lease
            # remain owned by this process and must still complete.
            pass
    finally:
        os.close(descriptor)


def _read_lease_owner_result(descriptor: int) -> int | None:
    payload = bytearray()
    while len(payload) <= 32:
        chunk = os.read(descriptor, 32 - len(payload) + 1)
        if not chunk:
            break
        payload.extend(chunk)
        if b"\n" in chunk:
            break
    if not payload.endswith(b"\n") or len(payload) > 32:
        return None
    try:
        return int(payload[:-1].decode("ascii"))
    except ValueError:
        return None


def _wait_for_supervisor_continue(args: argparse.Namespace) -> None:
    descriptor = _inherited_pipe_descriptor(
        descriptor=args.internal_continue_fd,
        handle=args.internal_continue_handle,
        flags=os.O_RDONLY,
        label="continue-signal",
    )
    try:
        try:
            signal = os.read(descriptor, 1)
        except OSError:
            # Closing the outer process also closes its pipe endpoint. The real
            # shared lease is already owned here, so continuing is safe.
            return
        if signal not in (b"", b"1"):
            raise ValueError("lease owner received an invalid continue signal")
    finally:
        os.close(descriptor)


def _wait_for_lease_owner_ready(
    process: subprocess.Popen[Any],
    ready_descriptor: int,
    *,
    timeout_seconds: float,
) -> bool:
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ValueError("lease owner readiness timeout must be finite and non-negative")

    completed = threading.Event()
    signals: list[bytes] = []
    errors: list[OSError] = []

    def read_signal() -> None:
        try:
            signals.append(os.read(ready_descriptor, 1))
        except OSError as exc:
            errors.append(exc)
        finally:
            completed.set()

    reader = threading.Thread(target=read_signal, daemon=True)
    reader.start()
    if not completed.wait(timeout_seconds):
        _stop_unready_lease_owner(process)
        completed.wait(_LEASE_OWNER_STOP_TIMEOUT_SECONDS)
        raise TimeoutError("timed out waiting for backend runtime lease owner readiness")
    if errors:
        _stop_unready_lease_owner(process)
        raise errors[0]
    if signals != [b"1"] and process.poll() is None:
        _stop_unready_lease_owner(process)
    return signals == [b"1"]


def _stop_unready_lease_owner(process: subprocess.Popen[Any]) -> None:
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=_LEASE_OWNER_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=_LEASE_OWNER_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            pass


def _spawn_lease_owner(
    *,
    project_root: Path,
    timeout_seconds: float,
    command: list[str],
) -> tuple[subprocess.Popen[Any], int, int]:
    ready_read_descriptor, ready_write_descriptor = os.pipe()
    try:
        continue_read_descriptor, continue_write_descriptor = os.pipe()
    except BaseException:
        os.close(ready_read_descriptor)
        os.close(ready_write_descriptor)
        raise
    popen_kwargs: dict[str, Any] = {
        "env": _clean_environment(),
        "close_fds": True,
    }
    try:
        if os.name == "nt":
            import msvcrt

            ready_write_handle = msvcrt.get_osfhandle(ready_write_descriptor)
            continue_read_handle = msvcrt.get_osfhandle(continue_read_descriptor)
            os.set_handle_inheritable(ready_write_handle, True)
            os.set_handle_inheritable(continue_read_handle, True)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.lpAttributeList = {
                "handle_list": [ready_write_handle, continue_read_handle]
            }
            popen_kwargs["startupinfo"] = startupinfo
            ready_option = _INTERNAL_READY_HANDLE_OPTION
            ready_value = ready_write_handle
            continue_option = _INTERNAL_CONTINUE_HANDLE_OPTION
            continue_value = continue_read_handle
        else:
            popen_kwargs["pass_fds"] = (
                ready_write_descriptor,
                continue_read_descriptor,
            )
            ready_option = _INTERNAL_READY_FD_OPTION
            ready_value = ready_write_descriptor
            continue_option = _INTERNAL_CONTINUE_FD_OPTION
            continue_value = continue_read_descriptor

        lease_owner_command = build_backend_runtime_lease_owner_command(
            project_root=project_root,
            timeout_seconds=timeout_seconds,
            ready_option=ready_option,
            ready_value=ready_value,
            continue_option=continue_option,
            continue_value=continue_value,
            command=command,
        )
        process = subprocess.Popen(lease_owner_command, **popen_kwargs)
    except BaseException:
        os.close(ready_read_descriptor)
        os.close(continue_write_descriptor)
        raise
    finally:
        os.close(ready_write_descriptor)
        os.close(continue_read_descriptor)
    return process, ready_read_descriptor, continue_write_descriptor


def _guarded_target_popen_kwargs(platform_name: str = os.name) -> dict[str, Any]:
    if platform_name == "nt":
        return {
            "creationflags": int(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            )
        }
    return {"start_new_session": True}


def _confirm_posix_process_group_stopped(
    process_group_id: int,
    *,
    timeout_seconds: float = _LEASE_OWNER_STOP_TIMEOUT_SECONDS,
) -> None:
    def group_has_live_members() -> bool | None:
        try:
            import psutil
        except ImportError:
            return None
        zombie_statuses = {
            psutil.STATUS_ZOMBIE,
            getattr(psutil, "STATUS_DEAD", "dead"),
        }
        for process in psutil.process_iter(["pid", "status"]):
            try:
                status = process.info.get("status")
                if status in zombie_statuses:
                    continue
                if os.getpgid(process.info["pid"]) == process_group_id:
                    return True
            except (OSError, psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    if os.name == "nt":
        return
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return
        live_members = group_has_live_members()
        if live_members is False:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("timed out stopping guarded backend target process group")
        time.sleep(0.02)


def _stop_guarded_target_tree(
    process: subprocess.Popen[Any],
    *,
    terminate_tree=terminate_process_tree,
    confirm_tree=_confirm_posix_process_group_stopped,
    process_group_id: int | None = None,
) -> None:
    if os.name != "nt" and process_group_id is not None:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        # macOS can leave an orphaned descendant visible after the group
        # leader has already exited. Kill any remaining members individually
        # before the bounded confirmation so the lease is never released
        # while a target descendant still uses the runtime.
        try:
            import psutil

            for member in psutil.process_iter(["pid", "status"]):
                try:
                    if member.info.get("status") in {
                        psutil.STATUS_ZOMBIE,
                        getattr(psutil, "STATUS_DEAD", "dead"),
                    }:
                        continue
                    if os.getpgid(member.info["pid"]) == process_group_id:
                        os.kill(member.info["pid"], signal.SIGKILL)
                except (OSError, psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            pass
    else:
        terminate_tree(process)
    try:
        process.wait(timeout=_LEASE_OWNER_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=_LEASE_OWNER_STOP_TIMEOUT_SECONDS)
    if os.name != "nt":
        process_id = getattr(process, "pid", None)
        if process_id is not None:
            confirm_tree(process_id)


def _wait_for_guarded_target(
    process: subprocess.Popen[Any],
    *,
    terminate_tree=terminate_process_tree,
    confirm_tree=_confirm_posix_process_group_stopped,
) -> int:
    process_group_id = None
    if os.name != "nt":
        try:
            process_group_id = os.getpgid(process.pid)
        except (AttributeError, OSError):
            process_group_id = None
    try:
        returncode = process.wait()
    except BaseException:
        try:
            _stop_guarded_target_tree(
                process,
                terminate_tree=terminate_tree,
                confirm_tree=confirm_tree,
                process_group_id=process_group_id,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        raise
    _stop_guarded_target_tree(
        process,
        terminate_tree=terminate_tree,
        confirm_tree=confirm_tree,
        process_group_id=process_group_id,
    )
    return returncode


def _terminate_windows_owner_job(windows_job) -> None:
    windows_job.terminate()
    windows_job.close()
    raise RuntimeError("Windows backend target Job did not terminate its owner")


def _run_as_lease_owner(args: argparse.Namespace, command: list[str]) -> int:
    with backend_runtime_lock(
        args.project_root,
        timeout_seconds=args.timeout_seconds,
        mode="shared",
    ):
        windows_job = bind_current_process_to_windows_kill_on_close_job()
        result_descriptor = _notify_supervisor_ready(args)
        result_was_sent = False
        try:
            _wait_for_supervisor_continue(args)
            process = subprocess.Popen(
                command,
                env=_clean_environment(),
                **_guarded_target_popen_kwargs(),
            )
            if windows_job is None:
                returncode = _wait_for_guarded_target(process)
                _notify_supervisor_result(result_descriptor, returncode)
                result_was_sent = True
                return returncode

            try:
                returncode = process.wait()
            except BaseException:
                _notify_supervisor_result(result_descriptor, 1)
                result_was_sent = True
                _terminate_windows_owner_job(windows_job)
                raise
            _notify_supervisor_result(result_descriptor, returncode)
            result_was_sent = True
            _terminate_windows_owner_job(windows_job)
        except BaseException:
            if not result_was_sent:
                _notify_supervisor_result(result_descriptor, 1)
            if windows_job is not None:
                _terminate_windows_owner_job(windows_job)
            raise


def _run_as_supervisor(args: argparse.Namespace, command: list[str]) -> int:
    readiness_timeout = args.timeout_seconds + _LEASE_OWNER_STARTUP_GRACE_SECONDS
    if not math.isfinite(readiness_timeout) or readiness_timeout < 0:
        raise ValueError("backend runtime lock timeout must be finite and non-negative")
    ready_descriptor: int | None = None
    try:
        with backend_runtime_lock(
            args.project_root,
            timeout_seconds=args.timeout_seconds,
            mode="shared",
        ):
            process, ready_descriptor, continue_descriptor = _spawn_lease_owner(
                project_root=args.project_root,
                timeout_seconds=args.timeout_seconds,
                command=command,
            )
            try:
                owner_is_ready = _wait_for_lease_owner_ready(
                    process,
                    ready_descriptor,
                    timeout_seconds=readiness_timeout,
                )
                if owner_is_ready:
                    os.write(continue_descriptor, b"1")
            finally:
                os.close(continue_descriptor)
            if not owner_is_ready:
                os.close(ready_descriptor)
                ready_descriptor = None
                return_code = process.wait()
                print(
                    "Backend runtime lease owner exited before acquiring its shared lock.",
                    file=sys.stderr,
                )
                return return_code or 1

        target_returncode = _read_lease_owner_result(ready_descriptor)
        owner_returncode = process.wait()
        if target_returncode is None:
            print(
                "Backend runtime lease owner exited without a valid target result.",
                file=sys.stderr,
            )
            return owner_returncode or 1
        return target_returncode
    finally:
        if ready_descriptor is not None:
            os.close(ready_descriptor)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        print("Backend runtime lock supervisor requires a command.", file=sys.stderr)
        return 2

    try:
        if not math.isfinite(args.timeout_seconds) or args.timeout_seconds < 0:
            raise ValueError("backend runtime lock timeout must be finite and non-negative")
        if args.internal_lease_owner:
            return _run_as_lease_owner(args, command)
        if any(
            value is not None
            for value in (
                args.internal_ready_fd,
                args.internal_ready_handle,
                args.internal_continue_fd,
                args.internal_continue_handle,
            )
        ):
            raise ValueError("handoff options require internal lease-owner mode")
        return _run_as_supervisor(args, command)
    except (OSError, TimeoutError, ValueError) as exc:
        print(f"Backend runtime lock supervisor failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
