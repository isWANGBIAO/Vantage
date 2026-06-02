import numpy as np
import pandas as pd
import re

from src.scripts import plot as plot_module

SLEEP_SCHEDULE_WRAP_HOUR = 12
SLEEP_SCHEDULE_SUMMARY_POINTS = 45
SLEEP_SCHEDULE_DEFAULT_AXIS_MAX = 36
SLEEP_SCHEDULE_AXIS_INTERVAL = 2
SLEEP_SESSION_SEPARATOR_PATTERN = re.compile(r'[\uFF1B;]+')
SLEEP_TIME_PATTERN = re.compile(r'(\d{1,2})\s*[.:：]\s*(\d{1,2})')
SLEEP_AFTERNOON_MARKERS = ('\u4E0B\u5348', '\u665A\u4E0A')
SLEEP_NOON_MARKER = '\u4E2D\u5348'
SLEEP_MIN_PRIMARY_DURATION_HOURS = 2
SLEEP_MAX_PRIMARY_DURATION_HOURS = 18
HHH_SIGNED_COUNT_PATTERN = re.compile(r'([+-])\s*(\d+(?:\.\d+)?)')
HHH_DIRECT_COUNT_PATTERN = re.compile(r'[+-]?\s*\d+(?:\.0+)?')

TIME_WARNING_CHART_IDS = [
    'time-allocation',
    'time-screen-remaining',
    'time-averages',
    'time-delta',
    'radar-goal',
]
RUNNING_WARNING_CONFIG = {
    'running': {
        'id': 'running-missing-main',
        'title': '跑步主图存在未完整提取的记录',
        'message': '这些记录会让配速 / 心率 / 距离出现断点。请按原文修正 Excel 后再 refresh charts。',
    },
    'running-form': {
        'id': 'running-missing-form',
        'title': '跑步技术结构存在未完整提取的记录',
        'message': '这些记录会让用时 / 步频 / 步幅出现断点。请补齐原始文本后再 refresh charts。',
    },
    'running-hrc': {
        'id': 'running-missing-hrc',
        'title': 'HRC 分析存在未完整提取的记录',
        'message': '这些记录无法可靠计算 HRC，会直接影响趋势判断。请优先修正缺失字段。',
    },
    'running-excluded': {
        'id': 'running-excluded-records',
        'title': '已排除的异常跑步记录',
        'message': '这些记录未参与主跑步图 / 心率分析 / 技术结构图计算，避免明显失真的脏数据污染趋势。',
    },
}


def _to_chart_number(value, digits=2):
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(numeric) or np.isinf(numeric):
        return None
    return round(numeric, digits)


def _to_chart_date(value):
    if value is None or pd.isna(value):
        return None
    return pd.to_datetime(value).strftime('%Y-%m-%d')


def _format_total_minutes(value):
    if value is None or pd.isna(value):
        return None
    total_seconds = int(round(float(value) * 60))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f'{hours}小时{minutes:02d}分'
    return f'{minutes}分{seconds:02d}秒'


def _series_points(dates, values, digits=2):
    return [
        [_to_chart_date(date), _to_chart_number(value, digits)]
        for date, value in zip(dates, values)
    ]


def _forecast_balance_points(forecast_df):
    points = []
    for position, (_, row) in enumerate(forecast_df.iterrows()):
        point = {
            'value': [
                _to_chart_date(row.get('日期')),
                _to_chart_number(row.get('projected_balance'), 0),
            ],
        }
        if position > 0:
            monthly_income = _to_chart_number(row.get('total_income'), 2)
            if monthly_income is not None:
                point['monthlyIncome'] = monthly_income
        points.append(point)
    return points


def _category_values(values, digits=2):
    return [_to_chart_number(value, digits) for value in values]


def _zoom_start(total_points, focus_points=30):
    if total_points <= focus_points:
        return 0
    visible_ratio = focus_points / max(total_points, 1)
    return round((1 - visible_ratio) * 100, 2)


def _format_clock_text(value):
    if value is None:
        return None
    total_minutes = int(round(float(value) * 60)) % (24 * 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f'{hours:02d}:{minutes:02d}'


def _normalize_clock_hour(value, wrap_hour=SLEEP_SCHEDULE_WRAP_HOUR):
    if value is None:
        return None
    wrapped = float(value)
    if wrapped < wrap_hour:
        wrapped += 24
    return wrapped


def _parse_sleep_clock_match(segment, match):
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour < 0 or hour >= 24 or minute < 0 or minute >= 60:
        return None

    context = segment[max(0, match.start() - 4) : match.end() + 2]
    if hour < 12 and any(marker in context for marker in SLEEP_AFTERNOON_MARKERS):
        hour += 12
    elif hour < 11 and SLEEP_NOON_MARKER in context:
        hour += 12

    return hour + minute / 60.0


def _wrap_sleep_session_hours(bedtime_hour, wake_hour):
    bedtime_wrapped_hour = _normalize_clock_hour(bedtime_hour)
    wake_wrapped_hour = _normalize_clock_hour(wake_hour)
    if wake_wrapped_hour <= bedtime_wrapped_hour:
        wake_wrapped_hour += 24
    return bedtime_wrapped_hour, wake_wrapped_hour


def _parse_primary_sleep_session(value):
    if value is None or pd.isna(value):
        return None

    text = str(value).strip()
    if not text:
        return None

    candidates = []
    for segment in SLEEP_SESSION_SEPARATOR_PATTERN.split(text):
        segment = segment.strip()
        matches = list(SLEEP_TIME_PATTERN.finditer(segment))
        if len(matches) < 2:
            continue

        bedtime_hour = _parse_sleep_clock_match(segment, matches[0])
        wake_hour = _parse_sleep_clock_match(segment, matches[1])
        if bedtime_hour is None or wake_hour is None:
            continue

        bedtime_wrapped_hour, wake_wrapped_hour = _wrap_sleep_session_hours(bedtime_hour, wake_hour)
        duration_hours = wake_wrapped_hour - bedtime_wrapped_hour
        if duration_hours <= 0 or duration_hours > SLEEP_MAX_PRIMARY_DURATION_HOURS:
            continue

        candidates.append(
            {
                'bedtime_hour': bedtime_hour,
                'wake_hour': wake_hour,
                'bedtime_wrapped_hour': bedtime_wrapped_hour,
                'wake_wrapped_hour': wake_wrapped_hour,
                'duration_hours': duration_hours,
                'segment': segment,
            }
        )

    if not candidates:
        return None

    plausible_candidates = [
        candidate for candidate in candidates if candidate['duration_hours'] >= SLEEP_MIN_PRIMARY_DURATION_HOURS
    ]
    primary = max(plausible_candidates or candidates, key=lambda candidate: candidate['duration_hours'])
    return {
        'bedtime_hour': primary['bedtime_hour'],
        'wake_hour': primary['wake_hour'],
        'bedtime_wrapped_hour': primary['bedtime_wrapped_hour'],
        'wake_wrapped_hour': primary['wake_wrapped_hour'],
        'segment': primary['segment'],
    }


def _build_chart(chart_id, title, description, option, *, formatter='default', height=420, summary=None):
    return {
        'id': chart_id,
        'title': title,
        'description': description,
        'formatter': formatter,
        'height': height,
        'summary': summary or [],
        'option': option,
        'empty': False,
        'error': None,
    }


def _build_empty_chart(chart_id, title, description, error, *, formatter='default', height=420):
    return {
        'id': chart_id,
        'title': title,
        'description': description,
        'formatter': formatter,
        'height': height,
        'summary': [],
        'option': {},
        'empty': True,
        'error': str(error),
    }


def _safe_chart(chart_id, title, description, builder, *, formatter='default', height=420):
    try:
        return builder()
    except Exception as exc:
        return _build_empty_chart(
            chart_id,
            title,
            description,
            exc,
            formatter=formatter,
            height=height,
        )


def _build_time_data_warning(skipped_rows):
    if not skipped_rows:
        return None

    details = []
    for row in skipped_rows[:5]:
        date_text = _to_chart_date(row.get('日期')) or str(row.get('日期') or '未知日期')
        sleep_text = row.get('睡眠时间') or '未知'
        screen_text = row.get('手机屏幕使用时间') or '未知'
        reason_text = row.get('原因') or '时间数据无效'
        details.append(
            f"{date_text}：睡眠时间 {sleep_text}，手机屏幕使用时间 {screen_text}，原因：{reason_text}"
        )

    remaining_count = len(skipped_rows) - len(details)
    if remaining_count > 0:
        details.append(f"其余 {remaining_count} 条异常记录已省略，请直接检查 Excel 源数据。")

    return {
        'id': 'time-invalid-rows',
        'title': f'已跳过 {len(skipped_rows)} 条异常时间数据',
        'message': '这些记录未参与时间类图表计算。请修改 Excel 源数据后刷新 Plots 页面。',
        'details': details,
        'affected_chart_ids': TIME_WARNING_CHART_IDS,
    }


def _build_running_data_warnings(invalid_rows):
    if not invalid_rows:
        return []

    grouped_rows = {chart_id: [] for chart_id in RUNNING_WARNING_CONFIG}
    for row in reversed(invalid_rows):
        issues_by_chart = row.get('issues_by_chart') or {}
        date_text = _to_chart_date(row.get('日期')) or str(row.get('日期') or '未知日期')
        raw_text = str(row.get('原文') or '').strip()
        if len(raw_text) > 96:
            raw_text = f"{raw_text[:93]}..."

        for chart_id, issues in issues_by_chart.items():
            if chart_id not in grouped_rows:
                continue
            issue_text = '、'.join(issues) if issues else '关键字段异常'
            grouped_rows[chart_id].append(f"{date_text}：{issue_text}；原文：{raw_text or '空'}")

    warnings = []
    for chart_id, config in RUNNING_WARNING_CONFIG.items():
        details = grouped_rows.get(chart_id) or []
        if not details:
            continue
        visible_details = details[:6]
        remaining_count = len(details) - len(visible_details)
        if remaining_count > 0:
            visible_details.append(f"其余 {remaining_count} 条异常记录已省略，请直接检查 Excel 源数据。")
        warnings.append(
            {
                'id': config['id'],
                'title': config['title'],
                'message': config['message'],
                'details': visible_details,
                'affected_chart_ids': ['running', 'running-form', 'running-hrc']
                if chart_id == 'running-excluded'
                else [chart_id],
            }
        )

    return warnings


def _compute_time_trend_payload(data_frame):
    filtered_df, valid_sleep_hours, valid_screen_hours, remaining_hours, skipped_rows = (
        plot_module.compute_time_allocation_with_warnings(data_frame)
    )
    filtered_df_1 = filtered_df.copy()
    filtered_df_2 = filtered_df.copy()
    filtered_df_3 = filtered_df.copy()

    if filtered_df_1.empty or filtered_df_2.empty or filtered_df_3.empty:
        raise ValueError('用于时间趋势分析的数据不足')

    valid_1 = valid_sleep_hours
    valid_2 = valid_screen_hours

    y1 = np.zeros(len(filtered_df_1))
    y2 = np.zeros(len(filtered_df_2))
    y3 = np.zeros(len(filtered_df_3))

    for i in range(len(filtered_df_1)):
        y1[i] = valid_1[i:].mean()
    for i in range(len(filtered_df_2)):
        y2[i] = valid_2[i:].mean()
    for i in range(len(filtered_df_3)):
        y3[i] = remaining_hours[i:].mean()

    nearest_days = min(120, len(filtered_df_1), len(filtered_df_2), len(filtered_df_3))

    return {
        'filtered_df': filtered_df,
        'valid_sleep_hours': valid_sleep_hours,
        'valid_screen_hours': valid_screen_hours,
        'remaining_hours': remaining_hours,
        'sleep_df': filtered_df_1,
        'screen_df': filtered_df_2,
        'remaining_df': filtered_df_3,
        'y1': y1,
        'y2': y2,
        'y3': y3,
        'nearest_days': nearest_days,
        'warnings': skipped_rows,
    }


def _normalize_hhh_event_count(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if np.isnan(numeric) or np.isinf(numeric):
        return None

    rounded = round(numeric)
    if abs(numeric - rounded) > 1e-9:
        return None
    if rounded == 0 or abs(rounded) > 10:
        return None
    return float(rounded)


def _extract_hhh_values_for_dashboard(value):
    if isinstance(value, (int, float, np.integer, np.floating)):
        normalized = _normalize_hhh_event_count(value)
        return [normalized] if normalized is not None else []
    if not isinstance(value, str):
        return []

    text = value.strip()
    if not text:
        return []

    if HHH_DIRECT_COUNT_PATTERN.fullmatch(text):
        normalized = _normalize_hhh_event_count(text.replace(' ', ''))
        return [normalized] if normalized is not None else []

    events = []
    for match in HHH_SIGNED_COUNT_PATTERN.finditer(text):
        normalized = _normalize_hhh_event_count(f"{match.group(1)}{match.group(2)}")
        if normalized is not None:
            events.append(normalized)
    return events


def _parse_hhh_value_for_dashboard(value):
    events = _extract_hhh_values_for_dashboard(value)
    if not events:
        return None
    if all(event > 0 for event in events) or all(event < 0 for event in events):
        return sum(events)
    return events[-1]


def _build_hhh_event_frame_for_dashboard(data_frame):
    hhh_data = data_frame[['日期', 'HHH']].dropna().copy()
    records = []
    for _, row in hhh_data.iterrows():
        totals = {}
        for event_count in _extract_hhh_values_for_dashboard(row.get('HHH')):
            sign = 1 if event_count > 0 else -1
            totals[sign] = totals.get(sign, 0.0) + event_count
        for sign in (-1, 1):
            total = totals.get(sign)
            if total:
                records.append({'日期': row['日期'], 'HHH': total})

    if not records:
        return pd.DataFrame(columns=['日期', 'HHH'])
    return pd.DataFrame(records)


def _format_hhh_count_total(series):
    if series.empty:
        return '0'
    total = int(round(float(np.abs(series.to_numpy(dtype=float)).sum())))
    return str(total)


def _calculate_date_intervals(date_series):
    dates = pd.to_datetime(date_series).sort_values()
    return dates.diff().dt.days.dropna().tolist()


def _calculate_date_interval_points(date_series):
    dates = pd.to_datetime(date_series).sort_values().dropna()
    if len(dates) < 2:
        return [], []

    intervals = dates.diff().dt.days.dropna().tolist()
    interval_dates = dates.iloc[1:].tolist()
    return _series_points(interval_dates, intervals, digits=1), intervals


def _build_weight_bodyfat_dashboard_chart(data_frame):
    filtered_df_weight = data_frame.dropna(subset=['体重']).copy().sort_values('日期')
    if filtered_df_weight.empty:
        raise ValueError('体重数据为空')

    dates_weight = filtered_df_weight['日期'].tolist()
    weight_values = filtered_df_weight['体重'].to_numpy(dtype=float)
    average_weight = np.average(weight_values)

    option = {
        'color': [
            plot_module.COLORS['blue'],
            plot_module.COLORS['blue'],
            plot_module.COLORS['orange'],
            plot_module.COLORS['orange'],
            plot_module.COLORS['red'],
        ],
        'tooltip': {'trigger': 'axis'},
        'legend': {'top': 8},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'dataZoom': [
            {'type': 'inside', 'start': _zoom_start(len(dates_weight), 45), 'end': 100},
            {'type': 'slider', 'start': _zoom_start(len(dates_weight), 45), 'end': 100, 'bottom': 8},
        ],
        'grid': {'top': 72, 'left': 56, 'right': 72, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'time'},
        'yAxis': [
            {'type': 'value', 'name': '体重 (kg)', 'scale': True},
            {'type': 'value', 'name': '体脂率 (%)', 'position': 'right', 'scale': True},
            {'type': 'value', 'name': '脂肪质量 (kg)', 'position': 'right', 'offset': 64, 'scale': True},
        ],
        'series': [
            {
                'name': '体重',
                'type': 'line',
                'showSymbol': False,
                'smooth': True,
                'yAxisIndex': 0,
                'data': _series_points(dates_weight, weight_values),
            },
            {
                'name': '平均体重',
                'type': 'line',
                'showSymbol': False,
                'lineStyle': {'type': 'dashed', 'width': 1.4},
                'yAxisIndex': 0,
                'data': _series_points(dates_weight, np.full(len(dates_weight), average_weight)),
            },
        ],
    }

    summary = [
        {'label': '最新体重', 'value': f"{_to_chart_number(weight_values[-1], 2)} kg"},
        {'label': '平均体重', 'value': f"{_to_chart_number(average_weight, 2)} kg"},
    ]

    filtered_df_fat = data_frame.dropna(subset=['体脂率']).copy().sort_values('日期')
    if not filtered_df_fat.empty:
        fat_values = filtered_df_fat['体脂率'].to_numpy(dtype=float)
        average_fat = np.average(fat_values)
        option['series'].extend(
            [
                {
                    'name': '体脂率',
                    'type': 'line',
                    'showSymbol': False,
                    'smooth': True,
                    'yAxisIndex': 1,
                    'data': _series_points(filtered_df_fat['日期'].tolist(), fat_values),
                },
                {
                    'name': '平均体脂率',
                    'type': 'line',
                    'showSymbol': False,
                    'lineStyle': {'type': 'dashed', 'width': 1.4},
                    'yAxisIndex': 1,
                    'data': _series_points(
                        filtered_df_fat['日期'].tolist(),
                        np.full(len(filtered_df_fat), average_fat),
                    ),
                },
            ]
        )
        summary.append({'label': '最新体脂率', 'value': f"{_to_chart_number(fat_values[-1], 1)} %"})

    filtered_df_both = data_frame.dropna(subset=['体重', '体脂率']).copy().sort_values('日期')
    if not filtered_df_both.empty:
        fat_mass = (
            filtered_df_both['体脂率'].to_numpy(dtype=float) * 0.01 * filtered_df_both['体重'].to_numpy(dtype=float)
        )
        option['series'].append(
            {
                'name': '脂肪质量',
                'type': 'line',
                'showSymbol': False,
                'smooth': True,
                'yAxisIndex': 2,
                'data': _series_points(filtered_df_both['日期'].tolist(), fat_mass),
            }
        )
        summary.append({'label': '最新脂肪质量', 'value': f"{_to_chart_number(fat_mass[-1], 2)} kg"})

    return _build_chart(
        'weight-bodyfat',
        '体重 / 体脂率 / 脂肪质量趋势',
        '保留现有计算口径，用交互式多轴折线替代多张静态体重图。',
        option,
        formatter='weight-bodyfat',
        height=430,
        summary=summary,
    )


def _build_sleep_schedule_dashboard_chart(data_frame):
    if '起床时间' not in data_frame.columns:
        raise ValueError('缺少起床时间列')

    source = data_frame[['日期', '起床时间']].dropna(subset=['日期', '起床时间']).copy().sort_values('日期')
    parsed_rows = []
    for _, row in source.iterrows():
        parsed = _parse_primary_sleep_session(row.get('起床时间'))
        if parsed is None:
            continue
        parsed_rows.append(
            {
                '日期': row['日期'],
                **parsed,
            }
        )

    if not parsed_rows:
        raise ValueError('未找到可展示的主睡眠作息记录')

    parsed_frame = pd.DataFrame(parsed_rows).sort_values('日期')
    dates = parsed_frame['日期'].tolist()
    bedtime_wrapped = parsed_frame['bedtime_wrapped_hour'].to_numpy(dtype=float)
    wake_wrapped = parsed_frame['wake_wrapped_hour'].to_numpy(dtype=float)
    summary_frame = parsed_frame.tail(SLEEP_SCHEDULE_SUMMARY_POINTS)
    axis_max = max(
        SLEEP_SCHEDULE_DEFAULT_AXIS_MAX,
        int(np.ceil(max(float(bedtime_wrapped.max()), float(wake_wrapped.max())) / SLEEP_SCHEDULE_AXIS_INTERVAL))
        * SLEEP_SCHEDULE_AXIS_INTERVAL,
    )

    option = {
        'color': [
            plot_module.COLORS['purple'],
            plot_module.COLORS['green'],
        ],
        'tooltip': {'trigger': 'axis'},
        'legend': {'top': 8},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'dataZoom': [
            {'type': 'inside', 'start': _zoom_start(len(dates), SLEEP_SCHEDULE_SUMMARY_POINTS), 'end': 100},
            {
                'type': 'slider',
                'start': _zoom_start(len(dates), SLEEP_SCHEDULE_SUMMARY_POINTS),
                'end': 100,
                'bottom': 8,
            },
        ],
        'grid': {'top': 72, 'left': 56, 'right': 36, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'time'},
        'yAxis': {
            'type': 'value',
            'name': '时间',
            'min': 12,
            'max': axis_max,
            'interval': SLEEP_SCHEDULE_AXIS_INTERVAL,
        },
        'series': [
            {
                'name': '入睡时间',
                'type': 'line',
                'showSymbol': False,
                'data': _series_points(dates, bedtime_wrapped, 4),
            },
            {
                'name': '起床时间',
                'type': 'line',
                'showSymbol': False,
                'data': _series_points(dates, wake_wrapped, 4),
            },
        ],
    }

    return _build_chart(
        'sleep-schedule',
        '作息趋势',
        '把主睡眠的入睡时间和起床时间放到同一条时间轴上，并按起床当天归属，直接看作息是提前还是后移。',
        option,
        formatter='sleep-schedule',
        height=500,
        summary=[
            {'label': '最近入睡', 'value': _format_clock_text(parsed_frame['bedtime_hour'].iloc[-1])},
            {'label': '最近起床', 'value': _format_clock_text(parsed_frame['wake_hour'].iloc[-1])},
            {'label': '平均入睡', 'value': _format_clock_text(summary_frame['bedtime_wrapped_hour'].mean())},
            {'label': '平均起床', 'value': _format_clock_text(summary_frame['wake_wrapped_hour'].mean())},
            {'label': '样本天数', 'value': str(len(parsed_frame))},
        ],
    )


def _build_time_allocation_dashboard_chart(trend):
    filtered_df = trend['filtered_df']
    valid_sleep_hours = trend['valid_sleep_hours']
    valid_screen_hours = trend['valid_screen_hours']
    remaining_hours = trend['remaining_hours']
    dates = [_to_chart_date(value) for value in filtered_df['日期'].tolist()]

    option = {
        'color': [
            plot_module.COLORS['green'],
            plot_module.COLORS['orange'],
            plot_module.COLORS['lightblue'],
        ],
        'tooltip': {'trigger': 'axis', 'axisPointer': {'type': 'shadow'}},
        'legend': {'top': 8},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'dataZoom': [
            {'type': 'inside', 'start': _zoom_start(len(dates), 30), 'end': 100},
            {'type': 'slider', 'start': _zoom_start(len(dates), 30), 'end': 100, 'bottom': 8},
        ],
        'grid': {'top': 72, 'left': 56, 'right': 24, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'category', 'data': dates},
        'yAxis': {'type': 'value', 'name': '小时'},
        'series': [
            {'name': '睡眠时间', 'type': 'bar', 'stack': 'hours', 'data': _category_values(valid_sleep_hours)},
            {'name': '手机屏幕使用时间', 'type': 'bar', 'stack': 'hours', 'data': _category_values(valid_screen_hours)},
            {'name': '剩余时间', 'type': 'bar', 'stack': 'hours', 'data': _category_values(remaining_hours)},
        ],
    }

    return _build_chart(
        'time-allocation',
        '每日时间分配',
        '把睡眠、手机屏幕和剩余时间放进同一张可缩放堆叠图里，替代原始静态柱状图。',
        option,
        formatter='hours',
        height=430,
        summary=[
            {'label': '平均睡眠', 'value': f"{_to_chart_number(np.mean(valid_sleep_hours), 2)} h"},
            {'label': '平均屏幕时间', 'value': f"{_to_chart_number(np.mean(valid_screen_hours), 2)} h"},
            {'label': '平均剩余时间', 'value': f"{_to_chart_number(np.mean(remaining_hours), 2)} h"},
        ],
    )


def _build_time_screen_remaining_dashboard_chart(trend):
    screen_dates = trend['screen_df']['日期'].tolist()
    remaining_dates = trend['remaining_df']['日期'].tolist()

    option = {
        'color': [
            plot_module.COLORS['orange'],
            plot_module.COLORS['lightblue'],
            plot_module.COLORS['orange'],
            plot_module.COLORS['lightblue'],
        ],
        'tooltip': {'trigger': 'axis'},
        'legend': {'top': 8},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'dataZoom': [
            {'type': 'inside', 'start': _zoom_start(len(screen_dates), 45), 'end': 100},
            {'type': 'slider', 'start': _zoom_start(len(screen_dates), 45), 'end': 100, 'bottom': 8},
        ],
        'grid': {'top': 72, 'left': 56, 'right': 24, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'time'},
        'yAxis': {'type': 'value', 'name': '小时'},
        'series': [
            {
                'name': '手机屏幕使用时间',
                'type': 'line',
                'showSymbol': False,
                'data': _series_points(screen_dates, trend['valid_screen_hours']),
            },
            {
                'name': '剩余时间',
                'type': 'line',
                'showSymbol': False,
                'data': _series_points(remaining_dates, trend['remaining_hours']),
            },
            {
                'name': '平均手机屏幕使用时间',
                'type': 'line',
                'showSymbol': False,
                'lineStyle': {'type': 'dashed', 'width': 2.0},
                'data': _series_points(screen_dates, trend['y2']),
            },
            {
                'name': '平均剩余时间',
                'type': 'line',
                'showSymbol': False,
                'lineStyle': {'type': 'dashed', 'width': 2.0},
                'data': _series_points(remaining_dates, trend['y3']),
            },
        ],
    }

    return _build_chart(
        'time-screen-remaining',
        '手机屏幕时间 vs 剩余时间',
        '保留原始数值与均线，对比屏幕占用和当天可支配时间的相对变化。',
        option,
        formatter='hours',
        height=430,
    )


def _build_time_averages_dashboard_chart(trend):
    sleep_dates = trend['sleep_df']['日期'].tolist()
    screen_dates = trend['screen_df']['日期'].tolist()
    remaining_dates = trend['remaining_df']['日期'].tolist()

    option = {
        'color': [
            plot_module.COLORS['green'],
            plot_module.COLORS['green'],
            plot_module.COLORS['orange'],
            plot_module.COLORS['orange'],
            plot_module.COLORS['lightblue'],
            plot_module.COLORS['lightblue'],
        ],
        'tooltip': {'trigger': 'axis'},
        'legend': {'top': 8},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'dataZoom': [
            {'type': 'inside', 'start': _zoom_start(len(sleep_dates), 45), 'end': 100},
            {'type': 'slider', 'start': _zoom_start(len(sleep_dates), 45), 'end': 100, 'bottom': 8},
        ],
        'grid': {'top': 72, 'left': 56, 'right': 24, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'time'},
        'yAxis': {'type': 'value', 'name': '小时'},
        'series': [
            {'name': '平均睡眠时间', 'type': 'line', 'showSymbol': False, 'data': _series_points(sleep_dates, trend['y1'])},
            {
                'name': '目标睡眠时间 8h',
                'type': 'line',
                'showSymbol': False,
                'lineStyle': {'type': 'dashed', 'width': 1.8},
                'data': _series_points(sleep_dates, np.full(len(sleep_dates), 8.0)),
            },
            {
                'name': '平均手机屏幕使用时间',
                'type': 'line',
                'showSymbol': False,
                'data': _series_points(screen_dates, trend['y2']),
            },
            {
                'name': '目标屏幕时间 4h',
                'type': 'line',
                'showSymbol': False,
                'lineStyle': {'type': 'dashed', 'width': 1.8},
                'data': _series_points(screen_dates, np.full(len(screen_dates), 4.0)),
            },
            {'name': '平均剩余时间', 'type': 'line', 'showSymbol': False, 'data': _series_points(remaining_dates, trend['y3'])},
            {
                'name': '目标剩余时间 12h',
                'type': 'line',
                'showSymbol': False,
                'lineStyle': {'type': 'dashed', 'width': 1.8},
                'data': _series_points(remaining_dates, np.full(len(remaining_dates), 12.0)),
            },
        ],
    }

    return _build_chart(
        'time-averages',
        '时间均线 vs 目标',
        '把睡眠、屏幕和剩余时间放进同一个目标对照图，直接看长期偏离方向。',
        option,
        formatter='hours',
        height=430,
    )


def _build_time_delta_dashboard_chart(trend):
    sleep_dates = trend['sleep_df']['日期'].tolist()
    screen_dates = trend['screen_df']['日期'].tolist()
    remaining_dates = trend['remaining_df']['日期'].tolist()

    option = {
        'color': [
            plot_module.COLORS['green'],
            plot_module.COLORS['orange'],
            plot_module.COLORS['lightblue'],
        ],
        'tooltip': {'trigger': 'axis'},
        'legend': {'top': 8},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'dataZoom': [
            {'type': 'inside', 'start': _zoom_start(len(sleep_dates), 45), 'end': 100},
            {'type': 'slider', 'start': _zoom_start(len(sleep_dates), 45), 'end': 100, 'bottom': 8},
        ],
        'grid': {'top': 72, 'left': 56, 'right': 24, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'time'},
        'yAxis': {'type': 'value', 'name': '距离目标的差值 (小时)'},
        'series': [
            {'name': '平均睡眠时间 - 8h', 'type': 'line', 'showSymbol': False, 'data': _series_points(sleep_dates, trend['y1'] - 8.0)},
            {
                'name': '平均手机屏幕使用时间 - 4h',
                'type': 'line',
                'showSymbol': False,
                'data': _series_points(screen_dates, trend['y2'] - 4.0),
            },
            {'name': '平均剩余时间 - 12h', 'type': 'line', 'showSymbol': False, 'data': _series_points(remaining_dates, trend['y3'] - 12.0)},
        ],
    }

    return _build_chart(
        'time-delta',
        '距离目标的差距',
        '把三条时间目标统一换算成偏差值，负值和正值的变化会更直观。',
        option,
        formatter='hours-delta',
        height=430,
    )


def _find_date_column(data_frame):
    if '日期' in data_frame.columns:
        return '日期'
    for column in data_frame.columns:
        if pd.api.types.is_datetime64_any_dtype(data_frame[column]):
            return column
    return None


def _prepare_radar_time_frame(trend):
    frame = trend['filtered_df'].copy().reset_index(drop=True)
    frame['_sleep_hours'] = np.asarray(trend['valid_sleep_hours'], dtype=float)
    frame['_screen_hours'] = np.asarray(trend['valid_screen_hours'], dtype=float)
    frame['_remaining_hours'] = np.asarray(trend['remaining_hours'], dtype=float)

    date_column = _find_date_column(frame)
    if date_column is None:
        return frame

    frame['_window_date'] = pd.to_datetime(frame[date_column], errors='coerce')
    return frame.dropna(subset=['_window_date']).sort_values('_window_date')


def _prepare_radar_body_frame(data_frame):
    frame = data_frame.copy()
    measurement_columns = [column for column in ['体重', '体脂率'] if column in frame.columns]
    if measurement_columns:
        for column in measurement_columns:
            frame[column] = pd.to_numeric(frame[column], errors='coerce')
        frame = frame.dropna(subset=measurement_columns, how='all')

    date_column = _find_date_column(frame)
    if date_column is None:
        return frame

    frame['_window_date'] = pd.to_datetime(frame[date_column], errors='coerce')
    return frame.dropna(subset=['_window_date']).sort_values('_window_date')


def _select_goal_window(frame, window_name, days=30):
    if frame.empty:
        return frame

    if '_window_date' not in frame.columns:
        if window_name == 'month':
            return frame.tail(days)
        if window_name == 'latest':
            return frame.tail(1)
        return frame

    sorted_frame = frame.sort_values('_window_date')
    if window_name == 'month':
        anchor_date = sorted_frame['_window_date'].max()
        cutoff_date = anchor_date - pd.Timedelta(days=days - 1)
        return sorted_frame[
            (sorted_frame['_window_date'] >= cutoff_date)
            & (sorted_frame['_window_date'] <= anchor_date)
        ]
    if window_name == 'latest':
        anchor_date = sorted_frame['_window_date'].max()
        return sorted_frame[sorted_frame['_window_date'] == anchor_date].tail(1)
    return sorted_frame


def _numeric_mean(frame, column_name):
    if column_name not in frame.columns:
        return None
    values = pd.to_numeric(frame[column_name], errors='coerce').dropna()
    if values.empty:
        return None
    return float(values.mean())


def _goal_score(value, *, compare_mode, goal, min=None, max=None):
    if value is None:
        return None
    kwargs = {'compare_mode': compare_mode, 'goal': goal}
    if min is not None:
        kwargs['min'] = min
    if max is not None:
        kwargs['max'] = max
    return plot_module.compute_score(value, **kwargs)


def _build_goal_score_values(time_window, body_window):
    return [
        _goal_score(_numeric_mean(time_window, '_sleep_hours'), compare_mode='bigger_than', goal=8, min=5),
        _goal_score(_numeric_mean(time_window, '_screen_hours'), compare_mode='smaller_than', goal=4, max=24),
        _goal_score(_numeric_mean(time_window, '_remaining_hours'), compare_mode='bigger_than', goal=12, min=4),
        _goal_score(_numeric_mean(body_window, '体重'), compare_mode='smaller_than', goal=65, max=75),
        _goal_score(_numeric_mean(body_window, '体脂率'), compare_mode='smaller_than', goal=15, max=30),
    ]


def _average_goal_score(values):
    valid_values = [value for value in values if value is not None]
    if not valid_values:
        return None
    return float(np.mean(valid_values))


def _build_radar_goal_dashboard_chart(data_frame, trend):
    time_frame = _prepare_radar_time_frame(trend)
    body_frame = _prepare_radar_body_frame(data_frame)
    labels = ['睡眠时间', '手机屏幕时间', '剩余时间', '体重', '体脂率']
    window_specs = [
        ('全部历史平均', '历史综合达成率', 'all'),
        ('近30天平均', '近30天综合达成率', 'month'),
        ('最新一天', '最新一天综合达成率', 'latest'),
    ]
    radar_items = []
    summary = []
    for series_name, summary_label, window_name in window_specs:
        values = _build_goal_score_values(
            _select_goal_window(time_frame, window_name),
            _select_goal_window(body_frame, window_name),
        )
        rounded_values = _category_values(values, 1)
        radar_items.append({'value': rounded_values, 'name': series_name})

        average_score = _average_goal_score(values)
        summary_value = '--' if average_score is None else f"{_to_chart_number(average_score, 0)} %"
        summary.append({'label': summary_label, 'value': summary_value})

    option = {
        'color': [plot_module.COLORS['green'], plot_module.COLORS['blue'], plot_module.COLORS['orange']],
        'tooltip': {'trigger': 'item'},
        'legend': {'top': 8, 'data': [item['name'] for item in radar_items]},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'radar': {
            'radius': '62%',
            'indicator': [{'name': label, 'max': 100} for label in labels],
            'splitNumber': 5,
        },
        'series': [
            {
                'name': '目标达成率',
                'type': 'radar',
                'areaStyle': {'opacity': 0.12},
                'data': radar_items,
            }
        ],
    }

    return _build_chart(
        'radar-goal',
        '目标达成率雷达图',
        '同时对比全部历史、近30天和最新一天的目标达成率，避免把长期平均误看成当天表现。',
        option,
        formatter='percent',
        height=400,
        summary=summary,
    )


def _build_hhh_frequency_dashboard_chart(data_frame):
    if 'HHH' not in data_frame.columns:
        raise ValueError('未找到 HHH 列')

    hhh_data = _build_hhh_event_frame_for_dashboard(data_frame)
    if hhh_data.empty:
        raise ValueError('HHH 数据为空')

    sexual_intercourse = hhh_data[hhh_data['HHH'] > 0].sort_values('日期')
    masturbation = hhh_data[hhh_data['HHH'] < 0].sort_values('日期')

    option = {
        'color': [plot_module.COLORS['blue'], plot_module.COLORS['red']],
        'tooltip': {'trigger': 'item'},
        'legend': {'top': 8},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'dataZoom': [{'type': 'inside'}, {'type': 'slider', 'bottom': 8}],
        'grid': {'top': 72, 'left': 56, 'right': 24, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'time'},
        'yAxis': {'type': 'value', 'name': '频次'},
        'series': [
            {
                'name': '性生活',
                'type': 'scatter',
                'symbolSize': 10,
                'data': _series_points(
                    sexual_intercourse['日期'].tolist(),
                    sexual_intercourse['HHH'].to_numpy(dtype=float),
                ),
            },
            {
                'name': '自慰',
                'type': 'scatter',
                'symbolSize': 10,
                'data': _series_points(
                    masturbation['日期'].tolist(),
                    np.abs(masturbation['HHH'].to_numpy(dtype=float)),
                ),
            },
        ],
    }

    return _build_chart(
        'hhh-frequency',
        'HHH 频率分布',
        '把历史散点直接做成交互式频率图，悬浮即可看具体时间点和强度。',
        option,
        formatter='count',
        height=400,
        summary=[
            {'label': '性生活总次数', 'value': _format_hhh_count_total(sexual_intercourse['HHH'])},
            {'label': '自慰总次数', 'value': _format_hhh_count_total(masturbation['HHH'])},
        ],
    )


def _build_hhh_interval_dashboard_chart(data_frame):
    if 'HHH' not in data_frame.columns:
        raise ValueError('未找到 HHH 列')

    hhh_data = _build_hhh_event_frame_for_dashboard(data_frame)

    sexual_intercourse = hhh_data[hhh_data['HHH'] > 0].sort_values('日期')
    masturbation = hhh_data[hhh_data['HHH'] < 0].sort_values('日期')

    intercourse_points, intercourse_intervals = (
        _calculate_date_interval_points(sexual_intercourse['日期'])
        if not sexual_intercourse.empty
        else ([], [])
    )
    masturbation_points, masturbation_intervals = (
        _calculate_date_interval_points(masturbation['日期'])
        if not masturbation.empty
        else ([], [])
    )

    if not intercourse_intervals and not masturbation_intervals:
        raise ValueError('HHH 间隔数据不足')

    option = {
        'color': [plot_module.COLORS['blue'], plot_module.COLORS['red']],
        'tooltip': {'trigger': 'axis'},
        'legend': {'top': 8},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'dataZoom': [{'type': 'inside'}, {'type': 'slider', 'bottom': 8}],
        'grid': {'top': 72, 'left': 64, 'right': 70, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'time'},
        'yAxis': [
            {'type': 'value', 'name': '性生活间隔（天）', 'min': 0},
            {'type': 'value', 'name': '自慰间隔（天）', 'min': 0},
        ],
        'series': [
            {'name': '性生活间隔（天）', 'type': 'line', 'showSymbol': True, 'yAxisIndex': 0, 'data': intercourse_points},
            {'name': '自慰间隔（天）', 'type': 'line', 'showSymbol': True, 'yAxisIndex': 1, 'data': masturbation_points},
        ],
    }

    summary = []
    if intercourse_intervals:
        summary.append({'label': '性生活平均间隔', 'value': f"{_to_chart_number(np.mean(intercourse_intervals), 1)} 天"})
    if masturbation_intervals:
        summary.append({'label': '自慰平均间隔', 'value': f"{_to_chart_number(np.mean(masturbation_intervals), 1)} 天"})

    return _build_chart(
        'hhh-interval',
        'HHH 间隔趋势',
        '按真实日期展示每次间隔，左右轴分别承载两类节奏，避免小间隔被长间隔压扁。',
        option,
        formatter='days',
        height=400,
        summary=summary,
    )


def _build_balance_dashboard_chart():
    source_balance_df = plot_module.load_balance_sheet().copy().sort_values('日期')
    balance_df = plot_module.filter_balance_sheet_actuals(source_balance_df).sort_values('日期')
    if balance_df.empty:
        raise ValueError('资产数据为空')

    dates = balance_df['日期'].tolist()
    balance_col = plot_module._find_balance_column(
        balance_df,
        ['现金及现金等价物+股票', '实际/预测期末现金+股票', '现金及现金等价物'],
    )
    if balance_col is None:
        raise ValueError('未找到现金及现金等价物字段')

    forecast_series_df = plot_module.build_balance_sheet_forecast_series(
        source_balance_df,
        include_anchor=True,
    )

    series = [
        {
            'name': '现金及现金等价物+股票',
            'type': 'line',
            'showSymbol': False,
            'smooth': True,
            'lineStyle': {'width': 3},
            'areaStyle': {'opacity': 0.08},
            'data': _series_points(dates, balance_df[balance_col].to_numpy(dtype=float), 0),
        },
        {'name': '支付宝资产', 'type': 'line', 'showSymbol': False, 'data': _series_points(dates, balance_df['支付宝资产'].to_numpy(dtype=float), 0)},
        {'name': '银行卡资产', 'type': 'line', 'showSymbol': False, 'data': _series_points(dates, balance_df['银行卡资产'].to_numpy(dtype=float), 0)},
        {'name': '微信资产', 'type': 'line', 'showSymbol': False, 'data': _series_points(dates, balance_df['微信资产'].to_numpy(dtype=float), 0)},
        {'name': '股票资产', 'type': 'line', 'showSymbol': False, 'data': _series_points(dates, balance_df['股票资产'].to_numpy(dtype=float), 0)},
        {'name': '日均支出', 'type': 'line', 'showSymbol': False, 'smooth': True, 'yAxisIndex': 1, 'data': _series_points(dates, balance_df['日均支出'].to_numpy(dtype=float), 0)},
    ]

    if not forecast_series_df.empty and len(forecast_series_df) > 1:
        series.append(
            {
                'name': '预测期末现金+股票',
                'type': 'line',
                'showSymbol': False,
                'smooth': True,
                'lineStyle': {'width': 2, 'type': 'dashed'},
                'data': _forecast_balance_points(forecast_series_df),
            }
        )

    option = {
        'color': [
            plot_module.COLORS['blue'],
            plot_module.COLORS['green'],
            plot_module.COLORS['orange'],
            plot_module.COLORS['purple'],
            plot_module.COLORS['red'],
            plot_module.COLORS['lightblue'],
            plot_module.COLORS['gray'],
        ],
        'tooltip': {'trigger': 'axis'},
        'legend': {
            'top': 8,
            'selected': {
                '支付宝资产': False,
                '银行卡资产': False,
                '微信资产': False,
                '股票资产': False,
            },
        },
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'dataZoom': [
            {'type': 'inside', 'start': 0, 'end': 100},
            {'type': 'slider', 'start': 0, 'end': 100, 'bottom': 8},
        ],
        'grid': {'top': 72, 'left': 56, 'right': 56, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'time'},
        'yAxis': [
            {'type': 'value', 'name': '资产 (元)'},
            {'type': 'value', 'name': '日均支出 (元/天)', 'position': 'right'},
        ],
        'series': series,
    }

    latest_row = balance_df.iloc[-1]
    return _build_chart(
        'balance',
        '资产与支出',
        '把总资产、分账户资产和日均支出放进同一张可筛选图，而不是只看一张静态资金曲线。',
        option,
        formatter='currency',
        height=430,
        summary=[
            {'label': '最新总资产', 'value': f"¥{int(round(float(latest_row[balance_col]))):,}"},
            {'label': '最新日均支出', 'value': f"¥{int(round(float(latest_row['日均支出']))):,}/天"},
        ],
    )


def _build_running_dashboard_chart(running_df):
    dashboard_frames = running_df.attrs.get('dashboard_frames') or {}
    running_df = dashboard_frames.get('running', running_df).copy()
    running_df = running_df.dropna(subset=['pace_min_per_km', 'distance_km'], how='all').sort_values('日期')
    if running_df.empty:
        raise ValueError('未找到可展示的跑步配速数据')

    dates = running_df['日期'].tolist()
    pace_df = running_df.dropna(subset=['pace_min_per_km']).copy()
    heart_df = dashboard_frames.get('running-heart')
    if heart_df is None:
        heart_df = running_df.dropna(subset=['heart_rate_bpm']).copy()
    else:
        heart_df = heart_df.copy().dropna(subset=['heart_rate_bpm']).sort_values('日期')
    distance_df = running_df.dropna(subset=['distance_km']).copy()
    series = []

    if not pace_df.empty:
        series.append(
            {
                'name': '配速 Pace (min/km)',
                'type': 'line',
                'showSymbol': True,
                'symbolSize': 7,
                'smooth': True,
                'data': _series_points(pace_df['日期'].tolist(), pace_df['pace_min_per_km'].to_numpy(dtype=float), 2),
            }
        )

    if not heart_df.empty:
        series.append(
            {
                'name': '心率 Heart Rate (bpm)',
                'type': 'line',
                'showSymbol': False,
                'smooth': True,
                'yAxisIndex': 1,
                'data': _series_points(heart_df['日期'].tolist(), heart_df['heart_rate_bpm'].to_numpy(dtype=float), 0),
            }
        )

    if not distance_df.empty:
        series.append(
            {
                'name': '距离 Distance (km)',
                'type': 'line',
                'showSymbol': False,
                'smooth': True,
                'yAxisIndex': 2,
                'data': _series_points(distance_df['日期'].tolist(), distance_df['distance_km'].to_numpy(dtype=float), 2),
            }
        )

    option = {
        'color': ['#4f7cff', '#f97360', '#3ea37c'],
        'tooltip': {'trigger': 'axis'},
        'legend': {'top': 8},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'dataZoom': [
            {'type': 'inside', 'start': _zoom_start(len(dates), 30), 'end': 100},
            {'type': 'slider', 'start': _zoom_start(len(dates), 30), 'end': 100, 'bottom': 8},
        ],
        'grid': {'top': 72, 'left': 56, 'right': 108, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'time'},
        'yAxis': [
            {'type': 'value', 'name': '配速 (min/km)', 'scale': True, 'inverse': True},
            {'type': 'value', 'name': '心率 (bpm)', 'position': 'right', 'scale': True},
            {'type': 'value', 'name': '距离 (km)', 'position': 'right', 'offset': 64, 'scale': True},
        ],
        'series': series,
    }

    latest_row = running_df.iloc[-1]
    total_distance = running_df['distance_km'].dropna().sum()
    total_duration = running_df['duration_min'].dropna().sum()
    summary = [
        {'label': '最新配速', 'value': latest_row.get('pace_mmss') or f"{_to_chart_number(latest_row['pace_min_per_km'], 2)} /km"},
        {'label': '最新距离', 'value': f"{_to_chart_number(latest_row['distance_km'], 2)} km"},
        {'label': '总跑量', 'value': f"{_to_chart_number(total_distance, 2)} km"},
        {'label': '总跑步时间', 'value': _format_total_minutes(total_duration)},
    ]
    if pd.notna(latest_row.get('heart_rate_bpm')):
        summary.append({'label': '最新心率', 'value': f"{_to_chart_number(latest_row['heart_rate_bpm'], 0)} bpm"})
    duration_value = latest_row.get('duration_mmss')
    if isinstance(duration_value, str) and duration_value:
        summary.append({'label': '最近用时', 'value': duration_value})

    return _build_chart(
        'running',
        '跑步配速-心率耦合',
        '把配速、心率与距离放在同一时间轴上，直接观察节奏变化时心肺负荷是否同步变化。',
        option,
        formatter='generic',
        height=430,
        summary=summary,
    )


def _build_running_form_dashboard_chart(running_df):
    dashboard_frames = running_df.attrs.get('dashboard_frames') or {}
    running_df = dashboard_frames.get('running-form', running_df).copy()
    running_df = running_df.dropna(subset=['duration_min', 'cadence_spm', 'stride_m']).sort_values('日期')
    if running_df.empty:
        raise ValueError('未找到可展示的跑步技术结构数据')

    dates = running_df['日期'].tolist()
    series = []

    if running_df['duration_min'].notna().any():
        series.append(
            {
                'name': '用时 Duration (min)',
                'type': 'line',
                'showSymbol': True,
                'symbolSize': 7,
                'smooth': True,
                'data': _series_points(dates, running_df['duration_min'].to_numpy(dtype=float), 1),
            }
        )

    if running_df['cadence_spm'].notna().any():
        series.append(
            {
                'name': '步频 Cadence (spm)',
                'type': 'line',
                'showSymbol': False,
                'smooth': True,
                'yAxisIndex': 1,
                'data': _series_points(dates, running_df['cadence_spm'].to_numpy(dtype=float), 0),
            }
        )

    if running_df['stride_m'].notna().any():
        series.append(
            {
                'name': '步幅 Stride (m)',
                'type': 'line',
                'showSymbol': False,
                'smooth': True,
                'yAxisIndex': 2,
                'data': _series_points(dates, running_df['stride_m'].to_numpy(dtype=float), 2),
            }
        )

    option = {
        'color': ['#4f7cff', '#ff9f43', '#17a2b8'],
        'tooltip': {'trigger': 'axis'},
        'legend': {'top': 8},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'dataZoom': [
            {'type': 'inside', 'start': _zoom_start(len(dates), 30), 'end': 100},
            {'type': 'slider', 'start': _zoom_start(len(dates), 30), 'end': 100, 'bottom': 8},
        ],
        'grid': {'top': 72, 'left': 56, 'right': 108, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'time'},
        'yAxis': [
            {'type': 'value', 'name': '用时 (min)', 'scale': True},
            {'type': 'value', 'name': '步频 (spm)', 'position': 'right', 'scale': True},
            {'type': 'value', 'name': '步幅 (m)', 'position': 'right', 'offset': 64, 'scale': True},
        ],
        'series': series,
    }

    latest_row = running_df.iloc[-1]
    summary = []
    duration_value = latest_row.get('duration_mmss')
    if isinstance(duration_value, str) and duration_value:
        summary.append({'label': '最近用时', 'value': duration_value})
    cadence_mean = running_df['cadence_spm'].dropna().mean()
    if pd.notna(cadence_mean):
        summary.append({'label': '平均步频', 'value': f"{_to_chart_number(cadence_mean, 0)} spm"})
    stride_mean = running_df['stride_m'].dropna().mean()
    if pd.notna(stride_mean):
        summary.append({'label': '平均步幅', 'value': f"{_to_chart_number(stride_mean, 2)} m"})

    return _build_chart(
        'running-form',
        '跑步技术结构',
        '把单次用时、步频、步幅放在一起，更容易看清动作结构是否稳定，而不是只看单一配速。',
        option,
        formatter='generic',
        height=400,
        summary=summary,
    )


def _build_running_hrc_dashboard_chart(running_df):
    dashboard_frames = running_df.attrs.get('dashboard_frames') or {}
    running_df = dashboard_frames.get('running-hrc', running_df).copy()
    running_df = running_df.dropna(subset=['heart_rate_bpm', 'HRC_m_per_beat']).sort_values('日期')
    if running_df.empty:
        raise ValueError('未找到可展示的 HRC 数据')

    rolling_window = min(len(running_df), 5)
    running_df['HRC_rolling'] = running_df['HRC_m_per_beat'].rolling(window=rolling_window, min_periods=1).mean()
    dates = running_df['日期'].tolist()
    option = {
        'color': ['#1f7a5a', '#83c5a3'],
        'tooltip': {'trigger': 'axis'},
        'legend': {'top': 8},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'dataZoom': [
            {'type': 'inside', 'start': _zoom_start(len(dates), 30), 'end': 100},
            {'type': 'slider', 'start': _zoom_start(len(dates), 30), 'end': 100, 'bottom': 8},
        ],
        'grid': {'top': 72, 'left': 56, 'right': 36, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'time'},
        'yAxis': [{'type': 'value', 'name': 'HRC (m/beat)', 'scale': True}],
        'series': [
            {
                'name': 'HRC (m/beat)',
                'type': 'line',
                'showSymbol': True,
                'symbolSize': 7,
                'smooth': True,
                'data': _series_points(dates, running_df['HRC_m_per_beat'].to_numpy(dtype=float), 3),
            },
            {
                'name': f'Rolling HRC ({rolling_window})',
                'type': 'line',
                'showSymbol': False,
                'smooth': True,
                'lineStyle': {'type': 'dashed', 'width': 2},
                'data': _series_points(dates, running_df['HRC_rolling'].to_numpy(dtype=float), 3),
            },
        ],
    }

    latest_row = running_df.iloc[-1]
    summary = [
        {'label': '最新 HRC', 'value': f"{_to_chart_number(latest_row['HRC_m_per_beat'], 3)} m/beat"},
        {'label': '最佳 HRC', 'value': f"{_to_chart_number(running_df['HRC_m_per_beat'].max(), 3)} m/beat"},
        {'label': f'{rolling_window}次均值', 'value': f"{_to_chart_number(running_df['HRC_rolling'].iloc[-1], 3)} m/beat"},
    ]
    if pd.notna(latest_row.get('heart_rate_bpm')):
        summary.append({'label': '对应心率', 'value': f"{_to_chart_number(latest_row['heart_rate_bpm'], 0)} bpm"})

    return _build_chart(
        'running-hrc',
        'Heart Rate Cost of Running (HRC)',
        '这里按速度 ÷ 心率计算 HRC，单位是 m/beat。数值越高，表示单位心搏支持的前进效率越高。',
        option,
        formatter='generic',
        height=400,
        summary=summary,
    )


def build_plot_dashboard_data():
    data_frame = plot_module.load_time_data()
    time_trend_payload = None
    time_trend_error = None
    running_metrics = None
    running_metrics_error = None
    warnings = []

    try:
        time_trend_payload = _compute_time_trend_payload(data_frame)
        time_warning = _build_time_data_warning(time_trend_payload.get('warnings'))
        if time_warning is not None:
            warnings.append(time_warning)
    except Exception as exc:
        time_trend_error = exc

    try:
        running_metrics = plot_module.compute_preferred_running_metrics(data_frame)
        running_warning_rows = list(running_metrics.attrs.get('invalid_rows') or [])
        running_warning_rows.extend(running_metrics.attrs.get('excluded_rows') or [])
        warnings.extend(_build_running_data_warnings(running_warning_rows))
    except Exception as exc:
        running_metrics_error = exc

    def get_time_trend_payload():
        if time_trend_error is not None:
            raise time_trend_error
        return time_trend_payload

    def get_running_metrics():
        if running_metrics_error is not None:
            raise running_metrics_error
        return running_metrics

    charts = [
        _safe_chart(
            'sleep-schedule',
            '作息趋势',
            '把主睡眠的入睡时间和起床时间放到同一条时间轴上，并按起床当天归属，直接看作息是提前还是后移。',
            lambda: _build_sleep_schedule_dashboard_chart(data_frame),
            formatter='sleep-schedule',
            height=500,
        ),
        _safe_chart(
            'weight-bodyfat',
            '体重 / 体脂率 / 脂肪质量趋势',
            '保留现有计算口径，用交互式多轴折线替代多张静态体重图。',
            lambda: _build_weight_bodyfat_dashboard_chart(data_frame),
            formatter='weight-bodyfat',
            height=430,
        ),
        _safe_chart(
            'time-allocation',
            '每日时间分配',
            '把睡眠、手机屏幕和剩余时间放进同一张可缩放堆叠图里，替代原始静态柱状图。',
            lambda: _build_time_allocation_dashboard_chart(get_time_trend_payload()),
            formatter='hours',
            height=430,
        ),
        _safe_chart(
            'time-screen-remaining',
            '手机屏幕时间 vs 剩余时间',
            '保留原始数值与均线，对比屏幕占用和当天可支配时间的相对变化。',
            lambda: _build_time_screen_remaining_dashboard_chart(get_time_trend_payload()),
            formatter='hours',
            height=430,
        ),
        _safe_chart(
            'time-averages',
            '时间均线 vs 目标',
            '把睡眠、屏幕和剩余时间放进同一个目标对照图，直接看长期偏离方向。',
            lambda: _build_time_averages_dashboard_chart(get_time_trend_payload()),
            formatter='hours',
            height=430,
        ),
        _safe_chart(
            'time-delta',
            '距离目标的差距',
            '把三条时间目标统一换算成偏差值，负值和正值的变化会更直观。',
            lambda: _build_time_delta_dashboard_chart(get_time_trend_payload()),
            formatter='hours-delta',
            height=430,
        ),
        _safe_chart(
            'radar-goal',
            '目标达成率雷达图',
            '保留原来的达成率口径，但把它做成交互式雷达图，便于一眼看结构性短板。',
            lambda: _build_radar_goal_dashboard_chart(data_frame, get_time_trend_payload()),
            formatter='percent',
            height=400,
        ),
        _safe_chart(
            'hhh-frequency',
            'HHH 频率分布',
            '把历史散点直接做成交互式频率图，悬浮即可看具体时间点和强度。',
            lambda: _build_hhh_frequency_dashboard_chart(data_frame),
            formatter='count',
            height=400,
        ),
        _safe_chart(
            'hhh-interval',
            'HHH 间隔趋势',
            '按真实日期展示每次间隔，左右轴分别承载两类节奏，避免小间隔被长间隔压扁。',
            lambda: _build_hhh_interval_dashboard_chart(data_frame),
            formatter='days',
            height=400,
        ),
        _safe_chart(
            'balance',
            '资产与支出',
            '把总资产、分账户资产和日均支出放进同一张可筛选图，而不是只看一张静态资金曲线。',
            _build_balance_dashboard_chart,
            formatter='currency',
            height=430,
        ),

        _safe_chart(
            'running',
            '跑步配速-心率耦合',
            '把配速、心率与距离放在同一时间轴上，直接观察节奏变化时心肺负荷是否同步变化。',
            lambda: _build_running_dashboard_chart(get_running_metrics()),
            formatter='generic',
            height=430,
        ),
        _safe_chart(
            'running-form',
            '跑步技术结构',
            '把单次用时、步频、步幅放在一起，更容易看清动作结构是否稳定，而不是只看单一配速。',
            lambda: _build_running_form_dashboard_chart(get_running_metrics()),
            formatter='generic',
            height=400,
        ),
        _safe_chart(
            'running-hrc',
            'Heart Rate Cost of Running (HRC)',
            '这里按速度 ÷ 心率计算 HRC，单位是 m/beat。数值越高，表示单位心搏支持的前进效率越高。',
            lambda: _build_running_hrc_dashboard_chart(get_running_metrics()),
            formatter='generic',
            height=400,
        ),
    ]

    return {
        'generated_at': pd.Timestamp.now().isoformat(),
        'count': len(charts),
        'charts': charts,
        'warnings': warnings,
    }
