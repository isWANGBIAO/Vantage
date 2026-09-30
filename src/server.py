"""HTTP composition root and backward-compatible backend entry point.

Business functions and APIRouters live in :mod:`src.backend`; this module only
assembles the application, preserves historical Python imports, and launches it.
New code should import the owning backend domain instead of this legacy facade.
"""
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.append(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

# This must run before any optional camera runtime is imported.
if sys.platform == "darwin":
    skip_camera_auth = os.environ.get("VANTAGE_MACOS_SKIP_CAMERA_AUTH")
    should_skip_camera_auth = (
        skip_camera_auth != "0"
        if skip_camera_auth is not None
        else os.environ.get("VANTAGE_APP_MODE") != "packaged"
    )
    os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1" if should_skip_camera_auth else "0")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.backend import (
    action_plans,
    camera,
    chat,
    face,
    finance_data,
    finance_recommendations,
    health,
    media,
    observability,
    plots,
    processes,
    projects,
    providers,
    runtime,
    security,
    settings,
    system,
    transcription,
)
from src.backend.compat import install_legacy_exports
from src.core.backend_connection import backend_bind_address

app = FastAPI(lifespan=runtime.lifespan)
runtime.bind_app(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(security.TRUSTED_BROWSER_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(security.enforce_loopback_backend_access)

ROUTE_MODULES = (
    settings,
    camera,
    system,
    media,
    plots,
    action_plans,
    chat,
    providers,
    transcription,
    observability,
    finance_recommendations,
    finance_data,
    face,
    health,
    projects,
)
for route_module in ROUTE_MODULES:
    app.include_router(route_module.router)


# Application-level job/scheduler adapters are composed after all domains.
from src.backend import application

app.include_router(application.build_router())


def main():
    import uvicorn

    host, port = backend_bind_address()
    uvicorn.run(app, host=host, port=port, access_log=False)


install_legacy_exports(
    sys.modules[__name__],
    (*ROUTE_MODULES, processes, runtime, security),
)

if __name__ == "__main__":
    main()
