"""Issuing and rotating refresh tokens."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import db_now, rows_touched
from app.core.errors import NotAuthenticated
from app.core.logging import get_logger
from app.modules.auth.models import RefreshToken

log = get_logger(__name__, tag="auth")

#: How long a user stays signed in without touching a provider again.
#:
#: Long, because signing in is friction at the exact moment the product is
#: trying to be useful — someone opening the app the night before a board
#: review. Affordable because rotation makes a stolen token detectable and
#: revocation is a row, not a wait for expiry.
REFRESH_TOKEN_TTL = timedelta(days=60)

#: 32 bytes of `secrets` output. Unguessable, so the stored hash needs no salt
#: and no slow KDF.
TOKEN_BYTES = 32


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class RefreshTokenService:
    """The long half of a session."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def issue(self, *, user_id: uuid.UUID) -> str:
        """A new token, starting a new family. Called at sign-in."""
        return await self._mint(user_id=user_id, family_id=uuid.uuid4())

    async def rotate(self, *, token: str) -> tuple[uuid.UUID, str]:
        """Spend a refresh token and return its replacement."""
        held = await self._find(token)
        if held is None:
            raise NotAuthenticated()

        now = await db_now(self._db)

        if held.used_at is not None:
            # Somebody is replaying a token that was already spent, which means
            # two parties hold credentials from one sign-in. We cannot tell
            # which is the real user — the thief may have rotated first, leaving
            # the victim with the spent one — so the session ends for both.
            await self._revoke_family(held.family_id, at=now)
            await self._db.commit()
            log.warning(
                "refresh_token_reused",
                user_id=str(held.user_id),
                family_id=str(held.family_id),
            )
            raise NotAuthenticated(
                user_id=str(held.user_id), rejected_because="token_reuse"
            )

        if held.revoked_at is not None:
            raise NotAuthenticated(
                user_id=str(held.user_id), rejected_because="family_revoked"
            )

        if held.expires_at <= now:
            raise NotAuthenticated(
                user_id=str(held.user_id), rejected_because="expired"
            )

        held.used_at = now
        return held.user_id, await self._mint(
            user_id=held.user_id, family_id=held.family_id
        )

    async def sign_out(self, *, token: str) -> None:
        """End the session this token belongs to.

        Silent about whether the token existed. Answering differently would let
        anyone test a stolen string for liveness against an endpoint that needs
        no credential to reach.

        The whole family goes, not just the row presented: the client holds one
        token from a chain, and revoking only that one leaves every ancestor
        still spendable by whoever else has a copy.
        """
        held = await self._find(token)
        if held is None:
            return

        await self._revoke_family(held.family_id, at=await db_now(self._db))
        await self._db.commit()
        log.info("signed_out", user_id=str(held.user_id), family_id=str(held.family_id))

    async def sweep(self) -> None:
        """Delete tokens that have expired. Nothing else.

        Expiry, deliberately, rather than "used" or "revoked". A spent token is
        what reuse detection reads — remove it early and a replay stops looking
        like reuse and starts looking like a token we never issued. Still
        refused, but the family is no longer revoked, so the thief keeps their
        session. That failure is silent and every other test still passes, which
        is why the retention rule lives here in writing.
        """
        now = await db_now(self._db)
        result = await self._db.execute(
            delete(RefreshToken).where(RefreshToken.expires_at <= now)
        )
        await self._db.commit()

        swept = rows_touched(result)
        if swept:
            log.info("refresh_tokens_swept", deleted=swept)

    async def _revoke_family(self, family_id: uuid.UUID, *, at: datetime) -> None:
        await self._db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=at)
        )

    async def _mint(self, *, user_id: uuid.UUID, family_id: uuid.UUID) -> str:
        token = secrets.token_urlsafe(TOKEN_BYTES)
        now = await db_now(self._db)
        self._db.add(
            RefreshToken(
                token_hash=_hash(token),
                user_id=user_id,
                family_id=family_id,
                expires_at=now + REFRESH_TOKEN_TTL,
            )
        )
        await self._db.commit()
        return token

    async def _find(self, token: str) -> RefreshToken | None:
        result = await self._db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == _hash(token))
        )
        return result.scalar_one_or_none()
