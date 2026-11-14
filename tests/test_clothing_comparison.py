"""Synthetic clothing examples only; no personal workbook or trial data."""

from copy import deepcopy

import pytest

from src.services.clothing_comparison import compare_clothing


def record(**overrides):
    result = {
        "row": 7, "garment": "示例外套", "brand": "示例品牌", "style_code": "DEMO-001", "category": "外套",
        "size": "X", "component": "外壳", "length_cm": 70, "chest_cm": 110, "chest_width_cm": 55,
        "shoulder_cm": 45, "sleeve_cm": 62, "length_basis": "后肩衣长", "sleeve_basis": "肩点袖长",
        "measurement_source": "尺码截图", "measurement_tolerance_cm": 1, "trial_date": "2030-01-02",
        "feedback_scope": "外壳", "overall_feedback": "合适", "shoulder_feedback": "合适",
        "sleeve_feedback": "合适", "length_feedback": "合适", "chest_feedback": "",
        "mobility_feedback": "活动正常", "layering": "薄内搭", "notes": "", "warnings": [], "record_kind": "garment",
    }
    result.update(overrides)
    return result


def test_deltas_are_candidate_minus_history_and_inputs_remain_unchanged():
    old = record()
    candidate = record(length_cm=72, chest_cm=114, chest_width_cm=57, shoulder_cm=46)
    snapshot = deepcopy((candidate, old))
    result = compare_clothing(candidate, [old])
    assert [(item["field"], item["delta_cm"]) for item in result["matches"][0]["differences"]] == [
        ("length_cm", 2), ("chest_cm", 4), ("shoulder_cm", 1), ("sleeve_cm", 0),
    ]
    assert (candidate, old) == snapshot
    assert result["matches"][0]["known_suitable"] is True
    assert "最接近" in result["summary"]


@pytest.mark.parametrize("field,value", [("component", "内胆"), ("component", "未知"), ("category", "裤装"), ("record_kind", "body")])
def test_incompatible_parts_categories_and_body_measurements_are_excluded(field, value):
    assert compare_clothing(record(), [record(**{field: value})])["matches"] == []


def test_unknown_category_needs_same_explicit_brand_and_style():
    assert len(compare_clothing(record(category="未知"), [record(category="未知")])["matches"]) == 1
    for overrides in ({"brand": ""}, {"style_code": ""}, {"brand": "另一品牌"}):
        assert compare_clothing(record(category="未知"), [record(category="未知", **overrides)])["matches"] == []


def test_same_style_priority_does_not_turn_reused_brand_codes_into_same_style():
    candidate = record()
    rows = [record(row=8, brand="另一个品牌"), record(row=9, length_cm=74)]
    matches = compare_clothing(candidate, rows)["matches"]
    assert [item["row"] for item in matches] == [9, 8]
    assert matches[1]["same_style"] is False


def test_chest_width_is_explicitly_converted_and_does_not_count_as_second_dimension():
    candidate = record(chest_cm=None, chest_width_cm=56)
    result = compare_clothing(candidate, [record()])
    chest = next(item for item in result["matches"][0]["differences"] if item["field"] == "chest_cm")
    assert chest["candidate_cm"] == 112
    assert chest["combined_tolerance_cm"] == 3
    assert any("平铺胸宽×2" in warning for warning in result["warnings"])
    chest_only = record(length_cm=None, shoulder_cm=None, sleeve_cm=None)
    assert compare_clothing(chest_only, [chest_only])["matches"] == []


def test_conflicting_chest_dimensions_are_not_silently_selected():
    candidate = record(chest_cm=111, chest_width_cm=55, shoulder_cm=None, sleeve_cm=None)
    result = compare_clothing(candidate, [record()])
    assert not result["matches"]
    assert any("不一致" in warning for warning in result["warnings"])


def test_legacy_ambiguous_chest_column_is_not_a_measurement():
    candidate = record(chest_cm=None, chest_width_cm=None, legacy_chest_width=115)
    match = compare_clothing(candidate, [record()])["matches"][0]
    assert all(item["field"] != "chest_cm" for item in match["differences"])


@pytest.mark.parametrize("basis", ["未知", "连肩袖长", ""])
def test_unknown_or_different_sleeve_basis_does_not_compare(basis):
    match = compare_clothing(record(), [record(sleeve_basis=basis)])["matches"][0]
    assert all(item["field"] != "sleeve_cm" for item in match["differences"])
    assert any("袖长测量口径" in warning for warning in match["warnings"])


def test_unknown_length_basis_is_not_made_comparable_by_identical_numbers():
    match = compare_clothing(record(length_basis="未知"), [record(length_basis="未知")])["matches"][0]
    assert all(item["field"] != "length_cm" for item in match["differences"])


def test_measurement_errors_add_and_unknown_is_not_zero_certainty():
    candidate = record(length_cm=73, measurement_tolerance_cm=2)
    known = compare_clothing(candidate, [record(measurement_tolerance_cm=1)])["matches"][0]
    length = known["differences"][0]
    assert length["within_tolerance"] is True
    assert length["combined_tolerance_cm"] == 3
    unknown = compare_clothing(candidate, [record(measurement_tolerance_cm=None)])["matches"][0]
    assert all(item["tolerance_known"] is False for item in unknown["differences"])
    assert all(item["combined_tolerance_cm"] is None for item in unknown["differences"])
    assert any("误差未知" in warning for warning in unknown["warnings"])


@pytest.mark.parametrize("overall", ["不合适", "不太合适", "可能合适", "衣长合适", "未确认", "合适但肩部偏窄"])
def test_negation_uncertainty_and_part_only_claims_never_certify_overall_fit(overall):
    result = compare_clothing(record(), [record(overall_feedback=overall)])
    assert result["matches"][0]["known_suitable"] is False
    assert "缺少同口径" in result["summary"]


def test_whole_garment_feedback_is_quoted_but_does_not_certify_separate_shell():
    old = record(feedback_scope="整件", overall_feedback="合适", shoulder_feedback="显窄", mobility_feedback="未记录")
    result = compare_clothing(record(), [old])
    match = result["matches"][0]
    assert match["known_suitable"] is False
    assert any("整件试穿 · 肩部：显窄" in item for item in match["feedback"])
    assert any("不能当成活动受限" in item for item in match["warnings"])
    assert any("不能推断" in item for item in match["warnings"])
    assert not any("偏紧" in item for item in match["feedback"])


def test_unknowns_are_explicit_and_no_records_are_invented():
    result = compare_clothing({}, [])
    assert result["matches"] == []
    assert "暂不能判断" in result["summary"]
    assert any("类别未确认" in item for item in result["unknowns"])
    assert any("活动感受" in item for item in result["unknowns"])
    assert any("不能从一件衣服" in item for item in result["warnings"])


def test_a_body_measurement_cannot_be_a_candidate_even_when_dimensions_match():
    result = compare_clothing(record(record_kind="body"), [record()])
    assert not result["matches"]
    assert any("身体测量" in item for item in result["unknowns"])


def test_length_and_chest_risks_need_matching_feedback_scope_and_known_tolerances():
    candidate = record(length_cm=75, chest_cm=104, chest_width_cm=52)
    result = compare_clothing(candidate, [record()])
    warnings = result["matches"][0]["warnings"]
    assert any("有偏长可能" in item for item in warnings)
    assert any("有偏紧可能" in item for item in warnings)
    for overrides in ({"measurement_tolerance_cm": None}, {"feedback_scope": "整件"}):
        warnings = compare_clothing(candidate, [record(**overrides)])["matches"][0]["warnings"]
        assert not any("有偏长可能" in item or "有偏紧可能" in item for item in warnings)


def test_within_error_differences_do_not_create_length_or_chest_risks():
    candidate = record(length_cm=71, chest_cm=109, chest_width_cm=54.5)
    warnings = compare_clothing(candidate, [record()])["matches"][0]["warnings"]
    assert not any("有偏长可能" in item or "有偏紧可能" in item for item in warnings)


@pytest.mark.parametrize("bad", [True, False, float("nan"), float("inf"), -1, 0, "70"])
def test_invalid_numeric_measurements_are_not_coerced(bad):
    candidate = record(length_cm=bad, shoulder_cm=bad, sleeve_cm=bad)
    assert compare_clothing(candidate, [record()])["matches"] == []


@pytest.mark.parametrize("candidate,rows", [(None, []), ({}, None), ([], [])])
def test_invalid_input_shapes_fail_explicitly(candidate, rows):
    with pytest.raises(ValueError):
        compare_clothing(candidate, rows)
