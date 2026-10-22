"""Preserve Markdown semantics across project progress and plan persistence."""

import asyncio
from unittest.mock import patch

from src.backend import projects
from src.utils.action_plan_sanitizer import sanitize_action_plan_markdown


def test_project_progress_ignores_fenced_examples_and_accepts_gfm_task_markers(tmp_path):
    source = tmp_path / "Prompt_Project_Management.md"
    source.write_text("""## 项目任务
- [x] Completed dash
* [ ] Pending star
+   [X] Completed plus
1. [ ] Pending ordered
2) [x] Completed parenthesis
```md
- [ ] Not a task
## 项目示例
```
~~~markdown
* [x] Not completed
~~~
- [ ] Still original project
""", encoding="utf-8")
    with patch.object(projects.DataLoader, "resolve_data_path", return_value=source), patch.object(projects, "_load_recent_git_commits", return_value=[]):
        result = asyncio.run(projects.get_project_progress())
    assert result["stats"]["total_tasks"] == 6
    assert result["stats"]["completed_tasks"] == 3
    assert [task["task"] for task in result["tasks"]["pending"]] == ["Pending star", "Pending ordered", "Still original project"]
    assert all(task["project"] == "项目任务" for task in result["tasks"]["pending"])


def test_plan_sanitizer_retains_nested_lists_fenced_code_and_hard_breaks():
    markdown = '# Plan\n- Parent\n    - Child\n        - Grandchild\n\n```python\nif ready:\n    print("<p>literal</p>")\n\n\n\n    keep = "a  b"\n```\n\nLine with hard break  \nNext line'
    assert sanitize_action_plan_markdown(markdown) == markdown


def test_indented_code_is_not_unindented_or_html_sanitized():
    markdown = '    first  line\n    <p>literal</p>\n    second  line'
    assert sanitize_action_plan_markdown(markdown) == markdown


def test_analysis_separator_inside_code_is_literal_not_a_protocol_boundary():
    for markdown in ['```python\nvalue = "---ANALYSIS_END---"\n```', '```text\n---ANALYSIS_END---\n```', '    ---ANALYSIS_END---']:
        assert sanitize_action_plan_markdown(markdown) == markdown
