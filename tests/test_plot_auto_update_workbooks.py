"""Real synthetic workbooks, API cache, and chart calculations together."""

import asyncio
import hashlib
import os

import httpx
import pandas as pd
from fastapi import FastAPI
from openpyxl import load_workbook

from src.backend import plots
from src.utils.data_loader import DataLoader


def _workbooks(root):
    dates = pd.date_range("2001-01-01", periods=40)
    pd.DataFrame({
        "日期": dates, "起床时间": ["1.00-8.00"] * 40,
        "睡眠时间": ["7小时"] * 40, "手机屏幕\n使用时间": ["3小时"] * 40,
        "体重": [70.0] * 40, "体脂率": [20.0] * 40,
        "HHH": ["+1", "-1"] * 20,
        "运动": ["跑步4公里，用时24分，心率150，步频160，步幅104厘米"] * 40,
    }).to_excel(root / "Time.xlsx", index=False)
    pd.DataFrame({
        "日期": dates, "现金及现金等价物+股票": [10000] * 40,
        "支付宝资产": [2000] * 40, "银行卡资产": [7000] * 40,
        "微信资产": [500] * 40, "股票资产": [500] * 40,
        "日均消费": [50] * 40, "实际消费": [100] * 40,
    }).to_excel(root / "Balance Sheet.xlsx", index=False)


def _chart(payload, name):
    return next(chart for chart in payload["charts"] if chart["id"] == name)


def _edit(path, column, value):
    workbook = load_workbook(path)
    sheet = workbook.active
    headers = {cell.value: cell.column for cell in sheet[1]}
    sheet.cell(2, headers[column], value)
    workbook.save(path)
    workbook.close()


def test_real_workbooks_revalidate_old_rows_and_do_not_write_sources(tmp_path, monkeypatch):
    _workbooks(tmp_path)
    monkeypatch.setattr(DataLoader, "resolve_data_path", staticmethod(lambda name, **_: tmp_path / name))
    app = FastAPI()
    app.include_router(plots.router)
    plots._clear_plot_dashboard_cache()

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            def fingerprints():
                return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.glob("*.xlsx")}

            original = fingerprints()
            response = await client.get("/api/v1/plots/data")
            assert response.status_code == 200
            first = response.json()
            assert not first.get("retry_required"), [(c["id"], c.get("error")) for c in first["charts"]]
            revision = first["source_revision"]
            assert (await client.get("/api/v1/plots/data", params={"known_revision": revision})).json()["unchanged"]
            assert fingerprints() == original

            # Change a decades-old row, keeping mtime unchanged: content, not
            # recent-week filtering or timestamps alone, controls freshness.
            time_path = tmp_path / "Time.xlsx"
            stat = time_path.stat()
            _edit(time_path, "起床时间", "2.00-9.00")
            _edit(time_path, "体重", 72)
            os.utime(time_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            edited = fingerprints()
            second = (await client.get("/api/v1/plots/data", params={"known_revision": revision})).json()
            assert second["source_revision"] != revision
            assert _chart(second, "sleep-schedule")["option"]["series"][0]["data"][0][1] == 26
            assert _chart(second, "weight-bodyfat")["option"] != _chart(first, "weight-bodyfat")["option"]
            assert fingerprints() == edited

            balance_path = tmp_path / "Balance Sheet.xlsx"
            _edit(balance_path, "日均消费", 90)
            edited = fingerprints()
            third = (await client.get("/api/v1/plots/data", params={"known_revision": second["source_revision"]})).json()
            assert third["source_revision"] != second["source_revision"]
            assert _chart(third, "balance")["option"] != _chart(second, "balance")["option"]
            assert fingerprints() == edited

            workbook = load_workbook(time_path)
            workbook.active.delete_rows(2)
            workbook.save(time_path)
            workbook.close()
            fourth = (await client.get("/api/v1/plots/data", params={"known_revision": third["source_revision"]})).json()
            assert len(_chart(fourth, "sleep-schedule")["option"]["series"][0]["data"]) == 39
            assert fourth["source_revision"] != third["source_revision"]

            restored = time_path.read_bytes()
            time_path.unlink()
            missing = (await client.get("/api/v1/plots/data", params={"known_revision": fourth["source_revision"]})).json()
            assert missing["retry_required"] and "source_revision" not in missing
            time_path.write_bytes(restored)
            final = (await client.get("/api/v1/plots/data", params={"known_revision": fourth["source_revision"]})).json()
            assert not final.get("retry_required")
            assert len(_chart(final, "sleep-schedule")["option"]["series"][0]["data"]) == 39
            assert time_path.read_bytes() == restored

    try:
        asyncio.run(exercise())
    finally:
        plots._clear_plot_dashboard_cache()
