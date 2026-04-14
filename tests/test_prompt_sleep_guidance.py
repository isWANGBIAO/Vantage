from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_ai_instructions_require_cbti_style_sleep_guidance_when_sleep_is_poor():
    content = (PROJECT_ROOT / "Prompt_AI_Instructions.md").read_text(encoding="utf-8")

    assert "CBT-I" in content
    assert "失眠" in content
    assert "睡眠不足" in content
    assert "昼夜节律紊乱" in content
    assert "固定起床时间" in content
    assert "睡眠限制" in content
    assert "晨光暴露" in content
    assert "夜间降光" in content
    assert "规律运动" in content
    assert "正念" in content
    assert "低剂量褪黑素" in content


def test_action_plan_template_requires_explicit_sleep_interventions_when_triggered():
    content = (PROJECT_ROOT / "Prompt_Action_Plan.md").read_text(encoding="utf-8")

    assert "CBT-I" in content
    assert "固定起床时间" in content
    assert "睡眠限制" in content
    assert "晨光暴露" in content
    assert "夜间降光" in content
    assert "规律运动" in content
    assert "正念" in content
    assert "低剂量褪黑素" in content
    assert "仅作为辅助" in content
