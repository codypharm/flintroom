"""The loop that runs extraction, and why it is not the one in `sessions/`.

**A separate task, for a reason that would otherwise be a billing outage.**
`SweepRunner` awaits its sweeps in sequence, one pass every fifteen seconds, and
a pass that takes longer than the interval delays the next one. Reading a
pro-tier deck is fifteen model calls behind a CPU-bound render of three hundred
pages — minutes, not seconds. Hanging that off the same pass would stop the
meter for the duration, and the meter stopping is money that is never charged
for rooms the provider is still billing us for.

**Shutdown may cancel this one, which is the other real difference.**
`SweepRunner.stop()` is deliberately not a cancellation: it writes money, and a
task cancelled inside a commit leaves a session half-settled. Nothing here is
half-writable — the claim, the three endings and the release are each a single
transaction, and a deck abandoned mid-read is simply a stale `claimed_at` that
the next process's `release_stalled` gives back. So a deploy does not have to
wait minutes for a deck to finish; it takes the deck back instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.storage import ObjectStorage
from app.modules.ingestion.extraction_model import ExtractionModel
from app.modules.ingestion.extractor import (
    DEFAULT_DAILY_PAGE_CEILING,
    ExtractionService,
)

log = get_logger(__name__, tag="ingestion")

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

#: How long to wait before looking for work again, when the last look found
#: none. Short, because it is what a user who has just uploaded a deck waits
#: before anything starts happening — and long enough that an idle deployment is
#: not asking an empty question several times a second.
#:
#: It paces *idleness only*. While there is a queue the loop comes straight
#: back, so a backlog does not cost one interval per deck ahead of you.
POLL_INTERVAL_SECONDS = 10.0


class ExtractionRunner:
    """Reads waiting decks, one at a time, until asked to stop."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        storage: ObjectStorage,
        model: ExtractionModel,
        daily_page_ceiling: int = DEFAULT_DAILY_PAGE_CEILING,
        interval: float = POLL_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._model = model
        self._daily_page_ceiling = daily_page_ceiling
        self._interval = interval
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        """Sweep until asked to stop, waiting only when there was nothing to do."""
        log.info("extraction_loop_started", interval_seconds=self._interval)

        while not self._stopping.is_set():
            worked = await self._pass()

            # One line per pass, empty ones included. No error is raised when
            # nothing is running, so silence is the only symptom there is — and
            # an alert on the *absence* of this line is what makes a plain loop
            # safe to depend on. See `docs/deployment.md`.
            log.info("extraction_swept", worked=worked)

            if worked:
                # Straight back round. Waiting between decks would cost a user
                # one interval for every deck ahead of them in the queue, which
                # stays invisible until the queue is long enough to matter.
                continue

            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=self._interval
                )
            except TimeoutError:
                # The ordinary path: nobody asked us to stop, so look again.
                pass

        log.info("extraction_loop_stopped")

    def stop(self) -> None:
        """Ask the loop to stop after the deck it is holding, if any.

        Unlike the billing sweeps, it is also safe to cancel this task outright
        rather than wait — see the module docstring. A deck abandoned mid-read
        is a stale claim, and a stale claim is exactly what `release_stalled`
        exists to return.
        """
        self._stopping.set()

    async def _pass(self) -> bool:
        """One deck, on a session of its own.

        A session per pass rather than one for the life of the loop, following
        `SweepRunner`: a long-lived session holds a long-lived transaction, and
        every pass after the first would be reading the world as it looked when
        the process booted.

        The broad catch is the same call the billing sweeps make, for the same
        reason. Nothing is waiting on an answer here, so letting a bug propagate
        would end extraction entirely until somebody redeployed. Logged with its
        traceback so it stays a visible defect rather than an absorbed one — and
        a deck left claimed by a failure in here is released by a later pass,
        which is the property that makes swallowing it survivable.
        """
        try:
            async with self._session_factory() as db:
                return await ExtractionService(
                    db,
                    storage=self._storage,
                    model=self._model,
                    daily_page_ceiling=self._daily_page_ceiling,
                ).sweep()
        except Exception:
            log.exception("extraction_pass_failed")
            return False
