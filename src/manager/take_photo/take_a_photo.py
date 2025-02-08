# 该代码用于从摄像头捕获照片，并将其保存到指定的文件夹中。同时，将照片的信息（包括时间戳和路径）更新到一个JSON格式的知识库文件中。

import cv2
import os
from datetime import datetime
from .get_best_photo import capture_best_photo
import cv2
import sys
from ..get_location import save_image_with_gps
import mediapipe as mp


def take_photo(cam, latitude, longitude):
    # TODO: 如无需要，勿增实体。等到这里成为性能瓶颈再优化代码，提高拍照的效率,使得每次拍照尽量清晰以及对齐时间间隔

    # 获取最清晰的一帧图像
    print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Taking photo")
    # 直接拍照
    frame = capture_best_photo(cam)
    t1 = cv2.getTickCount()
    # 初始化MediaPipe人体检测
    mp_pose = mp.solutions.pose
    pose = mp_pose.Pose(static_image_mode=True, min_detection_confidence=0.1)
    # 转换为RGB格式
    # 计算处理的时间
    image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = pose.process(image_rgb)
    t2 = cv2.getTickCount()
    time = (t2 - t1) / cv2.getTickFrequency()
    fps = 1.0 / time

    if results.pose_landmarks:
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Detected a person, photo captured! Time: {time}, FPS: {fps}")

        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Saving photo")
        # 生成当前时间的时间戳
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # 构建照片文件名
        photo_name = f'photo_{timestamp}.jpg'

        # 按照年月日创建四级文件夹，然后把当天的照片放到当天的文件夹的下面
        now = datetime.now()
        year = now.strftime('%Y')
        month = now.strftime('%m')
        day = now.strftime('%d')
        hour = now.strftime('%H')
        daily_folder = os.path.join('.', 'logs', 'photos', year, month, day, hour)
        if not os.path.exists(daily_folder):
            os.makedirs(daily_folder)
        photo_path = os.path.join(daily_folder, photo_name)

        # 保存捕获的图像到指定路径
        save_image_with_gps(photo_path, frame, latitude, longitude)

        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Photo taken and saved as {photo_path}")
        return True, photo_path
    else:
        return False, None
