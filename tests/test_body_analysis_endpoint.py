import asyncio
import json
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from src.backend import application, body_analysis
from src.services.body_analysis_jobs import BodyAnalysisJobService
from src.scripts.body_analysis_sam3 import build_report


def test_http_contract_restricts_assets_and_never_returns_python_path(tmp_path, monkeypatch):
    async def run():
        root = tmp_path / "reports"
        folder = root / "published" / "version1"
        (folder / "masks").mkdir(parents=True)
        (folder / "masks" / "safe.png").write_bytes(b"PNG")
        report = build_report([], [])
        report["assets"] = ["masks/safe.png"]
        (folder / "report.json").write_text(json.dumps(report))
        root.mkdir(exist_ok=True)
        (root / "current.json").write_text(json.dumps({"directory": "version1", "fingerprint": "a" * 64}))
        settings = {"body_analysis_enabled": False}
        service = BodyAnalysisJobService(root=root, settings_loader=lambda: settings)
        service._environment = {"ready": True, "missing": [], "reason": "ready", "python_executable": "C:/private/python.exe"}
        monkeypatch.setattr(application, "get_services", lambda: SimpleNamespace(body_analysis=service))
        app = FastAPI()
        app.include_router(body_analysis.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
            status = await client.get("/api/v1/body-analysis/status")
            assert status.status_code == 200
            assert status.json()["last_report_available"] is True
            assert "private" not in status.text
            setup = await client.get("/api/v1/body-analysis/setup")
            assert setup.status_code == 200 and "private" not in setup.text
            assert (await client.get("/api/v1/body-analysis/report")).json()["complete"] is True
            assert (await client.get("/api/v1/body-analysis/assets/masks/safe.png")).status_code == 200
            assert (await client.get("/api/v1/body-analysis/assets/masks/not-listed.png")).status_code == 404
            assert (await client.get("/api/v1/body-analysis/assets/%2e%2e/masks/safe.png")).status_code != 200
            assert (await client.post("/api/v1/body-analysis/install")).status_code == 409
            assert (await client.post("/api/v1/body-analysis/retry")).status_code == 409
        await service.close()
    asyncio.run(run())
