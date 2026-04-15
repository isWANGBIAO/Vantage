from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_action_plan_template_requires_past_seven_days_training_analysis():
    content = (PROJECT_ROOT / "Prompt_Action_Plan.md").read_text(encoding="utf-8")

    assert "过去 7 天" in content
    assert "训练频率" in content
    assert "肌群覆盖" in content
    assert "强度" in content
    assert "恢复状态" in content
    assert "补量、维持还是降量" in content
    assert "{past_7_days_rows}" in content
