"""An access token for a phone on your desk, and nothing else.

Sign-in is real and tested (`auth/service.py`), but no native sign-in library is
installed yet, so there is no way for a device to obtain an Apple or Google
`idToken` — and therefore no way into a room. That is a genuine piece of work
with external setup attached (OAuth clients, an Apple capability), and it should
be done on its own merits rather than rushed to unblock a measurement.

So this mints a token directly, the way the server would have after a successful
sign-in: same `AccessTokens`, same secret, same claims, same expiry. It creates
the account and grants the free-tier minutes exactly as sign-in does, so a room
started with it is metered against a real balance rather than a special case.

**Local only, and structurally so.** This is a script, not an endpoint: there is
nothing here a deployed process serves, nothing a client can call, and no code
path in `app/` that behaves differently because a token came from here. It works
only for whoever already holds `JWT_SECRET`, which is to say whoever could
already sign anything they liked. It is not a back door so much as an
acknowledgement of who owns the front one.

Usage, from `backend/`:

    uv run python -m scripts.dev_token

Writes `EXPO_PUBLIC_DEV_TOKEN` into `app/.env.local` and prints it. Expo inlines
that into the bundle, so the room screen comes up with the field already filled
and the phone needs only a reload — pasting two hundred characters into a
handset with a thumb is not a workflow, it is a deterrent.

`.env.local` is already ignored by the root `.gitignore` (`.env.*`), and the
screen only reads the variable under `__DEV__`, so a release build cannot carry
one in even if the file were present when it was made.

Re-running with the same `--email` returns a token for the same account, so a
second run does not strand the balance from the first.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.core.actors import ActorContext
from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.modules.auth.models import AuthIdentity
from app.modules.auth.tokens import AccessTokens
from app.modules.billing.models import Account
from app.modules.billing.service import LedgerService
from app.modules.billing.tiers import FREE_TIER
from app.modules.sessions.models import Session
from app.modules.sessions.schemas import SessionState
from app.modules.sessions.service import SessionService

#: The provider this pretends to be. A real one, so the row is shaped exactly as
#: sign-in would leave it and a later real sign-in with the same email links to
#: the same account rather than making a second one.
PROVIDER = "google"

#: What the room screen reads. `EXPO_PUBLIC_` is what makes Expo inline it.
ENV_VAR = "EXPO_PUBLIC_DEV_TOKEN"

#: States in which a session still blocks the next one. `settled` and `failed`
#: do not — a user in yesterday's debrief is free to start a fresh room.
HOLDS_THE_LOCK = {
    SessionState.PROVISIONING,
    SessionState.ACTIVE,
    SessionState.FINALIZING,
}


async def release(db, user_id: uuid.UUID) -> int:
    """End any room still holding this account's lock.

    One interrogation at a time is a real product rule and the runaway-cost
    circuit breaker, so a room that failed to open still blocks the next one
    until the reaper sweeps it. During a device session that is every retry
    after the first, and the symptom — `active_session_exists` — reads like the
    rule working rather than like debris.
    """
    rows = list(await db.scalars(select(Session).where(Session.state.in_(HOLDS_THE_LOCK))))
    for row in rows:
        await SessionService(db).fail(session_id=row.id)
    return len(rows)


async def top_up(db, user_id: uuid.UUID, minutes: int) -> None:
    """Put minutes on the account, the way a purchase would.

    Into the top-up bucket rather than the free grant, and that is the whole
    reason this is not simply a second `grant_signup_free_minutes`. The free
    grant is idempotent by design — it has to be, or every sign-in would hand
    out another one — so re-running this script cannot refill it, and a
    developer who has used their thirty minutes has no way back into a room
    except by editing the database.

    Top-up is also the bucket that never expires (§4.5), so a period boundary
    mid-testing will not silently take these away.

    A fresh idempotency key each run, unlike everything else here. Idempotency
    exists to stop a retried webhook granting twice; a person typing
    `--minutes 60` is asking for sixty more minutes, and refusing them because
    they asked yesterday would be the guard misfiring.
    """
    granted = await LedgerService(db, actor=ActorContext.system()).grant_topup(
        user_id=user_id,
        seconds=minutes * 60,
        idempotency_key=f"dev-topup:{uuid.uuid4()}",
    )
    if granted:
        print(f"granted {minutes} top-up minutes", file=sys.stderr)


async def issue(*, email: str, tier: str, hours: int, minutes: int = 0) -> str:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)

    try:
        async with sessions() as db:
            subject = f"dev:{email}"
            user_id = await db.scalar(
                select(AuthIdentity.user_id).where(
                    AuthIdentity.provider == PROVIDER,
                    AuthIdentity.subject == subject,
                )
            )

            if user_id is None:
                user_id = uuid.uuid4()
                db.add(Account(user_id=user_id, entitlement_tier=tier))
                await db.flush()
                db.add(
                    AuthIdentity(
                        user_id=user_id,
                        provider=PROVIDER,
                        subject=subject,
                        email=email,
                    )
                )
                await db.commit()

            # Idempotent by construction, exactly as sign-in relies on — so a
            # second run tops nothing up and a room is metered against a real
            # balance rather than an unlimited one.
            await LedgerService(db, actor=ActorContext.system()).grant_signup_free_minutes(
                user_id=user_id
            )

            # Always, not on request. Every run of this script is somebody about
            # to open a room, and a stale lock is the one thing guaranteed to
            # stop them.
            if minutes:
                await top_up(db, user_id, minutes)

            if freed := await release(db, user_id):
                print(f"released {freed} stale room(s)", file=sys.stderr)

            # Always, and to stderr so it never pollutes the token on stdout.
            # "No minutes remaining" is otherwise a dead end: the free grant is
            # idempotent, so re-running looks like it should have helped and
            # silently did nothing.
            balance = await LedgerService(db, actor=ActorContext.system()).balance(
                user_id=user_id
            )
            print(
                f"balance: {balance.remaining_minutes} min "
                f"(allowance {balance.allowance_seconds // 60}, "
                f"free {balance.free_seconds // 60}, "
                f"top-up {balance.topup_seconds // 60})",
                file=sys.stderr,
            )

        return AccessTokens(
            secret=settings.jwt_secret, ttl=timedelta(hours=hours)
        ).issue(user_id=user_id)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--email",
        default="device@flintroom.local",
        help="Which account to issue for. The same value returns the same account.",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=8,
        help=(
            "How long the token lasts. The real TTL is fifteen minutes and the "
            "app refreshes; there is no refresh token here, and re-pasting one "
            "mid-measurement is how a latency run gets abandoned."
        ),
    )
    parser.add_argument(
        "--tier",
        default=FREE_TIER,
        help="Entitlement tier for a newly created account. Ignored if it exists.",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=0,
        help=(
            "Grant this many top-up minutes. The free signup grant is "
            "idempotent and cannot be repeated, so this is the way back into a "
            "room once it is spent."
        ),
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Only print the token, leaving app/.env.local alone.",
    )
    args = parser.parse_args()

    token = asyncio.run(
        issue(
            email=args.email,
            tier=args.tier,
            hours=args.hours,
            minutes=args.minutes,
        )
    )
    print(token)

    if not args.no_write:
        written = _write_env(token)
        print(f"\nwritten to {written}", file=sys.stderr)
        print("reload the app on the phone; the field will be filled", file=sys.stderr)


def _write_env(token: str) -> pathlib.Path:
    """Put the token where Expo will find it, without disturbing anything else.

    Rewrites only our own line. A developer's `.env.local` is theirs and may
    hold an `EXPO_PUBLIC_API_URL` pointing at staging — clobbering the file to
    save a few lines here would be a script quietly undoing somebody's setup.
    """
    env = pathlib.Path(__file__).resolve().parents[2] / "app" / ".env.local"
    keep = [
        line
        for line in (env.read_text().splitlines() if env.exists() else [])
        if not line.startswith(f"{ENV_VAR}=")
    ]
    env.write_text("\n".join([*keep, f"{ENV_VAR}={token}"]) + "\n")
    return env


if __name__ == "__main__":
    main()
