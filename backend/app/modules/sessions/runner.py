"""The loop that runs the sweeps.

A plain asyncio task rather than a task queue, because the guarantee a queue
sells — that exactly one worker picks up each job — is one this design
deliberately does not need. Both sweeps derive what they owe from the database's
clock and are idempotent, so two processes running them at the same moment reach
the same answer and the second one's writes are refused as duplicates. Paying
for a broker to prevent a harmless overlap buys nothing.

What it does cost: if every process running this is down, nothing bills while
the voice provider carries on charging for rooms that are still open. Arrears
means the user is never overcharged, so the loss is ours — which is why every
pass logs, including the empty ones. `meter_swept` is emitted unconditionally
once per pass, and an alert on its *absence* is the thing that makes this design
safe. There is no substitute for it: no error is raised when nothing is running,
which is exactly why silence has to be what the alert watches for. See
`docs/deployment.md`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.storage import ObjectStorage
from app.modules.auth.rate_limit import PostgresRateLimiter
from app.modules.auth.refresh import RefreshTokenService
from app.modules.sessions.meter import MeterService
from app.modules.sessions.reaper import ReaperService
from app.modules.sessions.retention import RecordingRetention
from app.modules.sessions.schemas import TICK_INTERVAL

log = get_logger(__name__, tag="sessions")

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class SweepRunner:
    """Runs the meter and the reaper on a schedule, forever."""

    def __init__(
        self,
        session_factory: SessionFactory,
        interval: float = TICK_INTERVAL.total_seconds(),
        storage: ObjectStorage | None = None,
    ) -> None:
        self._session_factory = session_factory
        # Optional, so a deployment without object storage still bills and
        # reaps. Nothing was recorded in that case either, so there is nothing
        # to expire — but see `docs/deployment.md`, because the same silence
        # would follow from storage being *misconfigured* in a deployment that
        # is recording, and only one of those is fine.
        self._storage = storage
        self._interval = interval
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        """Sweep every interval until asked to stop.

        The wait is on the stop signal with a timeout, not a plain sleep. Both
        pace the loop identically, but this one wakes the instant shutdown is
        requested rather than finishing out an interval first — the difference
        between a rolling deploy and one that appears to hang.
        """
        log.info("sweep_loop_started", interval_seconds=self._interval)
        while not self._stopping.is_set():
            try:
                await self.once()
            except Exception:
                # Opening the session failed, so neither sweep ran and neither
                # guard applied. Almost always the database being briefly
                # unreachable — a restart, or an exhausted pool. The loop is
                # what recovers from that, because nothing else is watching it:
                # dying here would stop billing until somebody redeployed.
                log.exception("sweep_pass_failed")
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=self._interval
                )
            except TimeoutError:
                # The ordinary path: nobody asked us to stop, so sweep again.
                pass
        log.info("sweep_loop_stopped")

    def stop(self) -> None:
        """Ask the loop to finish its current pass and exit.

        Deliberately not a cancellation. These sweeps write money, and a task
        cancelled inside a commit is the one shutdown that could leave a session
        half-settled — which is precisely the state the reaper exists to repair,
        so causing it on every deploy would be self-inflicted.
        """
        self._stopping.set()

    async def once(self) -> None:
        """One pass of both sweeps, on a session of its own.

        A session per pass rather than one for the life of the loop: a
        long-lived session holds a long-lived transaction, and every pass after
        the first would be reading the world as it looked when the process
        booted.

        The meter runs first. It is the one that closes rooms at their caps, so
        letting it go ahead means the reaper spends the same pass finishing
        those closures rather than meeting them a full interval later.

        Retention runs last and only when there is somewhere for audio to have
        been. It is the only sweep here that talks to a network service other
        than the database, so a slow object store delays housekeeping rather
        than the meter — and `BATCH` is what stops a large expiring cohort
        holding the pass open at all.

        The auth sweeps come before it and are pure housekeeping — expired refresh
        tokens and dead rate-limit windows, neither of which anyone is waiting
        on. They ride this loop rather than one of their own because a second
        scheduler would be a second thing to run, monitor and get wrong, for
        work that is measured in deleted rows.
        """
        async with self._session_factory() as db:
            await self._guarded("meter", MeterService(db).sweep)
            await self._guarded("reaper", ReaperService(db).reap)
            await self._guarded("refresh_tokens", RefreshTokenService(db).sweep)
            await self._guarded("rate_limits", PostgresRateLimiter(db).sweep)
            if self._storage is not None:
                await self._guarded(
                    "recordings", RecordingRetention(db, self._storage).sweep
                )

    @staticmethod
    async def _guarded(name: str, sweep: Callable[[], Awaitable[None]]) -> None:
        """Run one sweep, surviving anything it throws.

        A deliberately broad catch, and the one place it is the right call. In a
        request handler an unexpected exception should surface as a 500, because
        something is waiting for an answer; here the only thing listening is the
        loop, and letting a bug propagate would end billing entirely until
        somebody redeployed. Logged with its traceback so it stays a visible
        defect rather than a silently absorbed one.

        Scoped per sweep rather than per pass so that a bug in one does not
        stop the other — they share a pass for convenience, not because either
        depends on the other.
        """
        try:
            await sweep()
        except Exception:
            log.exception("sweep_failed", sweep=name)
