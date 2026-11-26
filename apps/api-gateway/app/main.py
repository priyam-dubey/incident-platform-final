from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from incident_llm import LLMClient

from app.config import get_settings
from app.db import make_pool
from app.rate_limit import SlidingWindowLimiter
from app.repository import Repository
from app.routes import applications, auth, code, github, incidents, internal, telemetry, workspaces

logger = logging.getLogger("api-gateway")
MAX_BODY_BYTES = 1_000_000


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')
    if settings.environment != "development" and settings.secret_is_insecure_default:
        raise RuntimeError("AUTH_SECRET_KEY must be set to a strong random value outside development")
    if not hasattr(app.state, "telemetry"):
        app.state.telemetry = None
        if settings.clickhouse_url:
            from app.clickhouse import ClickHouseExecutor
            try:
                app.state.telemetry = ClickHouseExecutor(settings.clickhouse_url, settings.clickhouse_user, settings.clickhouse_password,
                                                         settings.clickhouse_db, settings.telemetry_query_timeout_seconds)
            except Exception:
                logger.exception("clickhouse_connect_failed - telemetry queries will report unavailable")
        else:
            logger.warning("CLICKHOUSE_URL not set - telemetry queries are disabled")
    if not hasattr(app.state, "repo"):
        app.state.pool = make_pool(settings.database_url)
        app.state.repo = Repository(app.state.pool)
    stop = None
    if settings.scan_worker_enabled and not getattr(app.state, "no_worker", False):
        import threading

        from app.scan_worker import run_forever
        stop = threading.Event()
        threading.Thread(target=run_forever, args=(app.state.repo, stop), daemon=True, name="scan-worker").start()
    det_stop = None
    if settings.detection_enabled and app.state.telemetry is not None and not getattr(app.state, "no_worker", False):
        import threading

        from app.detection_loop import run_forever as detect_forever
        det_stop = threading.Event()
        threading.Thread(target=detect_forever, args=(app.state.repo, app.state.telemetry, settings, det_stop,
                         lambda: getattr(app.state, "llm", None)), daemon=True, name="detection").start()
    elif settings.detection_enabled:
        logger.warning("DETECTION_ENABLED is set but telemetry storage is unavailable; loop not started")
    yield
    if det_stop is not None:
        det_stop.set()
    if stop is not None:
        stop.set()
    pool = getattr(app.state, "pool", None)
    if pool is not None:
        pool.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Incident Platform - API Gateway", version="0.1.0", lifespan=lifespan)
    app.state.auth_limiter = SlidingWindowLimiter(settings.auth_rate_limit_per_minute)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    )

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("unhandled_error path=%s", request.url.path)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    app.include_router(auth.router)
    app.include_router(workspaces.router)
    app.include_router(applications.router)
    app.include_router(telemetry.router)
    app.include_router(incidents.router)
    app.include_router(github.router)
    app.include_router(github.public)
    app.include_router(code.router)
    app.include_router(incidents.ingest_router)
    app.include_router(internal.router)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    def readyz():
        try:
            with app.state.pool.connection() as conn:
                conn.execute("SELECT 1")
        except Exception:
            return JSONResponse({"status": "unavailable", "database": "down"}, status_code=503)
        return {"status": "ready", "database": "up"}

    @app.get("/v1/system/status", tags=["ops"])
    def system_status() -> dict:
        # Configuration status only; never secret values.
        return {"llm": LLMClient().status(), "environment": settings.environment,
                "telemetry_store": "configured" if app.state.telemetry is not None else "not_configured"}

    return app


app = create_app()
