import cv2
import os
import json
from datetime import datetime

KNOWLEDGE_BASE = 'knowledge_base.json'


def take_photo():
    cam = cv2.VideoCapture(0)
    ret, frame = cam.read()
    if ret:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        photo_name = f'photo_{timestamp}.png'
        photo_path = os.path.join('photos', photo_name)

        if not os.path.exists('photos'):
            os.makedirs('photos')

        cv2.imwrite(photo_path, frame)
        print(f'Photo taken and saved as {photo_path}')

        # 更新知识库
        with open(KNOWLEDGE_BASE, 'r+') as f:
            data = json.load(f)
            data[timestamp] = {'photo': photo_path}
            f.seek(0)
            json.dump(data, f, indent=4)
    else:
        print('Failed to capture image.')
    cam.release()
