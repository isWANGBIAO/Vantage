import glob
import os
import sys
import time


def configure_output(output_path="gpu_diag_output.txt"):
    stream = open(output_path, "w", encoding="utf-8")
    sys.stdout = stream
    sys.stderr = stream
    return stream


def configure_windows_gpu_environment():
    if os.name != "nt":
        return

    try:
        import nvidia.cublas
        import nvidia.cudnn

        cudnn_dir = os.path.dirname(nvidia.cudnn.__file__)
        cublas_dir = os.path.dirname(nvidia.cublas.__file__)

        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(os.path.join(cudnn_dir, "bin"))
            os.add_dll_directory(os.path.join(cublas_dir, "bin"))

        os.environ["PATH"] = (
            os.path.join(cudnn_dir, "bin")
            + os.pathsep
            + os.path.join(cublas_dir, "bin")
            + os.pathsep
            + os.environ["PATH"]
        )
        print(f"Added DLL paths: {cudnn_dir}, {cublas_dir}")
    except Exception as e:
        print(f"Setup failed: {e}")


def choose_model_path():
    onnx_files = glob.glob(os.path.expanduser("~/.uniface/models/*.onnx"))
    if not onnx_files:
        onnx_files = glob.glob("src/scripts/models/*.onnx")

    if not onnx_files:
        return None

    return onnx_files[0]


def main():
    stream = configure_output()
    try:
        import numpy as np
        import onnxruntime as ort

        configure_windows_gpu_environment()
        print("Available providers:", ort.get_available_providers())

        so = ort.SessionOptions()
        so.log_severity_level = 0

        model_path = choose_model_path()
        if not model_path:
            print("No ONNX model found to test.")
            return 1

        print(f"Testing with {model_path}")

        sess = ort.InferenceSession(model_path, so, providers=["CUDAExecutionProvider"])
        print("Session created. Providers in use:", sess.get_providers())

        inp = sess.get_inputs()[0]
        name = inp.name
        data = np.random.randn(1, 3, 512, 512).astype(np.float32)

        print("Running warmup...")
        sess.run(None, {name: data})
        print("Warmup done. Running loop...")

        start = time.time()
        for _ in range(50):
            sess.run(None, {name: data})
        end = time.time()

        print(f"Done 50 iters in {end - start:.2f}s. Avg FPS: {50 / (end - start):.2f}")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        stream.flush()
        stream.close()


if __name__ == "__main__":
    raise SystemExit(main())
