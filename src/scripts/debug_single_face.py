
import cv2
import mediapipe as mp
import numpy as np
import os

# --- Exact Copy of Logic from analyze_face.py ---

mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=True,
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5
)

def calculate_dark_circle_score(image, landmarks, w, h):
    # Convert to LAB color space for lightness analysis
    lab_image = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel, _, _ = cv2.split(lab_image)
    
    # Helper to get mean intensity of a polygon defined by landmarks
    def get_region_mean(indices, label):
        mask = np.zeros((h, w), dtype=np.uint8)
        points = np.array([(int(landmarks[i].x * w), int(landmarks[i].y * h)) for i in indices], dtype=np.int32)
        
        # Debug: Print points for this region
        # print(f"Region {label} points: {points}")
        
        cv2.fillPoly(mask, [points], 255)
        mean_val = cv2.mean(l_channel, mask=mask)[0]
        print(f"Region {label} mean L: {mean_val}")
        return mean_val

    # Indices based on MediaPipe Face Mesh (approximate) - COPIED FROM SOURCE
    left_under_eye_indices = [349, 348, 347, 346, 345, 340, 261, 265] 
    left_cheek_indices = [425, 266, 329, 349] 
    right_under_eye_indices = [120, 119, 118, 117, 116, 111, 31, 35] 
    right_cheek_indices = [205, 36, 100, 120] 
    
    try:
        l_undereye = get_region_mean(left_under_eye_indices, "Left UnderEye")
        l_cheek = get_region_mean(left_cheek_indices, "Left Cheek")
        
        r_undereye = get_region_mean(right_under_eye_indices, "Right UnderEye")
        r_cheek = get_region_mean(right_cheek_indices, "Right Cheek")
        
        # Score is the difference. If cheek is bright (high L) and undereye is dark (low L), diff is positive and large.
        left_score = max(0, l_cheek - l_undereye)
        right_score = max(0, r_cheek - r_undereye)
        
        print(f"Left Score: {left_score}, Right Score: {right_score}")
        
        return (left_score + right_score) / 2.0
    except Exception as e:
        print(f"Error calculating score: {e}")
        import traceback
        traceback.print_exc()
        return 0.0

def test_image(path):
    print(f"Testing image: {path}")
    if not os.path.exists(path):
        print("File not found!")
        return

    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None: return

    h, w, c = image.shape
    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    
    mp_res = face_mesh.process(rgb_image)
    
    if mp_res.multi_face_landmarks:
        print("SUCCESS: Face Landmarks Detected!")
        landmarks = mp_res.multi_face_landmarks[0].landmark
        
        score = calculate_dark_circle_score(image, landmarks, w, h)
        print(f"FINAL SCORE: {score}")
    else:
        print("FAILURE: No face landmarks detected.")

if __name__ == "__main__":
    test_path = r"C:\Users\97012\OneDrive\图片\本机照片\2025\02\06\22\photo_20250206_224514.jpg"
    test_image(test_path)
