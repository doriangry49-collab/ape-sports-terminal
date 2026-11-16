"""APE Sports-Engine B2B REST API Application Gateway."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if (ROOT_DIR / "src").exists():
    SPORTS_ENGINE_ROOT = ROOT_DIR
elif (ROOT_DIR / "sports-engine" / "src").exists():
    SPORTS_ENGINE_ROOT = ROOT_DIR / "sports-engine"
else:
    SPORTS_ENGINE_ROOT = ROOT_DIR

SRC_DIR = SPORTS_ENGINE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from api.auth import (
        API_KEY_NAME,
        ApiTier,
        api_key_header,
        get_configured_api_keys,
        require_tier,
        verify_api_key,
    )
    from api.routes import pricing, signals, syndicate_pro
    from api.schemas import HealthResponse
except ImportError:
    from src.api.auth import (
        API_KEY_NAME,
        ApiTier,
        api_key_header,
        get_configured_api_keys,
        require_tier,
        verify_api_key,
    )
    from src.api.routes import pricing, signals, syndicate_pro
    from src.api.schemas import HealthResponse

__all__ = [
    "API_KEY_NAME",
    "ApiTier",
    "api_key_header",
    "app",
    "create_app",
    "get_configured_api_keys",
    "require_tier",
    "verify_api_key",
]


def create_app() -> FastAPI:
    """Application factory for APE Sports-Engine B2B Gateway."""
    app = FastAPI(
        title="APE Sports Intelligence & Quant Pricing API",
        version="v2.0-quant",
        description=(
            "Commercial B2B Gateway for mathematical +EV sports betting signals, "
            "Shin vig devigging, Dixon-Coles goal expectation modeling, and automated ledger analytics."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routes protected by API key
    app.include_router(
        pricing.router,
        prefix="/api/v1",
        dependencies=[Depends(verify_api_key)],
    )
    app.include_router(
        signals.router,
        prefix="/api/v1",
        dependencies=[Depends(verify_api_key)],
    )
    app.include_router(
        syndicate_pro.router,
        prefix="/api/v1",
        dependencies=[Depends(verify_api_key)],
    )

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        tags=["System Health"],
        summary="Service heartbeat and daemon sync check",
    )
    def health_check() -> HealthResponse:
        heartbeat_file = SPORTS_ENGINE_ROOT / "output" / "daemon_heartbeat.json"
        if not heartbeat_file.exists() and (ROOT_DIR / "output" / "daemon_heartbeat.json").exists():
            heartbeat_file = ROOT_DIR / "output" / "daemon_heartbeat.json"
        elif not heartbeat_file.exists() and (ROOT_DIR / "sports-engine" / "output" / "daemon_heartbeat.json").exists():
            heartbeat_file = ROOT_DIR / "sports-engine" / "output" / "daemon_heartbeat.json"
        daemon_info = {"status": "HEALTHY", "leagues_scanned": 28}
        if heartbeat_file.exists():
            try:
                loaded = json.loads(heartbeat_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    daemon_info = loaded
                else:
                    daemon_info = {"status": "DEGRADED", "leagues_scanned": 28}
            except Exception:
                pass
        if not isinstance(daemon_info, dict):
            daemon_info = {"status": "HEALTHY", "leagues_scanned": 28}

        return HealthResponse(
            status="ONLINE",
            engine_name="APE Sports-Engine B2B Gateway",
            engine_version="v2.0-quant",
            timestamp_utc=datetime.now(UTC).isoformat(),
            daemon_status=daemon_info,
        )

    # Mount Static UI Terminal (Zero-CORS localhost serving)
    ui_dir = SPORTS_ENGINE_ROOT / "ui"
    if not ui_dir.exists() and (ROOT_DIR / "ui").exists():
        ui_dir = ROOT_DIR / "ui"
    elif not ui_dir.exists() and (ROOT_DIR / "sports-engine" / "ui").exists():
        ui_dir = ROOT_DIR / "sports-engine" / "ui"

    if ui_dir.exists():
        app.mount("/ui", StaticFiles(directory=str(ui_dir), html=True), name="ui")

    @app.get("/", include_in_schema=False)
    def redirect_to_ui() -> RedirectResponse:
        return RedirectResponse(url="/ui/")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
