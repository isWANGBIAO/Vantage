# 黑眼圈算法说明

## 1. 文档目的

这份文档尽可能详细说明当前项目中的黑眼圈分析链路，包括：

- 数据从哪里来
- 单张照片如何被判定为有效/无效
- 黑眼圈分数如何计算
- 哪些质量门会直接把样本打回
- 趋势图、最轻/最重、报告缓存是怎么生成的
- 新增的“保守离群值过滤”放在什么位置、做了什么、不做什么

本文描述的实现以当前代码为准，核心代码位于：

- `src/scripts/analyze_face.py`
- `src/services/face_analysis_pipeline.py`
- `src/utils/face_analysis_db.py`

当前数据库算法版本号是 `dark_circle_v2`。

---

## 2. 整体链路总览

当前黑眼圈分析不是“拿整张图直接做一次回归”，而是一个多阶段流水线：

1. 扫描照片目录，找到符合命名规则的历史自拍。
2. 对每张照片做人脸检测，截取脸部区域。
3. 对脸部区域做人脸解析，得到皮肤、左右眼区域的掩码。
4. 根据眼睛下方与脸颊的颜色/亮度差异，分别计算左右眼分数。
5. 通过一组质量门过滤掉模糊、曝光极端、姿态不稳、左右眼不一致等无效样本。
6. 把单张结果写入 SQLite 数据库。
7. 用数据库中的有效结果生成报告：
   - 最严重样本
   - 最轻样本
   - 趋势图
   - 日/周/月/全历史四组趋势点
8. 在报告层再做一次“保守离群值过滤”，剔除极端单点跳变，避免污染趋势和极值展示。

这意味着当前系统有两层过滤：

- **单帧质量门**：决定一张图是否 `passed=1`
- **报告层离群过滤**：决定已经 `passed=1` 的样本是否参与展示

数据库保留原始结果，报告使用过滤后的结果。

---

## 3. 入口脚本与运行方式

入口脚本是 `src/scripts/analyze_face.py`。

它的职责不是实现打分细节，而是组织整条分析链路：

1. 初始化数据库和输出目录
2. 构造 `AnalysisConfig`
3. 初始化：
   - `MediaPipeFaceDetector`
   - `FaceParser`
4. 调用 `scan_photos()` 扫描照片
5. 跳过数据库里已经分析过的路径
6. 对待分析照片逐张调用 `analyze_photo_file()`
7. 每张结果 `upsert` 到 `history/face_analysis.db`
8. 所有记录加载出来后调用 `build_face_report()`
9. 把报告 JSON 写入数据库缓存表 `face_report_cache`

如果带 `--export` 参数，还会把有效数据导出成 Excel。

### 3.1 常用 CLI 参数

- `--day YYYYMMDD`
  - 只扫描某一天的照片，例如 `20260314`
- `--limit N`
  - 过滤后只取最近 `N` 张
- `--rebuild`
  - 忽略现有缓存，重建结果集
- `--export`
  - 导出 Excel
- `--dir`
  - 指定扫描目录
- `--model`
  - 指定 ONNX 人脸解析模型

---

## 4. 输入数据：照片如何被发现

### 4.1 默认搜索路径

`discover_photo_search_paths()` 会在若干根目录下寻找 `本机照片`：

- `D:\WANGBIAO`
- `OneDrive`
- 用户主目录下的 `OneDrive`
- 用户主目录

候选子目录包括：

- `Pictures\本机照片`
- `图片\本机照片`
- `本机照片`

最终返回存在的绝对路径集合。

### 4.2 文件命名约定

`scan_photos()` 只接受满足下面规则的文件：

- 文件名以 `photo_` 开头
- 文件名以 `.jpg` 结尾
- 文件名中能解析出时间戳

例如：

```text
photo_20260314_205227.jpg
```

时间戳解析规则是：

- 从文件名中提取 `YYYYMMDD_HHMMSS`
- 转成 `datetime`
- 生成：
  - `path`
  - `date`
  - `timestamp`

最后按时间升序排序。

---

## 5. 单张照片分析：总体结构

单张照片分析入口是 `analyze_photo_file()`。

它做两件事：

1. 从文件名解析拍摄时间
2. 用 OpenCV 读取图片后，调用 `analyze_image_data()`

真正的黑眼圈算法核心几乎全部在 `analyze_image_data()` 里。

---

## 6. 配置参数 `AnalysisConfig`

`AnalysisConfig` 负责管理质量门和打分相关超参数。当前默认值如下：

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `min_detection_confidence` | `0.5` | 人脸检测最小置信度 |
| `face_padding_ratio` | `0.35` | 人脸框外扩比例 |
| `blur_threshold` | `50.0` | 拉普拉斯方差低于该值判模糊 |
| `min_face_size` | `120` | 最小人脸尺寸 |
| `min_mask_pixels` | `12` | 眼区/脸颊掩码最小像素数 |
| `under_band_ratio` | `0.45` | 下眼睑 ROI 相对眼高的带宽 |
| `cheek_offset_ratio` | `0.75` | 脸颊 ROI 相对下眼区的偏移 |
| `score_delta_e_weight` | `0.6` | 色差权重 |
| `score_delta_l_weight` | `0.4` | 亮度差权重 |
| `max_face_center_offset_ratio` | `0.32` | 脸框偏离画面中心的最大比例 |
| `min_face_box_aspect_ratio` | `0.75` | 脸框最小长宽比 |
| `max_face_box_aspect_ratio` | `1.35` | 脸框最大长宽比 |
| `min_mean_brightness` | `45.0` | 最低平均亮度 |
| `max_mean_brightness` | `210.0` | 最高平均亮度 |
| `max_dark_pixel_ratio` | `0.55` | 极暗像素比例上限 |
| `max_bright_pixel_ratio` | `0.40` | 极亮像素比例上限 |
| `min_under_eye_pixels` | `60` | 下眼区最小像素数 |
| `max_eye_area_ratio` | `2.5` | 左右眼面积比例上限 |
| `max_left_right_score_gap` | `20.0` | 左右眼分数差上限 |
| `max_brightness_l_gap` | `18.0` | 左右眼亮度差上限 |
| `max_eye_center_y_ratio` | `0.1` | 左右眼中心高度差上限 |
| `max_eye_width_ratio` | `1.8` | 左右眼宽度比例上限 |

这些参数共同决定“哪些图可分析”“哪些分数可信”。

---

## 7. 第一步：人脸检测与裁剪

### 7.1 人脸检测器

`MediaPipeFaceDetector` 使用 `mediapipe.solutions.face_detection.FaceDetection`。

处理流程：

1. 输入 BGR 图像
2. 转 RGB
3. 运行 MediaPipe 人脸检测
4. 如果没有检测结果，返回 `None`
5. 如果有多个检测框，取置信度最高的一个
6. 把相对坐标转成像素坐标 `(x, y, w, h)`

### 7.2 人脸裁剪

`detect_face_crop()` 负责把检测框变成可分析的人脸裁剪图。

逻辑如下：

1. 调用检测器拿到 `bbox`
2. 如果没有脸，返回 `NoFace`
3. 如果脸框尺寸小于 `min_face_size`，返回 `FaceTooSmall`
4. 按 `face_padding_ratio=0.35` 给脸框四周留边
5. 裁剪得到 `crop`
6. 如果裁剪为空，返回 `FaceCropEmpty`

此时后续所有模糊、曝光、解析、打分都基于 `crop`，而不是整张照片。

这点很重要：背景复杂、房间纹理、桌面物体不会直接参与黑眼圈打分。

---

## 8. 第二步：脸框稳定性和基础质量门

在拿到脸部裁剪后，算法不会立刻打分，而是先做几道基础质量门。

### 8.1 脸框稳定性 `_face_box_fail_reasons()`

检查内容：

- 脸框中心偏离整张图中心太多
- 脸框长宽比过扁或过长

如果不满足，返回：

- `UnstableFaceBox`

这一步主要用于挡掉：

- 侧脸太厉害
- 画面里只拍到部分脸
- 脸在画面边缘

### 8.2 模糊检测

算法对 `crop_gray` 计算：

```text
variance = Laplacian(crop_gray).var()
```

如果 `variance < blur_threshold`，返回：

- `Blurry(<整数方差>)`

例如 `Blurry(31)`、`Blurry(44)`。

### 8.3 曝光检测 `_exposure_fail_reasons()`

检查内容：

- 平均亮度过低
- 平均亮度过高
- 极暗像素比例过大
- 极亮像素比例过大

如果触发，返回：

- `ExtremeExposure`

注意：这是极端曝光门；一般的左右亮度不一致，后面还会由 `UnstableBrightness` 再拦一次。

---

## 9. 第三步：人脸解析与眼区定位

### 9.1 主路径：ONNX 人脸解析

`FaceParser` 的主路径是加载 ONNX 模型：

```text
src/scripts/models/face_parsing.farl.lapa.int8.onnx
```

处理流程：

1. 人脸裁剪缩放到 `512x512`
2. BGR 转 RGB
3. 像素归一化到 `[-1, 1]`
4. 转成 `NCHW` blob
5. ONNX Runtime 推理
6. 对输出做 `argmax` 得到 `parsing_map`

`parsing_map` 中每个像素是一个类别索引，例如：

- `skin`
- `l_eye`
- `r_eye`

### 9.2 回退路径：MediaPipe FaceMesh

如果满足任一条件：

- 模型文件不存在
- ONNX Runtime 初始化失败

则切换到回退实现：

- `mediapipe.solutions.face_mesh.FaceMesh`

回退逻辑不是完整语义分割，而是根据 landmark 人工填充：

- 脸部椭圆区 -> `skin`
- 左眼多边形 -> `l_eye`
- 右眼多边形 -> `r_eye`

因此回退模式的分割精度低于 ONNX 主路径，但能保证系统不中断。

### 9.3 眼区缺失时的 fallback 合并

如果主解析结果里左右眼像素为 0，并且 parser 支持 `infer_fallback()`：

1. 再跑一次 fallback
2. 把 fallback 检出的左右眼和皮肤区域并回主 `parsing_map`

这是一个“补洞”机制，用来应对主模型偶发漏检眼睛区域的情况。

---

## 10. 第四步：构造下眼区和脸颊区 ROI

真正的黑眼圈打分并不是看“眼睛本身”，而是比较：

- **下眼睑阴影区**
- **下方脸颊参考区**

这部分逻辑在 `_analyze_eye_region()`。

### 10.1 先找眼睛框

对于左眼或右眼：

1. 从 `parsing_map` 中取出该眼睛类别的 mask
2. 计算其最小外接矩形 `eye_box = (ex, ey, ew, eh)`

如果眼睛 mask 根本不存在，函数直接返回 `None`。

### 10.2 构造下眼区

以眼睛框为基准：

- 下眼区高度 `band_h = max(2, int(eh * under_band_ratio))`
- 当前默认 `under_band_ratio = 0.45`

也就是把眼睛框正下方的一条横带当成候选下眼区，然后再与 `skin_mask` 相交，避免跑到眉毛、头发或背景。

### 10.3 构造脸颊区

脸颊参考区在下眼区再往下一点：

- `cheek_offset_ratio = 0.75`
- 高度大约取眼高的 `0.6`
- 宽度大约取眼宽的 `0.8`

这块区域同样会和 `skin_mask` 相交。

### 10.4 像素数量门槛

如果：

- 下眼区像素 < `min_mask_pixels`
- 或脸颊区像素 < `min_mask_pixels`

函数返回 `None`。

这一步是 ROI 级别的基础保护，防止掩码太稀疏时还继续算分。

---

## 11. 第五步：黑眼圈分数计算公式

### 11.1 颜色空间

算法把 `resized_img` 转到 Lab 色彩空间：

```text
lab = cv2.cvtColor(resized_img, cv2.COLOR_BGR2LAB)
```

Lab 的好处是：

- `L` 通道表示亮度
- `a/b` 通道表示颜色
- 比直接在 RGB 上做差更适合比较“阴影 + 色偏”

### 11.2 统计方式

对下眼区和脸颊区分别提取所有 Lab 像素，取 **中位数**：

- `under_med`
- `cheek_med`

不是取均值，而是取中位数。这样更能抗局部噪点和少量错误像素。

### 11.3 两个核心量

#### 1. 亮度差 `delta_l`

```text
delta_l = max(0, cheek_L - under_L)
```

如果下眼区比脸颊更暗，`delta_l` 变大。

#### 2. Lab 色差 `delta_e`

```text
delta_e = ||cheek_med - under_med||
```

这是脸颊与下眼区整体颜色差异的欧氏距离。

### 11.4 最终单眼分数

```text
score = 0.6 * delta_e + 0.4 * delta_l
```

也就是说当前算法更重视“综合色差”，亮度差次之。

### 11.5 双眼合并

左右眼分别算出：

- `score_left`
- `score_right`
- `delta_e_left`
- `delta_e_right`
- `delta_l_left`
- `delta_l_right`

最终单张总分：

```text
score = (score_left + score_right) / 2
```

分数越高，代表下眼区相对脸颊越暗、越偏色，也就是算法认为黑眼圈越重。

---

## 12. 第六步：双眼一致性与姿态稳定性质量门

算出左右眼分数后，算法仍不会立刻判 `passed=1`，还要经过 `_stability_fail_reasons()`。

### 12.1 下眼区像素不足

如果左右眼下眼区像素最小值低于 `min_under_eye_pixels=60`：

- `UnderEyePixelsTooSmall`

### 12.2 左右眼分差过大

如果：

```text
abs(score_left - score_right) > max_left_right_score_gap
```

返回：

- `UnstableLeftRightGap`

### 12.3 左右亮度不一致

分别比较：

- 左右下眼区亮度差
- 左右脸颊亮度差

如果最大差值超过 `max_brightness_l_gap=18`：

- `UnstableBrightness`

这一步主要挡：

- 一侧阴影明显更重
- 局部光照只照到半张脸

### 12.4 左右眼几何结构不一致

算法还比较：

- 左右眼中心高度差
- 左右眼宽度比
- 左右眼面积比

如果眼面积比例过大：

- `UnstableEyeArea`

如果眼中心高度差或眼宽比例过大：

- `UnstablePose`

这几步主要挡：

- 明显低头/歪头/侧脸
- 一只眼闭得更多
- 眼睛解析错位

---

## 13. `analyze_image_data()` 的完整决策顺序

把整个函数按决策顺序串起来，当前逻辑如下：

1. 初始化结果字典，默认：
   - `passed=False`
   - `score=None`
   - `fail_reason=[]`
2. 如果图片为空：
   - `ReadError`
3. 人脸检测与裁剪
   - 无脸 -> `NoFace`
   - 脸太小 -> `FaceTooSmall`
   - 裁剪空 -> `FaceCropEmpty`
4. 脸框稳定性检查
   - 不稳 -> `UnstableFaceBox`
5. 模糊检测
   - 方差低 -> `Blurry(x)`
6. 极端曝光检测
   - `ExtremeExposure`
7. 人脸解析
   - 如必要，触发 fallback 补眼区
8. 皮肤掩码像素过少
   - `FaceMaskTooSmall`
9. 左眼 ROI 分析
   - 失败 -> `LeftEyeROIInvalid`
10. 右眼 ROI 分析
   - 失败 -> `RightEyeROIInvalid`
11. 双眼稳定性检查
   - `UnderEyePixelsTooSmall`
   - `UnstableLeftRightGap`
   - `UnstableBrightness`
   - `UnstableEyeArea`
   - `UnstablePose`
12. 如果以上都通过：
   - 写入左右眼分数和总分
   - `passed=True`

一旦某一步失败，函数立刻返回，不会继续往后算。

---

## 14. 失败原因清单及含义

当前单帧分析里可能出现的失败原因包括：

- `ReadError`
  - 图片读取失败
- `NoFace`
  - 没检测到人脸
- `FaceTooSmall`
  - 人脸框太小
- `FaceCropEmpty`
  - 脸部裁剪空
- `UnstableFaceBox`
  - 脸框位置或比例异常
- `Blurry(x)`
  - 人脸裁剪太模糊
- `ExtremeExposure`
  - 曝光极端
- `FaceMaskTooSmall`
  - 皮肤解析区域太少
- `LeftEyeROIInvalid`
  - 左眼 ROI 构造失败
- `RightEyeROIInvalid`
  - 右眼 ROI 构造失败
- `UnderEyePixelsTooSmall`
  - 下眼区像素不够
- `UnstableLeftRightGap`
  - 左右眼分差过大
- `UnstableBrightness`
  - 左右亮度条件不一致
- `UnstableEyeArea`
  - 左右眼区域面积差异过大
- `UnstablePose`
  - 左右眼几何结构不一致，通常是姿态问题

这些原因会原样写进数据库字段 `fail_reason_json`。

---

## 15. 数据库存储逻辑

当前黑眼圈结果存在 SQLite 数据库：

```text
history/face_analysis.db
```

### 15.1 主结果表 `face_analysis_results`

每张照片按 `path` 唯一存一条记录，关键字段包括：

- `path`
- `datetime`
- `timestamp`
- `passed`
- `score`
- `score_left`
- `score_right`
- `delta_e_left`
- `delta_e_right`
- `delta_l_left`
- `delta_l_right`
- `fail_reason_json`

### 15.2 报告缓存表 `face_report_cache`

存当前最新报告 JSON。

### 15.3 进度缓存表 `face_progress_cache`

存当前分析进度：

- 当前处理到第几张
- 总数
- 百分比
- 当前文件名

### 15.4 元信息表 `face_analysis_meta`

记录：

- `analysis_algorithm_version`
- `storage_backend`

如果 `analysis_algorithm_version` 变化，初始化时会清空旧结果和缓存。

---

## 16. 报告生成逻辑

报告生成入口是 `build_face_report(results, output_dir)`。

### 16.1 原始有效行提取

先从数据库结果中取出：

- `passed=True`
- `score is not None`

这批数据称为原始有效样本。

### 16.2 原始失败行统计

同时统计失败样本：

- `failed`
- `fail_reason_counts`

这些质量统计不受报告层离群过滤影响，仍然反映原始单帧判定结果。

---

## 17. 趋势图和平滑逻辑

### 17.1 `plot_trend()`

趋势图由两部分组成：

- 原始散点 `Raw Score`
- 样本移动平均 `Sample Moving Average`

图标题显示：

```text
Dark Circle Severity Trend (Valid Samples=N)
```

### 17.2 `compute_trend_series()`

平滑逻辑：

- 单天数据使用 `30min` 滚动窗口
- 多天数据使用 `1D` 滚动窗口
- 如果间隔太大，按 gap 切段分别平滑
  - 单天 gap 限制：30 分钟
  - 多天 gap 限制：12 小时
- 小于 3 个样本的窗口平滑值置为 `NaN`

这意味着趋势线不会跨越长时间中断强行连起来。

### 17.3 `build_trend_views()`

报告里还有四组结构化趋势点：

- `day`: 最近 24 小时，保留原始点
- `week`: 最近 7 天，按天聚合均值
- `month`: 最近 30 天，按天聚合均值
- `all`: 全部历史，按天聚合均值

输出给前端时，每个点包含：

- `timestamp`
- `datetime`
- `score`

---

## 18. 报告层离群值过滤：为什么还需要这一层

单帧质量门已经挡掉了大量坏图，但实际运行中仍会出现极少数“漏网帧”：

- 明显低头
- 眼睛半闭
- 局部光照不稳
- 邻近帧大量失败，但个别帧侥幸通过

这类帧会产生非常离谱的分数，例如：

- `30 -> 66 -> 31`
- `31 -> 4 -> 30`

从单张逻辑看它们是 `passed=1`，但从时间序列看显然是异常单点。  
所以当前实现额外加了一层 **保守离群值过滤**，只在报告层使用。

---

## 19. 报告层离群过滤 `filter_report_outlier_points()`

这个函数只处理已经 `passed=1` 的有效样本。

### 19.1 设计目标

- 不改数据库原始结果
- 只剔除孤立极端点
- 不误杀连续变化
- 只在时间连续片段内判断

### 19.2 处理步骤

1. 把结果转成 DataFrame
2. 解析 `datetime`
3. 如果缺失 `timestamp`，就根据时间生成
4. 丢掉时间或分数为空的行
5. 按时间排序
6. 计算左右眼分差 `lr_gap`
7. 按时间间隔切成多个 segment
   - 当前 segment 间隔阈值：30 分钟

### 19.3 核心判定条件

对于 segment 中某个点，如果同时满足：

1. 它和前一个有效点差很多
2. 它和后一个有效点也差很多
3. 前后两个邻居彼此又比较接近
4. 它显著偏离局部中位数
5. 左右眼分差不过大

则认为这是 **孤立跳点**，从报告层剔除。

当前默认阈值：

- `jump_threshold = 25.0`
- `neighbor_similarity_threshold = 12.0`
- `local_window = 5`
- `local_deviation_threshold = 18.0`
- `segment_gap_minutes = 30.0`

### 19.4 这层过滤会影响什么

会影响：

- `count`
- `heaviest`
- `lightest`
- `trend_plot_path`
- `trend_views`
- `quality.passed`

不会影响：

- `face_analysis_results` 原始记录
- `quality.failed`
- `quality.fail_reason_counts`

此外，报告现在还会给出：

- `quality.filtered_outliers`

表示这次报告层剔除了多少个已通过样本。

### 19.5 为什么是“保守”过滤

这层过滤不会删除所有可疑值，只删除最典型的单点尖峰/谷底。  
例如连续偏高、连续偏低、或者变化比较平滑的片段，通常仍会保留。

这就是为什么有些偏可疑但不够“孤立”的值仍然可能留在报告里。

---

## 20. `filter_stable_trend_points()` 与 `filter_report_outlier_points()` 的区别

代码里现在有两个时序过滤函数：

### 20.1 `filter_stable_trend_points()`

更早的稳定趋势工具，逻辑偏泛化：

- 左右眼分差过滤
- 局部中位数偏差过滤
- 孤立尖峰过滤

它当前更像一个通用趋势过滤工具，**不是当前报告主路径的核心入口**。

### 20.2 `filter_report_outlier_points()`

这是当前真正接入 `build_face_report()` 的报告层过滤函数，特点是：

- 只做保守剔除
- 强调“邻居要彼此接近”
- 强调“只在短时间连续片段内判断”
- 直接服务于最终报告展示

---

## 21. 最终报告输出结构

`build_face_report()` 最终返回的大致结构：

```json
{
  "count": 381,
  "heaviest": {
    "path": "...",
    "score": 57.39,
    "date": "2026-03-14 16:14:24"
  },
  "lightest": {
    "path": "...",
    "score": 1.73,
    "date": "2025-02-07 15:59:17"
  },
  "trend_plot_path": ".../dark_circles_trend.png",
  "trend_views": {
    "day": { "label": "最近24小时", "points": [...] },
    "week": { "label": "最近7天", "points": [...] },
    "month": { "label": "最近30天", "points": [...] },
    "all": { "label": "全部历史", "points": [...] }
  },
  "quality": {
    "passed": 381,
    "failed": 1087,
    "filtered_outliers": 5,
    "fail_reason_counts": { ... }
  }
}
```

前端实际消费的是这个报告结构，而不是直接读数据库原始表。

---

## 22. 如何理解当前分数

当前分数本质上是一个 **相对色差/亮度差指标**，不是医学诊断分值。

它表示的是：

- 下眼区相对脸颊有多暗
- 下眼区相对脸颊有多偏色

所以：

- 分数高：算法认为黑眼圈更明显
- 分数低：算法认为黑眼圈更轻

但它受到下列因素影响：

- 低头
- 闭眼
- 侧脸
- 局部阴影
- 相机曝光
- ROI 分割精度

因此这个分数更适合：

- 看同一设备、相似环境下的趋势
- 看大量样本后的总体变化

不适合：

- 把单张图一个分数当作绝对真值
- 跨设备、跨光照场景直接横向比较

---

## 23. 当前算法的已知局限

### 23.1 仍然依赖拍摄姿态

即使有姿态质量门，低头、闭眼、侧脸仍可能漏掉少量帧。

### 23.2 对光照仍敏感

虽然做了：

- 极端曝光过滤
- 左右亮度一致性过滤
- 报告层离群值过滤

但室内灯光、屏幕反光、局部阴影仍会影响分数。

### 23.3 当前分数是手工构造指标

本质上是：

- Lab 色差
- 亮度差
- ROI 规则

它不是端到端训练出来的黑眼圈回归模型。

### 23.4 保守离群过滤不会删除所有可疑值

这是故意的。  
当前策略优先避免误删正常样本，所以只杀最极端的孤立点。

---

## 24. 如果后续还要继续改进，方向有哪些

后续可以继续改进的方向包括：

### 24.1 更强的单帧质量门

例如增加：

- 闭眼程度检测
- 头部俯仰角检测
- 眼裂高度门槛

这样能在 `passed=1` 之前就拦掉更多坏帧。

### 24.2 更严格的报告层过滤

可以在保守过滤基础上进一步处理：

- 57 这类偏高但没到最极端的值
- 7~15 这类偏低但不一定被当前规则判成孤立谷底的值

### 24.3 让 Excel 导出也复用报告层过滤

目前 Excel 导出的是原始有效样本，不是过滤后的报告样本。

### 24.4 引入学习式模型

如果未来有足够标注数据，可以考虑：

- 训练专门的黑眼圈严重度回归模型
- 或训练更强的样本质量判别器

---

## 25. 一句话总结

当前黑眼圈算法是一个“**人脸检测 -> 脸部裁剪 -> 人脸解析 -> 下眼区/脸颊色差打分 -> 单帧质量门 -> 报告层保守离群过滤**”的多阶段规则系统。

它的重点不是让每一张图都绝对准确，而是：

- 尽量从大量历史照片中筛出可比样本
- 用稳定样本形成可读趋势
- 把明显离谱的单点误判挡在报告之外

如果你后续要继续细化，我建议下一份文档直接写“失败原因逐项案例说明”或“参数调优手册”。
