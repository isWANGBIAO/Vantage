"""Optional model process. Input/output are bounded local JSON lines, not HTTP."""
from __future__ import annotations
import argparse
import base64
import contextlib
import json
import os
from pathlib import Path
import sys

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", OPENCV_OPENCL_RUNTIME="disabled")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class OnnxAdapter:
    def __init__(self, model):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.log_severity_level = 3
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(model, sess_options=options, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    def infer(self, bgr):
        import cv2
        import numpy as np
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
        normalized = (rgb - np.array([.485, .456, .406], np.float32)) / np.array([.229, .224, .225], np.float32)
        logits = self.session.run(None, {self.input_name: normalized.transpose(2, 0, 1)[None].astype(np.float32)})[0]
        if logits.shape != (1, 19, 512, 512):
            raise ValueError("UnsupportedOnnxOutput")
        return logits[0].argmax(0).astype(np.uint8)


class Sam3Adapter:
    def __init__(self, model):
        import torch
        from transformers import Sam3Model, Sam3Processor
        if not torch.cuda.is_available():
            raise RuntimeError("CudaUnavailable")
        self.torch = torch
        self.model = Sam3Model.from_pretrained(model, local_files_only=True).to("cuda").eval()
        self.processor = Sam3Processor.from_pretrained(model, local_files_only=True)
        self.dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16

    def infer(self, bgr):
        import cv2
        import numpy as np
        from PIL import Image
        torch = self.torch
        image = self.processor(images=Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)), return_tensors="pt").to("cuda")
        with torch.inference_mode(), torch.autocast("cuda", dtype=self.dtype):
            vision = self.model.get_vision_features(pixel_values=image.pixel_values)
        unions = []
        for prompt in ("face", "eye", "eyebrow"):
            text = self.processor(text=prompt, return_tensors="pt").to("cuda")
            with torch.inference_mode(), torch.autocast("cuda", dtype=self.dtype):
                prediction = self.model(vision_embeds=vision, **text)
            result = self.processor.post_process_instance_segmentation(prediction, threshold=.5, mask_threshold=.5, target_sizes=image["original_sizes"].tolist())[0]
            masks = result["masks"].detach().cpu().numpy().astype(bool)
            unions.append(np.any(masks, axis=0) if len(masks) else np.zeros((512, 512), bool))
        face, eyes, brows = unions
        parsing = np.zeros((512, 512), np.uint8)
        parsing[face & ~eyes & ~brows] = 1
        # The shared ROI pairs the two largest connected components spatially.
        parsing[eyes] = 4
        parsing[brows] = 2
        return parsing


def _error(exc):
    if isinstance(exc, ModuleNotFoundError):
        return f"所选 Python 缺少依赖：{exc.name}；请在该环境自行安装。"
    if str(exc) == "CudaUnavailable":
        return "SAM3 环境未检测到可用 CUDA 显卡。"
    if str(exc) == "UnsupportedOnnxOutput":
        return "ONNX 模型不兼容；请选择 BiSeNet ResNet18 的 19 类模型。"
    return f"本地分析失败（{type(exc).__name__}）；请检查模型和依赖是否完整。"


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--method", choices=("onnx", "sam3"), required=True)
    cli.add_argument("--model", required=True)
    args = cli.parse_args()
    adapter = None
    output = sys.stdout
    for line in sys.stdin:
        try:
            if len(line) > 4 * 1024 * 1024:
                raise ValueError("InputTooLarge")
            with contextlib.redirect_stdout(sys.stderr):
                import cv2
                import numpy as np
                from src.services.face_brow_analysis import analyze_segmented_face
                cv2.setNumThreads(2)
                request = json.loads(line)
                encoded = base64.b64decode(request["image"], validate=True)
                image = cv2.imdecode(np.frombuffer(encoded, np.uint8), cv2.IMREAD_COLOR)
                if image is None or image.shape != (512, 512, 3):
                    raise ValueError("InvalidCrop")
                if adapter is None:
                    adapter = OnnxAdapter(args.model) if args.method == "onnx" else Sam3Adapter(args.model)
                parsing = adapter.infer(image)
                result = analyze_segmented_face(image, parsing)
                regions = result.pop("regions", None)
                overlay = None
                if result.get("passed") and regions:
                    painted = image.copy()
                    under = regions["left"]["under_mask"] | regions["right"]["under_mask"]
                    cheek = regions["left"]["cheek_mask"] | regions["right"]["cheek_mask"]
                    painted[under.astype(bool)] = (0, 140, 255)
                    painted[cheek.astype(bool)] = (100, 210, 80)
                    view = cv2.addWeighted(image, .55, painted, .45, 0)
                    cv2.putText(view, "Orange: under-eye | Green: cheek", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1)
                    ok, png = cv2.imencode(".png", view)
                    if ok:
                        overlay = base64.b64encode(png).decode("ascii")
                response = {"ok": True, "result": result, "overlay": overlay}
        except Exception as exc:
            response = {"ok": False, "error": _error(exc)}
        output.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
        output.flush()


if __name__ == "__main__":
    main()
