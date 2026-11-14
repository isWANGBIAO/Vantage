"""Snapshot-based clothing records backed by one existing Excel worksheet."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import threading
import zipfile
from contextlib import contextmanager, suppress
from datetime import date, datetime
from pathlib import Path

import openpyxl
from openpyxl.comments import Comment

HEADERS = (
    "衣服/款式", "试穿总体感受", "尺码", "身高", "胸宽", "胸围", "后肩衣长", "肩宽",
    "身宽（胸围一半）", "袖长", "试穿日期", "品牌", "款号", "部件", "肩部感受", "袖长感受",
    "衣长感受", "内搭/试穿方式", "来源与备注",
)
META_PREFIX = "[Vantage clothing v1]"
META_FIELDS = (
    "category", "length_basis", "sleeve_basis", "measurement_source", "measurement_tolerance_cm",
    "feedback_scope", "chest_feedback", "mobility_feedback",
)
TEXT_FIELDS = (
    "garment", "brand", "style_code", "category", "size", "component", "length_basis", "sleeve_basis",
    "measurement_source", "feedback_scope", "shoulder_feedback", "sleeve_feedback", "length_feedback",
    "chest_feedback", "mobility_feedback", "overall_feedback", "layering", "notes",
)
MEASUREMENT_FIELDS = ("length_cm", "chest_cm", "chest_width_cm", "shoulder_cm", "sleeve_cm")
_COMPONENTS = {"外壳", "内胆", "整件", "未知"}
_LOCK = threading.RLock()
_MAX_BYTES = 32 * 1024 * 1024
_MAX_ROWS = 10_000
_MAX_TEXT = 4_000


class WorkbookError(ValueError):
    """The configured workbook or submitted records cannot be used safely."""


class WorkbookConflict(WorkbookError):
    """The workbook changed since the user reviewed the current snapshot."""


class WorkbookBusy(WorkbookConflict):
    """Excel or another writer currently owns the workbook."""


def _path(value) -> Path:
    try:
        path = Path(value).expanduser().resolve(strict=True)
    except (OSError, TypeError, ValueError):
        raise WorkbookError("衣服数据文件不存在或无法读取，请检查所选Excel文件。") from None
    if path.suffix.lower() != ".xlsx" or not path.is_file():
        raise WorkbookError("请选择已有的.xlsx文件；不会自动新建或替换业务表。")
    return path


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while block := handle.read(128 * 1024):
                result.update(block)
    except OSError:
        raise WorkbookBusy("Excel文件暂不可读取；请保存并关闭Excel后重试。") from None
    return result.hexdigest()


def _assert_revision(path: Path, expected: str):
    if _digest(path) != expected:
        raise WorkbookConflict("Excel已被其他操作修改；未写入，请刷新并校对后重试。")


def _assert_not_owned(path: Path):
    if path.with_name("~$" + path.name).exists():
        raise WorkbookBusy("Excel正在打开此文件；请先保存并关闭Excel，再重新读取并保存。")


@contextmanager
def _transaction(path: Path):
    """Serialize Vantage writers across threads and processes, outside the data folder."""
    lock_root = Path(tempfile.gettempdir()) / "vantage-clothing-locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / (hashlib.sha256(os.fsencode(str(path))).hexdigest() + ".lock")
    with _LOCK, lock_path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise WorkbookBusy("另一项衣服记录保存正在进行，请稍后刷新重试。") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _snapshot(path: Path):
    try:
        if path.stat().st_size > _MAX_BYTES:
            raise WorkbookError("衣服Excel文件超过32MB，请检查所选文件。")
        with tempfile.TemporaryDirectory(prefix="vantage-clothing-") as directory:
            snapshot = Path(directory) / "snapshot.xlsx"
            before = _digest(path)
            shutil.copyfile(path, snapshot)
            _assert_revision(path, before)
            if _digest(snapshot) != before:
                raise WorkbookConflict("Excel复制期间发生变化，未使用不完整快照，请重试。")
            yield snapshot, before
    except WorkbookError:
        raise
    except OSError:
        raise WorkbookBusy("Excel快照不可用；原文件未被修改，请关闭Excel后重试。") from None


def _load(snapshot: Path, *, writable: bool = False):
    try:
        with zipfile.ZipFile(snapshot) as archive:
            entries = archive.infolist()
            if sum(item.file_size for item in entries) > _MAX_BYTES * 4 or len(entries) > 2_000:
                raise WorkbookError("Excel内容过大，不能安全读取。")
            if writable:
                unsupported = ("xl/externalLinks/", "xl/drawings/", "xl/charts/", "xl/pivot", "xl/threadedComments/",
                               "xl/activeX/", "xl/ctrlProps/", "xl/controls/", "xl/embeddings/", "xl/slicer",
                               "xl/queryTables/", "xl/connections.xml", "customXml/")
                for item in entries:
                    comment_drawing = re.fullmatch(r"xl/drawings/commentsDrawing\d+\.vml", item.filename)
                    if comment_drawing:
                        content = archive.read(item)
                        shapes = re.findall(rb"<(?:[A-Za-z_]\w*:)?shape(?=[\s>])", content)
                        note_types = re.findall(rb"<(?:[A-Za-z_]\w*:)?ClientData\b[^>]*\bObjectType=[\"']([^\"']+)", content)
                        if not shapes or len(shapes) != len(note_types) or any(kind != b"Note" for kind in note_types):
                            raise WorkbookError("此Excel包含非普通注释的VML高级结构，不能安全回写；未修改原表。")
                    if (item.filename.startswith(unsupported) and not comment_drawing) or item.filename == "xl/vbaProject.bin":
                        raise WorkbookError("此Excel包含不支持安全回写的绘图、链接或高级结构，请在Excel中维护；未修改原表。")
                    if item.filename.startswith("xl/worksheets/") and item.filename.endswith(".xml"):
                        if re.search(rb"<(?:[A-Za-z_]\w*:)?extLst\b", archive.read(item)):
                            raise WorkbookError("此Excel包含扩展工作表结构，不能安全回写；未修改原表。")
        workbook = openpyxl.load_workbook(snapshot, data_only=False, keep_links=True, rich_text=True)
    except WorkbookError:
        raise
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, SyntaxError):
        raise WorkbookError("Excel文件损坏或格式不支持；未修改原表。") from None
    if workbook.sheetnames != ["Sheet1"]:
        workbook.close()
        raise WorkbookError("衣服数据需要保留一个名为Sheet1的工作表；不会拆表或自动重建。")
    sheet = workbook["Sheet1"]
    if sheet.max_row > _MAX_ROWS or sheet.max_column > 100:
        workbook.close()
        raise WorkbookError("衣服表范围过大，请检查所选文件。")
    if writable and sheet.merged_cells.ranges:
        workbook.close()
        raise WorkbookError("衣服表含合并单元格，不能安全追加记录；请在Excel中维护。")
    return workbook


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value) and 0 < value <= 500:
        return float(value)
    return None


def _category(garment: str):
    for words, category in (
        (("冲锋衣",), "冲锋衣"), (("外套", "夹克"), "外套"), (("T恤", "T-shirt", "t恤"), "T恤"),
        (("衬衫",), "衬衫"), (("毛衣", "针织衫"), "毛衣"), (("polo", "Polo", "POLO"), "Polo衫"),
        (("裤",), "裤装"), (("裙",), "裙装"),
    ):
        if any(word in garment for word in words):
            return category
    return "未知"


def _metadata(cell, warnings):
    comment = cell.comment
    if not comment or META_PREFIX not in comment.text:
        return {}
    marker = comment.text.rfind(META_PREFIX)
    encoded = comment.text[marker + len(META_PREFIX):].strip()
    try:
        if len(encoded) > 16_000:
            raise ValueError
        metadata = json.loads(encoded)
        if not isinstance(metadata, dict):
            raise ValueError
        clean = normalize_record({key: value for key, value in metadata.items() if key in META_FIELDS})
        if "chest_circumference_confirmed" in metadata and type(metadata["chest_circumference_confirmed"]) is not bool:
            raise ValueError
        return {**{key: clean[key] for key in metadata if key in META_FIELDS},
                "chest_circumference_confirmed": metadata.get("chest_circumference_confirmed") is True}
    except (ValueError, TypeError, KeyError):
        warnings.append("记录附加口径信息损坏，已按未知处理；原注释保留。")
        return {}


def _parse_row(sheet, row):
    cells = [sheet.cell(row, column) for column in range(1, 20)]
    values = [cell.value for cell in cells]
    if not any(value is not None for value in values):
        return None
    warnings = []
    metadata = _metadata(cells[18], warnings)
    garment, overall, size = map(_text, values[:3])
    notes = _text(values[18])
    component_text = _text(values[13])
    component = "内胆" if "内胆" in component_text else component_text if component_text in _COMPONENTS else "未知"
    body_text = " ".join(map(_text, (values[3], values[6])))
    kind = "body" if not garment and not overall and re.search("本人|胸围|腰围|最新数据", body_text) else "garment" if garment or overall else "unclassified"
    chest = _number(values[5])
    if chest is not None and chest < 70 and not metadata.get("chest_circumference_confirmed"):
        chest = None
        warnings.append("F列胸围小于70cm，可能混用平铺胸宽；未擅自乘二，需确认口径。")
    if values[4] is not None:
        warnings.append("旧E列胸宽口径含混，未纳入尺寸比较。")
    width = _number(values[8])
    if isinstance(values[8], str) and values[8].upper() == f"=F{row}/2" and chest is not None:
        width = chest / 2
    sleeve = _number(values[9])
    sleeve_basis = "未知"
    if isinstance(values[9], str):
        match = re.fullmatch(r"\s*连肩袖长\s*(\d+(?:\.\d+)?)\s*(?:cm|厘米)?\s*", values[9], re.IGNORECASE)
        if match:
            sleeve = _number(float(match.group(1)))
            sleeve_basis = "连肩袖长"
    if sleeve is not None and sleeve_basis == "未知" and "sleeve_basis" not in metadata:
        warnings.append("袖长测量起点未确认，不与连肩袖长或肩点袖长混算。")
    if chest is not None and width is not None and abs(chest - width * 2) > 1:
        warnings.append("胸围与平铺胸宽不一致，请核对原表。")
    if kind != "garment":
        warnings.append("可能是身体量度或未分类行，保留展示但不作为衣服试穿比较依据。")
    feedback_scope = "整件" if "反馈针对整件试穿" in notes else "未知"
    source = "尺码截图" if "尺码截图" in notes else "历史未确认"
    tolerance_match = re.search(r"允许\s*\d+(?:\.\d+)?\s*[-–—至~]\s*(\d+(?:\.\d+)?)\s*cm", notes, re.IGNORECASE)
    tolerance = float(tolerance_match.group(1)) if tolerance_match and float(tolerance_match.group(1)) <= 20 else None
    trial_date = _text(values[10]) or None
    if trial_date is not None:
        try:
            if date.fromisoformat(trial_date).isoformat() != trial_date:
                raise ValueError
        except ValueError:
            warnings.append("原试穿日期格式不明确，未推断具体日期；原单元格保留。")
            trial_date = None
    record = {
        "row": row, "garment": garment, "brand": _text(values[11]), "style_code": _text(values[12]),
        "category": _category(garment or overall), "size": size, "component": component,
        "length_cm": _number(values[6]), "chest_cm": chest, "chest_width_cm": width,
        "shoulder_cm": _number(values[7]), "sleeve_cm": sleeve,
        "length_basis": "后肩衣长" if sheet.cell(1, 7).value == "后肩衣长" else "未知",
        "sleeve_basis": sleeve_basis, "measurement_source": source, "measurement_tolerance_cm": tolerance,
        "trial_date": trial_date, "feedback_scope": feedback_scope,
        "shoulder_feedback": _text(values[14]), "sleeve_feedback": _text(values[15]),
        "length_feedback": _text(values[16]), "chest_feedback": "", "mobility_feedback": "",
        "overall_feedback": overall, "layering": _text(values[17]), "notes": notes,
        "record_kind": kind, "raw_fields": {chr(65 + index): _text(value) if value is not None else None for index, value in enumerate(values)},
    }
    record.update(metadata)
    record["warnings"] = warnings
    return record


def _state(workbook, revision):
    sheet = workbook["Sheet1"]
    records = [record for row in range(2, sheet.max_row + 1) if (record := _parse_row(sheet, row)) is not None]
    warnings = []
    if any(_text(sheet.cell(1, column).value) != header for column, header in enumerate(HEADERS[:10], 1)):
        warnings.append("旧A:J表头与标准不完全一致，按原位置读取并保留；含混字段不会静默重写。")
    if any(record["warnings"] for record in records):
        warnings.append("部分历史记录口径不完整，请查看逐条提示；未知不代表合适或不合适。")
    return {"revision": revision, "sheet": "Sheet1", "records": records, "warnings": warnings}


def read_workbook(path) -> dict:
    resolved = _path(path)
    with _LOCK, _snapshot(resolved) as (snapshot, revision):
        workbook = _load(snapshot)
        try:
            return _state(workbook, revision)
        finally:
            workbook.close()


def normalize_record(record: dict) -> dict:
    """Validate user-reviewed fields without guessing missing measurements or fit."""
    if not isinstance(record, dict):
        raise WorkbookError("衣服记录必须是对象。")
    result = {}
    if "row" in record and record["row"] is not None:
        if type(record["row"]) is not int or not 2 <= record["row"] <= _MAX_ROWS:
            raise WorkbookError("记录行号无效。")
        result["row"] = record["row"]
    for field in TEXT_FIELDS:
        value = record.get(field, "")
        if value is None:
            value = ""
        if not isinstance(value, str) or len(value) > _MAX_TEXT or any(ord(char) < 32 and char not in "\n\r\t" for char in value):
            raise WorkbookError(f"记录字段 {field} 无效或过长。")
        result[field] = value.strip()
    for field in MEASUREMENT_FIELDS:
        value = record.get(field)
        if value is not None and _number(value) is None:
            raise WorkbookError(f"记录字段 {field} 必须为0至500之间的厘米数值或未知。")
        result[field] = float(value) if value is not None else None
    tolerance = record.get("measurement_tolerance_cm")
    if tolerance is not None and (isinstance(tolerance, bool) or not isinstance(tolerance, (int, float))
                                  or not math.isfinite(tolerance) or not 0 <= tolerance <= 20):
        raise WorkbookError("测量误差必须是0至20cm之间的数值或未知。")
    result["measurement_tolerance_cm"] = float(tolerance) if tolerance is not None else None
    for field in ("component", "feedback_scope"):
        result[field] = result[field] or "未知"
        if result[field] not in _COMPONENTS:
            raise WorkbookError(f"记录字段 {field} 必须区分外壳、内胆、整件或未知。")
    for field, allowed in (("length_basis", {"后肩衣长", "未知"}), ("sleeve_basis", {"肩点袖长", "连肩袖长", "未知"})):
        result[field] = result[field] or "未知"
        if result[field] not in allowed:
            raise WorkbookError(f"记录字段 {field} 的测量口径无效。")
    result["category"] = result["category"] or "未知"
    result["measurement_source"] = result["measurement_source"] or "未知"
    trial = record.get("trial_date")
    if trial is not None and trial != "":
        if not isinstance(trial, str):
            raise WorkbookError("试穿日期必须为YYYY-MM-DD或未知。")
        try:
            if date.fromisoformat(trial).isoformat() != trial:
                raise ValueError
        except ValueError:
            raise WorkbookError("试穿日期必须为YYYY-MM-DD或未知。") from None
        result["trial_date"] = trial
    else:
        result["trial_date"] = None
    return result


def _literal(cell, value):
    cell.value = value
    if isinstance(value, str):
        cell.data_type = "s"


def _write_metadata(cell, record):
    metadata = {key: record[key] for key in META_FIELDS}
    metadata["chest_circumference_confirmed"] = record.get("chest_circumference_confirmed") is True
    old = cell.comment.text if cell.comment else ""
    if META_PREFIX in old:
        marker = old.rfind(META_PREFIX)
        try:
            previous = json.loads(old[marker + len(META_PREFIX):].strip())
            if isinstance(previous, dict):
                if "chest_circumference_confirmed" in previous and type(previous["chest_circumference_confirmed"]) is not bool:
                    raise ValueError
                normalize_record({key: value for key, value in previous.items() if key in META_FIELDS})
                old = old[:marker].rstrip()
        except (ValueError, TypeError):
            pass  # Preserve damaged original annotations as evidence.
    encoded = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > 16_000 or len(old) > 16_000:
        raise WorkbookError("记录注释过长，不能安全保存。")
    author = cell.comment.author if cell.comment else "Vantage"
    cell.comment = Comment((old + "\n\n" if old else "") + META_PREFIX + "\n" + encoded, author)


def _apply_record(sheet, incoming):
    if incoming.get("record_kind", "garment") != "garment":
        raise WorkbookError("身体尺寸或未分类记录不能保存为衣服试穿记录。")
    record = normalize_record(incoming)
    row = record.get("row")
    existing = None
    if row is not None:
        if row > sheet.max_row or not any(sheet.cell(row, column).value is not None for column in range(1, 20)):
            raise WorkbookConflict("选中的记录已不存在，请刷新后重试。")
        existing = _parse_row(sheet, row)
        if existing["record_kind"] != "garment":
            raise WorkbookError("此行不是已确认的衣服记录，不能通过试穿页面修改。")
        for key in (*MEASUREMENT_FIELDS, "garment", "size", "brand", "style_code", "category", "component",
                    "length_basis", "sleeve_basis", "measurement_source", "measurement_tolerance_cm"):
            if key in incoming and record[key] != existing[key]:
                raise WorkbookError("历史行的原始尺寸、款式和尺码不能覆盖；尺寸校正请另存为新记录。")
        # Omitted feedback fields preserve values rather than clearing unrelated history.
        merged = {**existing, **{key: record[key] for key in incoming if key in record}}
        record = normalize_record(merged)
        record["chest_circumference_confirmed"] = existing.get("chest_circumference_confirmed") is True
    else:
        if not record["garment"] or not record["size"]:
            raise WorkbookError("新记录至少需要衣服款式与尺码。")
        row = sheet.max_row + 1
        record["chest_circumference_confirmed"] = record["chest_cm"] is not None
        if row > _MAX_ROWS:
            raise WorkbookError("衣服记录数量已达到上限。")
        for column, field in ((1, "garment"), (3, "size"), (6, "chest_cm"), (7, "length_cm"),
                              (8, "shoulder_cm"), (9, "chest_width_cm"), (10, "sleeve_cm")):
            _literal(sheet.cell(row, column), record[field])
        if record["chest_width_cm"] is None and record["chest_cm"] is not None:
            sheet.cell(row, 9, f"=F{row}/2")
        if record["sleeve_cm"] is not None and record["sleeve_basis"] == "连肩袖长":
            _literal(sheet.cell(row, 10), f"连肩袖长{record['sleeve_cm']:g}")
    for column, field in ((2, "overall_feedback"), (11, "trial_date"), (12, "brand"), (13, "style_code"),
                          (14, "component"), (15, "shoulder_feedback"), (16, "sleeve_feedback"),
                          (17, "length_feedback"), (18, "layering"), (19, "notes")):
        if existing is None or record[field] != existing[field]:
            _literal(sheet.cell(row, column), record[field])
    _write_metadata(sheet.cell(row, 19), record)


def _publish(path: Path, staged: Path, revision: str):
    _assert_not_owned(path)
    _assert_revision(path, revision)
    try:
        os.replace(staged, path)
    except OSError:
        raise WorkbookBusy("Excel文件被占用或无法写入，原表未替换；请关闭Excel后刷新重试。") from None


def save_records(path, records: list[dict], expected_revision: str) -> dict:
    resolved = _path(path)
    if not isinstance(expected_revision, str) or re.fullmatch(r"[0-9a-f]{64}", expected_revision) is None:
        raise WorkbookConflict("缺少有效的Excel版本，请先刷新记录。")
    if not isinstance(records, list) or not 1 <= len(records) <= 100:
        raise WorkbookError("每次需要保存1至100条已校对记录。")
    for record in records:
        normalize_record(record)
    rows = [record.get("row") for record in records if isinstance(record, dict) and record.get("row") is not None]
    if len(rows) != len(set(rows)):
        raise WorkbookError("同一次保存不能重复修改同一行。")
    with _transaction(resolved):
        _assert_not_owned(resolved)
        with _snapshot(resolved) as (snapshot, revision):
            if revision != expected_revision:
                raise WorkbookConflict("Excel已被其他操作修改；未写入，请刷新并校对后重试。")
            workbook = _load(snapshot, writable=True)
            staged = None
            try:
                sheet = workbook["Sheet1"]
                anchors = ((3, "尺码"), (7, "衣长"), (8, "肩宽"), (10, "袖长"))
                if sum(label in _text(sheet.cell(1, column).value) for column, label in anchors) < 3:
                    raise WorkbookError("A:J不符合已知衣服表布局，不能安全回写；请选择正确的数据源。")
                for column, header in enumerate(HEADERS[10:], 11):
                    existing = sheet.cell(1, column).value
                    if existing is None:
                        _literal(sheet.cell(1, column), header)
                    elif existing != header:
                        raise WorkbookError("K:S字段位置与预期不符，不能安全回写；请先核对表头。")
                for record in records:
                    _apply_record(sheet, record)
                descriptor, filename = tempfile.mkstemp(prefix=".vantage-clothing-", suffix=".xlsx", dir=resolved.parent)
                os.close(descriptor)
                staged = Path(filename)
                workbook.save(staged)
                # Check that the new workbook is readable before any publication.
                checked = _load(staged)
                checked.close()
                new_revision = _digest(staged)
                _publish(resolved, staged, revision)
                staged = None
                return _state(workbook, new_revision)
            except WorkbookError:
                raise
            except (OSError, ValueError, TypeError):
                raise WorkbookError("衣服记录保存失败；未替换原表，请刷新后重试。") from None
            finally:
                workbook.close()
                if staged is not None:
                    with suppress(OSError):
                        staged.unlink(missing_ok=True)
