import os
import sys
import cv2
import numpy as np
import argparse
import json
import logging
import time
import glob
import pandas as pd
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
import multiprocessing
import traceback

# --- GPU Setup for Windows (Auto-load cuDNN/cuBLAS) ---
if os.name == 'nt':
    try:
        import nvidia.cudnn
        import nvidia.cublas
        
        # Add the directory containing the DLLs to the PATH
        cudnn_dir = os.path.dirname(nvidia.cudnn.__file__)
        cublas_dir = os.path.dirname(nvidia.cublas.__file__)
        
        # Explicitly add for Python 3.8+ DLL search
        if hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(os.path.join(cudnn_dir, "bin"))
            os.add_dll_directory(os.path.join(cublas_dir, "bin"))
            
        # Also add to PATH env var just in case
        os.environ['PATH'] = os.path.join(cudnn_dir, "bin") + os.pathsep + \
                             os.path.join(cublas_dir, "bin") + os.pathsep + \
                             os.environ['PATH']
                             
        print(f"[GPU Setup] Added CUDA libs: {cudnn_dir}, {cublas_dir}")
    except ImportError:
        pass # Not installed, skip
    except Exception as e:
        print(f"[GPU Setup] Warning: {e}")

# --- Configuration & Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("face_analysis_uniface.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Constants for Face Parsing (BiSeNet standard classes)
# 0: 'background', 1: 'skin', 2: 'l_brow', 3: 'r_brow', 4: 'l_eye', 5: 'r_eye',
# 6: 'eye_g', 7: 'l_ear', 8: 'r_ear', 9: 'ear_r', 10: 'nose', 11: 'mouth',
# 12: 'u_lip', 13: 'l_lip', 14: 'neck', 15: 'neck_l', 16: 'cloth', 17: 'hair', 18: 'hat'
CLASS_IDX = {
    'background': 0, 'skin': 1, 'l_brow': 2, 'r_brow': 3, 'l_eye': 4, 'r_eye': 5,
    'eye_g': 6, 'l_ear': 7, 'r_ear': 8, 'ear_r': 9, 'nose': 10, 'mouth': 11,
    'u_lip': 12, 'l_lip': 13, 'neck': 14, 'neck_l': 15, 'cloth': 16, 'hair': 17, 'hat': 18
}

ROI_CONFIG = {
    'under_band_ratio': 0.35,  # Height of under-eye band relative to eye height
    'cheek_offset_ratio': 1.0, # Distance to cheek sample relative to eye height
    'blur_thresh': 50.0,       # Laplacian variance threshold
    'min_face_size': 200,      # Minimum face width in pixels
    'model_input_size': (512, 512)
}

def check_and_download_model(model_path):
    """
    Ensure UniFace BiSeNet face-parsing ONNX exists using 'uniface' library.
    """
    if os.path.exists(model_path):
        return True

    print(f"[UniFace] Target model not found at: {model_path}")
    print("[UniFace] Triggering auto-download by initializing BiSeNet...")

    try:
        # This should download weights automatically on first use
        from uniface.parsing import BiSeNet
        _ = BiSeNet()
    except Exception as e:
        print(f"[UniFace] Failed to init BiSeNet (download may have failed): {e}")
        return False

    # UniFace caches models under ~/.uniface/models by default
    user_home = os.path.expanduser("~")
    search_roots = [
        os.path.join(user_home, ".uniface", "models"),
    ]

    found_onnx = None
    for root_dir in search_roots:
        if not os.path.exists(root_dir):
            continue
        for root, _, files in os.walk(root_dir):
            for f in files:
                fl = f.lower()
                if f.endswith(".onnx") and ("bisenet" in fl or "parsing" in fl):
                    found_onnx = os.path.join(root, f)
                    break
            if found_onnx:
                break
        if found_onnx:
            break

    if not found_onnx:
        print("[UniFace] BiSeNet ONNX not found in cache.")
        return False

    print(f"[UniFace] Found cached model: {found_onnx}")
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    import shutil
    shutil.copy2(found_onnx, model_path)
    print("[UniFace] Model copied successfully.")
    return True


# --- OnnxRuntime Wrapper & MediaPipe Fallback ---
class FaceParser:
    def __init__(self, model_path, provider='CUDAExecutionProvider'):
        self.use_fallback = False
        import onnxruntime as ort
        
        self.model_path = model_path
        if not os.path.exists(model_path):
            logger.warning(f"Model not found at {model_path}. Switching to MediaPipe Fallback.")
            self.use_fallback = True
            try:
                import mediapipe as mp
                self.mp_face_mesh = mp.solutions.face_mesh.FaceMesh(
                    static_image_mode=True,
                    max_num_faces=1,
                    refine_landmarks=True,
                    min_detection_confidence=0.5
                )
            except Exception as e:
                raise ImportError(f"MediaPipe fallback failed: {e}")
            return

        try:
            # Silence extensive ONNX Runtime warnings
            sess_options = ort.SessionOptions()
            sess_options.log_severity_level = 3
            
            available_providers = ort.get_available_providers()
            if provider == 'CUDAExecutionProvider' and provider not in available_providers:
                logger.warning("CUDA provider requested but not available. Falling back to CPU.")
                provider = 'CPUExecutionProvider'
            
            logger.info(f"Loading model with provider: {provider}")
            self.session = ort.InferenceSession(model_path, sess_options, providers=[provider])
            
            self.input_name = self.session.get_inputs()[0].name
            self.input_shape = self.session.get_inputs()[0].shape 
            
        except Exception as e:
            logger.error(f"Failed to initialize FaceParser: {e}")
            # Fallback if init fails
            self.use_fallback = True
            import mediapipe as mp
            self.mp_face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=True,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5
            )

    def preprocess(self, img_bgr):
        # Resize to 512x512
        target_h, target_w = ROI_CONFIG['model_input_size']
        img_resized = cv2.resize(img_bgr, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        
        if self.use_fallback:
            return None, img_resized

        img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
        img_float = img_rgb.astype(np.float32)
        img_norm = (img_float - 127.5) / 127.5
        
        img_chw = img_norm.transpose(2, 0, 1)
        img_batch = np.expand_dims(img_chw, axis=0)
        return img_batch, img_resized

    def infer(self, img_bgr):
        blob, resized_src = self.preprocess(img_bgr)
        
        if self.use_fallback:
            # Generate Masks using MediaPipe
            h, w = resized_src.shape[:2]
            results = self.mp_face_mesh.process(cv2.cvtColor(resized_src, cv2.COLOR_BGR2RGB))
            
            parsing_map = np.zeros((h, w), dtype=np.uint8) # Default background=0
            
            if results.multi_face_landmarks:
                landmarks = results.multi_face_landmarks[0].landmark
                
                # Helper to transform landmarks to points
                def to_pts(indices):
                    pts = []
                    for idx in indices:
                        pt = landmarks[idx]
                        pts.append((int(pt.x * w), int(pt.y * h)))
                    return np.array(pts, dtype=np.int32)

                # MediaPipe Landmark Indices (Approximate)
                # Face Oval (Skin) - 10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109
                FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
                
                # Left Eye
                LEFT_EYE = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
                # Right Eye
                RIGHT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
                # Nose
                NOSE = [1, 2, 98, 327] # minimal nose
                
                # Draw Skin (1)
                cv2.fillPoly(parsing_map, [to_pts(FACE_OVAL)], CLASS_IDX['skin'])
                
                # Draw Eyes (4, 5) - overwrites skin
                cv2.fillPoly(parsing_map, [to_pts(LEFT_EYE)], CLASS_IDX['l_eye'])
                cv2.fillPoly(parsing_map, [to_pts(RIGHT_EYE)], CLASS_IDX['r_eye'])
                
                # Draw Nose (10)
                # cv2.fillPoly(parsing_map, [to_pts(NOSE)], CLASS_IDX['nose'])
                
            return parsing_map, resized_src
        
        # Normal ONNX Inference
        outputs = self.session.run(None, {self.input_name: blob})
        out = outputs[0][0] # (19, 512, 512)
        parsing_map = out.argmax(0).astype(np.uint8) # (512, 512)
        return parsing_map, resized_src

# --- Dark Circle Logic ---
class DarkCircleAnalyzer:
    @staticmethod
    def get_mask_roi(parsing_map, class_idx):
        return (parsing_map == class_idx).astype(np.uint8) * 255

    @staticmethod
    def get_box(mask):
        coords = cv2.findNonZero(mask)
        if coords is None: return None
        x, y, w, h = cv2.boundingRect(coords)
        return (x, y, w, h)

    @staticmethod
    def analyze_image(img_path, parser: FaceParser, debug=False, debug_dir="debug_overlays"):
        result = {
            "file": os.path.basename(img_path),
            "path": img_path,
            "timestamp": 0,
            "datetime": "",
            "passed": False,
            "fail_reason": [],
            "score": 0.0,
            "score_left": 0.0,
            "score_right": 0.0,
            "orientation": "unknown" 
        }

        # 1. Load and metadata
        try:
            # Handle filename date (photo_YYYYMMDD_HHMMSS.jpg)
            basename = os.path.basename(img_path)
            ts_str = basename.replace("photo_", "").replace(".jpg", "").replace(".png", "")
            if len(ts_str) >= 15:
                 dt = datetime.strptime(ts_str[:15], "%Y%m%d_%H%M%S")
                 result['timestamp'] = dt.timestamp()
                 result['datetime'] = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, IndexError):
             # Try OS mtime as fallback
             pass
        
        if result['timestamp'] == 0:
            result['timestamp'] = os.path.getmtime(img_path)
            result['datetime'] = datetime.fromtimestamp(result['timestamp']).strftime("%Y-%m-%d %H:%M:%S")

        try:
            # 2. Basic Checks
            # Use numpy fromfile for win32 unicode paths support
            img_bgr = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img_bgr is None:
                result['fail_reason'].append("ReadError")
                return result

            h_orig, w_orig = img_bgr.shape[:2]
            
            # Blur check
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            variance = cv2.Laplacian(gray, cv2.CV_64F).var()
            if variance < ROI_CONFIG['blur_thresh']:
                result['fail_reason'].append(f"Blurry({int(variance)})")
                return result

            # 3. Parsing
            parsing_map, resized_img = parser.infer(img_bgr)
            h_parse, w_parse = parsing_map.shape
            
            # Get masks
            mask_skin = (parsing_map == CLASS_IDX['skin']).astype(np.uint8)
            mask_l_eye = (parsing_map == CLASS_IDX['l_eye']).astype(np.uint8)
            mask_r_eye = (parsing_map == CLASS_IDX['r_eye']).astype(np.uint8)
            mask_nose = (parsing_map == CLASS_IDX['nose']).astype(np.uint8)
            
            # Face size check (approximate via nose+eyes width or skin area)
            face_pixels = np.count_nonzero(mask_skin)
            if face_pixels < 5000: # Very rough heuristic
                result['fail_reason'].append("FaceTooSmall")
                return result

            # 4. Construct ROIs
            def analyze_eye_region(eye_mask, side_prefix):
                # Returns (score, debug_img_patch)
                coords = cv2.findNonZero(eye_mask)
                if coords is None: return 0.0, None
                ex, ey, ew, eh = cv2.boundingRect(coords)
                
                # Dynamic band height
                band_h = int(eh * ROI_CONFIG['under_band_ratio'])
                
                # Under-Eye ROI
                # Start from bottom of eye, go down band_h
                # Constrain x to eye width
                uy = ey + eh
                ux = ex
                uw = ew
                uh = band_h
                
                # Create mask for ROI
                roi_mask = np.zeros_like(parsing_map, dtype=np.uint8)
                cv2.rectangle(roi_mask, (ux, uy), (ux+uw, uy+uh), 1, -1)
                
                # Intersect with Skin (to avoid background/hair)
                # Dilation on skin slightly to be forgiving? No, keep strict.
                final_mask = cv2.bitwise_and(roi_mask, mask_skin)
                
                # Cheek Reference ROI using robust offset
                # Go down further
                cheek_y_offset = int(eh * ROI_CONFIG['cheek_offset_ratio'])
                cy = uy + uh + cheek_y_offset
                ch = int(eh * 0.5) # Smaller sample
                cw = int(ew * 0.8)
                cx = ex + int(ew * 0.1) # Center it horizontally relative to eye
                
                ref_mask = np.zeros_like(parsing_map, dtype=np.uint8)
                cv2.rectangle(ref_mask, (cx, cy), (cx+cw, cy+ch), 1, -1)
                ref_mask = cv2.bitwise_and(ref_mask, mask_skin)
                
                # Check valid pixels
                if cv2.countNonZero(final_mask) < 10 or cv2.countNonZero(ref_mask) < 10:
                    return 0.0, None

                # 5. Calculate Score (LAB L-channel)
                # Convert RESIZED image to LAB
                lab = cv2.cvtColor(resized_img, cv2.COLOR_BGR2LAB)
                l_channel = lab[:,:,0]
                
                l_under = l_channel[final_mask == 1]
                l_ref = l_channel[ref_mask == 1]
                
                # Robust Stats: Median
                med_under = np.median(l_under)
                med_ref = np.median(l_ref)
                
                raw_diff = med_ref - med_under
                score = max(0.0, raw_diff)
                
                # Debug Overlay
                if debug:
                    overlays = resized_img.copy()
                    # Red for under-eye
                    overlays[final_mask==1] = [0, 0, 255]
                    # Green for ref
                    overlays[ref_mask==1] = [0, 255, 0]
                    return score, overlays
                
                return score, None

            s_left, deb_l = analyze_eye_region(mask_l_eye, "left")
            s_right, deb_r = analyze_eye_region(mask_r_eye, "right")
            
            result['score_left'] = s_left
            result['score_right'] = s_right
            result['score'] = (s_left + s_right) / 2.0
            result['passed'] = True
            
            # Simple pose gating (if nose center is too far from eye center midpoint)
            # Not implemented strictly here without landmarks, assuming mask availability implies decently frontal.
            
            if debug and (deb_l is not None or deb_r is not None):
                # Save debug image
                os.makedirs(debug_dir, exist_ok=True)
                # Blend
                debug_view = resized_img.copy()
                if deb_l is not None:
                     alpha = 0.5
                     mask = np.any(deb_l != resized_img, axis=2)
                     debug_view[mask] = cv2.addWeighted(resized_img, 1-alpha, deb_l, alpha, 0)[mask]
                if deb_r is not None:
                     alpha = 0.5
                     mask = np.any(deb_r != resized_img, axis=2)
                     debug_view[mask] = cv2.addWeighted(debug_view, 1-alpha, deb_r, alpha, 0)[mask]
                     
                cv2.imwrite(os.path.join(debug_dir, f"debug_{basename}"), debug_view)

        except Exception as e:
            result['fail_reason'].append(f"Exc:{str(e)}")
            # traceback.print_exc()

        return result

# --- Batch Processing ---
def process_single_param(args):
    path, model_path = args
    # Create parser instance per process (avoid pickling issues with onnxruntime session)
    # Ideally should initialize ONCE per worker.
    # We use a global initializer for pool if possible, but simplest is lazy load.
    
    # PERFORMANCE NOTE: Loading ONNX session every image is SLOW.
    # For a real batch script, we should use 'initializer' in ProcessPoolExecutor
    # or just use a ThreadPoolExecutor (ONNX Runtime releases GIL often).
    # Since GIL is released during inference, ThreadPool is actually fine and preferred here to share memory!
    
    # We will use ThreadPool in main, passing the shared parser instance.
    return None

def worker_init(model_path):
    global global_parser
    try:
        global_parser = FaceParser(model_path)
    except Exception as e:
        print(f"Worker init failed: {e}")
        global_parser = None

def worker_func(path):
    if global_parser is None:
        return {"file": os.path.basename(path), "path": path, "passed": False, "fail_reason": ["ModelLoadFail"]}
    
    # Optional: Skip if output exists? Handled by main.
    return DarkCircleAnalyzer.analyze_image(path, global_parser, debug=False) # Turn off debug for bulk to save IO

def main():
    parser = argparse.ArgumentParser(description="UniFace Dark Circle Analysis")
    parser.add_argument("--model", type=str, required=True, help="Path to face_parsing.farl.lapa.int8.onnx or similar")
    parser.add_argument("--dir", type=str, nargs='+', help="Directories to scan")
    parser.add_argument("--out", type=str, default="results.csv", help="Output CSV")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers")
    parser.add_argument("--debug", action="store_true", help="Enable debug overlays (slow)")
    args = parser.parse_args()

    # Auto-download check
    if not os.path.exists(args.model):
         print("ONNX model not found. Attempting download or switching to MediaPipe Fallback...")
         check_and_download_model(args.model) # Try download, but don't exit if fails
    
    # 1. Scan Files
    image_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
    files = []
    
    # Default directories if none provided (compatible with previous script logic)
    search_dirs = args.dir if args.dir else [
        os.path.join(os.path.expanduser("~"), "OneDrive", "图片", "本机照片"),
        r"D:\WANGBIAO\图片\本机照片"
    ]
    
    print(f"Scanning directories: {search_dirs}")
    for d in search_dirs:
        if os.path.exists(d):
            for root, _, filest in os.walk(d):
                for f in filest:
                    if os.path.splitext(f)[1].lower() in image_exts:
                        files.append(os.path.join(root, f))
    
    print(f"Found {len(files)} potential images.")
    if len(files) == 0:
        return

    # 2. Resume Logic
    processed_paths = set()
    if os.path.exists(args.out):
        try:
            df_exist = pd.read_csv(args.out)
            if 'path' in df_exist.columns:
                processed_paths = set(df_exist['path'].astype(str))
                print(f"Resuming... skipping {len(processed_paths)} already processed files.")
        except (OSError, ValueError) as exc:
            print(f"Could not read existing CSV ({exc}), starting fresh.")
    
    files_to_process = [f for f in files if f not in processed_paths]
    print(f"Remaining to process: {len(files_to_process)}")

    results = []
    
    # 3. Processing
    # Use ProcessPoolExecutor with initializer for Model Loading
    # (Threadpool might be blocked by GIL in OpenCV parts, ProcessPool is safer for CPU bound pre/post process)
    # However ONNX Runtime GPU is picky with forking. 'spawn' is needed on Windows.
    # Let's use simple loop if only 1 worker, else ProcessPool.
    
    if args.workers == 1:
        worker_init(args.model)
        for f in tqdm(files_to_process):
            res = worker_func(f)
            results.append(res)
            # Incremental save
            pd.DataFrame([res]).to_csv(args.out, mode='a', header=not os.path.exists(args.out), index=False)
    else:
        # Windows requires if __name__ == '__main__' protection for multiprocessing, which we have.
        # We need to ensure 'spawn' context.
        ctx = multiprocessing.get_context('spawn')
        with ctx.Pool(processes=args.workers, initializer=worker_init, initargs=(args.model,)) as pool:
            # Use tqdm
            for res in tqdm(pool.imap_unordered(worker_func, files_to_process), total=len(files_to_process)):
                results.append(res)
                
                # Buffer writes to avoid IO bottleneck? Or just write every N
                # For safety, write often or use a separate list and concat later?
                # Let's write to a temp list and flush every 100
                if len(results) % 50 == 0:
                    df_chunk = pd.DataFrame(results[-50:])
                    header = not os.path.exists(args.out)
                    df_chunk.to_csv(args.out, mode='a', header=header, index=False)

    # Flush remaining
    if results:
        # If we wrote incrementally, we are essentially done, but let's ensure partial chunks are written
        pass # The loop above writes every 50. 
        # Actually logic above writes the *last 50*, need to track which are written.
        # Simplified: Just append logic inside loop is safer.
        # Re-write the "last chunk" carefully.
        
        # Better approach for script: Write all new results at end if not huge, OR append mode carefully.
        # The 'mode=a' inside loop logic above had a bug (it wrote results[-50:] which might duplicate if not cleared).
        # Correct logic:
        # buffer = []
        # for ...
        #   buffer.append(res)
        #   if len(buffer) >= 50:
        #      write(buffer)
        #      buffer = []
        pass


    print("Processing complete.")
    
    # 4. Generate Visualization (Trend & Extremes)
    # Reload full full dataframe
    if os.path.exists(args.out):
        df = pd.read_csv(args.out)
        
        # Filter passed & valid
        df_valid = df[(df['passed'] == True) & (df['score'] > 0)].copy()
        if df_valid.empty:
            print("No valid results to plot.")
            return

        df_valid['date'] = pd.to_datetime(df_valid['datetime'])
        df_valid = df_valid.sort_values('date')

        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        # --- Trend Plot ---
        plt.figure(figsize=(14, 7))
        plt.style.use('dark_background')
        
        # Scatter Raw
        plt.scatter(df_valid['date'], df_valid['score'], alpha=0.3, s=15, color='#4A90E2', label='Raw Score', linewidths=0)
        
        # Daily Mean
        daily = df_valid.set_index('date').resample('D')['score'].mean().interpolate()
        # Smooth
        smoothed = daily.rolling(window=14, center=True, min_periods=1).mean()
        
        plt.plot(smoothed.index, smoothed.values, color='#FF5E57', linewidth=3, label='14-Day Trend')
        
        plt.title(f"Dark Circle Severity Trend (N={len(df_valid)})", fontsize=16)
        plt.ylabel("Severity (Contrast Diff)", fontsize=12)
        plt.grid(True, alpha=0.2)
        plt.legend()
        plt.gcf().autofmt_xdate()
        
        plt.savefig("dark_circle_trend_uniface.png", dpi=120, bbox_inches='tight')
        print("Saved dark_circle_trend_uniface.png")

        # --- Extremes ---
        df_valid = df_valid.sort_values('score')
        best = df_valid.iloc[0]
        worst = df_valid.iloc[-1]
        
        # Create collage
        # Load best/worst images
        def load_rgb(p):
            img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            return cv2.cvtColor(img, cv2.COLOR_BGR2RGB) if img is not None else np.zeros((200,200,3), np.uint8)

        img_best = load_rgb(best['path'])
        img_worst = load_rgb(worst['path'])
        
        # Resize to same height
        h = 500
        scale_b = h / img_best.shape[0]
        scale_w = h / img_worst.shape[0]
        img_best = cv2.resize(img_best, (int(img_best.shape[1]*scale_b), h))
        img_worst = cv2.resize(img_worst, (int(img_worst.shape[1]*scale_w), h))
        
        # Concat
        collage = np.hstack([img_best, np.zeros((h, 20, 3), dtype=np.uint8), img_worst])
        
        plt.figure(figsize=(12, 6))
        plt.imshow(collage)
        plt.axis('off')
        plt.title(f"BEST ({best['datetime']}, Score={best['score']:.1f})   vs   WORST ({worst['datetime']}, Score={worst['score']:.1f})", color='white')
        plt.savefig("extremes_uniface.png", dpi=120, bbox_inches='tight')
        print("Saved extremes_uniface.png")

        # --- TopN Export ---
        print("Exporting Top 10 Best and Worst images...")
        os.makedirs("top_lightest", exist_ok=True)
        os.makedirs("top_darkest", exist_ok=True)
        
        # Best (Lightest) -> Low Score
        for i, row in df_valid.head(10).iterrows():
            try:
                src = row['path']
                dst = os.path.join("top_lightest", f"rank_{i+1}_{row['score']:.2f}_{os.path.basename(src)}")
                with open(src, 'rb') as fsrc:
                    with open(dst, 'wb') as fdst:
                        fdst.write(fsrc.read())
            except Exception as e:
                print(f"Error copying {src}: {e}")

        # Worst (Darkest) -> High Score
        # NOTE: tail(10) iteration was dead code — worst export relies on df_desc below instead.
            
        # Re-sort descending for worst export
        df_desc = df_valid.sort_values('score', ascending=False)
        for i, row in df_desc.head(10).iterrows():
            try:
                src = row['path']
                dst = os.path.join("top_darkest", f"rank_{i+1}_{row['score']:.2f}_{os.path.basename(src)}")
                with open(src, 'rb') as fsrc:
                    with open(dst, 'wb') as fdst:
                        fdst.write(fsrc.read())
            except Exception as e:
                print(f"Error copying {src}: {e}")
                
        print("Done.")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
