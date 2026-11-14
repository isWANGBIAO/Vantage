"""Local, evidence-limited clothing measurements and trial comparison.

This module performs no model calls and never persists the supplied records.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping


_UNKNOWN = {"", "未知", "未记录", "未说明", "未确认", "未单独确认", "不详", "unknown", "none"}
_COMPONENTS = {"外壳": "外壳", "壳": "外壳", "内胆": "内胆", "抓绒内胆": "内胆", "整件": "整件"}
_METRICS = (
    ("length_cm", "衣长", "length_basis", {"后肩衣长"}),
    ("chest_cm", "胸围", None, None),
    ("shoulder_cm", "肩宽", None, None),
    ("sleeve_cm", "袖长", "sleeve_basis", {"肩点袖长", "连肩袖长"}),
)
_FEEDBACK = (
    ("overall_feedback", "总体"),
    ("shoulder_feedback", "肩部"),
    ("chest_feedback", "胸部"),
    ("sleeve_feedback", "袖长"),
    ("length_feedback", "衣长"),
    ("mobility_feedback", "活动"),
)


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _key(value) -> str:
    return unicodedata.normalize("NFKC", _text(value)).casefold()


def _known(value) -> bool:
    return _key(value) not in _UNKNOWN


def _number(value, *, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0 or (not allow_zero and number == 0):
        return None
    return number


def _component(record) -> str:
    return _COMPONENTS.get(_text(record.get("component")), "未知")


def _tolerance(record):
    return _number(record.get("measurement_tolerance_cm"), allow_zero=True)


def _measurements(record):
    """One chest dimension only; a confirmed flat width is explicitly doubled."""
    values = {field: _number(record.get(field)) for field, *_ in _METRICS}
    tolerance = _tolerance(record)
    tolerances = {field: tolerance for field in values}
    warnings = []
    chest, width = values["chest_cm"], _number(record.get("chest_width_cm"))
    if chest is not None and width is not None and abs(chest - width * 2) > 0.01:
        values["chest_cm"] = None
        warnings.append("胸围与平铺胸宽×2不一致，胸部尺寸暂不参与比较，请先校对。")
    elif chest is None and width is not None:
        values["chest_cm"] = width * 2
        tolerances["chest_cm"] = tolerance * 2 if tolerance is not None else None
        warnings.append("胸围由明确标注的平铺胸宽×2换算；不是把含糊的旧“胸宽”列直接当胸围。")
    return values, tolerances, warnings


def _compatible(candidate, historical):
    component = _component(candidate)
    if component == "未知" or component != _component(historical):
        return False, False, []
    candidate_brand, old_brand = candidate.get("brand"), historical.get("brand")
    same_style = (
        _known(candidate.get("style_code")) and _known(historical.get("style_code"))
        and _key(candidate["style_code"]) == _key(historical["style_code"])
        and _known(candidate_brand) and _known(old_brand)
        and _key(candidate_brand) == _key(old_brand)
    )
    categories_known = _known(candidate.get("category")) and _known(historical.get("category"))
    same_category = categories_known and _key(candidate["category"]) == _key(historical["category"])
    # A reused style code at another brand is never same-style evidence. Known
    # contradictory categories also require correction instead of trusting IDs.
    if categories_known and not same_category:
        return False, False, []
    if not same_style and not same_category:
        return False, False, []
    warnings = []
    if not categories_known:
        warnings.append("类别未确认，仅按明确相同品牌与款号作同款尺寸参考。")
    if not same_style:
        warnings.append("这不是同款比较；相同类别也可能因版型、面料或内搭而不同。")
    return True, same_style, warnings


def _basis_agrees(candidate, historical, key, allowed):
    if key is None:
        return True
    return candidate.get(key) in allowed and candidate.get(key) == historical.get(key)


def _feedback(record):
    scope = _text(record.get("feedback_scope")) or "未知"
    result = []
    date = _text(record.get("trial_date"))
    prefix = f"{date} · " if date else ""
    for key, label in _FEEDBACK:
        value = _text(record.get(key))
        if _known(value):
            result.append(f"{prefix}{scope}试穿 · {label}：{value}")
    layering = _text(record.get("layering"))
    if _known(layering):
        result.append(f"内搭/试穿方式：{layering}")
    return result


def _known_suitable(record):
    scope = _COMPONENTS.get(_text(record.get("feedback_scope")), "未知")
    if scope == "未知" or scope != _component(record):
        return False
    # A statement about one dimension cannot certify the whole garment. Do not
    # search for the substring "合适" inside negation or uncertainty.
    overall = re.sub(r"[\s，,。.!！]", "", _text(record.get("overall_feedback")))
    if not re.fullmatch(r"(?:(?:整体|整件|总体|试穿|穿着))?(?:很|非常|挺|比较)?(?:合适|正好|刚刚好)", overall):
        return False
    for key, _ in _FEEDBACK:
        value = _text(record.get(key))
        if re.search(r"不(?:太|怎么)?合适|未(?:确认|说明)|可能|显窄|偏[长短紧小大窄宽]|太[长短紧小大]|受限|勒|不舒服", value):
            return False
    return True


def _fit_risks(record, differences):
    scope = _COMPONENTS.get(_text(record.get("feedback_scope")), "未知")
    if scope == "未知" or scope != _component(record):
        return []
    result = []
    for item in differences:
        if not item["tolerance_known"] or item["within_tolerance"]:
            continue
        field, delta = item["field"], item["delta_cm"]
        if field == "length_cm" and delta > 0 and (
            _known_suitable(record) or _text(record.get("length_feedback")) in {"合适", "正好", "刚刚好", "偏长"}
        ):
            result.append(f"新衣服衣长比这条已记录试穿感受的样本长{delta:g}cm，有偏长可能；版型和穿着条件不同仍需实穿确认。")
        if field == "chest_cm" and delta < 0 and (
            _known_suitable(record) or _text(record.get("chest_feedback")) in {"合适", "正好", "刚刚好", "偏紧"}
        ):
            result.append(f"新衣服胸围比这条已记录试穿感受的样本小{abs(delta):g}cm，有偏紧可能；面料弹性和内搭不同仍需实穿确认。")
    return result


def _candidate_unknowns(candidate):
    result = []
    if not _known(candidate.get("category")):
        result.append("新衣服的类别未确认；不能仅凭尺码字母跨类别比较。")
    if _component(candidate) == "未知":
        result.append("新尺码属于外壳、内胆还是整件未确认，暂不与其他部件比较。")
    if not _known(candidate.get("style_code")):
        result.append("款号未知，无法确认是否为同一具体款式。")
    if _tolerance(candidate) is None:
        result.append("新尺码表的测量误差未记录，不能把数值差异直接判为真实差异。")
    values, _, _ = _measurements(candidate)
    for field, label, basis_key, allowed in _METRICS:
        if values[field] is None:
            result.append(f"新衣服的{label}缺失或口径冲突。")
        elif basis_key and candidate.get(basis_key) not in allowed:
            result.append(f"新衣服的{label}测量口径未确认，此项暂不比较。")
    if not _known(candidate.get("layering")):
        result.append("内搭/试穿方式未记录，无法评估内搭对松紧感的影响。")
    if not _known(candidate.get("mobility_feedback")):
        result.append("尚无新衣服的活动感受；肩部显窄不等于偏紧或活动受限。")
    return result


def compare_clothing(candidate: dict, records: list[dict]) -> dict:
    """Compare reviewed centimetre measurements, keeping fit claims scoped."""
    if not isinstance(candidate, Mapping) or not isinstance(records, list):
        raise ValueError("candidate must be an object and records must be a list")
    if candidate.get("record_kind") in {"body", "unclassified"}:
        return {
            "summary": "新记录不是已确认的衣服尺寸，暂不能与衣服试穿历史比较。",
            "matches": [], "unknowns": ["请先确认这是衣服尺寸，而非身体测量或未分类记录。"],
            "warnings": ["身体尺寸不能直接当作衣服成衣尺寸。"],
        }
    values, tolerances, candidate_warnings = _measurements(candidate)
    matches = []
    skipped = 0
    for historical in records:
        if not isinstance(historical, Mapping) or historical.get("record_kind") in {"body", "unclassified"}:
            skipped += 1
            continue
        compatible, same_style, warnings = _compatible(candidate, historical)
        if not compatible:
            skipped += 1
            continue
        old_values, old_tolerances, old_warnings = _measurements(historical)
        warnings.extend(old_warnings)
        differences = []
        for field, label, basis_key, allowed in _METRICS:
            if values[field] is None or old_values[field] is None:
                continue
            if not _basis_agrees(candidate, historical, basis_key, allowed):
                warnings.append(f"{label}测量口径未知或不同，此项未比较。")
                continue
            delta = values[field] - old_values[field]
            left_tolerance, right_tolerance = tolerances[field], old_tolerances[field]
            tolerance_known = left_tolerance is not None and right_tolerance is not None
            combined = left_tolerance + right_tolerance if tolerance_known else None
            differences.append({
                "field": field, "label": label, "candidate_cm": values[field], "history_cm": old_values[field],
                "delta_cm": round(delta, 4), "within_tolerance": tolerance_known and abs(delta) <= combined,
                "tolerance_known": tolerance_known, "combined_tolerance_cm": combined,
            })
        if len(differences) < 2:
            skipped += 1
            continue
        if any(not item["tolerance_known"] for item in differences):
            warnings.append("至少一方的测量误差未知；这些差值不能用于确认显著差异或保证合身。")
        warnings.extend(_fit_risks(historical, differences))
        if historical.get("feedback_scope") != historical.get("component"):
            warnings.append("历史反馈针对整件或未确认范围，不能推断此外壳/内胆单独试穿合适。")
        if not _known(historical.get("mobility_feedback")):
            warnings.append("历史活动感受未记录；肩部显窄只描述外观，不能当成活动受限。")
        if not _known(historical.get("layering")):
            warnings.append("历史内搭/试穿方式未知，实际松紧不可直接外推。")
        if not _known(historical.get("measurement_source")):
            warnings.append("历史尺寸来源未确认，需先核对原始测量。")
        inherited_warnings = historical.get("warnings")
        if isinstance(inherited_warnings, list):
            warnings.extend(item for item in inherited_warnings if isinstance(item, str))
        result = {key: historical.get(key) for key in ("row", "garment", "brand", "style_code", "size", "component", "category")}
        result.update({
            "known_suitable": _known_suitable(historical),
            "score": round(sum(abs(item["delta_cm"]) for item in differences) / len(differences), 4),
            "same_style": same_style, "differences": differences, "feedback": _feedback(historical),
            "warnings": list(dict.fromkeys(warnings)),
        })
        matches.append(result)
    matches.sort(key=lambda item: (not item["same_style"], item["score"], str(item["row"])))
    suitable = next((item for item in matches if item["known_suitable"]), None)
    if suitable:
        summary = (f"在可比较的已知合适试穿记录中，最接近的是第{suitable['row']}行"
                   f"「{suitable.get('garment') or '未命名衣服'}」{suitable.get('size') or ''}。"
                   "这是尺寸接近的参考，不是新衣服合身的保证；请逐项核对差值与试穿条件。")
    elif matches:
        summary = ("找到同款或同类别、同部件的尺寸参考，但缺少同口径且明确合适的试穿证据。"
                   "不能仅凭最接近的尺寸确认合身，请保留已记录的偏长/肩部外观等原话与未知项。")
    else:
        summary = "暂无至少两个可比尺寸的同款/同类别、同部件历史记录，暂不能判断接近哪件合适衣服。"
    unknowns = _candidate_unknowns(candidate)
    if not suitable:
        unknowns.append("缺少范围明确、同口径且总体合适的历史试穿样本。")
    if skipped:
        unknowns.append(f"{skipped}条记录因部件、类别、测量口径或有效尺寸不足而未参与排名；原记录未改动。")
    return {
        "summary": summary, "matches": matches,
        "unknowns": list(dict.fromkeys(unknowns)),
        "warnings": list(dict.fromkeys([*candidate_warnings, "只比较具体记录，不能从一件衣服推断某品牌永远穿M或L。"])),
    }
