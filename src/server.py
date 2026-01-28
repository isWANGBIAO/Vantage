import os
import sys
import cv2
import json
import time
import subprocess
import threading
import glob
import asyncio
from fastapi import FastAPI, WebSocket, Request, UploadFile, File, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import psutil
import shutil
import requests

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from manager.manager_main import Monitor
from cv2_enumerate_cameras import enumerate_cameras

app = FastAPI()

# Allow CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State
class SystemState:
    def __init__(self):
        self.camera = None
        self.monitor = None
        self.latest_frame = None
        self.is_running = True
        self.lock = threading.Lock()
        self.paths = {'photo': None, 'screenshot': None}
        self.photos_path = None
        self.screenshots_path = None
        self.legacy_size = 0 # Cache for legacy storage size

state = SystemState()

def update_legacy_storage_stats():
    """Background task to calculate legacy storage usage once to avoid blocking main loop"""
    print("Starting background legacy storage scan...")
    try:
        total_size = 0
        
        # Candidates for legacy paths (OneDrive)
        candidates = []
        onedrive_env = os.environ.get("OneDrive")
        user_home = os.path.expanduser("~")
        
        roots_to_check = []
        if onedrive_env:
            roots_to_check.append(onedrive_env)
        roots_to_check.append(os.path.join(user_home, "OneDrive"))
        
        # STRICT SUBDIRECTORIES: Only folders created by THIS program
        subdirs = [
             os.path.join("Pictures", "本机照片"),
             os.path.join("图片", "本机照片"),
             os.path.join("Pictures", "Screenshots"),
             os.path.join("图片", "屏幕截图"),
             "本机照片", 
             os.path.join("Pictures", "屏幕截图"),
             os.path.join("图片", "Screenshots")
        ]
        
        for root_dir in set(roots_to_check): # unique roots
            if root_dir and os.path.exists(root_dir):
                for sub in subdirs:
                    candidates.append(os.path.join(root_dir, sub))

        # Filter out invalid or current paths
        checked_paths = set()
        for cand in candidates:
            if not os.path.exists(cand): continue
            
            # Skip if current path
            if state.photos_path and os.path.abspath(cand) == os.path.abspath(state.photos_path): continue
            if state.screenshots_path and os.path.abspath(cand) == os.path.abspath(state.screenshots_path): continue
            
            # Avoid duplicates
            abs_cand = os.path.abspath(cand)
            if abs_cand in checked_paths: continue
            checked_paths.add(abs_cand)
            
            print(f"Scanning legacy path: {abs_cand}")
            for root, dirs, files in os.walk(cand):
                total_size += sum(os.path.getsize(os.path.join(root, f)) for f in files)
        
        state.legacy_size = total_size
        print(f"Legacy storage scan complete: {state.legacy_size / (1024**2):.2f} MB")
        
    except Exception as e:
        print(f"Legacy storage scan error: {e}")

# ... (existing imports/functions) ...

@app.on_event("startup")
async def startup_event():
    print("Starting up server...")
    # ... (rest of startup) ...

def get_camera_index():
    camera_index = 0
    # Simple logic to find USB camera, similar to main_window.py
    for camera_info in enumerate_cameras(cv2.CAP_MSMF):
        if "USB Camera" in camera_info.name:
            camera_index = camera_info.index
            break
    return camera_index

def identify_logs_folder():
    # User requested D:\WANGBIAO as the base path
    onedrive_path = "D:\\WANGBIAO"
    if not os.path.exists(onedrive_path):
        try:
            os.makedirs(onedrive_path, exist_ok=True)
        except:
             # Fallback if D drive doesn't exist or permission error, though user asked for it.
             onedrive_path = os.environ.get("OneDrive", os.path.expanduser("~"))

    pictures_path = os.path.join(onedrive_path, "Pictures")
    if not os.path.exists(pictures_path):
        pictures_path = os.path.join(onedrive_path, "图片")
        
    screenshots_path = os.path.join(pictures_path, "Screenshots")
    if not os.path.exists(screenshots_path):
         screenshots_path = os.path.join(pictures_path, "屏幕截图")

    photos_path = os.path.join(pictures_path, "本机照片")
    
    # Ensure directories exist
    os.makedirs(photos_path, exist_ok=True)
    os.makedirs(screenshots_path, exist_ok=True)

    return photos_path, screenshots_path

@app.on_event("startup")
async def startup_event():
    print("Starting up server...")
    print("Starting up server...")
    try:
        # DEPRECATED IN FAVOR OF camera_loop: 
        # idx = get_camera_index()
        # state.camera = cv2.VideoCapture(idx)
        # if not state.camera.isOpened():
        #      print("Warning: Camera not opened")
        pass # Camera init moved to camera_loop to centralize resolution settings
    except Exception as e:
        print(f"Startup camera init error: {e}")
        
    # RESUME initialization (Unindented to run regardless of camera init success/failure)
    try:
        state.photos_path, state.screenshots_path = identify_logs_folder()
        print(f"----------------------------------------------------------------")
        print(f"[Storage] Photos Path: {state.photos_path}")
        print(f"[Storage] Screenshots Path: {state.screenshots_path}")
        print(f"----------------------------------------------------------------")
        
        state.monitor = Monitor(state.camera, state.paths, state.photos_path, state.screenshots_path)
        
        # Start background frame reading thread
        threading.Thread(target=camera_loop, daemon=True).start()
        
        # Start background monitor task thread (every 10s)
        threading.Thread(target=monitor_loop, daemon=True).start()
        
        # Start background legacy storage calculation (doesn't block startup)
        threading.Thread(target=update_legacy_storage_stats, daemon=True).start()

        # Mount static directories for photos and plots
        if state.photos_path and os.path.exists(state.photos_path):
            app.mount("/static/photos", StaticFiles(directory=state.photos_path), name="photos")
        
        plot_dir = os.path.join(os.getcwd(), "plot_outputs")
        if not os.path.exists(plot_dir):
            os.makedirs(plot_dir)
        app.mount("/static/plots", StaticFiles(directory=plot_dir), name="plots")
        
        if state.screenshots_path and os.path.exists(state.screenshots_path):
            if state.screenshots_path != state.photos_path:
                app.mount("/static/screenshots", StaticFiles(directory=state.screenshots_path), name="screenshots")
            else:
                app.mount("/static/screenshots", StaticFiles(directory=state.screenshots_path), name="screenshots")
                
        # Attempt to find latest existing files to populate state
        try:
            def find_latest_file_recursive(directory, extensions={'.jpg', '.png'}):
                latest_file = None
                latest_time = 0
                for root, dirs, files in os.walk(directory):
                    for f in files:
                        if os.path.splitext(f)[1].lower() in extensions:
                            full_path = os.path.join(root, f)
                            try:
                                mtime = os.path.getmtime(full_path)
                                if mtime > latest_time:
                                    latest_time = mtime
                                    latest_file = full_path
                            except:
                                pass
                return latest_file

            print("Scanning for latest existing images...")
            if not state.paths.get('photo') and state.photos_path:
                 latest_photo = find_latest_file_recursive(state.photos_path)
                 if latest_photo:
                     state.paths['photo'] = latest_photo
                     print(f"Found latest photo: {latest_photo}")

            if not state.paths.get('screenshot') and state.screenshots_path:
                 latest_screen = find_latest_file_recursive(state.screenshots_path)
                 if latest_screen:
                     state.paths['screenshot'] = latest_screen
                     print(f"Found latest screenshot: {latest_screen}")
        except Exception as e:
            print(f"Error finding latest files: {e}")

    except Exception as e:
        print(f"Startup logic error: {e}")

def monitor_loop():
    print("Starting monitor loop (10s interval)...")
    while state.is_running:
        try:
            if state.monitor:
                # CRITICAL: Ensure Monitor uses the current active camera instance (initialized in camera_loop)
                # If camera is not ready yet, skip this cycle to avoid errors or default-init
                if state.camera is None or not state.camera.isOpened():
                    # print("Monitor skipping: Camera not ready")
                    time.sleep(2)
                    continue
                
                # Update the camera reference in monitor to match the global state (which is 4K)
                state.monitor.camera = state.camera
                
                # Run the periodic task (take photo, screenshot, etc.)
                state.monitor.run_task()
        except Exception as e:
            print(f"Monitor loop error: {e}")
        time.sleep(10)

def camera_loop():
    print(f"Starting camera loop... Camera Index: {get_camera_index()}")
    while state.is_running:
        if state.camera is None:
             idx = get_camera_index()
             try:
                 # Use DirectShow (CAP_DSHOW) on Windows for better resolution control
                 state.camera = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                 
                 # Request 4K resolution (16:9)
                 target_w, target_h = 3840, 2160
                 state.camera.set(cv2.CAP_PROP_FRAME_WIDTH, target_w)
                 state.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, target_h)
                 
                 # Verify actual resolution
                 actual_w = state.camera.get(cv2.CAP_PROP_FRAME_WIDTH)
                 actual_h = state.camera.get(cv2.CAP_PROP_FRAME_HEIGHT)
                 print(f"Camera Initialized: Requested {target_w}x{target_h}, Got {int(actual_w)}x{int(actual_h)}")
                 
                 # If 4K failed (e.g. got low res), try strict 1080p fallback
                 if actual_w < 1280: 
                     print("4K failed or ignored, trying strict 1080p force...")
                     state.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                     state.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                     print(f"Fallback resolution: {int(state.camera.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(state.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
                     
             except Exception as e:
                 print(f"Camera init failed: {e}")
                 time.sleep(2)
                 continue

        if state.camera and state.camera.isOpened():
            try:
                ret, frame = state.camera.read()
                if ret:
                    with state.lock:
                        state.latest_frame = frame
                else:
                    print("Warning: Can't receive frame (stream end?). Exiting ...")
                    state.camera.release()
                    state.camera = None
                    time.sleep(2)
            except Exception as e:
                print(f"Camera read error: {e}")
                time.sleep(1)
        else:
             print("Camera not opened, retrying...")
             state.camera = None
             time.sleep(2)
             
        time.sleep(0.03)

def generate_frames():
    while True:
        frame = None
        with state.lock:
            if state.latest_frame is not None:
                frame = state.latest_frame.copy()
            else:
                # Create a black placeholder image (16:9 aspect ratio)
                import numpy as np
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                cv2.putText(frame, "Camera Offline", (400, 360), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 2)
        
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.04)

@app.get("/api/stream")
async def video_feed():
    return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/api/status")
async def get_status():
    return {
        "camera_online": state.camera.isOpened() if state.camera else False,
        "paths": state.paths,
        "photos_path": state.photos_path,
        "screenshots_path": state.screenshots_path,
        "cwd": os.getcwd()
    }

@app.get("/api/sys_stats")
async def get_sys_stats():
    try:
        cpu_usage = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        
        photos_size = 0
        if state.photos_path and os.path.exists(state.photos_path):
            for root, dirs, files in os.walk(state.photos_path):
                photos_size += sum(os.path.getsize(os.path.join(root, f)) for f in files)
        
        screenshots_size = 0
        if state.screenshots_path and os.path.exists(state.screenshots_path):
            for root, dirs, files in os.walk(state.screenshots_path):
                screenshots_size += sum(os.path.getsize(os.path.join(root, f)) for f in files)
        
        # Use cached legacy size from background thread
        legacy_size = state.legacy_size
        
        total, used, free = shutil.disk_usage(state.photos_path or ".")
        
        return {
            "cpu_usage": cpu_usage,
            "memory_used_gb": round(memory.used / (1024**3), 2),
            "memory_total_gb": round(memory.total / (1024**3), 2),
            "memory_percent": memory.percent,
            "disk_free_gb": round(free / (1024**3), 2),
            "storage_used_mb": round((photos_size + screenshots_size + legacy_size) / (1024**2), 2)
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/aqi")
async def get_aqi_stats(lat: Optional[float] = None, lon: Optional[float] = None):
    """Fetch current AQI (US) based on Location (Default: SJTU Minhang)"""
    try:
        # Default to Shanghai Jiao Tong University Minhang Campus
        # Lat: 31.025, Lon: 121.433
        target_lat = 31.025
        target_lon = 121.433
        city = "SJTU Minhang"
        
        # Only use provided coordinates if they seem valid and distinct from a generic VPN exit?
        # User requested "Directly display...", so let's prefer the hardcoded value 
        # unless we are very sure about the frontend provided ones.
        # But for now, to satisfy "Then just display...", I will default to these 
        # and only override if the frontend EXPLICITLY sends something different 
        # AND we trust it. 
        # Actually, let's just make it the default fallback instead of IP.
        # If frontend sends coordinates (permission granted), it might be accurate.
        # If permission denied, frontend sends null, we use SJTU.
        
        if lat is not None and lon is not None:
             target_lat = lat
             target_lon = lon
             city = "Current Location" 
        
        print(f"[AQI] Fetching for Lat: {target_lat}, Lon: {target_lon}, City: {city}")

        # 2. Get API (US Standard) from Open-Meteo
        aqi_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={target_lat}&longitude={target_lon}&current=us_aqi"
        
        aqi_res = await asyncio.to_thread(requests.get, aqi_url, timeout=5)
        if not aqi_res.ok:
            return JSONResponse(status_code=502, content={"error": "AQI API failed"})
            
        aqi_data = aqi_res.json()
        current = aqi_data.get("current", {})
        us_aqi = current.get("us_aqi")
        
        if us_aqi is None:
             return JSONResponse(status_code=404, content={"error": "No AQI data"})
             
        # Determine Level
        level = "Good"
        color = "#00e400" # Green
        if us_aqi > 50:
            level = "Moderate"
            color = "#ffff00" # Yellow
        if us_aqi > 100:
            level = "Unhealthy for Sensitive Groups"
            color = "#ff7e00" # Orange
        if us_aqi > 150:
            level = "Unhealthy"
            color = "#ff0000" # Red
        if us_aqi > 200:
            level = "Very Unhealthy"
            color = "#8f3f97" # Purple
        if us_aqi > 300:
            level = "Hazardous"
            color = "#7e0023" # Maroon
            
        return {
            "aqi": us_aqi,
            "city": city,
            "level": level,
            "color": color,
            "lat": lat,
            "lon": lon
        }
        
    except Exception as e:
        print(f"AQI Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/latest_images")
def get_latest_images():
    try:
        photo_path = state.paths.get('photo')
        screenshot_path = state.paths.get('screenshot')
        
        photo_url = None
        if photo_path and state.photos_path:
            try:
                rel_path = os.path.relpath(photo_path, state.photos_path)
                rel_path = rel_path.replace("\\", "/") # Ensure web-friendly slashes
                photo_url = f"/static/photos/{rel_path}"
            except ValueError:
                photo_url = f"/static/photos/{os.path.basename(photo_path)}"
            
        screenshot_url = None
        if screenshot_path and state.screenshots_path:
            try:
                # Always relative to screenshots_path mount
                rel_path = os.path.relpath(screenshot_path, state.screenshots_path)
                rel_path = rel_path.replace("\\", "/")
                screenshot_url = f"/static/screenshots/{rel_path}"
            except ValueError:
                screenshot_url = f"/static/screenshots/{os.path.basename(screenshot_path)}"

        return {
            "photo": photo_url,
            "screenshot": screenshot_url,
            "photo_name": os.path.basename(photo_path) if photo_path else "",
            "screenshot_name": os.path.basename(screenshot_path) if screenshot_path else ""
        }
    except Exception as e:
        print(f"ERROR in get_latest_images: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/plots/refresh")
async def refresh_plots(background_tasks: BackgroundTasks):
    # Locate plot.py in src/scripts
    current_dir = os.path.dirname(os.path.abspath(__file__)) # src/server.py -> src
    script_path = os.path.join(current_dir, "scripts", "plot.py")
    
    if not os.path.exists(script_path):
        # Fallback to absolute path check
        script_path = os.path.abspath("src/scripts/plot.py")

    if not os.path.exists(script_path):
        return JSONResponse(status_code=404, content={"error": "plot.py not found"})

    def run_plot_script():
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            subprocess.run([sys.executable, script_path, "--dark"], check=True, env=env, cwd=os.getcwd())
            print("Plots refreshed successfully")
        except Exception as e:
            print(f"Error refreshing plots: {e}")

    background_tasks.add_task(run_plot_script)
    return {"message": "Plot refresh started in background"}

def ensure_thumbnail(file_path, thumb_path):
    if not os.path.exists(thumb_path):
        try:
            img = cv2.imread(file_path)
            if img is not None:
                h, w = img.shape[:2]
                scale = 60.0 / float(h)
                new_w = int(w * scale)
                dim = (new_w, 60)
                resized = cv2.resize(img, dim, interpolation=cv2.INTER_AREA)
                cv2.imwrite(thumb_path, resized)
        except Exception as e:
            print(f"Error creating thumbnail for {file_path}: {e}")

@app.get("/api/plots/list")
async def list_plots():
    """Return list of all plot images for carousel display"""
    plot_dir = os.path.join(os.getcwd(), "plot_outputs")
    if not os.path.exists(plot_dir):
        return {"plots": [], "error": "plot_outputs directory not found"}
    
    thumb_dir = os.path.join(plot_dir, "thumbnails")
    if not os.path.exists(thumb_dir):
        os.makedirs(thumb_dir, exist_ok=True)
    
    try:
        # Get all PNG files except collages and screen files
        files = [f for f in os.listdir(plot_dir) 
                 if f.endswith(".png") 
                 and not f.startswith("plot_collage") 
                 and not f.endswith("_screen.png")]
        
        # Sort by predefined order (same as PyQt version)
        order = [
            "weight_bodyfat", "time_allocation_bar", "time_trend_screen_remaining",
            "time_trend_averages", "time_trend_delta", "running_pace",
            "radar_goal", "hhh_frequency", "hhh_interval_trend", "balance_sheet"
        ]
        
        def sort_key(name):
            for index, prefix in enumerate(order):
                if name.startswith(prefix):
                    return (index, name)
            return (len(order), name)
        
        sorted_files = sorted(files, key=sort_key)
        
        # Generate thumbnails and build response
        plot_list = []
        for f in sorted_files:
            file_path = os.path.join(plot_dir, f)
            thumb_path = os.path.join(thumb_dir, f)
            
            # Use threading to avoid blocking event loop for image processing
            await asyncio.to_thread(ensure_thumbnail, file_path, thumb_path)
            
            plot_list.append({
                "name": f,
                "url": f"/static/plots/{f}",
                "thumbnail_url": f"/static/plots/thumbnails/{f}"
            })
        
        return {
            "plots": plot_list,
            "count": len(plot_list)
        }
    except Exception as e:
        print(f"Error listing plots: {e}")
        return {"plots": [], "error": str(e)}

@app.get("/api/action_plan/today")
async def get_today_action_plan():
    """Return today's latest action plan if it exists"""
    from datetime import datetime
    
    today = datetime.now().strftime("%Y%m%d")  # Format: YYYYMMDD
    history_dir = os.path.join(os.getcwd(), "history")
    
    if not os.path.exists(history_dir):
        return {"exists": False, "content": None, "date": today}
    
    try:
        # Find all action_plan files for today, sorted by modification time (newest first)
        pattern = f"action_plan_{today}_*.md"
        import glob
        files = glob.glob(os.path.join(history_dir, pattern))
        
        if not files:
            return {"exists": False, "content": None, "date": today}
        
        # Get the most recent file
        latest_file = max(files, key=os.path.getmtime)
        
        with open(latest_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        return {
            "exists": True, 
            "content": content, 
            "date": today,
            "filename": os.path.basename(latest_file)
        }
    except Exception as e:
        return {"exists": False, "content": None, "error": str(e), "date": today}

class ChatRequest(BaseModel):
    message: str
    context_file: Optional[str] = None

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    # Locate run_prompt.py in src/scripts
    current_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(current_dir, "scripts", "run_prompt.py")
    if not os.path.exists(script_path):
         script_path = os.path.abspath("src/scripts/run_prompt.py")
    
    # Determine context file (similar logic to ChatWorker)
    context_file = request.context_file
    if not context_file:
         context_file = os.path.join(os.getcwd(), "history", "latest_context.json")

    cmd = [
        sys.executable, 
        script_path, 
        "--chat_message", request.message,
        "--context_file", context_file
    ]
    
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        # Use StreamingResponse for real-time chat output
        async def process_chat_stream():
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.dirname(script_path),
                env=env
            )
            
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    decoded = line.decode('utf-8').rstrip()
                except:
                    decoded = line.decode('gbk', errors='replace').rstrip()
                
                # Yield as NDJSON line
                # We strip to avoid double newlines, but keep empty lines if meaningful?
                # Usually log lines are fine.
                msg = decoded.strip()
                if msg:
                     yield json.dumps({"log": msg}) + "\n"
            
            await proc.wait()
            
            if proc.returncode != 0:
                 stderr_data = await proc.stderr.read()
                 err_msg = stderr_data.decode('utf-8', errors='replace')
                 yield json.dumps({"error": err_msg}) + "\n"

        return StreamingResponse(process_chat_stream(), media_type="application/x-ndjson")

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/action_plan")
async def generate_action_plan():
    # Locate run_prompt.py in src/scripts
    current_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(current_dir, "scripts", "run_prompt.py")
    if not os.path.exists(script_path):
         script_path = os.path.abspath("src/scripts/run_prompt.py")
    
    cmd = [sys.executable, script_path] # Default runs action plan generation
    
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    # Streaming response for real-time logs? 
    # For now, let's just return the full result or stream lines.
    # To support streaming to frontend, we might need Server Sent Events (SSE).
    # Since existing UI accumulates text, we can just return the full text for simplicity for now,
    # OR implement a simple generator.
    
    async def process_stream():
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, # Redirect stderr to stdout so errors appear in stream
            cwd=os.path.dirname(script_path),
            env=env
        )
        
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    decoded = line.decode('utf-8').rstrip()
                except:
                    decoded = line.decode('gbk', errors='replace').rstrip()
                yield json.dumps({"log": decoded}) + "\n"
                
            await proc.wait()
            
        except asyncio.CancelledError:
            print("Stream cancelled by client")
            proc.terminate()
            raise
        finally:
            if proc.returncode is None:
                print("Killing orphan process")
                proc.kill()
    
    return StreamingResponse(process_stream(), media_type="application/x-ndjson")

@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    # 获取上传文件的扩展名
    original_filename = file.filename or "recording.webm"
    ext = os.path.splitext(original_filename)[1] or ".webm"
    
    # 保存临时文件到项目根目录
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    temp_filename = os.path.join(project_root, f"temp_audio_{int(time.time())}{ext}")
    
    print(f"[Transcribe] Saving uploaded file to: {temp_filename}")
    
    with open(temp_filename, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
        print(f"[Transcribe] File size: {len(content)} bytes")
        
    # Locate run_prompt.py in src/scripts
    current_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(current_dir, "scripts", "run_prompt.py")
    if not os.path.exists(script_path):
         script_path = os.path.abspath("src/scripts/run_prompt.py")
    
    cmd = [sys.executable, script_path, "--transcribe", temp_filename]
    print(f"[Transcribe] Running command: {' '.join(cmd)}")
    
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=project_root,  # 在项目根目录运行
        env=env
    )
    
    stdout, stderr = await proc.communicate()
    
    # Cleanup
    if os.path.exists(temp_filename):
        os.remove(temp_filename)
        
    output = ""
    try:
        output = stdout.decode('utf-8')
    except:
        output = stdout.decode('gbk', errors='replace')
    
    # 打印调试信息
    if stderr:
        try:
            stderr_text = stderr.decode('utf-8')
        except:
            stderr_text = stderr.decode('gbk', errors='replace')
        print(f"[Transcribe] Stderr: {stderr_text}")
    
    print(f"[Transcribe] Stdout: {output}")
        
    transcription = ""
    for line in output.splitlines():
        if line.startswith("TRANSCRIPTION_RESULT:"):
            transcription = line.replace("TRANSCRIPTION_RESULT:", "").strip()
            break
    
    print(f"[Transcribe] Result: '{transcription}'")
            
    return {"transcription": transcription}

@app.get("/api/action_plan_content")
async def get_action_plan_content():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        history_dir = os.path.join(project_root, "history")
        
        if not os.path.exists(history_dir):
            return {"content": ""}
            
        # Find latest action_plan file
        files = glob.glob(os.path.join(history_dir, "action_plan_*.md"))
        if not files:
            return {"content": ""}
            
        latest_file = max(files, key=os.path.getctime)
        
        with open(latest_file, "r", encoding="utf-8") as f:
            content = f.read()
            
        return {"content": content, "timestamp": os.path.getctime(latest_file)}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/system_logs")
async def get_system_logs():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        log_file = os.path.join(project_root, "logs", "server.log")
        
        if not os.path.exists(log_file):
            return {"logs": ["Log file not found."]}
            
        # Read last 200 lines to avoid huge payload
        with open(log_file, "r", encoding="utf-8", errors='ignore') as f:
            # Simple approach: read all then slice (optimized for small logs)
            # For huge logs, seek would be better.
            lines = f.readlines()
            
        return {"logs": lines[-200:]}
    except Exception as e:
        return {"logs": [f"Error reading logs: {str(e)}"]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
