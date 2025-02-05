# 该代码用于从摄像头捕获照片，并将其保存到指定的文件夹中。同时，将照片的信息（包括时间戳和路径）更新到一个JSON格式的知识库文件中。

import cv2
import os
import json
from datetime import datetime

KNOWLEDGE_BASE = 'knowledge_base.json'


def take_photo():
    # 打开摄像头
    cam = cv2.VideoCapture(0)
    
    # 检查摄像头是否成功打开
    if not cam.isOpened():
        print('Failed to open camera.')
        return

    # 读取一帧图像
    ret, frame = cam.read()
    
    # 检查是否成功读取图像
    if ret:
        # 生成当前时间的时间戳
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 构建照片文件名
        photo_name = f'photo_{timestamp}.png'
        
        # 构建照片保存路径
        photo_path = os.path.join('photos', photo_name)

        # 检查照片保存目录是否存在，如果不存在则创建
        if not os.path.exists('photos'):
            os.makedirs('photos')

        # 保存捕获的图像到指定路径
        cv2.imwrite(photo_path, frame)
        print(f'Photo taken and saved as {photo_path}')

        # 更新知识库文件
        try:
            # 检查知识库文件是否存在
            if os.path.exists(KNOWLEDGE_BASE):
                # 以读写模式打开知识库文件
                with open(KNOWLEDGE_BASE, 'r+') as f:
                    # 尝试加载现有的JSON数据
                    data = json.load(f)
                    
                    # 更新数据，添加新的照片信息
                    data[timestamp] = {'photo': photo_path}
                    
                    # 将文件指针移动到文件开头
                    f.seek(0)
                    
                    # 将更新后的数据写回文件
                    json.dump(data, f, indent=4)
                    
                    # 截断文件，删除多余的内容
                    f.truncate()
            else:
                # 如果知识库文件不存在，创建并写入新的数据
                with open(KNOWLEDGE_BASE, 'w') as f:
                    data = {timestamp: {'photo': photo_path}}
                    json.dump(data, f, indent=4)
        except json.JSONDecodeError:
            # 捕获JSON解码错误，提示文件可能已损坏
            print(f'Error decoding JSON from {KNOWLEDGE_BASE}. The file might be corrupted.')
            return
    else:
        # 如果未能捕获图像，打印错误信息
        print('Failed to capture image.')
    
    # 释放摄像头资源
    cam.release()