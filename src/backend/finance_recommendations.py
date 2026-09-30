"""Purchase recommendation generation, caching, dismissals, and HTTP routes."""

import asyncio
import copy
import hashlib
import json
import logging
import math
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.core.config import Config
from src.services.llm_client import LLMClient
from src.utils.data_loader import DataLoader

from . import chat as _chat

router = APIRouter()

class PurchaseRecommendationDismissRequest(BaseModel):
    cache_key: Optional[str] = None
    group_key: Optional[str] = None
    item: Optional[dict] = None

class PurchaseRecommendationRequest(BaseModel):
    recommendation_count: Optional[int] = None
    model: Optional[str] = None
    provider_route: Optional[str] = None
    reasoning_effort: Optional[str] = None
    service_tier: Optional[str] = None

PURCHASE_RECOMMENDATION_GROUPS = [
    ("practical", "实用补缺"),
    ("night_guard", "夜间防冲动"),
    ("wishlist", "愿望清单"),
]

PURCHASE_RECOMMENDATION_CACHE_DIR = "balance_sheet_purchase_recommendations"

PURCHASE_RECOMMENDATION_PROMPT_VERSION = 4

DEFAULT_PURCHASE_RECOMMENDATION_COUNT = 12

MIN_PURCHASE_RECOMMENDATION_COUNT = 3

MAX_PURCHASE_RECOMMENDATION_COUNT = 30

PURCHASE_CONTEXT_TIME_SERIES_DAYS = 90

PURCHASE_CONTEXT_TIME_SERIES_START_DATE = None

PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL = "contextual"

PURCHASE_RECOMMENDATION_MODE_RANDOM = "random"

PURCHASE_RECOMMENDATION_MODES = {
    PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL,
    PURCHASE_RECOMMENDATION_MODE_RANDOM,
}

def _purchase_recommendation_cache_dir():
    cache_dir = Path(Config.get_cache_dir()) / PURCHASE_RECOMMENDATION_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "covers").mkdir(parents=True, exist_ok=True)
    return cache_dir

def _stable_json_hash(payload):
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def _purchase_recommendation_cache_key(prompt_payload, request_config=None, context_hash=None, dismissed_hash=None):
    cache_payload = {
        "prompt_version": PURCHASE_RECOMMENDATION_PROMPT_VERSION,
        "balance_sheet": prompt_payload,
        "request_config": request_config or {},
        "context_hash": context_hash or "",
        "dismissed_hash": dismissed_hash or "",
    }
    return _stable_json_hash(cache_payload)

def _purchase_recommendation_cache_file(cache_key):
    return _purchase_recommendation_cache_dir() / f"{cache_key}.json"

def _purchase_recommendation_db_path():
    history_dir = Path(Config.get_history_dir())
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir / "state.db"

def _normalize_purchase_text_key(value):
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())

def _purchase_dismissal_key(group_key, item_name):
    group_part = _normalize_purchase_text_key(group_key)
    name_part = _normalize_purchase_text_key(item_name)
    return hashlib.sha256(f"{group_part}|{name_part}".encode("utf-8")).hexdigest()

def _normalize_purchase_recommendation_count(value=None):
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = DEFAULT_PURCHASE_RECOMMENDATION_COUNT
    return max(MIN_PURCHASE_RECOMMENDATION_COUNT, min(MAX_PURCHASE_RECOMMENDATION_COUNT, count))

def _normalize_purchase_group_limit(value=None):
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = DEFAULT_PURCHASE_RECOMMENDATION_COUNT
    return max(0, min(MAX_PURCHASE_RECOMMENDATION_COUNT, count))

def _purchase_recommendation_mode_counts(recommendation_count):
    total_count = _normalize_purchase_group_limit(recommendation_count)
    random_count = math.ceil(total_count / 2)
    return {
        PURCHASE_RECOMMENDATION_MODE_RANDOM: random_count,
        PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL: total_count - random_count,
    }

def _normalize_purchase_recommendation_mode(value=None, default=PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL):
    mode = str(value or default or PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL).strip().lower()
    if mode not in PURCHASE_RECOMMENDATION_MODES:
        return PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL
    return mode

def _normalize_purchase_request_config(config=None):
    source = config if isinstance(config, dict) else {}
    model = str(source.get("model") or "").strip() or None
    provider_route = str(source.get("provider_route") or "").strip() or None
    reasoning_effort = _chat._normalize_reasoning_effort(source.get("reasoning_effort"))
    service_tier = _chat._normalize_service_tier(source.get("service_tier"))
    return {
        "recommendation_count": _normalize_purchase_recommendation_count(source.get("recommendation_count")),
        "model": model,
        "provider_route": provider_route,
        "reasoning_effort": reasoning_effort,
        "service_tier": service_tier,
    }

def _build_purchase_recommendations_unavailable_payload(path, error, request_config=None):
    request_config = _normalize_purchase_request_config(request_config)
    error_text = str(error)
    return {
        "status": "unavailable",
        "from_cache": False,
        "cache_key": "",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "text_model": None,
        "request_config": request_config,
        "source": {
            "path": str(path or "Balance Sheet.xlsx"),
            "available": False,
            "error": error_text,
        },
        "context": {
            "time_xlsx_included": False,
            "balance_sheet_included": False,
            "prompt_hash": "",
        },
        "recommendation_mix_requested": _purchase_recommendation_mode_counts(
            request_config["recommendation_count"],
        ),
        "recommendation_mix": {
            PURCHASE_RECOMMENDATION_MODE_RANDOM: {"requested": 0, "actual": 0},
            PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL: {"requested": 0, "actual": 0},
        },
        "recommendation_groups": [
            {"key": key, "title": title, "items": []}
            for key, title in PURCHASE_RECOMMENDATION_GROUPS
        ],
        "recommendation_count_requested": request_config["recommendation_count"],
        "recommendation_count_actual": 0,
        "recommendation_count_underfilled": False,
        "dismissed_count": 0,
        "usage": {
            PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL: None,
            PURCHASE_RECOMMENDATION_MODE_RANDOM: None,
        },
        "response_raw": {},
        "error": error_text,
    }

def _purchase_dismissed_hash(dismissed_items):
    simplified = [
        {
            "id": item.get("id"),
            "group_key": item.get("group_key", ""),
            "name": item.get("name", ""),
            "category": item.get("category", ""),
        }
        for item in (dismissed_items or [])
    ]
    return _stable_json_hash(simplified)

def _ensure_purchase_recommendation_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS purchase_recommendation_dismissals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dismissal_key TEXT NOT NULL UNIQUE,
            name_key TEXT NOT NULL,
            group_key TEXT NOT NULL,
            cache_key TEXT,
            name TEXT NOT NULL,
            category TEXT,
            estimated_price TEXT,
            reason TEXT,
            evidence TEXT,
            duplicate_check TEXT,
            impulse_risk TEXT,
            item_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_purchase_dismissals_name_key
        ON purchase_recommendation_dismissals (name_key)
        """
    )
    conn.commit()

def _connect_purchase_recommendation_db():
    conn = sqlite3.connect(_purchase_recommendation_db_path())
    conn.row_factory = sqlite3.Row
    _ensure_purchase_recommendation_schema(conn)
    return conn

def _dismissed_purchase_row_to_item(row):
    try:
        item_json = json.loads(row["item_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        item_json = {}
    return {
        "id": row["id"],
        "cache_key": row["cache_key"] or "",
        "group_key": row["group_key"] or "",
        "name": row["name"] or "",
        "category": row["category"] or "",
        "estimated_price": row["estimated_price"] or "",
        "reason": row["reason"] or "",
        "evidence": row["evidence"] or "",
        "duplicate_check": row["duplicate_check"] or "",
        "impulse_risk": row["impulse_risk"] or "",
        "recommendation_mode": _normalize_purchase_recommendation_mode(item_json.get("recommendation_mode")),
        "created_at": row["created_at"] or "",
    }

def _list_dismissed_purchase_items():
    with closing(_connect_purchase_recommendation_db()) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM purchase_recommendation_dismissals
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
    return [_dismissed_purchase_row_to_item(row) for row in rows]

def _build_purchase_dismissed_payload():
    items = _list_dismissed_purchase_items()
    return {"items": items, "count": len(items)}

def _record_purchase_recommendation_dismissal(cache_key, group_key, item):
    normalized_item = _normalize_purchase_item(item)
    name = normalized_item["name"]
    if not name:
        raise ValueError("Recommendation item name is required.")
    normalized_group = str(group_key or "").strip() or "unknown"
    name_key = _normalize_purchase_text_key(name)
    dismissal_key = _purchase_dismissal_key(normalized_group, name)
    created_at = datetime.now().isoformat(timespec="seconds")
    with closing(_connect_purchase_recommendation_db()) as conn:
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO purchase_recommendation_dismissals (
                dismissal_key,
                name_key,
                group_key,
                cache_key,
                name,
                category,
                estimated_price,
                reason,
                evidence,
                duplicate_check,
                impulse_risk,
                item_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dismissal_key,
                name_key,
                normalized_group,
                str(cache_key or "").strip(),
                name,
                normalized_item["category"],
                normalized_item["estimated_price"],
                normalized_item["reason"],
                normalized_item["evidence"],
                normalized_item["duplicate_check"],
                normalized_item["impulse_risk"],
                json.dumps(normalized_item, ensure_ascii=False, separators=(",", ":")),
                created_at,
            ),
        )
        created = conn.total_changes > before
        conn.commit()
        row = conn.execute(
            """
            SELECT *
            FROM purchase_recommendation_dismissals
            WHERE dismissal_key = ?
            """,
            (dismissal_key,),
        ).fetchone()
    payload = _build_purchase_dismissed_payload()
    item_payload = _dismissed_purchase_row_to_item(row) if row else {**normalized_item, "group_key": normalized_group}
    return {"ok": True, "created": created, "count": payload["count"], "item": item_payload}

def _clear_purchase_recommendation_dismissals():
    with closing(_connect_purchase_recommendation_db()) as conn:
        conn.execute("DELETE FROM purchase_recommendation_dismissals")
        conn.commit()
    return {"ok": True, "items": [], "count": 0}

def _delete_purchase_recommendation_dismissal(item_id):
    try:
        normalized_id = int(item_id)
    except (TypeError, ValueError):
        # The conversion failure is not useful to the caller; report only that
        # the id was not an integer.
        raise ValueError("Dismissed recommendation id must be an integer.") from None
    with closing(_connect_purchase_recommendation_db()) as conn:
        conn.execute("DELETE FROM purchase_recommendation_dismissals WHERE id = ?", (normalized_id,))
        conn.commit()
    payload = _build_purchase_dismissed_payload()
    return {"ok": True, "items": payload["items"], "count": payload["count"]}

def _filter_dismissed_purchase_groups(groups, dismissed_items):
    dismissed_name_keys = {
        _normalize_purchase_text_key(item.get("name"))
        for item in (dismissed_items or [])
        if item.get("name")
    }
    dismissed_category_keys = {
        _normalize_purchase_text_key(item.get("category"))
        for item in (dismissed_items or [])
        if item.get("category")
    }
    if not dismissed_name_keys and not dismissed_category_keys:
        return groups
    filtered_groups = []
    for group in groups or []:
        next_group = copy.deepcopy(group)
        kept_items = []
        for item in next_group.get("items") or []:
            name_key = _normalize_purchase_text_key(item.get("name"))
            category_key = _normalize_purchase_text_key(item.get("category"))
            same_name = name_key in dismissed_name_keys
            similar_name = any(
                dismissed_name
                and name_key
                and (dismissed_name in name_key or name_key in dismissed_name)
                for dismissed_name in dismissed_name_keys
            )
            same_category = category_key in dismissed_category_keys
            if same_name or similar_name or same_category:
                continue
            kept_items.append(item)
        next_group["items"] = kept_items
        filtered_groups.append(next_group)
    return filtered_groups

def _count_purchase_recommendation_items(groups):
    return sum(len(group.get("items") or []) for group in (groups or []))

def _count_purchase_recommendation_items_by_mode(groups):
    counts = {
        PURCHASE_RECOMMENDATION_MODE_RANDOM: 0,
        PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL: 0,
    }
    for group in groups or []:
        for item in group.get("items") or []:
            mode = _normalize_purchase_recommendation_mode(item.get("recommendation_mode"))
            counts[mode] += 1
    return counts

def _build_purchase_recommendation_mix(requested_counts, groups):
    requested_counts = requested_counts if isinstance(requested_counts, dict) else {}
    actual_counts = _count_purchase_recommendation_items_by_mode(groups)
    return {
        PURCHASE_RECOMMENDATION_MODE_RANDOM: {
            "requested": int(requested_counts.get(PURCHASE_RECOMMENDATION_MODE_RANDOM) or 0),
            "actual": actual_counts[PURCHASE_RECOMMENDATION_MODE_RANDOM],
        },
        PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL: {
            "requested": int(requested_counts.get(PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL) or 0),
            "actual": actual_counts[PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL],
        },
    }

def _purchase_recommendation_mix_underfilled(mix):
    return any(
        (entry.get("actual") or 0) < (entry.get("requested") or 0)
        for entry in (mix or {}).values()
        if isinstance(entry, dict)
    )

def _with_dismissed_purchase_filter(payload, dismissed_items=None):
    dismissed_items = dismissed_items if dismissed_items is not None else _list_dismissed_purchase_items()
    next_payload = copy.deepcopy(payload)
    next_payload["dismissed_count"] = len(dismissed_items)
    next_payload["recommendation_groups"] = _filter_dismissed_purchase_groups(
        next_payload.get("recommendation_groups") or [],
        dismissed_items,
    )
    requested_count = _normalize_purchase_recommendation_count(
        next_payload.get("recommendation_count_requested")
        or (next_payload.get("request_config") or {}).get("recommendation_count")
        or next_payload.get("recommendation_count")
    )
    actual_count = _count_purchase_recommendation_items(next_payload.get("recommendation_groups") or [])
    requested_mix = next_payload.get("recommendation_mix_requested") or _purchase_recommendation_mode_counts(requested_count)
    next_payload["recommendation_mix"] = _build_purchase_recommendation_mix(
        requested_mix,
        next_payload.get("recommendation_groups") or [],
    )
    next_payload["recommendation_count_requested"] = requested_count
    next_payload["recommendation_count_actual"] = actual_count
    next_payload["recommendation_count_underfilled"] = (
        actual_count < requested_count or _purchase_recommendation_mix_underfilled(next_payload["recommendation_mix"])
    )
    return next_payload

def _read_purchase_recommendation_cache_payload(cache_key):
    cache_file = _purchase_recommendation_cache_file(cache_key)
    if not cache_file.exists():
        return None
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("cache_key") != cache_key:
        return None
    return payload

def _load_purchase_recommendation_cache(cache_key):
    payload = _read_purchase_recommendation_cache_payload(cache_key)
    if payload is None:
        return None
    payload["from_cache"] = True
    return payload

def _save_purchase_recommendation_cache(payload):
    cache_file = _purchase_recommendation_cache_file(payload["cache_key"])
    cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def _extract_json_object_from_text(text):
    value = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", value, re.IGNORECASE)
    if fenced:
        value = fenced.group(1)
    else:
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end > start:
            value = value[start : end + 1]
    return json.loads(value)

def _normalize_purchase_item(item, recommendation_mode=None):
    source = item if isinstance(item, dict) else {}
    item_mode = _normalize_purchase_recommendation_mode(
        source.get("recommendation_mode") or source.get("mode"),
        default=recommendation_mode or PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL,
    )
    return {
        "name": str(source.get("name") or "").strip(),
        "category": str(source.get("category") or "").strip(),
        "estimated_price": str(source.get("estimated_price") or source.get("price") or "").strip(),
        "reason": str(source.get("reason") or "").strip(),
        "evidence": str(source.get("evidence") or "").strip(),
        "duplicate_check": str(source.get("duplicate_check") or "").strip(),
        "impulse_risk": str(source.get("impulse_risk") or "").strip(),
        "recommendation_mode": item_mode,
    }

def _trim_purchase_groups_to_total(groups, recommendation_count):
    target_count = _normalize_purchase_group_limit(recommendation_count)
    while sum(len(group.get("items") or []) for group in groups) > target_count:
        removable = [
            (len(group.get("items") or []), index)
            for index, group in enumerate(groups)
            if group.get("items")
        ]
        if not removable:
            break
        _size, group_index = max(removable, key=lambda item: (item[0], item[1]))
        groups[group_index]["items"].pop()
    return groups

def _normalize_purchase_recommendation_groups(raw_groups, recommendation_count=None, recommendation_mode=None):
    by_key = {}
    if isinstance(raw_groups, list):
        for group in raw_groups:
            if isinstance(group, dict) and group.get("key"):
                by_key[str(group.get("key"))] = group
    elif isinstance(raw_groups, dict):
        for key, value in raw_groups.items():
            if isinstance(value, dict):
                by_key[str(key)] = {"key": key, **value}
            elif isinstance(value, list):
                by_key[str(key)] = {"key": key, "items": value}

    groups = []
    for key, title in PURCHASE_RECOMMENDATION_GROUPS:
        group = by_key.get(key) or {}
        items = group.get("items") if isinstance(group, dict) else []
        normalized_items = [
            _normalize_purchase_item(item, recommendation_mode=recommendation_mode)
            for item in (items if isinstance(items, list) else [])
        ]
        groups.append({
            "key": key,
            "title": str(group.get("title") or title).strip(),
            "items": [item for item in normalized_items if item.get("name")],
        })
    return _trim_purchase_groups_to_total(groups, recommendation_count)

def _build_purchase_recommendation_messages(context_prompt, dismissed_items=None, recommendation_count=None):
    if not isinstance(context_prompt, str):
        context_prompt = (
            "## Balance Sheet Data (JSON)\n\n```json\n"
            f"{json.dumps(context_prompt, ensure_ascii=False, separators=(',', ':'), default=str)}\n```"
        )
    total_count = _normalize_purchase_group_limit(recommendation_count)
    dismissed_payload = [
        {
            "name": item.get("name", ""),
            "category": item.get("category", ""),
            "group_key": item.get("group_key", ""),
            "reason": item.get("reason", ""),
            "evidence": item.get("evidence", ""),
            "duplicate_check": item.get("duplicate_check", ""),
            "impulse_risk": item.get("impulse_risk", ""),
        }
        for item in (dismissed_items or [])
    ]
    dismissed_json = json.dumps(dismissed_payload, ensure_ascii=False, separators=(",", ":"))
    system_prompt = (
        "你是一个克制、具体、讲证据的个人购物建议助手。"
        "必须同时使用 Time.xlsx 行为/健康/计划上下文、Balance Sheet 财务数据、个人目标、库存和已排除推荐。"
        "不要推荐已明显买过、资产中已有、功能重复，或用户已经打叉排除的物品。"
        "如果个人资源、项目资源或历史记录中出现了某个设备/资产，但 Balance Sheet 的 Asset 表未记录，"
        "必须把它视为“Asset 可能缺漏/待核实补录”，而不是新的购买需求。"
        "只输出 JSON，不要 Markdown。"
    )
    # The context bundle is the bulk of this prompt and is read-only between
    # edits, so it goes first. The instructions that embed the varying count and
    # dismissed list follow it, so a changed count or dismissal only invalidates
    # the trailing block instead of the whole cached payload.
    user_prompt = (
        f"Context bundle from Action Plan data sources:\n{context_prompt}\n\n"
        "输出结构必须是 JSON object，只包含 recommendation_groups。"
        "recommendation_groups 必须包含 key=practical/night_guard/wishlist 三组。"
        "每个 item 必须包含 name、category、estimated_price、reason、evidence、duplicate_check、impulse_risk、recommendation_mode。"
        "recommendation_mode 必须固定为 contextual。\n"
        "已排除购物推荐 / dismissed purchase recommendations JSON 表示用户已经打叉、不想再看到的方向。"
        "不要推荐同名、近似同类、功能重复的物品；如果排除项是一个品类，也要避开同用途替代品。\n"
        "购物策略：实用补缺优先找已有资产和预算结构中的缺口；夜间防冲动优先给低价、延迟消费、减少失眠冲动的工具；"
        "愿望清单可以更贵，但必须说明为什么不是重复购买，并给出冲动风险。\n\n"
        "Asset 可能缺漏标记规则：如果上下文显示某项资产已经存在于个人资源、项目资源或历史记录中，"
        "但 Balance Sheet 的 Asset 表没有对应记录，只能在 duplicate_check 或 evidence 中标记为“待核实补录”。"
        "不要把这类项目作为购买推荐；它们应被理解为需要补充价格、购买日期、归属和是否个人资产的台账补录项。"
        "例如宿舍台式机、已有笔记本、实验室/老师资产，都必须先区分个人资产还是非个人资产，不能编造成待购买物品。\n\n"
        f"Generate a total of {total_count} purchase recommendations across exactly three groups: "
        "practical, night_guard, wishlist. Keep all three groups present; distribute the total sensibly based on evidence.\n\n"
        f"Dismissed purchase recommendations JSON:\n{dismissed_json}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

def _build_purchase_random_recommendation_messages(dismissed_items=None, recommendation_count=None, random_seed=None):
    total_count = _normalize_purchase_group_limit(recommendation_count)
    dismissed_payload = [
        {
            "name": item.get("name", ""),
            "category": item.get("category", ""),
            "group_key": item.get("group_key", ""),
            "reason": item.get("reason", ""),
            "evidence": item.get("evidence", ""),
            "duplicate_check": item.get("duplicate_check", ""),
            "impulse_risk": item.get("impulse_risk", ""),
        }
        for item in (dismissed_items or [])
    ]
    dismissed_json = json.dumps(dismissed_payload, ensure_ascii=False, separators=(",", ":"))
    seed = str(random_seed or uuid.uuid4()).strip()
    system_prompt = (
        "你是一个购物灵感随机探索助手。你的任务是产生用户没有明确排除的随机购物想法，"
        "不要读取、推断或引用用户的财务表格、健康记录、库存、个人计划或历史行为上下文。"
        "只输出 JSON，不要 Markdown。"
    )
    user_prompt = (
        f"Generate a total of {total_count} random purchase recommendations across exactly three groups: "
        "practical, night_guard, wishlist. Keep all three groups present.\n"
        "输出结构必须是 JSON object，只包含 recommendation_groups。"
        "recommendation_groups 必须包含 key=practical/night_guard/wishlist 三组。"
        "每个 item 必须包含 name、category、estimated_price、reason、evidence、duplicate_check、impulse_risk、recommendation_mode。"
        "recommendation_mode 必须固定为 random。\n"
        "随机探索边界：可以跨生活工具、桌面收纳、户外通勤、厨房小物、学习爱好、旅行、维护保养、数字生活等方向。"
        "不要推荐违法、成人、赌博、金融投资、处方药、医疗诊断、危险武器、活体动物或明显成瘾消费。"
        "价格可以从低价小物到中等愿望清单，但每项必须写清楚它为什么只是随机探索而不是基于个人表格证据。\n"
        "已排除购物推荐 / dismissed purchase recommendations JSON 表示用户已经打叉、不想再看到的方向。"
        "不要推荐同名、近似同类、功能重复的物品；如果排除项是一个品类，也要避开同用途替代品。\n\n"
        # Everything above is constant. The seed and the dismissed list both
        # change between calls, so they are kept at the very end: the constant
        # instructions stay a reusable cache prefix instead of being invalidated
        # by a fresh seed each time.
        f"Random seed: {seed}. 按这个种子发散到彼此差异明显的品类，不要总是围绕同一批常见答案。\n\n"
        f"Dismissed purchase recommendations JSON:\n{dismissed_json}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

def _build_purchase_recommendation_retry_messages(messages, raw_content, requested_count, actual_count):
    retry_prompt = (
        f"The previous response only returned {actual_count} recommendation items, "
        f"but the user requested exactly {requested_count}. "
        f"Return a complete replacement JSON object with exactly {requested_count} total items across "
        "practical, night_guard, and wishlist. Keep all three groups present, do not include markdown, "
        "and do not repeat dismissed, same-name, same-category, or same-function items."
    )
    return [
        *messages,
        {"role": "assistant", "content": str(raw_content or "").strip()},
        {"role": "user", "content": retry_prompt},
    ]

def _build_purchase_context_prompt(prompt_payload):
    try:
        return DataLoader.construct_prompt(
            DataLoader.resolve_data_path("Prompt_Personal_Info.md"),
            DataLoader.resolve_data_path("Time.xlsx"),
            days=PURCHASE_CONTEXT_TIME_SERIES_DAYS,
            start_date=PURCHASE_CONTEXT_TIME_SERIES_START_DATE,
        )
    except Exception as exc:
        logging.warning("Failed to build purchase recommendation Action Plan context: %s", exc)
        balance_json = json.dumps(prompt_payload, ensure_ascii=False, separators=(",", ":"), default=str)
        fallback_payload = {"unavailable": True, "reason": str(exc)}
        return (
            "## Time Series Data (JSON)\n\n```json\n"
            f"{json.dumps(fallback_payload, ensure_ascii=False, separators=(',', ':'))}\n```\n\n"
            "## Balance Sheet Data (JSON)\n\n```json\n"
            f"{balance_json}\n```"
        )

def _build_purchase_context_metadata(context_prompt):
    return {
        "time_xlsx_included": "Time Series Data (JSON)" in str(context_prompt or ""),
        "balance_sheet_included": "Balance Sheet Data (JSON)" in str(context_prompt or ""),
        "prompt_hash": hashlib.sha256(str(context_prompt or "").encode("utf-8")).hexdigest(),
    }

def _dedupe_purchase_recommendation_groups(groups):
    seen_name_keys = set()
    deduped_groups = []
    for group in groups or []:
        next_group = copy.deepcopy(group)
        next_items = []
        for item in next_group.get("items") or []:
            name_key = _normalize_purchase_text_key(item.get("name"))
            if not name_key or name_key in seen_name_keys:
                continue
            seen_name_keys.add(name_key)
            next_items.append(item)
        next_group["items"] = next_items
        deduped_groups.append(next_group)
    return deduped_groups

def _merge_purchase_recommendation_groups(*group_sets):
    merged = []
    for key, title in PURCHASE_RECOMMENDATION_GROUPS:
        next_group = {"key": key, "title": title, "items": []}
        for groups in group_sets:
            for group in groups or []:
                if group.get("key") != key:
                    continue
                next_group["title"] = str(group.get("title") or next_group["title"]).strip()
                next_group["items"].extend(copy.deepcopy(group.get("items") or []))
                break
        merged.append(next_group)
    return _dedupe_purchase_recommendation_groups(merged)

def _generate_purchase_recommendation_groups(
    llm_client,
    messages,
    requested_count,
    recommendation_mode,
    request_config,
    metadata,
    dismissed_items=None,
):
    generation_attempts = 0
    llm_result = {}
    raw_content = ""
    recommendation_groups = []
    requested_count = _normalize_purchase_group_limit(requested_count)
    mode = _normalize_purchase_recommendation_mode(recommendation_mode)

    for attempt in range(1, 3):
        generation_attempts = attempt
        llm_result = llm_client.chat(
            messages=messages,
            stream=False,
            model=request_config["model"],
            provider_route=request_config["provider_route"],
            reasoning_effort=request_config["reasoning_effort"],
            service_tier=request_config["service_tier"],
            source=f"expense_purchase_recommendations_{mode}",
            entrypoint="src/server.py",
            metadata={
                **metadata,
                "purchase_recommendation_mode": mode,
                "purchase_recommendation_count": requested_count,
                "purchase_generation_attempt": attempt,
            },
        )
        raw_content = llm_result.get("content") if isinstance(llm_result, dict) else ""
        parsed = _extract_json_object_from_text(raw_content)
        recommendation_groups = _normalize_purchase_recommendation_groups(
            parsed.get("recommendation_groups"),
            recommendation_count=requested_count,
            recommendation_mode=mode,
        )
        recommendation_groups = _filter_dismissed_purchase_groups(recommendation_groups, dismissed_items or [])
        recommendation_groups = _dedupe_purchase_recommendation_groups(recommendation_groups)
        actual_count = _count_purchase_recommendation_items(recommendation_groups)
        if actual_count >= requested_count or attempt >= 2:
            break
        messages = _build_purchase_recommendation_retry_messages(
            messages,
            raw_content,
            requested_count,
            actual_count,
        )

    return {
        "groups": recommendation_groups,
        "attempts": generation_attempts,
        "result": llm_result,
        "raw_content": raw_content,
        "actual_count": _count_purchase_recommendation_items(recommendation_groups),
    }

def _build_purchase_recommendations_payload(force_regenerate=False, request_config=None):
    request_config = _normalize_purchase_request_config(request_config)
    path = DataLoader.resolve_data_path("Balance Sheet.xlsx")
    try:
        sheets = DataLoader.load_excel_sheets(path)
    except FileNotFoundError as exc:
        return _build_purchase_recommendations_unavailable_payload(path, exc, request_config)
    if not sheets:
        return _build_purchase_recommendations_unavailable_payload(
            path,
            "No sheets found in Balance Sheet.xlsx",
            request_config,
        )

    prompt_payload = DataLoader.build_balance_sheet_prompt_payload_from_sheets(sheets, file_name=path.name)
    dismissed_items = _list_dismissed_purchase_items()
    dismissed_hash = _purchase_dismissed_hash(dismissed_items)
    context_prompt = _build_purchase_context_prompt(prompt_payload)
    context_metadata = _build_purchase_context_metadata(context_prompt)
    cache_key = _purchase_recommendation_cache_key(
        prompt_payload,
        request_config=request_config,
        context_hash=context_metadata["prompt_hash"],
        dismissed_hash=dismissed_hash,
    )
    if not force_regenerate:
        cached = _load_purchase_recommendation_cache(cache_key)
        if cached:
            filtered_cached = _with_dismissed_purchase_filter(cached, dismissed_items)
            if not filtered_cached.get("recommendation_count_underfilled"):
                return filtered_cached

    requested_count = request_config["recommendation_count"]
    mode_counts = _purchase_recommendation_mode_counts(requested_count)
    random_seed = str(uuid.uuid4())
    base_metadata = {
        "balance_sheet_cache_key": cache_key,
        "purchase_context_hash": context_metadata["prompt_hash"],
        "purchase_dismissed_hash": dismissed_hash,
        "purchase_random_seed": random_seed,
    }

    contextual_messages = _build_purchase_recommendation_messages(
        context_prompt,
        dismissed_items=dismissed_items,
        recommendation_count=mode_counts[PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL],
    )
    random_messages = _build_purchase_random_recommendation_messages(
        dismissed_items=dismissed_items,
        recommendation_count=mode_counts[PURCHASE_RECOMMENDATION_MODE_RANDOM],
        random_seed=random_seed,
    )
    llm_client = LLMClient()
    contextual_generation = _generate_purchase_recommendation_groups(
        llm_client,
        contextual_messages,
        mode_counts[PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL],
        PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL,
        request_config,
        base_metadata,
        dismissed_items=dismissed_items,
    )
    random_generation = _generate_purchase_recommendation_groups(
        llm_client,
        random_messages,
        mode_counts[PURCHASE_RECOMMENDATION_MODE_RANDOM],
        PURCHASE_RECOMMENDATION_MODE_RANDOM,
        request_config,
        base_metadata,
        dismissed_items=dismissed_items,
    )
    recommendation_groups = _merge_purchase_recommendation_groups(
        contextual_generation["groups"],
        random_generation["groups"],
    )
    actual_count = _count_purchase_recommendation_items(recommendation_groups)
    recommendation_mix = _build_purchase_recommendation_mix(mode_counts, recommendation_groups)
    generation_attempts = max(contextual_generation["attempts"], random_generation["attempts"])
    contextual_result = contextual_generation["result"] if isinstance(contextual_generation["result"], dict) else {}
    random_result = random_generation["result"] if isinstance(random_generation["result"], dict) else {}
    payload = {
        "status": "ready",
        "from_cache": False,
        "cache_key": cache_key,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "text_model": contextual_result.get("model") or random_result.get("model"),
        "request_config": request_config,
        "context": context_metadata,
        "recommendation_mix_requested": mode_counts,
        "recommendation_mix": recommendation_mix,
        "recommendation_groups": recommendation_groups,
        "recommendation_count_requested": requested_count,
        "recommendation_count_actual": actual_count,
        "recommendation_count_underfilled": (
            actual_count < requested_count or _purchase_recommendation_mix_underfilled(recommendation_mix)
        ),
        "generation_attempts": generation_attempts,
        "usage": {
            PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL: contextual_result.get("usage"),
            PURCHASE_RECOMMENDATION_MODE_RANDOM: random_result.get("usage"),
        },
        "response_raw": {
            PURCHASE_RECOMMENDATION_MODE_CONTEXTUAL: contextual_result,
            PURCHASE_RECOMMENDATION_MODE_RANDOM: random_result,
        },
    }
    _save_purchase_recommendation_cache(payload)
    return _with_dismissed_purchase_filter(payload, dismissed_items)

@router.get("/api/v1/finance/purchase-recommendations")
async def get_balance_sheet_purchase_recommendations(
    recommendation_count: Optional[int] = None,
    model: Optional[str] = None,
    provider_route: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    service_tier: Optional[str] = None,
):
    request_config = _normalize_purchase_request_config({
        "recommendation_count": recommendation_count,
        "model": model,
        "provider_route": provider_route,
        "reasoning_effort": reasoning_effort,
        "service_tier": service_tier,
    })
    try:
        return await asyncio.to_thread(
            _build_purchase_recommendations_payload,
            force_regenerate=False,
            request_config=request_config,
        )
    except FileNotFoundError as exc:
        path = DataLoader.resolve_data_path("Balance Sheet.xlsx")
        return _build_purchase_recommendations_unavailable_payload(path, exc, request_config)
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "error": "Failed to generate purchase recommendations.",
                "details": str(exc),
            },
        )

@router.post("/api/v1/finance/purchase-recommendations/regenerate")
async def regenerate_balance_sheet_purchase_recommendations(request: Optional[PurchaseRecommendationRequest] = None):
    request_payload = None
    if request is not None:
        request_payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    request_config = _normalize_purchase_request_config(request_payload)
    try:
        return await asyncio.to_thread(
            _build_purchase_recommendations_payload,
            force_regenerate=True,
            request_config=request_config,
        )
    except FileNotFoundError as exc:
        path = DataLoader.resolve_data_path("Balance Sheet.xlsx")
        return _build_purchase_recommendations_unavailable_payload(path, exc, request_config)
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "error": "Failed to regenerate purchase recommendations.",
                "details": str(exc),
            },
        )

@router.post("/api/v1/finance/purchase-recommendations/dismiss")
async def dismiss_balance_sheet_purchase_recommendation(request: PurchaseRecommendationDismissRequest):
    try:
        return _record_purchase_recommendation_dismissal(
            cache_key=request.cache_key,
            group_key=request.group_key,
            item=request.item or {},
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "Failed to dismiss purchase recommendation.", "details": str(exc)},
        )

@router.get("/api/v1/finance/purchase-recommendations/dismissed")
async def get_dismissed_balance_sheet_purchase_recommendations():
    try:
        return _build_purchase_dismissed_payload()
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"items": [], "count": 0, "error": "Failed to load dismissed recommendations.", "details": str(exc)},
        )

@router.delete("/api/v1/finance/purchase-recommendations/dismissed")
async def clear_dismissed_balance_sheet_purchase_recommendations():
    try:
        return _clear_purchase_recommendation_dismissals()
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "Failed to clear dismissed recommendations.", "details": str(exc)},
        )

@router.delete("/api/v1/finance/purchase-recommendations/dismissed/{item_id}")
async def delete_dismissed_balance_sheet_purchase_recommendation(item_id: int):
    try:
        return _delete_purchase_recommendation_dismissal(item_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "Failed to restore dismissed recommendation.", "details": str(exc)},
        )
