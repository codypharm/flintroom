"""FastAPI application factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.core.errors import FlintroomError
from app.core.logging import configure_logging, get_logger
from app.core.request_context import RequestIdMiddleware
from app.core.storage_s3 import build_object_storage
from app.modules.auth.providers import build_verifiers
from app.modules.auth.router import router as auth_router
from app.modules.billing.router import router as billing_router
from app.modules.ingestion.extraction_models import build_extraction_model
from app.modules.ingestion.router import router as materials_router
from app.modules.sessions.router import router as sessions_router
from app.modules.sessions.runner import SweepRunner
from app.modules.voice.providers import build_voice_provider
from app.modules.voice.router import router as voice_router

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
    settings = get_settings()
    http = httpx.AsyncClient(timeout=5.0)
    app.state.verifiers = build_verifiers(settings, http)

    # One provider for the process, like the verifiers above. Left unset when
    # the deployment has no voice credentials: auth, balances and session
    # bookkeeping all work without them, and only the stream socket refuses.
    app.state.voice_provider = build_voice_provider(settings)
    if app.state.voice_provider is None:
        log.warning("voice_provider_unconfigured")

    # Same trade as the provider above: a deployment with no bucket takes only
    # ingestion down, and refusing to boot over it would stop auth, balances and
    # the voice loop over a feature none of them use.
    app.state.object_storage = build_object_storage(settings)
    if app.state.object_storage is None:
        log.warning("object_storage_unconfigured")

    # Built at boot rather than on first use so an unconfigured deployment says
    # so once, at startup, instead of once per deck that silently fails to
    # ground. The extraction sweep is what will consume it.
    app.state.extraction_model = build_extraction_model(settings)
    if app.state.extraction_model is None:
        log.warning("extraction_model_unconfigured")

    engine = create_engine(settings.database_url)
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


def operation_id(route: APIRoute) -> str:
    """Name an operation after what it does, not after its URL.

    FastAPI's default folds the path and method into the id, so the generated
    frontend client ends up with `readSessionV1SessionsSessionIdGet` — a method
    name that changes whenever the route moves, which is exactly when a client
    should keep compiling. Prefixed with the tag because route names are only
    unique within a module, and a collision here silently drops an endpoint
    from the generated client.
    """
    return f"{route.tags[0]}_{route.name}" if route.tags else route.name


def create_app() -> FastAPI:
    app = FastAPI(
        title="Flintroom API",
        lifespan=lifespan,
        generate_unique_id_function=operation_id,
    )
    # Outermost, so an id exists before anything else runs — including the
    # exception handlers, whose log lines are the ones most worth correlating.
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(sessions_router, prefix=API_PREFIX)
    app.include_router(billing_router, prefix=API_PREFIX)
    app.include_router(materials_router, prefix=API_PREFIX)
    app.include_router(voice_router, prefix=API_PREFIX)
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
