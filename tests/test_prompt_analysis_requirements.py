from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_general_analysis_requires_summary_records_table():
    content = (PROJECT_ROOT / "Prompt_AI_Instructions.md").read_text(encoding="utf-8")

    assert "分析总结" in content
    assert "Markdown 表格" in content
    assert "各力量训练动作" in content
    assert "历史最大训练重量" in content
    assert "当前建议目标" in content
    assert "身高" in content
    assert "年龄" in content
    assert "体重" in content
    assert "体脂" in content
    assert "跑步历史最快配速" in content
    assert "无法确认" in content


def test_improvement_tables_require_current_scores():
    content = (PROJECT_ROOT / "Prompt_AI_Instructions.md").read_text(encoding="utf-8")

    assert "目前分数（0-100）" in content
    assert "健康改善分数（0-100）" in content
    assert "时间改善分数（0-100）" in content
