from .take_photo.take_a_photo import take_photo
from .screenshot.take_a_screenshot import take_and_save_screenshots
import os
import json
import schedule
from datetime import datetime
import cv2
import time
from apscheduler.schedulers.background import BackgroundScheduler
import time
from .get_location import get_location
import sys
# manager/manager_main.py
import time


class Monitor:
    def __init__(self, camera):
        # 初始化摄像头
        self.camera = camera
        # 创建知识库文件
        # 获取当前运行路径（CWD）
        BASE_DIR = os.getcwd()
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} BASE_DIR: {BASE_DIR}")
        KNOWLEDGE_BASE = os.path.join(BASE_DIR, '.', 'logs', 'knowledge_base.json')
        if not os.path.exists(KNOWLEDGE_BASE):
            with open(KNOWLEDGE_BASE, 'w') as f:
                json.dump({}, f)

    def run_task(self):
        """
        基本管家功能：提供日程提醒、天气查询等基础功能。
        摄像头调用：使用摄像头定时拍照,并将照片保存到本地。
        照片存储：将照片保存到本地，并记录到简单的“知识库”中（可以用一个 JSON 文件存储照片及其元数据）。
        并且进行电脑全屏截图。
        """

        # TODO：能够实现建立本地知识库，查找信息的时候，能够给出答案，并且同时指出答案的来源。（文件名，pdf的第几页，缩略图）
        # TODO：实现操控电脑，写代码，写文档的功能，能自动取扫描电脑的文件，并且组成一个知识库，
        # TODO: 自动对定时拍照的照片进行识别，记录在日志库中，记录自己什么时候在做什么事情，像那个
        # TODO：把之前拍过的照片也放进来，然后用openai来识别，然后记录在日志库中，这样就可以知道自己在做什么事情了
        # TODO: 把time.xlsx的内容放到知识库中，
        # TODO: balance sheet.xlsx的内容放到知识库中，
        # todo 截图
        # TODO 加入微软TODO的功能
        # TODO 拍照照片加入 设备 位置 信息
        # TODO 加入自动识别照片功能，对于无意义照片删除

        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---------------------------------------------")
        # 获取经纬度信息
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Getting location")
        latitude, longitude = get_location()
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} take_photo()")
        # 有人在的时候才拍照截屏
        # 返回变量，如果是True，说明有人在，如果是False，说明没人在
        real_person = take_photo(self.camera, latitude, longitude)
        if real_person:
            print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} take_and_save_screenshots()")
            take_and_save_screenshots(latitude, longitude)
            print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Done.")
        else:
            print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} No person detected.", file=sys.stderr)
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---------------------------------------------")
