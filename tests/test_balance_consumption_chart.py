import pandas as pd
from unittest.mock import patch

from src.services import plot_dashboard


def frame():
    return pd.DataFrame({
        '日期': pd.to_datetime(['2025-01-31', '2025-02-28']),
        '现金及现金等价物+股票': [1000., 900.],
        '支付宝资产': [1000., 900.], '银行卡资产': [0., 0.],
        '微信资产': [0., 0.], '股票资产': [0., 0.],
        '期间支出': [300., 400.], '日均支出': [30., 40.],
        '实际消费': [100., 0.], '日均消费': [10., 0.],
    })


def chart_for(df):
    with patch.object(plot_dashboard.plot_module, 'load_balance_sheet', return_value=df):
        return plot_dashboard._build_balance_dashboard_chart()


def test_consumption_chart_prefers_new_fields_and_keeps_zero():
    chart = chart_for(frame())
    series = {s['name']: s for s in chart['option']['series']}
    assert [p[1] for p in series['实际消费']['data']] == [100., 0.]
    assert [p[1] for p in series['日均消费']['data']] == [10., 0.]
    assert '日均支出' not in series


def test_consumption_chart_supports_legacy_headers():
    chart = chart_for(frame().drop(columns=['实际消费', '日均消费']))
    series = {s['name']: s for s in chart['option']['series']}
    assert [p[1] for p in series['实际消费']['data']] == [300., 400.]
    assert [p[1] for p in series['日均消费']['data']] == [30., 40.]


def test_consumption_chart_does_not_replace_missing_new_values_with_gross_spend():
    df = frame()
    df.loc[1, ['实际消费', '日均消费']] = float('nan')
    chart = chart_for(df)
    series = {s['name']: s for s in chart['option']['series']}
    assert all(p[0] != '2025-02-28' or p[1] is None for p in series['实际消费']['data'])
    assert all(p[0] != '2025-02-28' or p[1] is None for p in series['日均消费']['data'])
    summaries = {s['label']: s['value'] for s in chart['summary']}
    assert summaries['最新实际消费'] == '—'
    assert summaries['最新日均消费'] == '—'


def test_static_balance_plot_accepts_new_daily_consumption_header(tmp_path):
    df = frame().drop(columns=['日均支出'])
    module = plot_dashboard.plot_module
    with patch.object(module, 'save_figure') as save, patch.object(module.plt, 'tight_layout'):
        module.plot_balance_sheet(df, output_dir=tmp_path)
        fig = save.call_args.args[0]
        try:
            assert fig.axes[0].get_ylabel() == '资产 / 消费 (元)'
            assert fig.axes[1].get_ylabel() == '日均消费'
            assert list(fig.axes[1].lines[0].get_ydata()) == [10., 0.]
        finally:
            module.plt.close(fig)
