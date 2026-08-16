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

Prints a token. Paste it into the room screen on the phone. Re-running with the
same `--email` returns a token for the same account, so a second run does not
strand the balance from the first.
"""

from __future__ import annotations

import argparse
import asyncio
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

#: The provider this pretends to be. A real one, so the row is shaped exactly as
#: sign-in would leave it and a later real sign-in with the same email links to
#: the same account rather than making a second one.
PROVIDER = "google"


async def issue(*, email: str, tier: str, hours: int) -> str:
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
    args = parser.parse_args()

    print(asyncio.run(issue(email=args.email, tier=args.tier, hours=args.hours)))


if __name__ == "__main__":
    main()
