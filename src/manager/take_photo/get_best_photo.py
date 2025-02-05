
import cv2
import time


def capture_best_photo(cam, frame_count=1, min_focus_change=5):

    # 等待摄像头自动调整曝光和对焦
    time.sleep(1)

    best_frame = None
    max_focus_measure = 0
    last_focus_measure = 0
    stable_frame_count = 0

    for _ in range(frame_count):
        ret, frame = cam.read()
        if not ret:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        focus_measure = cv2.Laplacian(gray, cv2.CV_64F).var()

        # 如果当前帧更清晰，则更新最佳帧
        if focus_measure > max_focus_measure:
            max_focus_measure = focus_measure
            best_frame = frame

        # 判断是否稳定，如果连续多帧清晰度变化很小，则提前结束
        if abs(focus_measure - last_focus_measure) < min_focus_change:
            stable_frame_count += 1
            if stable_frame_count >= 3:
                break
        else:
            stable_frame_count = 0

        last_focus_measure = focus_measure

    return best_frame


# 使用示例
if __name__ == "__main__":
    cam = cv2.VideoCapture(0)  # 打开默认摄像头
    best_photo = capture_best_photo(cam)
    if best_photo is not None:
        cv2.imwrite("best_photo.jpg", best_photo)
        print("照片已保存为 best_photo.jpg")
    else:
        print("未能捕获到清晰的照片")
    cam.release()
