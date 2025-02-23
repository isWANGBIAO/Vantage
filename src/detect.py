import os
import cv2
from datetime import datetime
from ultralytics import YOLO
import time

"""
在这个a.py 里面实现一个功能，检查logs文件夹下的照片有没有人没有的话，输出文件路径和以及对对应上下2秒以内的截图，问我要不要删除我想的是这些没有检测到人的照片和对应的截图放到一个temp文件夹内，我自己去看删除啊
"""


def detect_person_yolo(model, image):

    # 将置信度调低，提高一些人影的检测率，默认是0.25，这里调低到0.25*0.01
    results = model.predict(source=image, verbose=False, conf=0.25 * 0.01)
    person_count = 0
    for result in results:
        for box in result.boxes:
            if box.cls == 0:  # 类别0代表人物
                person_count += 1
    return person_count


def get_screenshots_within_time_range(photo_time, logs_path, time_range=2):
    # 获取指定时间范围内的截图
    screenshots = []
    screenshot_folder = os.path.join(logs_path, 'screenshots')
    for root, _, files in os.walk(screenshot_folder):
        for file in files:
            if file:
                screenshot_time_str = file.split('_')[1] + '_' + file.split('_')[2].split('.')[0]
                screenshot_time = datetime.strptime(screenshot_time_str, '%Y%m%d_%H%M%S')
                if abs((screenshot_time - photo_time).total_seconds()) <= time_range:
                    screenshots.append(os.path.join(root, file))
    return screenshots


def move_to_temp_folder(file_paths, temp_folder):
    if not os.path.exists(temp_folder):
        os.makedirs(temp_folder)
    for file_path in file_paths:
        file_name = os.path.basename(file_path)
        new_path = os.path.join(temp_folder, file_name)
        os.rename(file_path, new_path)
        print(f"已移动文件 {file_path} 到 {new_path}")
    print(f"已将文件移动到临时文件夹 {temp_folder}")


def move_back_to_original_folder(temp_folder, logs_path):
    for root, _, files in os.walk(temp_folder):
        for file in sorted(files, reverse=False):
            temp_file_path = os.path.join(root, file)
            date_time_str = file.split('_')[1] + file.split('_')[2].split('.')[0]
            date_time = datetime.strptime(date_time_str, '%Y%m%d%H%M%S')

            if 'monitor' in file:
                original_folder = os.path.join(logs_path, 'screenshots', date_time.strftime('%Y'), date_time.strftime('%m'), date_time.strftime('%d'), date_time.strftime('%H'))
            else:
                original_folder = os.path.join(logs_path, 'photos', date_time.strftime('%Y'), date_time.strftime('%m'), date_time.strftime('%d'), date_time.strftime('%H'))

            if not os.path.exists(original_folder):
                os.makedirs(original_folder)
            original_path = os.path.join(original_folder, file)
            os.rename(temp_file_path, original_path)
            print(f"已移动文件 {temp_file_path} 回到 {original_path}")


def detect(photo_folder, temp_folder, logs_path):
    # 获取所有照片文件
    all_files = []
    for root, _, files in os.walk(photo_folder):
        for file in files:
            if file:
                all_files.append(os.path.join(root, file))

    total_files = len(all_files)
    photos_with_people = 0
    photos_without_people = 0

    # 加载YOLO模型进行人物检测
    model = YOLO("yolo11n.pt")

    start_time = time.time()

    # 遍历照片文件夹中的所有文件
    for idx, photo_path in enumerate(all_files):
        # 确保这个文件还在
        if not os.path.exists(photo_path):
            continue
        # 使用YOLO模型检测图片中的人数
        person_count = detect_person_yolo(model, photo_path)

        # 如果没有检测到人，获取相应时间范围内的截图
        if person_count == 0:
            photos_without_people += 1
            print(f"未在照片中检测到人物：{photo_path}")
            # 从文件名中获得时间，并且要去除后缀
            photo_time_str = photo_path.split('_')[1] + '_' + photo_path.split('_')[2].split('.')[0]
            photo_time = datetime.strptime(photo_time_str, '%Y%m%d_%H%M%S')
            screenshots = get_screenshots_within_time_range(photo_time, logs_path)
            # 打印对应的截图路径
            for screenshot in screenshots:
                print(f"对应的截图：{screenshot}")
                # 将照片和截图移动到临时文件夹
            move_to_temp_folder([photo_path] + screenshots, temp_folder)
        else:
            photos_with_people += 1

        # 输出当前进度
        elapsed_time = time.time() - start_time
        processed_files = idx + 1
        remaining_files = total_files - processed_files
        detection_rate = processed_files / elapsed_time
        remaining_time = remaining_files / detection_rate
        print(f"已检测照片：{processed_files}/{total_files}，检测有人照片：{photos_with_people}，没人照片：{photos_without_people} 剩余照片：{remaining_files}，检测速率：{detection_rate:.2f} 张/秒，预计剩余时间：{remaining_time:.2f} 秒 = {remaining_time / 60:.2f} 分钟, 已用时间：{elapsed_time / 60:.2f} 分钟")


def main():
    # 设置日志文件夹路径
    logs_path = r'C:\Users\97012\OneDrive\Mine\logs'
    # logs_path = os.path.join(os.path.expanduser('~'), 'Desktop', 'logs')
    # 设置照片文件夹路径
    photo_folder = os.path.join(logs_path, 'photos')
    # 设置临时文件夹路径
    temp_folder = os.path.join(os.path.expanduser('~'), 'Desktop', 'temp')

    detect(photo_folder, temp_folder, logs_path)

    # # 询问用户是否将文件移回原始文件夹
    move_back = input(f"是否要将文件移回原始文件夹？(y/n)：")
    if move_back.lower() == 'y':
        move_back_to_original_folder(temp_folder, logs_path)


if __name__ == '__main__':
    main()
