
import os
import cv2
import mediapipe as mp
import numpy as np
import json
import argparse
import sys
import glob
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
import pandas as pd

# --- Configuration ---
CACHE_FILE = os.path.join("history", "face_analysis_cache.json")
PROGRESS_FILE = os.path.join("history", "analysis_progress.json")
PLOT_OUTPUT_DIR = os.path.join("plot_outputs")

def update_progress(current, total, status="analyzing", current_file=""):
    try:
        with open(PROGRESS_FILE, 'w') as f:
            json.dump({
                "current": current,
                "total": total,
                "percent": round((current / total) * 100, 2) if total > 0 else 0,
                "status": status,
                "current_file": current_file,
                "timestamp": datetime.now().timestamp()
            }, f)
    except:
        pass

# --- MediaPipe Initialization ---
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=True,
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5
)

def get_photo_search_paths():
    """Discover photo directories similar to server.py logic"""
    paths = []
    
    # Check Environment/Common locations
    onedrive_path = os.environ.get("OneDrive", os.path.expanduser("~\\OneDrive"))
    user_home = os.path.expanduser("~")
    
    potential_roots = [
        "D:\\WANGBIAO",
        onedrive_path,
        os.path.join(user_home, "OneDrive"),
        user_home
    ]
    
    subdirs = [
        os.path.join("Pictures", "本机照片"),
        os.path.join("图片", "本机照片"),
        "本机照片"
    ]
    
    for root in potential_roots:
        if root and os.path.exists(root):
            for sub in subdirs:
                p = os.path.join(root, sub)
                if os.path.exists(p):
                    paths.append(p)
    
    # De-duplicate
    unique_paths = list(set([os.path.abspath(p) for p in paths]))
    return unique_paths

def scan_photos(search_paths):
    """Recursively find photo_YYYYMMDD_HHMMSS.jpg files"""
    photo_files = []
    print(f"Scanning paths: {search_paths}")
    for search_path in search_paths:
        for root, dirs, files in os.walk(search_path):
            for file in files:
                if file.startswith("photo_") and file.endswith(".jpg"):
                    # Basic validation of filename format
                    try:
                        # Extract timestamp: photo_20240101_120000.jpg
                        ts_str = file.replace("photo_", "").replace(".jpg", "")
                        # Handle potential suffixes or oddities (though strict format is expected)
                        if len(ts_str) >= 15: # YYYYMMDD_HHMMSS
                            dt = datetime.strptime(ts_str[:15], "%Y%m%d_%H%M%S")
                            photo_files.append({
                                "path": os.path.join(root, file),
                                "date": dt,
                                "timestamp": dt.timestamp()
                            })
                    except ValueError:
                        continue
    
    # Sort by date
    photo_files.sort(key=lambda x: x["timestamp"])
    return photo_files

def calculate_dark_circle_score(image, landmarks, w, h):
    """
    Calculate dark circle score based on contrast between cheek and under-eye region.
    Higher score = Darker circles (worse).
    """
    # Convert to LAB color space for lightness analysis
    lab_image = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel, _, _ = cv2.split(lab_image)
    
    # Helper to get mean intensity of a polygon defined by landmarks
    def get_region_mean(indices):
        mask = np.zeros((h, w), dtype=np.uint8)
        points = np.array([(int(landmarks[i].x * w), int(landmarks[i].y * h)) for i in indices], dtype=np.int32)
        cv2.fillPoly(mask, [points], 255)
        mean_val = cv2.mean(l_channel, mask=mask)[0]
        return mean_val

    # Indices based on MediaPipe Face Mesh (approximate)
    # Left Eye Under: 
    left_under_eye_indices = [349, 348, 347, 346, 345, 340, 261, 265] # Below left eye
    # Left Cheek (Reference):
    left_cheek_indices = [425, 266, 329, 349] # Further down/out from eye (brighter area)
    
    # Right Eye Under:
    right_under_eye_indices = [120, 119, 118, 117, 116, 111, 31, 35] # Below right eye
    # Right Cheek (Reference):
    right_cheek_indices = [205, 36, 100, 120] # Further down/out
    
    try:
        l_undereye = get_region_mean(left_under_eye_indices)
        l_cheek = get_region_mean(left_cheek_indices)
        
        r_undereye = get_region_mean(right_under_eye_indices)
        r_cheek = get_region_mean(right_cheek_indices)
        
        # Score is the difference. If cheek is bright (high L) and undereye is dark (low L), diff is positive and large.
        left_score = max(0, l_cheek - l_undereye)
        right_score = max(0, r_cheek - r_undereye)
        
        return (left_score + right_score) / 2.0
    except Exception as e:
        print(f"Error calculating score: {e}")
        return 0.0

def analyze_all(photos, cache):
    results = []
    
    for i, photo in enumerate(photos):
        path = photo["path"]
        # Update progress every 1 item to ensure responsiveness
        update_progress(i + 1, len(photos), current_file=os.path.basename(path))
        
        ts_key = str(photo["timestamp"])
        
        # Check cache
        if ts_key in cache:
            results.append({
                "date": photo["date"],
                "score": cache[ts_key],
                "path": path
            })
            continue
            
        # Analyze new
        print(f"Analyzing [{i+1}/{len(photos)}]: {os.path.basename(path)}")
        try:
            # cv2.imread fails on Windows with unicode paths, use numpy + imdecode
            image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None: continue
            
            h, w, c = image.shape
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            mp_res = face_mesh.process(rgb_image)
            
            score = 0.0
            if mp_res.multi_face_landmarks:
                landmarks = mp_res.multi_face_landmarks[0].landmark
                score = calculate_dark_circle_score(image, landmarks, w, h)
            
            # Update cache/results
            cache[ts_key] = score
            results.append({
                "date": photo["date"],
                "score": score,
                "path": path
            })
            
            # Periodically save cache (every 50 images)
            if i % 50 == 0:
                try:
                    with open(CACHE_FILE, 'w') as f:
                        json.dump(cache, f)
                except:
                    pass
            
        except Exception as e:
            print(f"Failed to analyze {path}: {e}")
            
    return results

def plot_trend(results, output_dir):
    if not results: return None
    
    # 1. Prepare Data
    df = pd.DataFrame(results)
    if df.empty: return None
    
    # Ensure datetime matches
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    
    # Filter valid scores
    df = df[df['score'] > 0]
    if df.empty: return None

    # Setup Plot
    plt.figure(figsize=(12, 6))
    
    # 2. Scatter Plot for Raw Data (Low opacity, small dots)
    plt.scatter(df['date'], df['score'], 
                alpha=0.2, s=10, linewidths=0, label='Raw Data')
    
    # 3. Calculate Daily Trend
    # Resample to Daily frequency to get one point per day
    daily = df.set_index('date').resample('D')['score'].mean()
    
    # Interpolate missing days to keep the line continuous (optional, but looks better)
    daily_filled = daily.interpolate(method='linear')
    
    # Smooth the Daily Trend (7-day rolling average)
    smoothed = daily_filled.rolling(window=7, center=True, min_periods=1).mean()
    
    # 4. Plot Trend Line
    plt.plot(smoothed.index, smoothed.values, 
             color='#E15759', linewidth=2.5, label='7-Day Trend')
            
    plt.title("Dark Circle Severity Over Time (Higher is Worse)")
    plt.xlabel("Date")
    plt.ylabel("Severity Score (Contrast Diff)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    
    # Format X axis
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.gcf().autofmt_xdate()
    
    output_path = os.path.join(output_dir, "dark_circles_trend.png")
    plt.savefig(output_path, dpi=100, bbox_inches='tight')
    plt.close()
    print(f"Plot saved to {output_path}")
    return output_path

def export_excel(results):
    if not results: return
    df = pd.DataFrame(results)
    # Reorder/Rename for clarity
    df = df[['date', 'score', 'path']]
    df['date'] = df['date'].dt.strftime("%Y-%m-%d %H:%M:%S")
    
    filename = "Face_Analysis_History.xlsx"
    output_path = os.path.abspath(filename)
    df.to_excel(output_path, index=False)
    print(f"EXPORT_PATH:{output_path}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", action="store_true", help="Export to Excel")
    args = parser.parse_args()

    # Ensure directories
    os.makedirs("history", exist_ok=True)
    os.makedirs(PLOT_OUTPUT_DIR, exist_ok=True)
    
    # Load Cache
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
        except:
            pass
            
    # Scan
    paths = get_photo_search_paths()
    photos = scan_photos(paths)
    if not args.export:
        print(f"Found {len(photos)} photos.")
    
    # Analyze
    results = analyze_all(photos, cache)
    
    # Save Cache
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f) # Only saving ts -> score mapping
        
    # Find Extremes (only valid scores)
    valid_results = [r for r in results if r["score"] > 0]
    
    if args.export:
        export_excel(valid_results)
        return

    if not valid_results:
        print("No valid face data found.")
        return

    # Sort by score
    valid_results.sort(key=lambda x: x["score"])
    
    best = valid_results[0] # Lowest score (least dark circles)
    worst = valid_results[-1] # Highest score (heaviest dark circles)
    
    # Report
    report = {
        "count": len(valid_results),
        "heaviest": {
            "path": worst["path"],
            "score": worst["score"],
            "date": worst["date"].strftime("%Y-%m-%d %H:%M:%S")
        },
        "lightest": {
            "path": best["path"],
            "score": best["score"],
            "date": best["date"].strftime("%Y-%m-%d %H:%M:%S")
        }
    }
    
    print("REPORT_JSON:" + json.dumps(report))
    
    # Plot
    plot_trend(valid_results, PLOT_OUTPUT_DIR)

if __name__ == "__main__":
    main()
