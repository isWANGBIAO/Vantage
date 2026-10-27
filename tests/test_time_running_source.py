"""The reviewed Time exercise cells are the running dashboard's sole input."""
from unittest.mock import patch

import pandas as pd
import pytest

from src.scripts import plot
from src.backend import plots


def time_frame(text):
    return pd.DataFrame({'日期':[pd.Timestamp('2001-01-02')], '运动':[text]})


def test_running_runtime_never_reads_offline_exports():
    frame=time_frame('跑步4公里，用时24分，步频160，步幅104厘米（估算）')
    with patch.object(plot,'load_time_data',return_value=frame) as time_loader, patch.object(
        plot,'load_app_running_log_frame',side_effect=AssertionError('offline source accessed'),
    ):
        result=plot.compute_preferred_running_metrics()
    time_loader.assert_called_once()
    assert result.attrs['running_source']=='time_xlsx'
    assert result.iloc[0]['stride_m']==pytest.approx(1.04)
    assert result.iloc[0]['stride_source']=='calculated'


def test_plot_cache_does_not_depend_on_device_exports(tmp_path):
    with patch.object(plots.DataLoader,'resolve_data_path',side_effect=lambda name:tmp_path/name), patch.object(
        plots.DataLoader,'resolve_health_data_root',side_effect=AssertionError('offline source accessed'),
    ):
        key=plots._get_plot_dashboard_cache_key()
    assert len(key)==2
    assert {item[0] for item in key}=={str(tmp_path/'Time.xlsx'),str(tmp_path/'Balance Sheet.xlsx')}


@pytest.mark.parametrize('hr',['','，心率无','，心率0'])
def test_missing_heart_rate_and_gait_are_normal_gaps(hr):
    result=plot.compute_preferred_running_metrics(time_frame('跑步4公里，用时24分'+hr))
    assert pd.isna(result.iloc[0]['heart_rate_bpm'])
    assert pd.isna(result.iloc[0]['HRC_m_per_beat'])
    assert result.attrs['invalid_rows']==[]
    assert len(result.attrs['dashboard_frames']['running'])==1
    assert len(result.attrs['dashboard_frames']['running-form'])==1
    assert result.attrs['dashboard_frames']['running-hrc'].empty


def test_nonzero_implausible_heart_rate_remains_an_error():
    result=plot.compute_preferred_running_metrics(time_frame('跑步4公里，用时24分，心率300'))
    assert pd.isna(result.iloc[0]['heart_rate_bpm'])
    assert any('心率异常值 300' in issue for row in result.attrs['invalid_rows'] for issues in row['issues_by_chart'].values() for issue in issues)


def test_two_runs_keep_numbered_metric_addenda_separate():
    text=('晚上跑步1.4公里，用时10分，心率140；晚上跑步3公里，用时20分，心率160\n'
          '第1次指标补录（20:01:00）：步幅100厘米（计算）\n'
          '第2次指标补录（21:01:00）：步幅110厘米（估算）')
    result=plot.compute_preferred_running_metrics(time_frame(text))
    assert result['distance_km'].tolist()==[1.4,3]
    assert result['duration_min'].tolist()==[10,20]
    assert result['stride_m'].tolist()==[1,1.1]
    assert result['heart_rate_bpm'].tolist()==[140,160]
    assert result['distance_km'].sum()==pytest.approx(4.4)


def test_single_addendum_is_not_a_second_run_and_later_run_is_not_lost():
    text=('跑步4公里，用时24分\n该次指标补录（20:01:00）：步频160，步幅104厘米（估算）')
    first=plot.compute_preferred_running_metrics(time_frame(text))
    assert len(first)==1 and first.iloc[0]['cadence_spm']==160
    later=plot.compute_preferred_running_metrics(time_frame(text+'\n跑步2公里，用时12分，步频170，步幅98厘米'))
    assert later['distance_km'].tolist()==[4,2]
    # An unnumbered addendum is ambiguous after a second run is added; never mix it.
    assert pd.isna(later.iloc[0]['cadence_spm'])
    assert later.iloc[1]['cadence_spm']==170


def test_cycling_and_walking_do_not_supply_a_runs_distance_or_heart_rate():
    text='骑车8公里，用时20分，心率100；跑步3公里，用时18分，心率150，步频160'
    result=plot.compute_preferred_running_metrics(time_frame(text))
    assert result['distance_km'].tolist()==[3]
    assert result['heart_rate_bpm'].tolist()==[150]
    assert plot.compute_preferred_running_metrics(time_frame('骑行8公里，用时20分，心率100')).empty
    assert plot.compute_preferred_running_metrics(time_frame('散步4公里，用时60分，步频100')).empty


def test_inline_numbered_addenda_are_also_bound_to_their_own_runs():
    text=('跑步1.4公里，用时10分；跑步3公里，用时20分；'
          '第1次指标补录（20:01）：步幅100厘米（计算）；'
          '第2次指标补录（21:01）：步幅110厘米（估算）')
    result=plot.compute_preferred_running_metrics(time_frame(text))
    assert result['stride_m'].tolist()==[1,1.1]


def test_mid_run_comment_does_not_create_another_session():
    text='跑步3公里，用时20分，步频160，跑了七分钟后加速\n该次指标补录（20:01）：步幅94厘米（估算）'
    result=plot.compute_preferred_running_metrics(time_frame(text))
    assert len(result)==1
    assert result.iloc[0]['stride_m']==pytest.approx(0.94)


def test_walk_before_numeric_ran_note_does_not_replace_the_runs_metrics():
    text='先走了6km；跑了4km；感觉有点累\n该次指标补录（20:01）：用时24分，心率150，步幅100厘米（计算）'
    result=plot.compute_preferred_running_metrics(time_frame(text))
    assert len(result)==1
    assert result.iloc[0]['distance_km']==4
    assert result.iloc[0]['duration_min']==24
    assert result.iloc[0]['stride_m']==1
