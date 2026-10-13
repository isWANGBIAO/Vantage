"""Bounded bridge to user-owned optional face models; no ML imports here."""
from __future__ import annotations

import atexit
import base64
import hashlib
import json
import os
import queue
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from src.core.config import Config
from src.core.user_config import load_settings

ALGORITHM_VERSION = "brow-eye-relative-v1"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_runtimes = {}
_registry_lock = threading.Lock()


class LocalModelError(RuntimeError):
    pass


def _python_for(settings):
    if settings.get("face_analysis_method", "onnx") == "sam3":
        return settings.get("face_analysis_sam3_python") or settings.get("face_analysis_python", "")
    return settings.get("face_analysis_python", "")


def _identity(path):
    if not path:
        return ""
    resolved = Path(path).expanduser().resolve()
    try:
        stat = resolved.stat()
        return [str(resolved), stat.st_size, stat.st_mtime_ns]
    except OSError:
        return [str(resolved), None, None]


def profile_paths(settings=None, *, history_root=None):
    values = load_settings() if settings is None else settings
    method = values.get("face_analysis_method", "onnx")
    model = values.get("face_analysis_onnx_model", "") if method == "onnx" else values.get("face_analysis_sam3_model_dir", "")
    identity = [ALGORITHM_VERSION, method, _identity(_python_for(values)), _identity(model)]
    if method == "sam3" and model:
        identity.extend(_identity(Path(model) / name) for name in ("config.json", "model.safetensors", "model.safetensors.index.json"))
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    profile_id = f"{method}-{digest}"
    root = Path(history_root or Config.get_history_dir()) / "face_local" / profile_id
    return {"profile_id": profile_id, "root": root, "db_file": root / "face_analysis.db", "overlay": root / "latest-overlay.png"}


def configuration_status(settings=None, *, history_root=None):
    values = load_settings() if settings is None else settings
    paths = profile_paths(values, history_root=history_root)
    method = values.get("face_analysis_method", "onnx")
    python = _python_for(values)
    model = values.get("face_analysis_onnx_model", "") if method == "onnx" else values.get("face_analysis_sam3_model_dir", "")
    message = "已配置本地环境；首次分析会验证模型和依赖。"
    ready = True
    if method not in {"onnx", "sam3"}:
        ready, message = False, "请选择 ONNX 或 SAM3。"
    elif not python or not Path(python).is_file():
        ready, message = False, "请选择已安装分析依赖的本地 Python 可执行文件。"
    elif method == "onnx" and (not model or not Path(model).is_file()):
        ready, message = False, "请选择本地 BiSeNet ResNet18 ONNX 模型文件。"
    elif method == "sam3" and (not model or not (Path(model) / "config.json").is_file()):
        ready, message = False, "请选择包含完整权重和处理器文件的本地 SAM3 模型目录。"
    return {"ready": ready, "message": message, "method": method, "profile_id": paths["profile_id"], "algorithm_version": ALGORITHM_VERSION}


def build_worker_command(settings):
    script = Path(Config.get_project_root()) / "src" / "scripts" / "face_model_worker.py"
    method = settings.get("face_analysis_method", "onnx")
    model = settings.get("face_analysis_onnx_model", "") if method == "onnx" else settings.get("face_analysis_sam3_model_dir", "")
    return [_python_for(settings), "-u", str(script), "--method", method, "--model", model]


def decode_worker_response(line):
    try:
        data = json.loads(line)
    except (ValueError, TypeError) as exc:
        raise LocalModelError("本地分析进程返回了无效数据。") from exc
    if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
        raise LocalModelError("本地分析进程返回了无效数据。")
    if data["ok"] and not isinstance(data.get("result"), dict):
        raise LocalModelError("本地分析结果不完整。")
    return data


class LocalFaceRuntime:
    is_external_local = True

    def __init__(self, settings=None, *, timeout=90):
        self.settings = dict(load_settings() if settings is None else settings)
        self.paths = profile_paths(self.settings)
        self.timeout = timeout
        self.lock = threading.RLock()
        self.process = None
        self.responses = None
        self.last_error = None
        self.retry_after = 0.0

    def close(self):
        with self.lock:
            process, self.process = self.process, None
            if process:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                for stream in (process.stdin, process.stdout):
                    if stream:
                        stream.close()

    def _start(self):
        status = configuration_status(self.settings)
        if not status["ready"]:
            raise LocalModelError(status["message"])
        env = dict(os.environ)
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", OPENCV_OPENCL_RUNTIME="disabled", PYTHONUTF8="1", TOKENIZERS_PARALLELISM="false")
        env.pop("PYTHONPATH", None)
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        self.process = subprocess.Popen(build_worker_command(self.settings), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=env, **kwargs)
        self.responses = queue.Queue(maxsize=1)
        process, responses = self.process, self.responses

        def read():
            try:
                while True:
                    line = process.stdout.readline(MAX_RESPONSE_BYTES + 1)
                    if not line:
                        responses.put(None, timeout=.5)
                        break
                    if len(line) > MAX_RESPONSE_BYTES:
                        responses.put(None, timeout=.5)
                        break
                    responses.put(line, timeout=.5)
            except (OSError, ValueError, queue.Full):
                try:
                    responses.put_nowait(None)
                except queue.Full:
                    pass
        threading.Thread(target=read, name="face-local-response", daemon=True).start()

    def request(self, image_bgr):
        import cv2
        import time
        with self.lock:
            if self.last_error and time.monotonic() < self.retry_after:
                raise LocalModelError(self.last_error)
            try:
                if self.process is None or self.process.poll() is not None:
                    self.close()
                    self._start()
                ok, encoded = cv2.imencode(".png", image_bgr)
                if not ok:
                    raise LocalModelError("无法编码人脸裁剪。")
                payload = json.dumps({"image": base64.b64encode(encoded).decode("ascii")})
                deadline = time.monotonic() + self.timeout
                sent, write_errors = threading.Event(), []
                process = self.process
                def send():
                    try:
                        process.stdin.write(payload + "\n")
                        process.stdin.flush()
                    except (OSError, ValueError) as error:
                        write_errors.append(error)
                    finally:
                        sent.set()
                writer = threading.Thread(target=send, name="face-local-send", daemon=True)
                writer.start()
                if not sent.wait(max(0, deadline - time.monotonic())):
                    self.close()
                    writer.join(timeout=1)
                    raise LocalModelError("本地模型发送超时，分析进程已停止；请检查环境。")
                if write_errors:
                    raise LocalModelError("无法向本地模型发送请求；请检查环境。")
                line = self.responses.get(timeout=max(0, deadline - time.monotonic()))
                if line is None:
                    raise LocalModelError("本地分析进程已停止；请检查所选环境和依赖。")
                data = decode_worker_response(line)
                if not data["ok"]:
                    raise LocalModelError(data.get("error", "本地模型加载失败。"))
                self.last_error = None
                result = data["result"]
                overlay = data.get("overlay")
                if overlay:
                    result["_overlay"] = overlay
                return result
            except (OSError, ValueError, queue.Empty, LocalModelError) as exc:
                self.close()
                self.last_error = str(exc) if isinstance(exc, LocalModelError) else "本地模型请求失败或超时；请检查环境后重试。"
                self.retry_after = time.monotonic() + 30
                raise LocalModelError(self.last_error) from exc

    def analyze(self, image_bgr, *, source_path="", observed_at=None, detector=None, config=None):
        import cv2
        from src.services.face_analysis_pipeline import AnalysisConfig, MediaPipeFaceDetector, detect_face_crop, _face_box_fail_reasons, _exposure_fail_reasons
        observed_at = observed_at or datetime.now()
        config = config or AnalysisConfig()
        detector = detector or MediaPipeFaceDetector(config.min_detection_confidence)
        result = {"path": source_path, "datetime": observed_at.strftime("%Y-%m-%d %H:%M:%S"), "timestamp": observed_at.timestamp(), "passed": False, "score": None, "score_left": None, "score_right": None, "fail_reason": [], "method": self.settings.get("face_analysis_method", "onnx"), "algorithm_version": ALGORITHM_VERSION, "profile_id": self.paths["profile_id"]}
        if image_bgr is None or image_bgr.size == 0:
            result["fail_reason"] = ["ReadError"]
            return result
        crop, error, bbox = detect_face_crop(image_bgr, detector, config)
        if crop is None:
            result["fail_reason"] = [error or "NoFace"]
            return result
        result["fail_reason"] = _face_box_fail_reasons(image_bgr, bbox, config)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        if cv2.Laplacian(gray, cv2.CV_64F).var() < config.blur_threshold:
            result["fail_reason"].append("Blurry")
        result["fail_reason"].extend(_exposure_fail_reasons(gray, config))
        if result["fail_reason"]:
            return result
        crop = cv2.resize(crop, (512, 512))
        response = self.request(crop)
        result.update(response)
        overlay = result.pop("_overlay", None)
        if source_path and result.get("passed") and overlay:
            from src.core.user_config import _atomic_write_bytes
            with self.lock:
                meta_path = self.paths["root"] / "overlay-meta.json"
                try:
                    previous = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    previous = {}
                if float(result["timestamp"]) >= float(previous.get("timestamp", 0)):
                    self.paths["root"].mkdir(parents=True, exist_ok=True)
                    meta = {key: result.get(key) for key in ("score", "score_left", "score_right", "datetime", "timestamp", "method", "algorithm_version")}
                    _atomic_write_bytes(self.paths["overlay"], base64.b64decode(overlay, validate=True))
                    _atomic_write_bytes(meta_path, json.dumps(meta).encode("utf-8"))
        return result


def get_local_runtime(settings=None):
    values = load_settings() if settings is None else settings
    key = profile_paths(values)["profile_id"]
    with _registry_lock:
        if key not in _runtimes:
            for runtime in _runtimes.values():
                runtime.close()
            _runtimes.clear()
            _runtimes[key] = LocalFaceRuntime(values)
        return _runtimes[key]


def close_local_runtimes():
    with _registry_lock:
        for runtime in _runtimes.values():
            runtime.close()
        _runtimes.clear()


atexit.register(close_local_runtimes)
