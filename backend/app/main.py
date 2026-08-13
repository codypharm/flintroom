"""FastAPI application factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.core.errors import FlintroomError
from app.core.logging import configure_logging, get_logger
from app.modules.auth.providers import build_verifiers
from app.modules.auth.router import router as auth_router
from app.modules.sessions.router import router as sessions_router
from app.modules.sessions.runner import SweepRunner

log = get_logger(__name__, tag="http")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Process startup.

    Logging is installed here rather than in `create_app` because installing it
    replaces the root handlers — a global side effect. An application factory
    that reconfigures logging simply by being called will fight anything else
    that has an opinion about handlers, test capture included.
    """
    configure_logging()
    log.info("api_started")

    # The sweeps run in every API process. Both are idempotent, so overlapping
    # workers reach the same answer and the duplicate writes are refused —
    # which is what makes a plain loop sufficient here and a task queue an
    # unnecessary piece of infrastructure to own.
    # One HTTP client and one set of verifiers for the process. Each verifier
    # owns a JWKS cache, so building them per request would fetch a provider's
    # keys on every sign-in — the latency the cache exists to avoid, and the
    # hammering REFRESH_COOLDOWN exists to prevent.
    http = httpx.AsyncClient(timeout=5.0)
    app.state.verifiers = build_verifiers(get_settings(), http)

    engine = create_engine()
    session_factory = create_session_factory(engine)
    # Requests take their session from here via `get_db`. Built once, and by
    # the same scope that disposes of the engine.
    app.state.session_factory = session_factory
    runner = SweepRunner(session_factory)
    sweeps = asyncio.create_task(runner.run())

    try:
        yield
    finally:
        # Asked to stop, then waited for. Cancelling instead would risk landing
        # inside a commit, and a session left half-settled on every deploy is
        # the exact damage the reaper exists to repair.
        runner.stop()
        await sweeps
        await http.aclose()
        await engine.dispose()
        log.info("api_stopped")


#: Versioned from the first endpoint. A mobile client cannot be force-updated,
#: so old app versions keep calling whatever they were built against for as long
#: as they exist — and retrofitting a prefix later means breaking exactly those
#: installs.
API_PREFIX = "/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="Flintroom API", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(sessions_router, prefix=API_PREFIX)
    return app


def register_exception_handlers(app: FastAPI) -> None:
    """Translate exceptions to responses in exactly one place."""

    @app.exception_handler(FlintroomError)
    async def handle_known_error(request: Request, exc: FlintroomError) -> JSONResponse:
        # Client errors are expected traffic, not incidents. A 5xx from a
        # dependency is not — it needs to be findable in the logs.
        emit = log.warning if exc.status_code < 500 else log.error
        emit(
            exc.code,
            path=request.url.path,
            method=request.method,
            status_code=exc.status_code,
            **exc.context,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_response(),
            headers=exc.headers or None,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Anything not deliberately raised is a bug.

        Logged with its traceback and returned as a generic 500 — exception text
        routinely carries identifiers, paths and query fragments, so it is never
        echoed to the caller.
        """
        log.exception(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            exception_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Something went wrong."}},
        )
