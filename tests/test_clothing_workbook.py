"""Synthetic-only clothing workbook contracts; no personal workbooks are used."""

import hashlib
import json
import zipfile

import openpyxl
import pytest
from openpyxl.comments import Comment
from openpyxl.styles import Font

from src.services import clothing_workbook as clothing


def workbook_path(tmp_path, rows=()):
    path = tmp_path / "clothing.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet.append(clothing.HEADERS)
    for row in rows:
        sheet.append(row)
    book.save(path)
    book.close()
    return path


def new_record(**values):
    return {
        "garment": "示例外套", "brand": "示例品牌", "style_code": "DEMO-01", "size": "M", "category": "外套",
        "component": "外壳", "length_cm": 72, "chest_cm": 114, "shoulder_cm": 46, "sleeve_cm": 63,
        "length_basis": "后肩衣长", "sleeve_basis": "肩点袖长", "measurement_source": "尺码截图",
        "measurement_tolerance_cm": 2, "trial_date": "2026-01-10", "feedback_scope": "整件",
        "shoulder_feedback": "显窄", "sleeve_feedback": "合适", "length_feedback": "合适",
        "layering": "未知", "overall_feedback": "仅整件试穿", "notes": "示例截图尺寸，非实测尺寸。",
        **values,
    }


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_read_uses_stable_copy_and_never_changes_source(tmp_path, monkeypatch):
    path = workbook_path(tmp_path, [["示例T恤", "合适", "M", None, None, None, 68, 44, 50, 21]])
    before = path.read_bytes()
    original = clothing._load
    seen = []

    def load(snapshot, **kwargs):
        assert snapshot != path
        assert snapshot.parent != path.parent
        seen.append(snapshot)
        return original(snapshot, **kwargs)

    monkeypatch.setattr(clothing, "_load", load)
    state = clothing.read_workbook(path)
    assert state["sheet"] == "Sheet1"
    assert state["revision"] == fingerprint(path)
    assert len(state["records"]) == 1
    assert path.read_bytes() == before
    assert all(not snapshot.exists() for snapshot in seen)


def test_legacy_mixed_measurements_are_preserved_and_not_guessed(tmp_path):
    path = workbook_path(tmp_path, [
        ["示例Polo衫", None, "L", None, 108, 53, 72, 46, None, 20],
        ["示例外套", "小", "M", None, None, None, 66, 50, 64, "连肩袖长89"],
        [None, None, None, "本人量度", None, None, "胸围90腰围76", 43],
    ])
    first, second, body = clothing.read_workbook(path)["records"]
    assert first["chest_cm"] is None
    assert first["raw_fields"]["F"] == "53"
    assert first["chest_width_cm"] is None
    assert any("未擅自乘二" in warning for warning in first["warnings"])
    assert any("E列" in warning for warning in first["warnings"])
    assert second["sleeve_cm"] == 89
    assert second["sleeve_basis"] == "连肩袖长"
    assert second["overall_feedback"] == "小"
    assert second["shoulder_feedback"] == ""
    assert body["record_kind"] == "body"
    assert body["length_cm"] is None


def test_whole_garment_feedback_is_distinct_from_component_dimensions(tmp_path):
    row = ["示例三合一冲锋衣", "肩部显窄", "M", None, None, 114, 72, 46, 57, 63,
           "2026-01-10", "示例", "DEMO-01", "抓绒内胆", "未单独确认", "未单独确认", "未单独确认", "未记录",
           "用户提供尺码截图（cm，允许1–3cm测量误差）；反馈针对整件试穿，内胆单独感受未确认。"]
    record = clothing.read_workbook(workbook_path(tmp_path, [row]))["records"][0]
    assert record["component"] == "内胆"
    assert record["raw_fields"]["N"] == "抓绒内胆"
    assert record["feedback_scope"] == "整件"
    assert record["shoulder_feedback"] == "未单独确认"
    assert record["measurement_source"] == "尺码截图"
    assert record["measurement_tolerance_cm"] == 3


def test_append_preserves_old_rows_styles_formulas_and_one_sheet(tmp_path):
    path = workbook_path(tmp_path, [["旧衣服", "旧反馈", "S", "旧标记", "含混保留", None, 65, 42, 48, 60]])
    book = openpyxl.load_workbook(path)
    book.active["A2"].font = Font(bold=True, color="123456")
    book.active["T2"] = "=SUM(1,2)"
    book.active["S2"].comment = Comment("旧注释", "Original author")
    book.save(path)
    book.close()
    before = clothing.read_workbook(path)
    after = clothing.save_records(path, [new_record()], before["revision"])
    assert len(after["records"]) == 2
    assert after["revision"] != before["revision"]
    assert after["revision"] == fingerprint(path)
    book = openpyxl.load_workbook(path)
    assert book.sheetnames == ["Sheet1"]
    assert [book.active.cell(2, column).value for column in range(1, 11)] == ["旧衣服", "旧反馈", "S", "旧标记", "含混保留", None, 65, 42, 48, 60]
    assert book.active["A2"].font.bold
    assert book.active["A2"].font.color.rgb == "00123456"
    assert book.active["T2"].value == "=SUM(1,2)"
    assert book.active["S2"].comment.text == "旧注释"
    assert book.active["I3"].value == "=F3/2"
    assert after["records"][1]["chest_width_cm"] == 57
    book.close()


def test_metadata_survives_multiple_saves_without_new_data_files(tmp_path):
    path = workbook_path(tmp_path)
    first = clothing.save_records(path, [new_record()], clothing.read_workbook(path)["revision"])
    second = clothing.save_records(path, [{"row": 2, "chest_feedback": "略松", "mobility_feedback": "未测试"}], first["revision"])
    record = second["records"][0]
    assert record["sleeve_basis"] == "肩点袖长"
    assert record["measurement_tolerance_cm"] == 2
    assert record["chest_feedback"] == "略松"
    assert record["mobility_feedback"] == "未测试"
    assert record["overall_feedback"] == "仅整件试穿"
    assert record["shoulder_feedback"] == "显窄"
    assert [file.name for file in tmp_path.iterdir()] == ["clothing.xlsx"]


def test_edit_feedback_preserves_measurements_and_old_comment(tmp_path):
    path = workbook_path(tmp_path, [["旧衣服", "原反馈", "S", "标记", None, None, 65, 42, 48, 60]])
    book = openpyxl.load_workbook(path)
    book.active["S2"].comment = Comment("人工注释", "Original author")
    book.save(path)
    book.close()
    before = clothing.read_workbook(path)
    updated = clothing.save_records(path, [{"row": 2, "overall_feedback": "袖长合适", "feedback_scope": "整件"}], before["revision"])
    assert updated["records"][0]["length_cm"] == 65
    assert updated["records"][0]["overall_feedback"] == "袖长合适"
    book = openpyxl.load_workbook(path)
    assert book.active["S2"].comment.text.startswith("人工注释")
    assert book.active["S2"].comment.author == "Original author"
    assert book.active["D2"].value == "标记"
    book.close()


@pytest.mark.parametrize("patch", [{"length_cm": 99}, {"garment": "改名"}, {"size": "XL"}])
def test_historical_dimensions_cannot_be_overwritten(tmp_path, patch):
    path = workbook_path(tmp_path, [["旧衣服", "反馈", "S", None, None, None, 65, 42, 48, 60]])
    before = path.read_bytes()
    with pytest.raises(clothing.WorkbookError, match="另存"):
        clothing.save_records(path, [{"row": 2, **patch}], fingerprint(path))
    assert path.read_bytes() == before


def test_stale_revision_preserves_concurrent_edit(tmp_path):
    path = workbook_path(tmp_path)
    old = fingerprint(path)
    book = openpyxl.load_workbook(path)
    book.active["A2"] = "用户刚输入的内容"
    book.save(path)
    book.close()
    concurrent = path.read_bytes()
    with pytest.raises(clothing.WorkbookConflict):
        clothing.save_records(path, [new_record()], old)
    assert path.read_bytes() == concurrent


def test_late_concurrent_write_is_detected_before_publication(tmp_path, monkeypatch):
    path = workbook_path(tmp_path)
    publish = clothing._publish
    concurrent = []

    def change_before_publish(target, staged, revision):
        book = openpyxl.load_workbook(target)
        book.active["A2"] = "晚到的用户编辑"
        book.save(target)
        book.close()
        concurrent.append(target.read_bytes())
        publish(target, staged, revision)

    monkeypatch.setattr(clothing, "_publish", change_before_publish)
    with pytest.raises(clothing.WorkbookConflict):
        clothing.save_records(path, [new_record()], fingerprint(path))
    assert path.read_bytes() == concurrent[0]
    assert sorted(file.name for file in tmp_path.iterdir()) == ["clothing.xlsx"]


def test_excel_owner_file_prevents_writes_but_not_snapshot_reads(tmp_path):
    path = workbook_path(tmp_path)
    owner = path.with_name("~$" + path.name)
    owner.write_bytes(b"synthetic owner")
    before = path.read_bytes()
    assert clothing.read_workbook(path)["records"] == []
    with pytest.raises(clothing.WorkbookBusy):
        clothing.save_records(path, [new_record()], fingerprint(path))
    assert path.read_bytes() == before


def test_snapshot_detects_source_change_during_copy(tmp_path, monkeypatch):
    path = workbook_path(tmp_path)
    copy = clothing.shutil.copyfile

    def changed_copy(source, destination):
        copy(source, destination)
        with source.open("ab") as handle:
            handle.write(b"external edit")

    monkeypatch.setattr(clothing.shutil, "copyfile", changed_copy)
    with pytest.raises(clothing.WorkbookConflict):
        clothing.read_workbook(path)


def test_publication_permission_error_retains_original_and_cleans_stage(tmp_path, monkeypatch):
    path = workbook_path(tmp_path)
    before = path.read_bytes()

    def denied(*args):
        raise PermissionError

    monkeypatch.setattr(clothing.os, "replace", denied)
    with pytest.raises(clothing.WorkbookBusy):
        clothing.save_records(path, [new_record()], fingerprint(path))
    assert path.read_bytes() == before
    assert [file.name for file in tmp_path.iterdir()] == ["clothing.xlsx"]


@pytest.mark.parametrize("field,value", [("length_cm", True), ("chest_cm", float("nan")), ("shoulder_cm", -1),
    ("sleeve_cm", "60"), ("size", ["M"]), ("measurement_tolerance_cm", 21), ("trial_date", "2026-02-30"),
    ("component", "外壳和内胆"), ("row", True), ("row", []), ("notes", "\0"), ("sleeve_basis", "随便")])
def test_invalid_payload_is_rejected_before_publication(tmp_path, field, value):
    path = workbook_path(tmp_path)
    before = path.read_bytes()
    with pytest.raises(clothing.WorkbookError):
        clothing.save_records(path, [new_record(**{field: value})], fingerprint(path))
    assert path.read_bytes() == before


def test_spreadsheet_formula_injection_is_saved_as_literal_text(tmp_path):
    path = workbook_path(tmp_path)
    clothing.save_records(path, [new_record(garment="=HYPERLINK(\"https://invalid.example\")", notes="=1+1")], fingerprint(path))
    book = openpyxl.load_workbook(path)
    assert book.active["A2"].data_type == "s"
    assert book.active["S2"].data_type == "s"
    assert book.active["S2"].value == "=1+1"
    book.close()


@pytest.mark.parametrize("case", ["second-sheet", "wrong-name", "merged", "drawing", "wrong-headers"])
def test_unsupported_workbooks_fail_closed_without_rebuilding(tmp_path, case):
    path = workbook_path(tmp_path)
    book = openpyxl.load_workbook(path)
    if case == "second-sheet":
        book.create_sheet("Other")
    elif case == "wrong-name":
        book.active.title = "Other"
    elif case == "merged":
        book.active.merge_cells("A2:B2")
    elif case == "wrong-headers":
        book.active["K1"] = "别的内容"
    book.save(path)
    book.close()
    if case == "drawing":
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("xl/drawings/drawing99.xml", "<test/>")
    before = path.read_bytes()
    with pytest.raises(clothing.WorkbookError):
        clothing.save_records(path, [new_record()], fingerprint(path))
    assert path.read_bytes() == before


def test_missing_extension_headers_are_added_but_old_headers_are_never_rewritten(tmp_path):
    path = workbook_path(tmp_path)
    book = openpyxl.load_workbook(path)
    book.active["A1"] = "旧款式列"
    for column in range(11, 20):
        book.active.cell(1, column).value = None
    book.save(path)
    book.close()
    result = clothing.save_records(path, [new_record()], fingerprint(path))
    assert result["warnings"]
    book = openpyxl.load_workbook(path)
    assert book.active["A1"].value == "旧款式列"
    assert [book.active.cell(1, column).value for column in range(11, 20)] == list(clothing.HEADERS[10:])
    book.close()


def test_corrupt_metadata_is_not_trusted_or_executed(tmp_path):
    path = workbook_path(tmp_path, [["旧衣服", "反馈", "M"]])
    book = openpyxl.load_workbook(path)
    book.active["S2"].comment = Comment(clothing.META_PREFIX + "\n" + json.dumps({"feedback_scope": ["整件"]}), "test")
    book.save(path)
    book.close()
    record = clothing.read_workbook(path)["records"][0]
    assert record["feedback_scope"] == "未知"
    assert any("损坏" in warning for warning in record["warnings"])
    damaged = openpyxl.load_workbook(path)
    original_comment = damaged.active["S2"].comment.text
    damaged.close()
    clothing.save_records(path, [{"row": 2, "feedback_scope": "整件"}], fingerprint(path))
    repaired = openpyxl.load_workbook(path)
    assert original_comment in repaired.active["S2"].comment.text
    repaired.close()


def test_duplicate_update_rows_are_rejected(tmp_path):
    path = workbook_path(tmp_path, [["旧衣服", "反馈", "M"]])
    before = path.read_bytes()
    with pytest.raises(clothing.WorkbookError, match="重复"):
        clothing.save_records(path, [{"row": 2}, {"row": 2}], fingerprint(path))
    assert path.read_bytes() == before


def test_feedback_update_does_not_normalize_original_date_or_component_cells(tmp_path):
    from datetime import datetime

    row = ["示例冲锋衣", "整件反馈", "M", None, None, 114, 72, 46, 57, 63,
           datetime(2026, 1, 10), "示例", "DEMO-01", "抓绒内胆"]
    path = workbook_path(tmp_path, [row])
    state = clothing.read_workbook(path)
    clothing.save_records(path, [{**state["records"][0], "overall_feedback": "新整件反馈"}], state["revision"])
    book = openpyxl.load_workbook(path)
    assert book.active["K2"].value == datetime(2026, 1, 10)
    assert book.active["N2"].value == "抓绒内胆"
    assert book.active["B2"].value == "新整件反馈"
    book.close()


@pytest.mark.parametrize("entry", ["xl/drawings/vmlDrawing1.vml", "xl/embeddings/object1.bin", "xl/controls/control1.xml",
    "xl/externalLinks/externalLink1.xml", "xl/activeX/activeX1.bin", "xl/connections.xml"])
def test_advanced_structures_are_not_silently_dropped_on_save(tmp_path, entry):
    path = workbook_path(tmp_path)
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(entry, b"synthetic")
    before = path.read_bytes()
    with pytest.raises(clothing.WorkbookError, match="高级结构"):
        clothing.save_records(path, [new_record()], fingerprint(path))
    assert path.read_bytes() == before


def test_ambiguous_legacy_date_is_preserved_when_other_feedback_changes(tmp_path):
    row = ["示例外套", "反馈", "M", None, None, 114, 72, 46, 57, 63, "日期待核对"]
    path = workbook_path(tmp_path, [row])
    state = clothing.read_workbook(path)
    assert state["records"][0]["trial_date"] is None
    assert state["records"][0]["raw_fields"]["K"] == "日期待核对"
    assert any("日期格式" in warning for warning in state["records"][0]["warnings"])
    clothing.save_records(path, [{"row": 2, "overall_feedback": "袖长合适"}], state["revision"])
    book = openpyxl.load_workbook(path)
    assert book.active["K2"].value == "日期待核对"
    book.close()


def test_another_transaction_cannot_publish_while_current_writer_owns_lock(tmp_path):
    path = workbook_path(tmp_path)
    with clothing._transaction(path):
        with pytest.raises(clothing.WorkbookBusy):
            with clothing._transaction(path):
                pytest.fail("A second transaction must not acquire the same lock.")


def test_comment_named_vml_cannot_hide_form_controls(tmp_path):
    path = workbook_path(tmp_path)
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("xl/drawings/commentsDrawing9.vml", b'<v:shape><x:ClientData ObjectType="Button"/></v:shape>')
    before = path.read_bytes()
    with pytest.raises(clothing.WorkbookError, match="VML"):
        clothing.save_records(path, [new_record()], fingerprint(path))
    assert path.read_bytes() == before
