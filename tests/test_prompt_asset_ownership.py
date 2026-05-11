from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_prompt_marks_lab_computers_as_lab_assets():
    inventory = (PROJECT_ROOT / "Prompt_Inventory.md").read_text(encoding="utf-8")
    project_management = (PROJECT_ROOT / "Prompt_Project_Management.md").read_text(encoding="utf-8")

    assert "实验室资产：AMD Ryzen 9950X + RTX 5090" in inventory
    assert "实验室资产：无独显轻薄本" in inventory
    assert "1260p 笔记本（实验室资产）" in project_management
    assert "9950X + 5090（实验室资产）" in project_management
