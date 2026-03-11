import unittest

from src.services.face_pipeline_markdown import build_pipeline_markdown


class FacePipelineMarkdownTests(unittest.TestCase):
    def test_build_pipeline_markdown_includes_all_stages_and_assets(self):
        markdown = build_pipeline_markdown(
            {
                "sample_title": "示例样本",
                "source_path": r"D:\WANGBIAO\图片\本机照片\2026\03\11\23\photo_20260311_231320.jpg",
                "status": "passed",
                "fail_reasons": [],
                "assets": {
                    "original": "assets/original.jpg",
                    "detection": "assets/detection.jpg",
                    "crop": "assets/crop.jpg",
                    "parsing": "assets/parsing.jpg",
                    "roi": "assets/roi.jpg",
                },
                "metrics": {
                    "bbox": [1200, 1400, 680, 680],
                    "crop_size": [987, 1144],
                    "blur_variance": 98.7,
                    "skin_pixels": 46090,
                    "left_eye_pixels": 215,
                    "right_eye_pixels": 420,
                    "score_left": 40.22,
                    "score_right": 15.49,
                    "score": 27.86,
                    "delta_e_left": 41.04,
                    "delta_e_right": 15.81,
                    "delta_l_left": 39.0,
                    "delta_l_right": 15.0,
                },
            }
        )

        self.assertIn("# 图片处理流程", markdown)
        self.assertIn("## 1. 原始图片", markdown)
        self.assertIn("## 2. 人脸检测与剪裁", markdown)
        self.assertIn("## 3. Face Parsing", markdown)
        self.assertIn("## 4. 质量门控", markdown)
        self.assertIn("## 5. 多因子评分", markdown)
        self.assertIn("assets/original.jpg", markdown)
        self.assertIn("assets/roi.jpg", markdown)
        self.assertIn("score_left", markdown)


if __name__ == "__main__":
    unittest.main()
