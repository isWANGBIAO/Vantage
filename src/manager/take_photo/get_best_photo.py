import time

import cv2


def capture_best_photo(cam, frame_count=1, min_focus_change=5):
    if cam is None or not getattr(cam, "isOpened", lambda: False)():
        return None

    ret, frame = cam.read()
    if ret and frame is not None:
        return frame

    # Fall back to a short sampling loop if the first read fails.
    time.sleep(1)
    best_frame = None
    max_focus_measure = 0
    last_focus_measure = 0
    stable_frame_count = 0

    for _ in range(frame_count):
        ret, frame = cam.read()
        if not ret or frame is None:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        focus_measure = cv2.Laplacian(gray, cv2.CV_64F).var()

        if focus_measure > max_focus_measure:
            max_focus_measure = focus_measure
            best_frame = frame

        if abs(focus_measure - last_focus_measure) < min_focus_change:
            stable_frame_count += 1
            if stable_frame_count >= 3:
                break
        else:
            stable_frame_count = 0

        last_focus_measure = focus_measure

    return best_frame


if __name__ == "__main__":
    cam = cv2.VideoCapture(0)
    best_photo = capture_best_photo(cam)
    if best_photo is not None:
        cv2.imwrite("best_photo.jpg", best_photo)
        print("Saved best_photo.jpg")
    else:
        print("Failed to capture a sharp photo")
    cam.release()
