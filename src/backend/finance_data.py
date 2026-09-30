"""Workbook parsing, financial summaries, forecasts, and balance-sheet routes."""

import asyncio
import calendar
import math
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.utils.data_loader import DataLoader

router = APIRouter()

# Balance Sheet helpers
def _normalize_cell_value(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value

def _looks_like_date(text):
    if not isinstance(text, str):
        return False
    s = text.strip()
    if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$", s):
        return True
    if re.match(r"^\d{4}年\d{1,2}月\d{1,2}日$", s):
        return True
    return False

def _coerce_number(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s or _looks_like_date(s):
            return None
        cleaned = re.sub(r"[^\d\.\-]", "", s)
        if cleaned in ("", "-", "."):
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None

def _find_latest_date_in_df(df):
    if df is None or df.empty:
        return None
    preferred = [col for col in df.columns if any(k in str(col) for k in ["日期", "时间", "Date", "date", "Time", "time"])]
    fallback = [col for col in df.columns if "月份" in str(col)]
    for col in preferred + fallback:
        try:
            series = pd.to_datetime(df[col], errors="coerce")
        except Exception:
            continue
        if series.notna().any():
            latest = series.max()
            if pd.notna(latest):
                return latest.date()
    return None

def _find_date_column(df):
    if df is None or df.empty:
        return None

    preferred = [
        col
        for col in df.columns
        if any(k in str(col) for k in ["日期", "时间", "Date", "date", "Time", "time", "月份"])
    ]

    for col in preferred:
        try:
            series = pd.to_datetime(df[col], errors="coerce")
        except Exception:
            continue
        if series.notna().any():
            return col

    for col in df.columns:
        try:
            series = pd.to_datetime(df[col], errors="coerce")
        except Exception:
            continue
        if series.notna().sum() >= max(3, min(10, len(df))):
            return col

    return None

def _find_metric_from_columns(df, keywords):
    if df is None or df.empty:
        return None
    for col in _find_matching_columns(df.columns, keywords):
        values = []
        for v in df[col].tolist():
            num = _coerce_number(v)
            if num is not None:
                values.append(num)
        if values:
            return {"value": values[-1], "field": str(col)}
    return None

def _find_metric_from_rows(df, keywords):
    if df is None or df.empty:
        return None
    for _, row in df.iterrows():
        label_cell = None
        for cell in row.tolist():
            if isinstance(cell, str) and any(k in cell for k in keywords):
                label_cell = cell
                break
        if label_cell is None:
            continue
        # Prefer numeric values from right to left (often latest column)
        row_values = row.tolist()
        for col, cell in zip(reversed(df.columns), reversed(row_values)):
            num = _coerce_number(cell)
            if num is not None:
                return {"value": num, "field": str(col), "label": label_cell}
    return None

def _find_metric(sheets, keywords):
    for sheet_name, df in sheets.items():
        result = _find_metric_from_columns(df, keywords)
        if result:
            result["sheet"] = sheet_name
            return result
    for sheet_name, df in sheets.items():
        result = _find_metric_from_rows(df, keywords)
        if result:
            result["sheet"] = sheet_name
            return result
    return None

def _find_budget_sheet(sheets):
    if not sheets:
        return None, None
    for sheet_name, df in sheets.items():
        if str(sheet_name).strip().lower() == "budget":
            return sheet_name, df
    for sheet_name, df in sheets.items():
        name = str(sheet_name)
        if "预算" in name or "Budget" in name:
            return sheet_name, df
    for sheet_name, df in sheets.items():
        cols = [str(c) for c in df.columns]
        if any("是否必须" in c or "必需" in c for c in cols) and any("月" in c or "年" in c or "日" in c for c in cols):
            return sheet_name, df
    return None, None

def _parse_required_flag(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    lower_text = text.lower()
    optional_tokens = ["非必须", "不必须", "不是", "否", "not required", "optional", "no", "n"]
    required_tokens = ["必须", "必需", "是", "required", "yes", "y"]

    def matches(token):
        token_text = token.lower()
        if token_text in {"是", "否", "yes", "no", "y", "n", "required", "optional"}:
            return lower_text == token_text
        return token_text in lower_text

    if any(matches(k) for k in optional_tokens):
        return False
    if any(matches(k) for k in required_tokens):
        return True
    return None

def _find_first_column(columns_or_df, keywords):
    columns = None
    if hasattr(columns_or_df, "columns"):
        columns = columns_or_df.columns
    else:
        columns = columns_or_df

    matching_columns = _find_matching_columns(columns, keywords)
    return matching_columns[0] if matching_columns else None

def _find_matching_columns(columns, keywords):
    keyword_texts = [str(keyword) for keyword in keywords if keyword is not None]
    matches = []
    seen = set()
    for keyword in keyword_texts:
        for col in columns:
            name = str(col)
            if name == keyword and name not in seen:
                matches.append(col)
                seen.add(name)
    for keyword in keyword_texts:
        for col in columns:
            name = str(col)
            if keyword in name and name not in seen:
                matches.append(col)
                seen.add(name)
    return matches

def _find_record_type_column(df):
    if df is None or df.empty:
        return None
    return _find_first_column(df, ["记录类型", "数据类型", "类型", "record_type", "record type"])

def _row_type_masks(df, date_col=None, as_of=None):
    if df is None or df.empty:
        empty = pd.Series([], dtype=bool)
        return empty, empty

    record_col = _find_record_type_column(df)
    if record_col is not None:
        record_text = df[record_col].fillna("").astype(str).str.strip().str.lower()
        explicit_forecast = record_text.str.contains("预测|计划|forecast|plan", regex=True, na=False)
        explicit_actual = record_text.str.contains("实际|真实|actual|history|historical", regex=True, na=False)
    else:
        explicit_forecast = pd.Series(False, index=df.index)
        explicit_actual = pd.Series(False, index=df.index)

    if date_col is None:
        date_col = _find_date_column(df)
    if as_of is None:
        as_of = date.today()

    if date_col is not None:
        parsed_dates = pd.to_datetime(df[date_col], errors="coerce")
        future_dates = parsed_dates.dt.date > as_of
    else:
        future_dates = pd.Series(False, index=df.index)

    forecast_mask = explicit_forecast | (~explicit_actual & future_dates.fillna(False))
    actual_mask = explicit_actual | (~explicit_forecast & ~future_dates.fillna(False))
    return actual_mask, forecast_mask

def _filter_actual_expense_rows(df, date_col=None, as_of=None):
    if df is None or df.empty:
        return df
    actual_mask, _ = _row_type_masks(df, date_col=date_col, as_of=as_of)
    return df.loc[actual_mask].copy()

def _filter_forecast_expense_rows(df, date_col=None, as_of=None):
    if df is None or df.empty:
        return df
    _, forecast_mask = _row_type_masks(df, date_col=date_col, as_of=as_of)
    return df.loc[forecast_mask].copy()

def _find_expense_sheet(sheets):
    if not sheets:
        return None, None

    for sheet_name, df in sheets.items():
        normalized_name = str(sheet_name).strip().lower()
        if normalized_name == "expense":
            return sheet_name, df

    for sheet_name, df in sheets.items():
        name = str(sheet_name)
        if "开销" in name or "Expense" in name or "expense" in name:
            return sheet_name, df

    for sheet_name, df in sheets.items():
        date_col = _find_date_column(df)
        balance_col = _find_first_column(df, ["现金及现金等价物+股票", "现金及现金等价物", "现金", "股票"])
        daily_average_col = _find_first_column(df, ["日均支出", "日均开销", "日均成本"])
        period_spend_col = _find_first_column(df, ["期间支出", "支出"])

        if date_col is not None and any(col is not None for col in [balance_col, daily_average_col, period_spend_col]):
            return sheet_name, df

    return None, None

def _compute_monthly_from_row(row, days_in_month):
    month_col = _find_first_column(row.index, ["每月", "月消费", "月支出", "月开销", "月均", "月度"])
    year_col = _find_first_column(row.index, ["一年合计", "年消费", "年支出", "年开销", "年均", "年费", "年"])
    day_col = _find_first_column(row.index, ["每日", "日消费", "日支出", "日开销", "日均"])

    value = None
    if month_col is not None:
        value = _coerce_number(row.get(month_col))
    if value is None and year_col is not None:
        year_value = _coerce_number(row.get(year_col))
        if year_value is not None:
            value = year_value / 12.0
    if value is None and day_col is not None:
        day_value = _coerce_number(row.get(day_col))
        if day_value is not None and days_in_month:
            value = day_value * days_in_month
    return value, month_col or year_col or day_col

def _build_budget_summary(sheets):
    sheet_name, df = _find_budget_sheet(sheets)
    if df is None or df.empty:
        return None

    today = datetime.now()
    days_in_month = calendar.monthrange(today.year, today.month)[1]

    required_col = _find_first_column(df, ["是否必须", "必需", "是否必需"])

    monthly_required = 0.0
    monthly_optional = 0.0
    required_count = 0
    optional_count = 0
    source_col = None

    for _, row in df.iterrows():
        flag = _parse_required_flag(row.get(required_col)) if required_col else None
        monthly_value, value_col = _compute_monthly_from_row(row, days_in_month)
        if monthly_value is None:
            continue
        if source_col is None and value_col is not None:
            source_col = str(value_col)
        if flag is True:
            monthly_required += monthly_value
            required_count += 1
        elif flag is False:
            monthly_optional += monthly_value
            optional_count += 1

    return {
        "sheet": sheet_name,
        "monthly_required": monthly_required if required_count else None,
        "monthly_optional": monthly_optional if optional_count else None,
        "required_count": required_count,
        "optional_count": optional_count,
        "source_column": source_col
    }

def _sheet_to_payload(df, max_rows=200):
    if df is None:
        return {"columns": [], "rows": [], "row_count": 0, "truncated": False}
    populated_columns = df.notna().any(axis=0).tolist()
    last_populated_index = next(
        (index for index in range(len(populated_columns) - 1, -1, -1) if populated_columns[index]),
        -1,
    )
    df = df.iloc[:, : last_populated_index + 1]
    columns = [str(c) for c in df.columns]
    row_count = len(df)
    truncated = max_rows is not None and row_count > max_rows
    sliced = df
    if truncated:
        date_col = _find_date_column(df)
        if date_col is not None:
            dated = df.copy()
            dated["__payload_date__"] = pd.to_datetime(dated[date_col], errors="coerce")
            dated = dated.sort_values("__payload_date__", kind="stable")
            sliced = dated.tail(max_rows).drop(columns="__payload_date__")
        else:
            sliced = df.head(max_rows)
    rows = []
    for row in sliced.itertuples(index=False, name=None):
        rows.append([_normalize_cell_value(v) for v in row])
    return {
        "columns": columns,
        "rows": rows,
        "row_count": row_count,
        "truncated": truncated
    }

def _build_expense_trend_points(sheets):
    sheet_name, df = _find_expense_sheet(sheets)
    if df is None or df.empty:
        return []

    date_col = _find_date_column(df)
    if date_col is None:
        return []

    df = _filter_actual_expense_rows(df, date_col=date_col)
    if df is None or df.empty:
        return []

    balance_col = _find_first_column(df, ["现金及现金等价物+股票", "实际/预测期末现金+股票", "现金及现金等价物", "现金", "股票"])
    daily_average_col = _find_first_column(df, ["日均支出", "日均开销", "日均成本"])
    period_spend_col = _find_first_column(df, ["预测/实际支出", "期间支出", "支出"])

    if balance_col is None and daily_average_col is None and period_spend_col is None:
        return []

    trend_points = []
    for _, row in df.iterrows():
        raw_date = _normalize_cell_value(row.get(date_col))
        if raw_date is None:
            continue

        parsed_date = pd.to_datetime(raw_date, errors="coerce")
        if pd.isna(parsed_date):
            continue

        balance = _coerce_number(row.get(balance_col)) if balance_col is not None else None
        daily_average = _coerce_number(row.get(daily_average_col)) if daily_average_col is not None else None
        period_spend = _coerce_number(row.get(period_spend_col)) if period_spend_col is not None else None

        if balance is None and daily_average is None and period_spend is None:
            continue

        trend_points.append(
            {
                "date": parsed_date.strftime("%Y-%m-%d"),
                "balance": balance,
                "daily_average": daily_average,
                "period_spend": period_spend,
                "sheet": sheet_name,
            }
        )

    trend_points.sort(key=lambda item: item["date"])
    return trend_points

def _sum_present_numbers(values):
    present_values = [value for value in values if value is not None]
    if not present_values:
        return None
    return sum(present_values)

def _latest_numeric_value(df, value_col, date_col=None):
    if df is None or df.empty or value_col is None:
        return None

    working_df = df.copy()
    if date_col is not None and date_col in working_df.columns:
        working_df = working_df.sort_values(date_col)

    values = []
    for value in working_df[value_col].tolist():
        number = _coerce_number(value)
        if number is not None:
            values.append(number)
    return values[-1] if values else None

def _average_recent_numeric_values(df, value_col, date_col=None, count=6):
    if df is None or df.empty or value_col is None:
        return None

    working_df = df.copy()
    if date_col is not None and date_col in working_df.columns:
        working_df = working_df.sort_values(date_col)

    values = []
    for value in working_df[value_col].tolist():
        number = _coerce_number(value)
        if number is not None:
            values.append(number)

    recent_values = values[-count:]
    if not recent_values:
        return None
    return sum(recent_values) / len(recent_values)

def _build_balance_forecast_points(sheets, as_of=None):
    sheet_name, df = _find_expense_sheet(sheets)
    if df is None or df.empty:
        return []

    date_col = _find_date_column(df)
    if date_col is None:
        return []

    actual_df = _filter_actual_expense_rows(df, date_col=date_col, as_of=as_of)
    forecast_df = _filter_forecast_expense_rows(df, date_col=date_col, as_of=as_of)
    if forecast_df is None or forecast_df.empty:
        return []

    forecast_df = forecast_df.sort_values(date_col)
    balance_col = _find_first_column(
        actual_df,
        ["现金及现金等价物+股票", "实际/预测期末现金+股票", "现金及现金等价物", "现金", "股票"],
    )
    rolling_balance = _latest_numeric_value(actual_df, balance_col, date_col=date_col)
    actual_spend_col = _find_first_column(actual_df, ["期间支出", "实际支出", "支出", "monthly_spend", "spend"])
    estimated_monthly_spend = _average_recent_numeric_values(actual_df, actual_spend_col, date_col=date_col, count=6)

    living_income_col = _find_first_column(forecast_df, ["收入生活费", "生活费收入", "living_income"])
    fixed_income_col = _find_first_column(forecast_df, ["固定收入", "收入工资", "固定工资", "fixed_income"])
    extra_income_col = _find_first_column(forecast_df, ["额外收入", "收入其他", "extra_income"])
    total_income_col = _find_first_column(forecast_df, ["收入合计", "期间收入", "total_income"])
    planned_spend_col = _find_first_column(forecast_df, ["预测/实际支出", "预测支出", "计划支出", "planned_spend"])
    net_cash_flow_col = _find_first_column(forecast_df, ["净现金流", "net_cash_flow"])
    projected_balance_col = _find_first_column(
        forecast_df,
        ["实际/预测期末现金+股票", "预测期末现金+股票", "现金及现金等价物+股票", "projected_balance"],
    )

    forecast_points = []
    for _, row in forecast_df.iterrows():
        raw_date = _normalize_cell_value(row.get(date_col))
        if raw_date is None:
            continue

        parsed_date = pd.to_datetime(raw_date, errors="coerce")
        if pd.isna(parsed_date):
            continue

        fixed_income = _coerce_number(row.get(fixed_income_col)) if fixed_income_col is not None else None
        extra_income = _coerce_number(row.get(extra_income_col)) if extra_income_col is not None else None
        living_income = _coerce_number(row.get(living_income_col)) if living_income_col is not None else None
        total_income = _coerce_number(row.get(total_income_col)) if total_income_col is not None else None
        explicit_planned_spend = _coerce_number(row.get(planned_spend_col)) if planned_spend_col is not None else None
        net_cash_flow = _coerce_number(row.get(net_cash_flow_col)) if net_cash_flow_col is not None else None
        projected_balance = _coerce_number(row.get(projected_balance_col)) if projected_balance_col is not None else None

        if total_income is None:
            total_income = _sum_present_numbers([living_income, fixed_income, extra_income])
        planned_spend = estimated_monthly_spend if estimated_monthly_spend is not None else explicit_planned_spend
        if planned_spend is None:
            planned_spend = 0.0
        if total_income is not None and planned_spend is not None:
            net_cash_flow = total_income - planned_spend

        if net_cash_flow is not None and rolling_balance is not None:
            rolling_balance += net_cash_flow
            projected_balance = rolling_balance

        if all(value is None for value in [fixed_income, extra_income, total_income, net_cash_flow, projected_balance]):
            continue

        forecast_points.append(
            {
                "date": parsed_date.strftime("%Y-%m-%d"),
                "fixed_income": fixed_income,
                "extra_income": extra_income,
                "total_income": total_income,
                "planned_spend": planned_spend,
                "net_cash_flow": net_cash_flow,
                "projected_balance": projected_balance,
                "sheet": sheet_name,
            }
        )

    forecast_points.sort(key=lambda item: item["date"])
    return forecast_points

def _build_balance_summary(sheets):
    metric_sheets = dict(sheets)
    expense_sheet_name, expense_df = _find_expense_sheet(sheets)
    if expense_df is not None and not expense_df.empty:
        date_col = _find_date_column(expense_df)
        actual_expense_df = _filter_actual_expense_rows(expense_df, date_col=date_col)
        if actual_expense_df is not None and not actual_expense_df.empty:
            metric_sheets[expense_sheet_name] = actual_expense_df

    daily_avg = _find_metric(metric_sheets, ["日均支出", "日均开销", "日均成本"])
    monthly_total = _find_metric(metric_sheets, ["月支出", "月度支出", "当月支出", "月总支出"])
    monthly_avg = _find_metric(metric_sheets, ["月均支出", "月均开销", "月均成本"])

    latest_date = None
    if daily_avg and "sheet" in daily_avg:
        latest_date = _find_latest_date_in_df(metric_sheets.get(daily_avg["sheet"]))
    if latest_date is None and monthly_total and "sheet" in monthly_total:
        latest_date = _find_latest_date_in_df(metric_sheets.get(monthly_total["sheet"]))
    if latest_date is None and monthly_avg and "sheet" in monthly_avg:
        latest_date = _find_latest_date_in_df(metric_sheets.get(monthly_avg["sheet"]))
    if latest_date is None:
        for df in metric_sheets.values():
            latest_date = _find_latest_date_in_df(df)
            if latest_date:
                break

    days_in_month = 30
    if latest_date:
        days_in_month = calendar.monthrange(latest_date.year, latest_date.month)[1]

    daily_avg_value = daily_avg["value"] if daily_avg else None
    monthly_total_value = None
    if monthly_total:
        monthly_total_value = monthly_total["value"]
    elif monthly_avg:
        monthly_total_value = monthly_avg["value"]

    if daily_avg_value is None and monthly_total_value is not None:
        daily_avg_value = monthly_total_value / days_in_month if days_in_month else None

    per_minute = None
    if daily_avg_value is not None:
        per_minute = daily_avg_value / (24 * 60)
    elif monthly_total_value is not None:
        per_minute = (monthly_total_value / days_in_month) / (24 * 60) if days_in_month else None

    per_day_month = None
    if monthly_total_value is not None and days_in_month:
        per_day_month = monthly_total_value / days_in_month
    elif daily_avg_value is not None:
        per_day_month = daily_avg_value

    assets = {
        "fixed_assets": _find_metric(metric_sheets, ["固定资产"]),
        "current_assets": _find_metric(metric_sheets, ["流动资产"]),
        "total_assets": _find_metric(metric_sheets, ["总资产", "资产合计"]),
        "liabilities": _find_metric(metric_sheets, ["负债合计", "负债"]),
        "equity": _find_metric(metric_sheets, ["净资产", "所有者权益", "股东权益"]),
        "cash_and_stock": _find_metric(metric_sheets, ["现金及现金等价物+股票", "实际/预测期末现金+股票", "现金及现金等价物", "现金", "股票"])
    }

    budget = _build_budget_summary(sheets)

    return {
        "time_cost": {
            "daily_average": daily_avg_value,
            "monthly_total": monthly_total_value,
            "per_minute": per_minute,
            "per_day_month": per_day_month,
            "latest_date": latest_date.strftime("%Y-%m-%d") if latest_date else None,
            "source": {
                "daily_average": daily_avg,
                "monthly_total": monthly_total,
                "monthly_average": monthly_avg
            }
        },
        "assets": assets,
        "budget": budget
    }

def _build_balance_suggestions(summary):
    suggestions = []
    time_cost = summary.get("time_cost", {})
    assets = summary.get("assets", {})
    budget = summary.get("budget") or {}

    per_minute = time_cost.get("per_minute")
    per_day_month = time_cost.get("per_day_month")
    daily_average = time_cost.get("daily_average")

    if per_minute is not None:
        suggestions.append(f"时间成本：全天均摊每分钟约 {per_minute:.2f}，建议把高价值任务放在高专注时段，降低低价值碎片时间。")
    if per_day_month is not None:
        suggestions.append(f"月度均摊每日约 {per_day_month:.2f}，可结合预算上限设定每日支出阈值。")

    def extract_value(item):
        if not item:
            return None
        return item.get("value")

    total_assets = extract_value(assets.get("total_assets"))
    fixed_assets = extract_value(assets.get("fixed_assets"))
    current_assets = extract_value(assets.get("current_assets"))
    liabilities = extract_value(assets.get("liabilities"))
    cash_and_stock = extract_value(assets.get("cash_and_stock"))

    if total_assets and fixed_assets:
        fixed_ratio = fixed_assets / total_assets if total_assets else None
        if fixed_ratio is not None:
            if fixed_ratio > 0.6:
                suggestions.append("固定资产占比偏高，建议评估折旧压力和流动性风险，适度提升现金/可变资产比例。")
            elif fixed_ratio < 0.2:
                suggestions.append("固定资产占比较低，可结合长期规划评估必要的设备/能力投资。")

    if total_assets and current_assets:
        current_ratio = current_assets / total_assets if total_assets else None
        if current_ratio is not None and current_ratio < 0.25:
            suggestions.append("流动资产占比偏低，建议提高现金或短期可变资产以增强抗风险能力。")

    if total_assets and liabilities:
        debt_ratio = liabilities / total_assets if total_assets else None
        if debt_ratio is not None and debt_ratio > 0.6:
            suggestions.append("负债率偏高，建议优先偿还高利率负债，降低资金压力。")

    if cash_and_stock is not None and daily_average:
        cash_days = cash_and_stock / daily_average if daily_average else None
        if cash_days is not None:
            suggestions.append(f"现金+股票可覆盖约 {cash_days:.1f} 天日常开销，可据此设定安全垫目标。")

    monthly_required = budget.get("monthly_required")
    monthly_optional = budget.get("monthly_optional")
    if monthly_required is not None:
        suggestions.append(f"每月必须开支约 {monthly_required:.2f}，建议优先保障基础支出并定期复盘。")
    if monthly_optional is not None:
        suggestions.append(f"每月非必须开支约 {monthly_optional:.2f}，可设置弹性上限以控制超支。")

    if not suggestions:
        suggestions.append("当前可用指标较少，建议补充‘日均支出/资产/负债’等字段以获得更精确的优化建议。")

    return suggestions

def _build_balance_sheet_unavailable_payload(path, error):
    error_text = str(error)
    path_text = str(path or "Balance Sheet.xlsx")
    return {
        "status": "unavailable",
        "source": {
            "path": path_text,
            "sheet_count": 0,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "available": False,
            "error": error_text,
        },
        "summary": {},
        "suggestions": [],
        "trend_points": [],
        "forecast_points": [],
        "sheets": [],
        "prompt_payload": {
            "status": "unavailable",
            "file_name": Path(path_text).name or "Balance Sheet.xlsx",
            "sheet_count": 0,
            "total_rows": 0,
            "sheets": [],
            "error": error_text,
        },
        "error": error_text,
    }

def _build_balance_sheet_payload():
    path = DataLoader.resolve_data_path("Balance Sheet.xlsx")
    try:
        sheets = DataLoader.load_excel_sheets(path)

        if not sheets:
            return _build_balance_sheet_unavailable_payload(path, "No sheets found in Balance Sheet.xlsx")

        summary = _build_balance_summary(sheets)
        suggestions = _build_balance_suggestions(summary)
        trend_points = _build_expense_trend_points(sheets)
        forecast_points = _build_balance_forecast_points(sheets)

        sheet_payloads = []
        for sheet_name, df in sheets.items():
            payload = _sheet_to_payload(df, max_rows=None)
            payload["name"] = sheet_name
            sheet_payloads.append(payload)

        prompt_payload = DataLoader.build_balance_sheet_prompt_payload_from_sheets(
            sheets,
            file_name=path.name,
        )

        return {
            "source": {
                "path": str(path),
                "sheet_count": len(sheets),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            "summary": summary,
            "suggestions": suggestions,
            "trend_points": trend_points,
            "forecast_points": forecast_points,
            "sheets": sheet_payloads,
            "prompt_payload": prompt_payload,
        }
    except FileNotFoundError as exc:
        return _build_balance_sheet_unavailable_payload(path, exc)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

@router.get("/api/v1/finance/balance-sheet")
async def get_balance_sheet():
    return await asyncio.to_thread(_build_balance_sheet_payload)
