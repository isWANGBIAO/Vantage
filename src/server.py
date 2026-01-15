import os
import sys
import cv2
import json
import time
import subprocess
import threading
import asyncio
from fastapi import FastAPI, WebSocket, Request, UploadFile, File, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import psutil
import shutil

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

state = SystemState()

def get_camera_index():
    camera_index = 0
    # Simple logic to find USB camera, similar to main_window.py
    for camera_info in enumerate_cameras(cv2.CAP_MSMF):
        if "USB Camera" in camera_info.name:
            camera_index = camera_info.index
            break
    return camera_index

def identify_logs_folder():
    # Simplified version of the logic in main_window.py
    onedrive_path = os.environ.get("OneDrive", "")
    if not onedrive_path or not os.path.exists(onedrive_path):
        possible_paths = [
            os.path.expanduser("~/OneDrive"),
            os.path.expanduser("~/OneDrive - Personal"),
            os.path.expanduser("~/OneDrive - Business")
        ]
        for path in possible_paths:
            if os.path.exists(path):
                onedrive_path = path
                break
    
    if not onedrive_path:
        # Fallback to local user dir if OneDrive not found
        onedrive_path = os.path.expanduser("~")

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
    try:
        idx = get_camera_index()
        state.camera = cv2.VideoCapture(idx)
        if not state.camera.isOpened():
             print("Warning: Camera not opened")
        
        state.photos_path, state.screenshots_path = identify_logs_folder()
        state.monitor = Monitor(state.camera, state.paths, state.photos_path, state.screenshots_path)
        
        # Start background frame reading thread
        threading.Thread(target=camera_loop, daemon=True).start()

        # Mount static directories for photos and plots
        if state.photos_path and os.path.exists(state.photos_path):
            app.mount("/static/photos", StaticFiles(directory=state.photos_path), name="photos")
        
        plot_dir = os.path.join(os.getcwd(), "plot_outputs")
        if os.path.exists(plot_dir):
            app.mount("/static/plots", StaticFiles(directory=plot_dir), name="plots")
        
        # Also mount screenshots if different from photos
        if state.screenshots_path and os.path.exists(state.screenshots_path) and state.screenshots_path != state.photos_path:
             app.mount("/static/screenshots", StaticFiles(directory=state.screenshots_path), name="screenshots")

    except Exception as e:
        print(f"Startup error: {e}")

def camera_loop():
    print(f"Starting camera loop... Camera Index: {get_camera_index()}")
    while state.is_running:
        if state.camera is None:
             idx = get_camera_index()
             try:
                 state.camera = cv2.VideoCapture(idx)
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
                # Create a black placeholder image
                import numpy as np
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(frame, "Camera Offline", (200, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        
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
            photos_size += sum(os.path.getsize(os.path.join(state.photos_path, f)) for f in os.listdir(state.photos_path) if os.path.isfile(os.path.join(state.photos_path, f)))
        
        screenshots_size = 0
        if state.screenshots_path and os.path.exists(state.screenshots_path):
            screenshots_size += sum(os.path.getsize(os.path.join(state.screenshots_path, f)) for f in os.listdir(state.screenshots_path) if os.path.isfile(os.path.join(state.screenshots_path, f)))
        
        total, used, free = shutil.disk_usage(state.photos_path or ".")
        
        return {
            "cpu_usage": cpu_usage,
            "memory_used_gb": round(memory.used / (1024**3), 2),
            "memory_total_gb": round(memory.total / (1024**3), 2),
            "memory_percent": memory.percent,
            "disk_free_gb": round(free / (1024**3), 2),
            "storage_used_mb": round((photos_size + screenshots_size) / (1024**2), 2)
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/latest_images")
def get_latest_images():
    try:
        photo_path = state.paths.get('photo')
        screenshot_path = state.paths.get('screenshot')
        
        photo_url = None
        if photo_path:
            photo_url = f"/static/photos/{os.path.basename(photo_path)}"
            
        screenshot_url = None
        if screenshot_path:
             # Check if screenshots are in a separate mount
            if state.screenshots_path != state.photos_path:
                screenshot_url = f"/static/screenshots/{os.path.basename(screenshot_path)}"
            else:
                screenshot_url = f"/static/photos/{os.path.basename(screenshot_path)}"

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
        # Using execute asynchronously to avoid blocking the main thread
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.path.dirname(script_path),
            env=env
        )
        
        stdout, stderr = await proc.communicate()
        
        response_text = ""
        if stdout:
            try:
                response_text = stdout.decode('utf-8')
            except:
                response_text = stdout.decode('gbk', errors='replace')
        
        if stderr:
             print(f"STDERR: {stderr.decode()}")

        return {"response": response_text.strip(), "success": proc.returncode == 0}

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
            stderr=asyncio.subprocess.PIPE,
            cwd=os.path.dirname(script_path),
            env=env
        )
        
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                decoded = line.decode('utf-8')
            except:
                decoded = line.decode('gbk', errors='replace')
            yield json.dumps({"log": decoded}) + "\n"
        
        await proc.wait()
    
    return StreamingResponse(process_stream(), media_type="application/x-ndjson")

@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    # Save temp file
    temp_filename = f"temp_audio_{int(time.time())}.wav"
    with open(temp_filename, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
        
    # Locate run_prompt.py in src/scripts
    current_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(current_dir, "scripts", "run_prompt.py")
    if not os.path.exists(script_path):
         script_path = os.path.abspath("src/scripts/run_prompt.py")
    cmd = [sys.executable, script_path, "--transcribe", temp_filename]
    
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=os.path.dirname(script_path),
        env=env
    )
    
    stdout, _ = await proc.communicate()
    
    # Cleanup
    if os.path.exists(temp_filename):
        os.remove(temp_filename)
        
    output = ""
    try:
        output = stdout.decode('utf-8')
    except:
        output = stdout.decode('gbk', errors='replace')
        
    transcription = ""
    for line in output.splitlines():
        if line.startswith("TRANSCRIPTION_RESULT:"):
            transcription = line.replace("TRANSCRIPTION_RESULT:", "").strip()
            break
            
    return {"transcription": transcription}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
