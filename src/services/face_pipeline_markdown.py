from pathlib import Path


def _format_fail_reasons(fail_reasons):
    if not fail_reasons:
        return "通过"
    return "，".join(fail_reasons)


def build_pipeline_markdown(data: dict) -> str:
    assets = data["assets"]
    metrics = data["metrics"]
    lines = []
    lines.append("# 图片处理流程")
    lines.append("")
    lines.append("```mermaid")
    lines.append("flowchart LR")
    lines.append("  A[原始图片] --> B[人脸检测]")
    lines.append("  B --> C[人脸剪裁]")
    lines.append("  C --> D[Face Parsing]")
    lines.append("  D --> E[质量门控]")
    lines.append("  E --> F[多因子评分]")
    lines.append("```")
    lines.append("")
    lines.append(f"## 样本信息")
    lines.append(f"- 标题：{data['sample_title']}")
    lines.append(f"- 原图路径：`{data['source_path']}`")
    lines.append(f"- 当前状态：`{data['status']}`")
    lines.append(f"- 失败原因：`{_format_fail_reasons(data['fail_reasons'])}`")
    lines.append("")
    lines.append("## 1. 原始图片")
    lines.append(f"![original]({assets['original']})")
    lines.append("")
    lines.append("## 2. 人脸检测与剪裁")
    lines.append(f"- bbox: `{metrics['bbox']}`")
    lines.append(f"- crop_size: `{metrics['crop_size']}`")
    lines.append(f"![detection]({assets['detection']})")
    lines.append(f"![crop]({assets['crop']})")
    lines.append("")
    lines.append("## 3. Face Parsing")
    lines.append(f"- skin_pixels: `{metrics['skin_pixels']}`")
    lines.append(f"- left_eye_pixels: `{metrics['left_eye_pixels']}`")
    lines.append(f"- right_eye_pixels: `{metrics['right_eye_pixels']}`")
    lines.append(f"![parsing]({assets['parsing']})")
    lines.append("")
    lines.append("## 4. 质量门控")
    lines.append("| 指标 | 值 |")
    lines.append("| --- | --- |")
    lines.append(f"| blur_variance | `{metrics['blur_variance']}` |")
    lines.append(f"| gate_status | `{data['status']}` |")
    lines.append(f"| fail_reasons | `{_format_fail_reasons(data['fail_reasons'])}` |")
    lines.append("")
    lines.append("## 5. 多因子评分")
    lines.append(f"![roi]({assets['roi']})")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("| --- | --- |")
    lines.append(f"| score_left | `{metrics['score_left']}` |")
    lines.append(f"| score_right | `{metrics['score_right']}` |")
    lines.append(f"| score | `{metrics['score']}` |")
    lines.append(f"| delta_e_left | `{metrics['delta_e_left']}` |")
    lines.append(f"| delta_e_right | `{metrics['delta_e_right']}` |")
    lines.append(f"| delta_l_left | `{metrics['delta_l_left']}` |")
    lines.append(f"| delta_l_right | `{metrics['delta_l_right']}` |")
    lines.append("")
    lines.append("## 说明")
    lines.append("- 每张图片都先做人脸检测和剪裁，再进入 face parsing。")
    lines.append("- 质量门控失败的图片不会进入最终评分汇总。")
    lines.append("- 多因子评分同时看左右眼、LAB 明度差和颜色距离，而不是只看单一亮度。")
    lines.append("")
    return "\n".join(lines)


def write_pipeline_markdown(data: dict, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_pipeline_markdown(data), encoding="utf-8")
    return path
