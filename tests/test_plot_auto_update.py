"""Source-revision polling never freezes or publishes an incomplete build."""

import asyncio
import json
import os
import threading
from unittest.mock import patch

import httpx
import pandas as pd
import pytest
from fastapi import FastAPI

from src.backend import plots
from src.services import plot_dashboard


@pytest.fixture(autouse=True)
def clean_cache():
    plots._clear_plot_dashboard_cache()
    yield
    plots._clear_plot_dashboard_cache()


def healthy(value=1):
    return {'charts': [{'id': 'synthetic', 'option': {'value': value}, 'error': None}], 'count': 1}


def synthetic_time():
    return pd.DataFrame({'日期': pd.to_datetime(['2001-01-01', '2001-01-02']), '体重': [70, 71],
                         '体脂率': [20, 20], '睡眠时间': ['8小时', '8小时'],
                         '手机屏幕\n使用时间': ['2小时', '2小时'], '起床时间': ['00:00-08:00', '00:00-08:00'],
                         'HHH': [None, None], '运动': ['', '']})


def synthetic_balance():
    return pd.DataFrame({'日期': pd.to_datetime(['2001-01-01']), '实际消费': [10], '日均消费': [10],
                         '现金及现金等价物': [1000], '支付宝资产': [100], '银行卡资产': [900],
                         '微信资产': [0], '股票资产': [0]})


def test_unchanged_revision_avoids_rebuild_and_copy_mutation(monkeypatch):
    monkeypatch.setattr(plots, '_get_plot_dashboard_cache_key', lambda: ('source',))
    with patch.object(plot_dashboard, 'build_plot_dashboard_data', return_value=healthy()) as build:
        first = asyncio.run(plots.get_plot_dashboard_data())
        first['charts'][0]['option']['value'] = 999
        unchanged = asyncio.run(plots.get_plot_dashboard_data(first['source_revision']))
        full = asyncio.run(plots.get_plot_dashboard_data())
    assert unchanged == {'unchanged': True, 'source_revision': first['source_revision']}
    assert full['charts'][0]['option']['value'] == 1
    assert build.call_count == 1


def test_content_fingerprint_detects_same_size_same_mtime_edit(tmp_path):
    source = tmp_path / 'source.xlsx'
    source.write_bytes(b'old-row')
    before = source.stat()
    first = plots._file_signature(source)
    source.write_bytes(b'new-row')
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert plots._file_signature(source) != first
    source.unlink()
    missing = plots._file_signature(source)
    source.write_bytes(b'new-row')
    assert plots._file_signature(source) != missing


def test_locked_workbook_fingerprint_uses_a_disposable_copy(tmp_path, monkeypatch):
    source = tmp_path / 'source.xlsx'
    source.write_bytes(b'synthetic workbook content')
    real_digest = plots._source_digest
    snapshots = []

    def locked_digest(path):
        if path == source:
            raise PermissionError('Synthetic direct-read sharing denial')
        snapshots.append(path)
        return real_digest(path)

    monkeypatch.setattr(plots, '_source_digest', locked_digest)
    first = plots._file_signature(source)
    assert first[-1] == real_digest(source)
    assert snapshots and all(not path.exists() for path in snapshots)
    assert source.read_bytes() == b'synthetic workbook content'
    source.write_bytes(b'changed synthetic workbook')
    assert plots._file_signature(source) != first


def test_locked_workbook_failed_copy_cleans_snapshot_and_does_not_cache(tmp_path, monkeypatch):
    source = tmp_path / 'source.xlsx'
    source.write_bytes(b'synthetic')
    snapshots = []

    def deny(_):
        raise PermissionError('Synthetic sharing denial')

    def failed_copy(_source, destination):
        snapshots.append(destination)
        destination.write_bytes(b'partial copy')
        raise PermissionError('Synthetic copy denial')

    monkeypatch.setattr(plots, '_source_digest', deny)
    monkeypatch.setattr(plots, '_copy_plot_source_for_read', failed_copy)
    monkeypatch.setattr(plots, '_get_plot_dashboard_cache_key', lambda: plots._file_signature(source))
    result = asyncio.run(plots.get_plot_dashboard_data())
    assert result.status_code == 503
    assert plots._plot_dashboard_cache_payload is None
    assert snapshots and all(not path.exists() for path in snapshots)
    assert source.read_bytes() == b'synthetic'


def test_mid_build_edit_retries_before_publishing(monkeypatch):
    version = [1]
    calls = []
    monkeypatch.setattr(plots, '_get_plot_dashboard_cache_key', lambda: (version[0],))

    def build():
        calls.append(version[0])
        result = healthy(version[0])
        version[0] = 2
        return result

    monkeypatch.setattr(plot_dashboard, 'build_plot_dashboard_data', build)
    result = asyncio.run(plots.get_plot_dashboard_data())
    assert result['charts'][0]['option']['value'] == 2
    assert calls == [1, 2]
    assert asyncio.run(plots.get_plot_dashboard_data(result['source_revision']))['unchanged']


def test_repeated_changes_fail_without_caching(monkeypatch):
    version = [0]
    monkeypatch.setattr(plots, '_get_plot_dashboard_cache_key', lambda: (version[0],))

    def build():
        version[0] += 1
        return healthy(version[0])

    monkeypatch.setattr(plot_dashboard, 'build_plot_dashboard_data', build)
    result = asyncio.run(plots.get_plot_dashboard_data())
    assert result.status_code == 503
    assert json.loads(result.body)['retry_required']
    assert plots._plot_dashboard_cache_payload is None
    assert version == [2]


def test_failed_source_read_is_retried_without_edit(monkeypatch):
    monkeypatch.setattr(plots, '_get_plot_dashboard_cache_key', lambda: ('source',))
    failed = {'charts': [{'id': 'synthetic', 'empty': True, 'error': 'synthetic lock'}], 'count': 1}
    with patch.object(plot_dashboard, 'build_plot_dashboard_data', side_effect=[failed, healthy(2)]) as build:
        first = asyncio.run(plots.get_plot_dashboard_data())
        assert first['retry_required'] and 'source_revision' not in first
        second = asyncio.run(plots.get_plot_dashboard_data())
        assert second['charts'][0]['option']['value'] == 2
        assert second['source_revision']
        assert build.call_count == 2


def test_sparse_domain_gaps_are_cacheable_but_unknown_value_errors_retry(monkeypatch):
    monkeypatch.setattr(plots, '_get_plot_dashboard_cache_key', lambda: ('source',))

    def fail(error):
        raise error

    gap = plot_dashboard._safe_chart('synthetic', 'Synthetic', '', lambda: fail(
        plot_dashboard.PlotDataUnavailable('Synthetic known data gap'),
    ))
    unknown = plot_dashboard._safe_chart('synthetic', 'Synthetic', '', lambda: fail(ValueError('Synthetic reader failure')))
    assert gap['retry_required'] is False
    assert unknown['retry_required'] is True
    with patch.object(plot_dashboard, 'build_plot_dashboard_data', return_value={'charts': [gap]}) as build:
        first = asyncio.run(plots.get_plot_dashboard_data())
        assert first['source_revision']
        assert asyncio.run(plots.get_plot_dashboard_data(first['source_revision']))['unchanged']
        assert build.call_count == 1


def test_balance_loader_value_error_recovers_without_source_edit(monkeypatch):
    monkeypatch.setattr(plots, '_get_plot_dashboard_cache_key', lambda: ('source',))
    monkeypatch.setattr(plot_dashboard.plot_module, 'load_time_data', synthetic_time)
    with patch.object(plot_dashboard.plot_module, 'load_balance_sheet', side_effect=[
        ValueError('Synthetic temporary Excel parser error'), synthetic_balance(),
    ]) as load:
        first = asyncio.run(plots.get_plot_dashboard_data())
        assert first['retry_required'] and 'source_revision' not in first
        second = asyncio.run(plots.get_plot_dashboard_data())
        assert second['source_revision']
        assert not second.get('retry_required')
        assert load.call_count == 2


def test_day_rollover_invalidates_date_sensitive_forecast_cache(monkeypatch):
    day = ['2001-01-01']
    monkeypatch.setattr(plots, '_plot_day', lambda: day[0])
    monkeypatch.setattr(plots, '_get_plot_dashboard_cache_key', lambda: ('source',))
    with patch.object(plot_dashboard, 'build_plot_dashboard_data', return_value=healthy()) as build:
        first = asyncio.run(plots.get_plot_dashboard_data())
        day[0] = '2001-01-02'
        second = asyncio.run(plots.get_plot_dashboard_data(first['source_revision']))
    assert second['source_revision'] != first['source_revision']
    assert build.call_count == 2


def test_concurrent_pollers_share_one_build(monkeypatch):
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(plots, '_get_plot_dashboard_cache_key', lambda: ('source',))
    calls = []

    def build():
        calls.append(True)
        started.set()
        assert release.wait(10)
        return healthy()

    monkeypatch.setattr(plot_dashboard, 'build_plot_dashboard_data', build)

    async def exercise():
        first = asyncio.create_task(plots.get_plot_dashboard_data())
        assert await asyncio.to_thread(started.wait, 5)
        second = asyncio.create_task(plots.get_plot_dashboard_data())
        await asyncio.sleep(0)
        release.set()
        return await asyncio.gather(first, second)

    try:
        results = asyncio.run(exercise())
        assert results[0] == results[1]
        assert len(calls) == 1
    finally:
        release.set()


def test_revision_query_validation_and_http_protocol(monkeypatch):
    monkeypatch.setattr(plots, '_get_plot_dashboard_cache_key', lambda: ('source',))
    monkeypatch.setattr(plot_dashboard, 'build_plot_dashboard_data', healthy)
    app = FastAPI()
    app.include_router(plots.router)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            first = (await client.get('/api/v1/plots/data')).json()
            second = await client.get('/api/v1/plots/data', params={'known_revision': first['source_revision']})
            assert second.json() == {'unchanged': True, 'source_revision': first['source_revision']}
            assert (await client.get('/api/v1/plots/data?known_revision=bad')).status_code == 422
            await client.post('/api/v1/plots/refresh')
            third = (await client.get('/api/v1/plots/data', params={'known_revision': first['source_revision']})).json()
            assert third['source_revision'] != first['source_revision']

    asyncio.run(exercise())


def test_real_workbook_edit_to_old_row_rebuilds_actual_chart(tmp_path, monkeypatch):
    time_path, balance_path = tmp_path / 'Time.xlsx', tmp_path / 'Balance Sheet.xlsx'
    frame = synthetic_time()
    frame.to_excel(time_path, index=False)
    synthetic_balance().to_excel(balance_path, index=False)
    monkeypatch.setattr(plots.DataLoader, 'resolve_data_path', lambda name, **kwargs: tmp_path / name)
    first = asyncio.run(plots.get_plot_dashboard_data())
    assert first['source_revision']
    frame.loc[0, '体重'] = 77
    frame.to_excel(time_path, index=False)
    second = asyncio.run(plots.get_plot_dashboard_data(first.get('source_revision')))
    assert second['source_revision'] != first['source_revision']
    first_weight = next(chart for chart in first['charts'] if chart['id'] == 'weight-bodyfat')
    second_weight = next(chart for chart in second['charts'] if chart['id'] == 'weight-bodyfat')
    assert first_weight['option']['series'][0]['data'][0][1] == 70
    assert second_weight['option']['series'][0]['data'][0][1] == 77
