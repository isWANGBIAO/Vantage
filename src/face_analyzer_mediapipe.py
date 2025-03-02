import sys
import cv2
import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QProgressBar, QGroupBox, QGridLayout, QFileDialog)
from deepface import DeepFace
import mediapipe as mp
import os
import threading
import time


class FaceAnalyzerMP(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Face Analyzer (MediaPipe)")
        self.setGeometry(100, 100, 1200, 600)  # Reduced height since we removed 3D model

        # 初始化变量
        self.video_capture = None
        self.is_running = False
        self.current_frame = None

        # 初始化MediaPipe Face Mesh
        self.mp_face_mesh = mp.solutions.face_mesh
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_drawing_styles = mp.solutions.drawing_styles

        # MediaPipe的Face Mesh配置
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )

        # 定义MediaPipe面部关键点中的对称点对
        # MediaPipe有468个点，这些是根据面部区域选择的对称点对
        self.MOUTH_PAIRS = [
            (61, 291), (37, 267), (40, 270), (86, 316), (88, 318), (95, 325), (
                146, 375), (179, 409), (76, 306), (77, 307)
        ]

        self.EYES_PAIRS = [
            (33, 263), (160, 388), (158, 386), (144, 374), (153, 383), (157, 385),
            (173, 398), (7, 249), (130, 359), (25, 253), (110, 339)
        ]

        self.NOSE_PAIRS = [
            (129, 358), (209, 429), (198, 420), (49, 279), (114, 343), (220, 440),
            (45, 275), (4, 195)
        ]

        self.BROWS_PAIRS = [
            (70, 300), (63, 293), (105, 334), (66, 296), (107, 336)
        ]

        self.JAW_PAIRS = [
            (207, 427), (187, 411), (213, 433), (192, 422), (210, 435), (211, 431), (34, 264)
        ]

        # 设置界面
        self.init_ui()

        # 设置定时器用于更新视频
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)

        # DeepFace分析线程
        self.last_deepface_analysis = None
        self.deepface_thread = None
        self.deepface_running = False

    def init_ui(self):
        """初始化用户界面"""
        # 主窗口布局
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)

        # 左侧布局：视频显示
        left_layout = QVBoxLayout()

        # 视频显示
        self.video_container = QLabel()
        self.video_container.setFixedSize(640, 480)
        self.video_container.setStyleSheet("border: 1px solid gray;")
        self.video_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_container.setText("Camera feed will appear here")

        left_layout.addWidget(self.video_container)
        left_layout.addStretch()

        # 右侧分析结果面板
        analysis_panel = QWidget()
        analysis_layout = QVBoxLayout(analysis_panel)

        # 控制按钮
        control_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Camera")
        self.start_button.clicked.connect(self.toggle_camera)
        self.start_button.setFixedSize(120, 40)
        self.start_button.setStyleSheet("font-weight: bold;")

        # 添加图片分析按钮
        self.open_image_button = QPushButton("Open Image")
        self.open_image_button.clicked.connect(self.open_image)
        self.open_image_button.setFixedSize(120, 40)
        self.open_image_button.setStyleSheet("font-weight: bold;")

        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.open_image_button)
        control_layout.addStretch()

        # 整体对称性分数
        symmetry_group = QGroupBox("Face Symmetry (MediaPipe)")
        symmetry_layout = QGridLayout(symmetry_group)

        self.total_symmetry_label = QLabel("Total Symmetry: 0.0%")
        self.total_symmetry_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.total_symmetry_progress = QProgressBar()
        self.total_symmetry_progress.setRange(0, 100)
        self.total_symmetry_progress.setValue(0)
        self.symmetry_rating_label = QLabel("Rating: N/A")

        symmetry_layout.addWidget(self.total_symmetry_label, 0, 0)
        symmetry_layout.addWidget(self.total_symmetry_progress, 1, 0)
        symmetry_layout.addWidget(self.symmetry_rating_label, 2, 0)

        # 五官对称性评分
        features_group = QGroupBox("Features Symmetry")
        features_layout = QGridLayout(features_group)

        feature_names = ["Eyes", "Nose", "Mouth", "Eyebrows", "Jawline"]
        self.feature_labels = {}
        self.feature_progress = {}
        self.feature_ratings = {}

        for i, name in enumerate(feature_names):
            self.feature_labels[name] = QLabel(f"{name}: 0.0%")
            self.feature_progress[name] = QProgressBar()
            self.feature_progress[name].setRange(0, 100)
            self.feature_ratings[name] = QLabel("★")

            features_layout.addWidget(self.feature_labels[name], i, 0)
            features_layout.addWidget(self.feature_progress[name], i, 1)
            features_layout.addWidget(self.feature_ratings[name], i, 2)

        # DeepFace分析结果
        deepface_group = QGroupBox("DeepFace Analysis")
        deepface_layout = QGridLayout(deepface_group)

        self.age_label = QLabel("Age: N/A")
        self.gender_label = QLabel("Gender: N/A")
        self.emotion_label = QLabel("Emotion: N/A")
        self.race_label = QLabel("Race: N/A")

        deepface_layout.addWidget(self.age_label, 0, 0)
        deepface_layout.addWidget(self.gender_label, 1, 0)
        deepface_layout.addWidget(self.emotion_label, 2, 0)
        deepface_layout.addWidget(self.race_label, 3, 0)

        # 将所有组件添加到布局
        analysis_layout.addLayout(control_layout)
        analysis_layout.addWidget(symmetry_group)
        analysis_layout.addWidget(features_group)
        analysis_layout.addWidget(deepface_group)
        analysis_layout.addStretch()

        # 添加到主布局
        main_layout.addLayout(left_layout)
        main_layout.addWidget(analysis_panel)

        self.setCentralWidget(central_widget)

    def toggle_camera(self):
        """切换摄像头状态"""
        if self.is_running:
            self.stop_camera()
            self.start_button.setText("Start Camera")
        else:
            self.start_camera()
            self.start_button.setText("Stop Camera")

    def start_camera(self):
        """启动摄像头"""
        self.video_capture = cv2.VideoCapture(0)
        if not self.video_capture.isOpened():
            print("Error: Could not open camera.")
            return

        self.is_running = True
        self.timer.start(30)  # 30ms refresh (approx 33 fps)

        # 启动DeepFace分析线程
        self.deepface_running = True
        self.deepface_thread = threading.Thread(target=self.run_deepface_analysis)
        self.deepface_thread.daemon = True
        self.deepface_thread.start()

    def stop_camera(self):
        """停止摄像头"""
        self.is_running = False
        self.deepface_running = False
        if self.deepface_thread:
            self.deepface_thread.join(timeout=1.0)

        self.timer.stop()
        if self.video_capture:
            self.video_capture.release()

    def update_frame(self):
        """更新视频帧并进行面部分析"""
        if self.video_capture is None:
            return

        ret, frame = self.video_capture.read()
        if not ret:
            return

        # 镜像翻转
        frame = cv2.flip(frame, 1)
        self.current_frame = frame.copy()

        # 面部对称性分析
        display_frame = self.analyze_symmetry(frame)

        # 更新UI上的视频显示
        h, w, ch = display_frame.shape
        bytes_per_line = ch * w
        convert_to_qt_format = QImage(display_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        p = convert_to_qt_format.scaled(self.video_container.width(), self.video_container.height(),
                                        Qt.AspectRatioMode.KeepAspectRatio)
        self.video_container.setPixmap(QPixmap.fromImage(p))

    def run_deepface_analysis(self):
        """在单独线程中运行DeepFace分析"""
        while self.deepface_running:
            try:
                if self.current_frame is not None:
                    # 每隔2秒进行一次DeepFace分析（减少CPU使用率）
                    result = DeepFace.analyze(self.current_frame, actions=['age', 'gender', 'emotion', 'race'],
                                              enforce_detection=False)
                    if result:
                        self.last_deepface_analysis = result[0]
            except Exception as e:
                print(f"DeepFace analysis error: {e}")
            time.sleep(2)  # 2秒更新一次

    def analyze_symmetry(self, frame):
        """分析面部对称性并在图像上显示结果"""
        # 转换为RGB格式（MediaPipe需要RGB输入）
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, _ = frame.shape

        # 进行面部检测和关键点提取
        results = self.face_mesh.process(rgb_frame)

        # 将颜色转回BGR以便OpenCV绘图
        display_frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)

        if results.multi_face_landmarks:
            face_landmarks = results.multi_face_landmarks[0]  # 只处理第一张脸

            # 转换关键点坐标从相对坐标到像素坐标
            landmarks = np.array([(int(point.x * w), int(point.y * h)) for point in face_landmarks.landmark])

            # 计算对称性分数
            mouth_score = self.calculate_symmetry(landmarks, self.MOUTH_PAIRS)
            eyes_score = self.calculate_symmetry(landmarks, self.EYES_PAIRS)
            nose_score = self.calculate_symmetry(landmarks, self.NOSE_PAIRS)
            brows_score = self.calculate_symmetry(landmarks, self.BROWS_PAIRS)
            jaw_score = self.calculate_symmetry(landmarks, self.JAW_PAIRS)

            # 计算总体对称性分数（加权）
            total_score = (mouth_score * 2 + eyes_score * 2 + nose_score * 2 + brows_score + jaw_score) / 8

            # 更新UI上的对称性分数
            self.update_symmetry_ui(total_score, {
                "Eyes": eyes_score,
                "Nose": nose_score,
                "Mouth": mouth_score,
                "Eyebrows": brows_score,
                "Jawline": jaw_score
            })

            # 更新DeepFace分析结果
            self.update_deepface_ui()

            # 绘制面部特征点和对称线
            self.draw_facial_features(display_frame, landmarks)

        return display_frame

    def calculate_symmetry(self, landmarks, pairs):
        """计算指定对称点对的对称性分数（MediaPipe版本）"""
        if len(landmarks) == 0 or not pairs:
            return 100.0

        # 计算面部宽度作为归一化因子(使用鼻尖和下巴之间的距离)
        face_width = np.linalg.norm(landmarks[1] - landmarks[152])
        if face_width == 0:
            return 100.0

        # 计算面部对称轴
        # 使用鼻梁顶部(168)和鼻尖(1)确定垂直方向
        nose_top = landmarks[168]  # 鼻梁顶部
        nose_tip = landmarks[1]    # 鼻尖

        # 使用眉心点和下巴点
        between_eyes = landmarks[168]  # 眉心
        chin = landmarks[152]  # 下巴

        # 计算面部中心线方向向量
        direction_vector = np.zeros(2, dtype=np.float64)
        direction_vector += (nose_tip - nose_top)
        direction_vector += (chin - between_eyes)

        # 归一化方向向量
        if np.linalg.norm(direction_vector) > 0:
            direction_vector = direction_vector / np.linalg.norm(direction_vector)
        else:
            direction_vector = np.array([0.0, 1.0])  # 默认垂直方向

        # 计算垂直于方向向量的法向量
        normal_vector = np.array([-direction_vector[1], direction_vector[0]], dtype=np.float64)

        # 计算面部中心点 (MediaPipe特定点)
        face_center = (landmarks[10] + landmarks[152]) / 2

        # 计算对称点对之间的差异
        differences = []
        for i, j in pairs:
            # 获取对称点坐标
            left_point = landmarks[i]
            right_point = landmarks[j]

            # 计算点到对称轴的距离
            left_proj = np.dot(left_point - face_center, normal_vector)
            right_proj = np.dot(right_point - face_center, normal_vector)

            # 对称点应该在对称轴两侧有相等距离
            dist_diff = abs(abs(left_proj) - abs(right_proj))

            # 沿对称轴方向的位置差异
            axis_proj_left = np.dot(left_point - face_center, direction_vector)
            axis_proj_right = np.dot(right_point - face_center, direction_vector)
            axis_diff = abs(axis_proj_left - axis_proj_right)

            # 综合差异并考虑3D特性
            total_diff = (dist_diff + axis_diff * 0.5) / face_width
            differences.append(total_diff)

        # 计算平均差异并转换为百分比分数
        avg_diff = np.mean(differences) if differences else 0
        symmetry = max(0, 100 * (1 - avg_diff * 5))  # 乘以5使分数更敏感
        return min(100, symmetry)

    def get_rating(self, score):
        """根据分数获取评级和星级"""
        if score >= 95:
            return "Excellent", "★★★★★"
        elif score >= 90:
            return "Very Good", "★★★★☆"
        elif score >= 85:
            return "Good", "★★★☆☆"
        elif score >= 80:
            return "Fair", "★★☆☆☆"
        else:
            return "Normal", "★☆☆☆☆"

    def update_symmetry_ui(self, total_score, feature_scores):
        """更新UI上的对称性分数"""
        # 更新总体对称性
        self.total_symmetry_label.setText(f"Total Symmetry: {total_score:.1f}%")
        self.total_symmetry_progress.setValue(int(total_score))
        rating, stars = self.get_rating(total_score)
        self.symmetry_rating_label.setText(f"Rating: {rating} {stars}")

        # 更新五官对称性
        for feature, score in feature_scores.items():
            self.feature_labels[feature].setText(f"{feature}: {score:.1f}%")
            self.feature_progress[feature].setValue(int(score))
            rating, stars = self.get_rating(score)
            self.feature_ratings[feature].setText(stars)

    def update_deepface_ui(self):
        """更新UI上的DeepFace分析结果"""
        if self.last_deepface_analysis:
            try:
                self.age_label.setText(f"Age: {self.last_deepface_analysis['age']:.1f}")
                self.gender_label.setText(f"Gender: {self.last_deepface_analysis['dominant_gender']}")

                # 处理情绪
                emotion = self.last_deepface_analysis['dominant_emotion']
                emotion_score = self.last_deepface_analysis['emotion'][emotion]
                self.emotion_label.setText(f"Emotion: {emotion.capitalize()} ({emotion_score:.1f}%)")

                # 处理种族
                race = self.last_deepface_analysis['dominant_race']
                race_score = self.last_deepface_analysis['race'][race]
                self.race_label.setText(f"Race: {race.capitalize()} ({race_score:.1f}%)")
            except Exception as e:
                print(f"Error updating DeepFace UI: {e}")

    def draw_facial_features(self, frame, landmarks):
        """在图像上绘制面部特征和对称线"""
        colors = {
            'mouth': (0, 0, 255),    # 红色
            'eyes': (255, 0, 0),     # 蓝色
            'nose': (0, 255, 255),   # 黄色
            'brows': (255, 0, 255),  # 紫色
            'jaw': (0, 255, 0),      # 绿色
            'face': (255, 255, 255)  # 白色
        }

        # MediaPipe面部区域索引定义
        FACE_OVAL_INDICES = list(range(0, 17)) + [127, 162, 21, 54, 103, 67, 109] + list(range(10, 338, 30)) + [365, 379, 378, 400, 377, 152]
        LIPS_INDICES = list(range(61, 69)) + list(range(48, 61)) + list(range(68, 80)) + list(range(80, 96)) + list(range(96, 104)) + list(range(104, 106))
        LEFT_EYE_INDICES = list(range(362, 374))
        RIGHT_EYE_INDICES = list(range(33, 46))
        LEFT_BROW_INDICES = list(range(383, 398))
        RIGHT_BROW_INDICES = list(range(156, 172))
        NOSE_INDICES = list(range(122, 156)) + list(range(5, 13))

        # 定义各区域使用的颜色
        region_colors = {
            "face": (255, 255, 255),  # 白色
            "lips": (0, 0, 255),     # 红色
            "left_eye": (255, 0, 0),  # 蓝色
            "right_eye": (255, 0, 0),  # 蓝色
            "left_brow": (255, 0, 255),  # 紫色
            "right_brow": (255, 0, 255),  # 紫色
            "nose": (0, 255, 255),   # 黄色
            "other": (0, 255, 0)     # 绿色
        }

        # 绘制所有468个点
        for i, point in enumerate(landmarks):
            # 根据点的类别选择颜色
            if i in FACE_OVAL_INDICES:
                color = region_colors["face"]
            elif i in LIPS_INDICES:
                color = region_colors["lips"]
            elif i in LEFT_EYE_INDICES:
                color = region_colors["left_eye"]
            elif i in RIGHT_EYE_INDICES:
                color = region_colors["right_eye"]
            elif i in LEFT_BROW_INDICES:
                color = region_colors["left_brow"]
            elif i in RIGHT_BROW_INDICES:
                color = region_colors["right_brow"]
            elif i in NOSE_INDICES:
                color = region_colors["nose"]
            else:
                color = region_colors["other"]

            # 绘制点，使用小尺寸以避免拥挤
            cv2.circle(frame, tuple(point), 1, color, -1)

            # 可选：显示点的索引（如果需要查看特定点的位置）
            # 仅显示一些关键索引以避免拥挤
            if i % 50 == 0:
                cv2.putText(frame, str(i), tuple(point), cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)

        # 绘制各区域对称线
        pairs_with_colors = [
            (self.MOUTH_PAIRS, colors['mouth']),
            (self.EYES_PAIRS, colors['eyes']),
            (self.NOSE_PAIRS, colors['nose']),
            (self.BROWS_PAIRS, colors['brows']),
            (self.JAW_PAIRS, colors['jaw'])
        ]

        for pairs, color in pairs_with_colors:
            for i, j in pairs:
                pt1 = tuple(landmarks[i])
                pt2 = tuple(landmarks[j])
                cv2.line(frame, pt1, pt2, color, 1)

        # 计算面部对称轴
        # 使用MediaPipe特定的点
        nose_top = landmarks[168]  # 鼻梁顶部
        nose_tip = landmarks[1]    # 鼻尖
        between_eyes = landmarks[168]  # 眉心
        chin = landmarks[152]  # 下巴

        # 计算对称轴方向
        direction_vector = np.zeros(2, dtype=np.float64)
        direction_vector += (nose_tip - nose_top)
        direction_vector += (chin - between_eyes)

        # 归一化方向向量
        if np.linalg.norm(direction_vector) > 0:
            direction_vector = direction_vector / np.linalg.norm(direction_vector)
        else:
            direction_vector = np.array([0.0, 1.0])

        # 计算面部中心点
        face_center = (landmarks[10] + landmarks[152]) / 2

        # 计算对称轴线段
        face_height = np.linalg.norm(landmarks[10] - landmarks[152]) * 1.5
        axis_start = face_center - direction_vector * face_height / 2
        axis_end = face_center + direction_vector * face_height / 2

        # 绘制对称轴
        start_point = tuple(map(int, axis_start))
        end_point = tuple(map(int, axis_end))
        cv2.line(frame, start_point, end_point, (0, 255, 255), 2)

        # 添加箭头指示方向
        cv2.arrowedLine(frame,
                        tuple(map(int, face_center)),
                        tuple(map(int, face_center + direction_vector * 30)),
                        (0, 255, 255), 2, tipLength=0.3)

    def open_image(self):
        """打开图片文件并分析"""
        # 停止任何正在进行的相机流
        if self.is_running:
            self.stop_camera()
            self.start_button.setText("Start Camera")

        # 打开文件选择对话框
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片",
            "",
            "图片文件 (*.jpg *.jpeg *.png *.bmp)"
        )

        if file_path:
            # 加载和分析图像
            image = cv2.imread(file_path)
            if image is not None:
                # 调整图像大小以适应显示
                height, width = image.shape[:2]
                max_height = 480
                max_width = 640
                scale_factor = min(max_width / width, max_height / height)

                if scale_factor < 1:
                    new_width = int(width * scale_factor)
                    new_height = int(height * scale_factor)
                    image = cv2.resize(image, (new_width, new_height))

                # 分析面部对称性
                display_frame = self.analyze_symmetry(image)

                # 显示结果
                h, w, ch = display_frame.shape
                bytes_per_line = ch * w
                qt_image = QImage(display_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                self.video_container.setPixmap(QPixmap.fromImage(qt_image))

                # 更新窗口标题显示文件名
                self.setWindowTitle(f"Face Analyzer - {os.path.basename(file_path)}")
            else:
                print(f"无法加载图片: {file_path}")

    def closeEvent(self, event):
        """在窗口关闭时停止视频捕获"""
        self.stop_camera()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FaceAnalyzerMP()
    window.show()
    sys.exit(app.exec())
