"""HTTP composition root and backend entry point.

Business functions and APIRouters live in :mod:`src.backend`; this module only
assembles the application and launches it. Import domain functions from their
owning modules; native clients use the single versioned HTTP API.
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
from src.core.backend_connection import backend_bind_address
from src.core.user_config import ConfigurationReadError
from src.backend.responses import configuration_read_error_response

app = FastAPI(lifespan=runtime.lifespan)
app.add_exception_handler(ConfigurationReadError, configuration_read_error_response)
runtime.bind_app(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(security.TRUSTED_BROWSER_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(security.LoopbackAccessMiddleware)

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


if __name__ == "__main__":
    main()
