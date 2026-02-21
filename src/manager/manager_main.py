from .take_photo.take_a_photo import take_photo
from .screenshot.take_a_screenshot import take_and_save_screenshots
import os
import json
import schedule
from datetime import datetime
import cv2
import time
import threading
import subprocess
from apscheduler.schedulers.background import BackgroundScheduler
from .get_location import get_location
import sys


class Monitor:
    def __init__(self, camera, paths, photos_path, screenshots_path):
        self.camera = camera
        self.paths = paths
        self.photos_path = photos_path
        self.screenshots_path = screenshots_path
        # 创建知识库文件
        BASE_DIR = self.photos_path
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} BASE_DIR: {BASE_DIR}")
        KNOWLEDGE_BASE = os.path.join(BASE_DIR, 'knowledge_base.json')
        if not os.path.exists(KNOWLEDGE_BASE):
            with open(KNOWLEDGE_BASE, 'w') as f:
                json.dump({}, f)
                
        # 健康管家：久坐提醒状态变量
        self.continuous_sit_start = None
        self.last_missing_time = None
        self.last_notification_time = None
        self.sedentary_threshold = 40 * 60  # 40 分钟 (秒)
        self.notification_interval = 5 * 60 # 提醒后如果继续坐着，每 5 分钟再提醒一次
        self.grace_period = 2 * 60          # 允许离开镜头的宽限期 (2 分钟)，防止中途喝水或低头导致计时重置

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
        try:
            # 获取经纬度信息
            print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Getting location")
            latitude, longitude = get_location()
            print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} take_photo()")
            # 有人在的时候才拍照截屏
            # 返回变量，如果是True，说明有人在，如果是False，说明没人在
            real_person, photo_path = take_photo(self.camera, latitude, longitude, self.photos_path)
            
            current_time = time.time()
            if real_person:
                # 用户在座位上，重置离开倒计时
                self.last_missing_time = None
                
                # 初始化开始坐下的时间
                if self.continuous_sit_start is None:
                    self.continuous_sit_start = current_time
                    
                sit_duration = current_time - self.continuous_sit_start
                # 检查是否达到久坐阈值 (累计时间超过 self.sedentary_threshold)
                if sit_duration >= self.sedentary_threshold:
                    if self.last_notification_time is None or (current_time - self.last_notification_time) >= self.notification_interval:
                        threading.Thread(target=self.send_sedentary_notification, args=(int(sit_duration // 60),), daemon=True).start()
                        self.last_notification_time = current_time

                print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} take_and_save_screenshots()")
                screenshot_path = take_and_save_screenshots(latitude, longitude, self.screenshots_path)

                # 直接更新路径字典
                self.paths['photo'] = photo_path
                self.paths['screenshot'] = screenshot_path
                print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Done. (Sedentary: {int(sit_duration/60)} mins)")
            else:
                # 没人检测到，开始宽限期倒计时
                if self.last_missing_time is None:
                    self.last_missing_time = current_time
                
                missing_duration = current_time - self.last_missing_time
                if missing_duration >= self.grace_period:
                    if self.continuous_sit_start is not None:
                        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} User left for >2mins. Resetting sedentary timer.")
                    self.continuous_sit_start = None
                    self.last_notification_time = None
                else:
                    print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} No person detected. (Grace period: {int(self.grace_period - missing_duration)}s left)", file=sys.stderr)

        except Exception as e:
            print(f"Task error: {e}", file=sys.stderr)
        print(f"Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---------------------------------------------")

    def send_sedentary_notification(self, minutes):
        print(f"Sending sedentary notification for {minutes} minutes of continuous sitting.")
        try:
            ps_script = f"""
            Add-Type -AssemblyName System.Windows.Forms
            $notify = New-Object System.Windows.Forms.NotifyIcon
            $notify.Icon = [System.Drawing.SystemIcons]::Warning
            $notify.BalloonTipIcon = 'Warning'
            $notify.BalloonTipTitle = 'AI 健康管家 (久坐提醒)'
            $notify.BalloonTipText = '你已经连续工作了 {minutes} 分钟了！请起立活动一下，走动走动喝口水，防止病痛、保护视力。'
            $notify.Visible = $True
            $notify.ShowBalloonTip(10000)
            Start-Sleep -Seconds 10
            $notify.Dispose()
            """
            # 隐藏 PowerShell 的黑窗口
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], startupinfo=startupinfo)
        except Exception as e:
            print(f"Notification error: {e}")
