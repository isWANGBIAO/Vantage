import sys
import os

# Redirect stdout/stderr to file IMMEDIATELY
sys.stdout = open("gpu_diag_output.txt", "w", encoding="utf-8")
sys.stderr = sys.stdout

import onnxruntime as ort
import numpy as np
import time

# Try to setup environment like the main script
if os.name == 'nt':
    try:
        import nvidia.cudnn
        import nvidia.cublas
        
        cudnn_dir = os.path.dirname(nvidia.cudnn.__file__)
        cublas_dir = os.path.dirname(nvidia.cublas.__file__)
        
        if hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(os.path.join(cudnn_dir, "bin"))
            os.add_dll_directory(os.path.join(cublas_dir, "bin"))
            
        os.environ['PATH'] = os.path.join(cudnn_dir, "bin") + os.pathsep + \
                             os.path.join(cublas_dir, "bin") + os.pathsep + \
                             os.environ['PATH']
        print(f"Added DLL paths: {cudnn_dir}, {cublas_dir}")
    except Exception as e:
        print(f"Setup failed: {e}")

print("Available providers:", ort.get_available_providers())

try:
    so = ort.SessionOptions()
    so.log_severity_level = 0 # Verbose
    
    model_path = "src/scripts/models/parsing_resnet18.onnx" # default uniface model name?
    # Or find any onnx
    import glob
    onnx_files = glob.glob(os.path.expanduser("~/.uniface/models/*.onnx"))
    if not onnx_files:
        onnx_files = glob.glob("src/scripts/models/*.onnx")
        
    if not onnx_files:
        print("No ONNX model found to test.")
        sys.exit(1)
        
    model_path = onnx_files[0]
    print(f"Testing with {model_path}")
    
    sess = ort.InferenceSession(model_path, so, providers=['CUDAExecutionProvider'])
    print("Session created. Providers in use:", sess.get_providers())
    
    inp = sess.get_inputs()[0]
    shape = inp.shape
    name = inp.name
    
    # Fake input
    # adjust shape for common face parsing models
    # if shape has dynamic axes, it might show strings.
    # usually [1, 3, 512, 512]
    
    # Simple heuristic
    h, w = 512, 512
    data = np.random.randn(1, 3, h, w).astype(np.float32)
    
    print("Running warmup...")
    sess.run(None, {name: data})
    print("Warmup done. Running loop...")
    
    start = time.time()
    for i in range(50):
        sess.run(None, {name: data})
    end = time.time()
    
    print(f"Done 50 iters in {end-start:.2f}s. Avg FPS: {50/(end-start):.2f}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()


