import numpy as np
import pandas as pd

from src.scripts import plot as plot_module

TIME_WARNING_CHART_IDS = [
    'time-allocation',
    'time-screen-remaining',
    'time-averages',
    'time-delta',
    'radar-goal',
]


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


def _series_points(dates, values, digits=2):
    return [
        [_to_chart_date(date), _to_chart_number(value, digits)]
        for date, value in zip(dates, values)
    ]


def _category_values(values, digits=2):
    return [_to_chart_number(value, digits) for value in values]


def _zoom_start(total_points, focus_points=30):
    if total_points <= focus_points:
        return 0
    visible_ratio = focus_points / max(total_points, 1)
    return round((1 - visible_ratio) * 100, 2)


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


def _parse_hhh_value_for_dashboard(value):
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        pass

    parts = value.strip().split()
    for part in reversed(parts):
        try:
            return float(part)
        except (TypeError, ValueError):
            continue
    return None


def _calculate_date_intervals(date_series):
    dates = pd.to_datetime(date_series).sort_values()
    return dates.diff().dt.days.dropna().tolist()


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


def _build_radar_goal_dashboard_chart(data_frame, trend):
    nearest_days = trend['nearest_days']
    score_index = -nearest_days

    average_weight = np.average(data_frame['体重'].dropna().to_numpy())
    average_body_fat_rate = np.average(data_frame['体脂率'].dropna().to_numpy())

    values = [
        plot_module.compute_score(trend['y1'][score_index], compare_mode='bigger_than', goal=8, min=5),
        plot_module.compute_score(trend['y2'][score_index], compare_mode='smaller_than', goal=4, max=24),
        plot_module.compute_score(trend['y3'][score_index], compare_mode='bigger_than', goal=12, min=4),
        plot_module.compute_score(average_weight, compare_mode='smaller_than', goal=65, max=75),
        plot_module.compute_score(average_body_fat_rate, compare_mode='smaller_than', goal=15, max=30),
    ]

    labels = ['睡眠时间', '手机屏幕时间', '剩余时间', '体重', '体脂率']

    option = {
        'color': [plot_module.COLORS['green']],
        'tooltip': {'trigger': 'item'},
        'legend': {'top': 8},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'radar': {
            'radius': '62%',
            'indicator': [{'name': label, 'max': 100} for label in labels],
            'splitNumber': 5,
        },
        'series': [
            {
                'name': f'近 {nearest_days} 天达成率',
                'type': 'radar',
                'areaStyle': {'opacity': 0.2},
                'data': [{'value': _category_values(values, 1), 'name': '目标达成率'}],
            }
        ],
    }

    return _build_chart(
        'radar-goal',
        '目标达成率雷达图',
        '保留原来的达成率口径，但把它做成交互式雷达图，便于一眼看结构性短板。',
        option,
        formatter='percent',
        height=400,
        summary=[
            {'label': label, 'value': f"{_to_chart_number(value, 0)} %"}
            for label, value in zip(labels, values)
        ],
    )


def _build_hhh_frequency_dashboard_chart(data_frame):
    if 'HHH' not in data_frame.columns:
        raise ValueError('未找到 HHH 列')

    hhh_data = data_frame[['日期', 'HHH']].dropna().copy()
    hhh_data['HHH'] = hhh_data['HHH'].apply(_parse_hhh_value_for_dashboard)
    hhh_data = hhh_data.dropna(subset=['HHH'])
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
            {'label': '性生活总次数', 'value': str(len(sexual_intercourse))},
            {'label': '自慰总次数', 'value': str(len(masturbation))},
        ],
    )


def _build_hhh_interval_dashboard_chart(data_frame):
    if 'HHH' not in data_frame.columns:
        raise ValueError('未找到 HHH 列')

    hhh_data = data_frame[['日期', 'HHH']].dropna().copy()
    hhh_data['HHH'] = hhh_data['HHH'].apply(_parse_hhh_value_for_dashboard)
    hhh_data = hhh_data.dropna(subset=['HHH'])

    sexual_intercourse = hhh_data[hhh_data['HHH'] > 0].sort_values('日期')
    masturbation = hhh_data[hhh_data['HHH'] < 0].sort_values('日期')

    intercourse_intervals = _calculate_date_intervals(sexual_intercourse['日期']) if not sexual_intercourse.empty else []
    masturbation_intervals = _calculate_date_intervals(masturbation['日期']) if not masturbation.empty else []

    if not intercourse_intervals and not masturbation_intervals:
        raise ValueError('HHH 间隔数据不足')

    max_length = max(len(intercourse_intervals), len(masturbation_intervals))
    categories = list(range(1, max_length + 1))

    option = {
        'color': [plot_module.COLORS['blue'], plot_module.COLORS['red']],
        'tooltip': {'trigger': 'axis'},
        'legend': {'top': 8},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'grid': {'top': 72, 'left': 56, 'right': 24, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'category', 'name': '第 N 次行为', 'data': categories},
        'yAxis': {'type': 'value', 'name': '间隔天数'},
        'series': [
            {'name': '性生活间隔（天）', 'type': 'line', 'showSymbol': True, 'data': _category_values(intercourse_intervals)},
            {'name': '自慰间隔（天）', 'type': 'line', 'showSymbol': True, 'data': _category_values(masturbation_intervals)},
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
        '把每次间隔天数直接拉成可对比折线，更适合看节奏是否在收敛或发散。',
        option,
        formatter='days',
        height=400,
        summary=summary,
    )


def _build_balance_dashboard_chart():
    balance_df = plot_module.load_balance_sheet().copy().sort_values('日期')
    if balance_df.empty:
        raise ValueError('资产数据为空')

    dates = balance_df['日期'].tolist()
    option = {
        'color': [
            plot_module.COLORS['blue'],
            plot_module.COLORS['green'],
            plot_module.COLORS['orange'],
            plot_module.COLORS['purple'],
            plot_module.COLORS['red'],
            plot_module.COLORS['lightblue'],
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
            {'type': 'inside', 'start': _zoom_start(len(dates), 45), 'end': 100},
            {'type': 'slider', 'start': _zoom_start(len(dates), 45), 'end': 100, 'bottom': 8},
        ],
        'grid': {'top': 72, 'left': 56, 'right': 56, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'time'},
        'yAxis': [
            {'type': 'value', 'name': '资产 (元)'},
            {'type': 'value', 'name': '日均支出 (元/天)', 'position': 'right'},
        ],
        'series': [
            {
                'name': '现金及现金等价物+股票',
                'type': 'line',
                'showSymbol': False,
                'smooth': True,
                'lineStyle': {'width': 3},
                'areaStyle': {'opacity': 0.08},
                'data': _series_points(dates, balance_df['现金及现金等价物+股票'].to_numpy(dtype=float), 0),
            },
            {'name': '支付宝资产', 'type': 'line', 'showSymbol': False, 'data': _series_points(dates, balance_df['支付宝资产'].to_numpy(dtype=float), 0)},
            {'name': '银行卡资产', 'type': 'line', 'showSymbol': False, 'data': _series_points(dates, balance_df['银行卡资产'].to_numpy(dtype=float), 0)},
            {'name': '微信资产', 'type': 'line', 'showSymbol': False, 'data': _series_points(dates, balance_df['微信资产'].to_numpy(dtype=float), 0)},
            {'name': '股票资产', 'type': 'line', 'showSymbol': False, 'data': _series_points(dates, balance_df['股票资产'].to_numpy(dtype=float), 0)},
            {'name': '日均支出', 'type': 'line', 'showSymbol': False, 'smooth': True, 'yAxisIndex': 1, 'data': _series_points(dates, balance_df['日均支出'].to_numpy(dtype=float), 0)},
        ],
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
            {'label': '最新总资产', 'value': f"¥{int(round(float(latest_row['现金及现金等价物+股票']))):,}"},
            {'label': '最新日均支出', 'value': f"¥{int(round(float(latest_row['日均支出']))):,}/天"},
        ],
    )


def _build_running_dashboard_chart(data_frame):
    running_df = plot_module.compute_running_metrics(data_frame).copy()
    running_df = running_df.dropna(subset=['配速_min_per_km']).sort_values('日期')
    if running_df.empty:
        raise ValueError('未找到可展示的跑步配速数据')

    dates = running_df['日期'].tolist()
    series = [
        {
            'name': '配速（min/km）',
            'type': 'line',
            'showSymbol': True,
            'symbolSize': 7,
            'smooth': True,
            'data': _series_points(dates, running_df['配速_min_per_km'].to_numpy(dtype=float), 3),
        },
        {
            'name': '距离（km）',
            'type': 'line',
            'showSymbol': False,
            'smooth': True,
            'yAxisIndex': 1,
            'data': _series_points(dates, running_df['距离_km'].to_numpy(dtype=float), 2),
        },
    ]

    if '心率' in running_df.columns and running_df['心率'].notna().any():
        series.append(
            {
                'name': '心率',
                'type': 'line',
                'showSymbol': False,
                'yAxisIndex': 2,
                'data': _series_points(dates, running_df['心率'].to_numpy(dtype=float), 0),
            }
        )

    option = {
        'color': [
            plot_module.COLORS['purple'],
            plot_module.COLORS['lightblue'],
            plot_module.COLORS['red'],
        ],
        'tooltip': {'trigger': 'axis'},
        'legend': {'top': 8},
        'toolbox': {'right': 12, 'feature': {'saveAsImage': {}}},
        'dataZoom': [
            {'type': 'inside', 'start': _zoom_start(len(dates), 30), 'end': 100},
            {'type': 'slider', 'start': _zoom_start(len(dates), 30), 'end': 100, 'bottom': 8},
        ],
        'grid': {'top': 72, 'left': 56, 'right': 88, 'bottom': 72, 'containLabel': True},
        'xAxis': {'type': 'time'},
        'yAxis': [
            {'type': 'value', 'name': '配速 (min/km)', 'inverse': True},
            {'type': 'value', 'name': '距离 (km)', 'position': 'right'},
            {'type': 'value', 'name': '心率', 'position': 'right', 'offset': 64},
        ],
        'series': series,
    }

    latest_row = running_df.iloc[-1]
    latest_pace = latest_row.get('配速_mmss')
    pace_text = latest_pace if isinstance(latest_pace, str) and latest_pace else _to_chart_number(latest_row['配速_min_per_km'], 2)

    return _build_chart(
        'running',
        '跑步配速',
        '保留跑步配速主线，同时补上距离和心率，让训练质量比静态折线更完整。',
        option,
        formatter='running',
        height=430,
        summary=[
            {'label': '最新配速', 'value': f"{pace_text} /km"},
            {'label': '最新距离', 'value': f"{_to_chart_number(latest_row['距离_km'], 2)} km"},
        ],
    )


def build_plot_dashboard_data():
    data_frame = plot_module.load_time_data()
    time_trend_payload = None
    time_trend_error = None
    warnings = []

    try:
        time_trend_payload = _compute_time_trend_payload(data_frame)
        time_warning = _build_time_data_warning(time_trend_payload.get('warnings'))
        if time_warning is not None:
            warnings.append(time_warning)
    except Exception as exc:
        time_trend_error = exc

    def get_time_trend_payload():
        if time_trend_error is not None:
            raise time_trend_error
        return time_trend_payload

    charts = [
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
            '把每次间隔天数直接拉成可对比折线，更适合看节奏是否在收敛或发散。',
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
            '跑步配速',
            '保留跑步配速主线，同时补上距离和心率，让训练质量比静态折线更完整。',
            lambda: _build_running_dashboard_chart(data_frame),
            formatter='running',
            height=430,
        ),
    ]

    return {
        'generated_at': pd.Timestamp.now().isoformat(),
        'count': len(charts),
        'charts': charts,
        'warnings': warnings,
    }


