"""FastAPI application factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.core.config import Settings, get_settings
from app.core.database import create_engine, create_session_factory
from app.core.errors import FlintroomError
from app.core.logging import configure_logging, get_logger
from app.core.request_context import RequestIdMiddleware
from app.core.storage_s3 import build_object_storage
from app.modules.auth.providers import build_verifiers
from app.modules.auth.router import router as auth_router
from app.modules.billing.router import router as billing_router
from app.agents.weakness_models import build_weakness_reader
from app.modules.ingestion.extraction_models import build_extraction_model
from app.modules.ingestion.router import router as materials_router
from app.modules.panels.router import router as panels_router
from app.modules.ingestion.runner import ExtractionRunner
from app.modules.sessions.router import router as sessions_router
from app.modules.sessions.runner import SessionFactory, SweepRunner
from app.agents.claim_readers import build_claim_reader
from app.agents.panel_models import build_panel_model
from app.modules.voice.speakers import build_speaker
from app.modules.voice.transcribers import build_transcriber
from app.modules.voice.router import router as voice_router

log = get_logger(__name__, tag="http")

#: How long shutdown lets the extraction loop notice it was asked to stop.
#:
#: Not a wait for the deck it is reading — that can be minutes, and abandoning
#: it is safe. This is only enough for an idle loop to wake from its poll and
#: say so, which is what nearly every deploy meets.
EXTRACTION_SHUTDOWN_GRACE = 1.0


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

    # The three process-wide parts of a room, like the verifiers above. Each
    # holds connection state, so building them per socket would pay that on
    # every interrogation. The other half of a room — who is seated, what may be
    # attacked — is per session and comes from the database in `build_room`.
    #
    # Left unset when the deployment lacks the credentials: auth, balances,
    # ingestion and session bookkeeping all work without any of them, and
    # refusing to boot would take those down over a feature they do not use.
    app.state.transcriber = build_transcriber(settings)
    if app.state.transcriber is None:
        log.warning("transcriber_unconfigured")

    app.state.panel_model = build_panel_model(settings, http)
    if app.state.panel_model is None:
        log.warning("panel_model_unconfigured")

    # The only one of the three a room survives without. A silent panel still
    # transcribes, routes, composes and captions — and captions are a v1
    # requirement in their own right, not a fallback for missing audio.
    app.state.speaker = build_speaker(settings, http)
    if app.state.speaker is None:
        log.warning("speaker_unconfigured")

    # Same trade as the provider above: a deployment with no bucket takes only
    # ingestion down, and refusing to boot over it would stop auth, balances and
    # the voice loop over a feature none of them use.
    # The Auditor's ears. Absent is the mildest of the four: a room still
    # interrogates, it simply never notices a figure that moved.
    app.state.claim_reader = build_claim_reader(settings, http)
    if app.state.claim_reader is None:
        log.warning("claim_reader_unconfigured")

    app.state.object_storage = build_object_storage(settings)
    if app.state.object_storage is None:
        log.warning("object_storage_unconfigured")

    # Built at boot rather than on first use so an unconfigured deployment says
    # so once, at startup, instead of once per deck that silently fails to
    # ground. The extraction sweep is what will consume it.
    app.state.extraction_model = build_extraction_model(settings, http=http)
    if app.state.extraction_model is None:
        log.warning("extraction_model_unconfigured")

    # Same shape, and the same reason it is a warning rather than a boot
    # failure: a deployment without it signs people in, opens rooms and
    # keeps transcripts. What it cannot do is produce the ranked list
    # `Product.md` §3.5 calls "the part users will pay for", which is worth
    # saying once at startup rather than discovering per session.
    app.state.weakness_reader = build_weakness_reader(settings, http=http)
    if app.state.weakness_reader is None:
        log.warning("weakness_reader_unconfigured")

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    # Requests take their session from here via `get_db`. Built once, and by
    # the same scope that disposes of the engine.
    app.state.session_factory = session_factory
    # Storage passed in so the retention sweep can expire room audio. Without
    # it that sweep is skipped — correct for a deployment that records nothing,
    # and a silent hazard for one that does, which is why
    # `object_storage_unconfigured` is logged above and alerted on.
    runner = SweepRunner(session_factory, storage=app.state.object_storage)
    sweeps = asyncio.create_task(runner.run())

    # A second loop, deliberately. Reading a pro-tier deck is minutes of model
    # calls behind a CPU-bound render, and `SweepRunner` awaits its sweeps in
    # sequence — so hanging extraction off that pass would stop the meter for
    # the duration, which is money never charged for rooms the provider is
    # still billing us for. See `ingestion/runner.py`.
    extraction = _extraction_runner(app, settings, session_factory)
    extractions = (
        asyncio.create_task(extraction.run()) if extraction else None
    )

    try:
        yield
    finally:
        # Asked to stop, then waited for. Cancelling instead would risk landing
        # inside a commit, and a session left half-settled on every deploy is
        # the exact damage the reaper exists to repair.
        runner.stop()
        await sweeps

        if extraction and extractions:
            # Asked, given a moment, then cancelled — and the cancellation is
            # the difference from above. Nothing in extraction is half-writable
            # (the claim, the three endings and the release are each one
            # transaction), so an abandoned deck is a stale `claimed_at` that
            # the next process gives back. Waiting for a deck to finish would
            # hold a deploy for minutes to avoid a recovery that already works.
            #
            # The grace is for the idle case, which is nearly every deploy: the
            # loop is sitting on the stop event and needs one scheduling turn to
            # notice it and log that it stopped.
            extraction.stop()
            _, running = await asyncio.wait(
                {extractions}, timeout=EXTRACTION_SHUTDOWN_GRACE
            )
            for task in running:
                task.cancel()
            await asyncio.gather(extractions, return_exceptions=True)

        await http.aclose()
        await engine.dispose()
        log.info("api_stopped")


def _extraction_runner(
    app: FastAPI, settings: Settings, session_factory: SessionFactory
) -> ExtractionRunner | None:
    """The extraction loop, if this deployment has what it needs to run one.

    Both halves or neither: a bucket with no model reads nothing, and a model
    with no bucket has nothing to read. Absent rather than fatal, on the same
    grounds as the pieces themselves — auth, balances and the voice loop all
    work without extraction, and `docs/auditor-grounding.md` makes the deckless
    path first-class rather than degraded.

    Said once, loudly, at startup. The failure this avoids is a deployment that
    accepts uploads all day and never grounds a session, with nothing in the log
    to say why.
    """
    if app.state.object_storage is None or app.state.extraction_model is None:
        log.warning("extraction_sweep_disabled")
        return None

    return ExtractionRunner(
        session_factory,
        storage=app.state.object_storage,
        model=app.state.extraction_model,
        daily_page_ceiling=settings.daily_page_ceiling,
        libreoffice=settings.libreoffice_binary,
    )


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
    app.include_router(panels_router, prefix=API_PREFIX)
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
