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
import threading


def monitor():
    print("Time", datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "Taking photo...")
    take_photo()
    print("Time", datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "Taking screenshot...")
    take_and_save_screenshots()
    print("Time", datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "Done...")


def threaded_monitor():
    threading.Thread(target=monitor).start()


def manager():
    """
    基本管家功能：提供日程提醒、天气查询等基础功能。
    摄像头调用：使用摄像头定时拍照,并将照片保存到本地。
    照片存储：将照片保存到本地，并记录到简单的“知识库”中（可以用一个 JSON 文件存储照片及其元数据）。
    并且进行电脑全屏截图。
    """

    # 创建知识库文件
    KNOWLEDGE_BASE = 'knowledge_base.json'
    if not os.path.exists(KNOWLEDGE_BASE):
        with open(KNOWLEDGE_BASE, 'w') as f:
            json.dump({}, f)

    threaded_monitor()  # 运行时立即拍摄一张照片
    scheduler = BackgroundScheduler()
    scheduler.add_job(threaded_monitor, 'interval', seconds=60)
    scheduler.start()
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()

    # TODO：能够实现建立本地知识库，查找信息的时候，能够给出答案，并且同时指出答案的来源。（文件名，pdf的第几页，缩略图）
    # TODO：实现操控电脑，写代码，写文档的功能，能自动取扫描电脑的文件，并且组成一个知识库，
    # TODO: 自动对定时拍照的照片进行识别，记录在日志库中，记录自己什么时候在做什么事情，像那个
    # TODO：把之前拍过的照片也放进来，然后用openai来识别，然后记录在日志库中，这样就可以知道自己在做什么事情了
    # TODO: 把time.xlsx的内容放到知识库中，
    # TODO: balance sheet.xlsx的内容放到知识库中，
    # todo 截图
    # TODO 加入微软TODO的功能
    # TODO 加入界面可以后台运行
