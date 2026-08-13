"""Resolving a verified provider identity to a Flintroom user."""

from __future__ import annotations

import uuid
from typing import Mapping, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.errors import NotAuthenticated
from app.core.logging import get_logger
from app.modules.auth.models import AuthIdentity
from app.modules.auth.oidc import ProviderIdentity
from app.modules.billing.models import Account
from app.modules.billing.service import LedgerService
from app.modules.billing.tiers import FREE_TIER

log = get_logger(__name__, tag="auth")


class IdentityVerifier(Protocol):
    """Anything that can turn a provider's token into an identity."""

    async def verify(self, id_token: str) -> ProviderIdentity: ...


class AuthService:
    """Sign-in: who is this, and which account do they belong to."""

    def __init__(
        self, db: AsyncSession, verifiers: Mapping[str, IdentityVerifier]
    ) -> None:
        self._db = db
        self._verifiers = verifiers

    async def sign_in(self, *, provider: str, id_token: str) -> uuid.UUID:
        """Verify a provider token and return the user it belongs to."""
        verifier = self._verifiers.get(provider)
        if verifier is None:
            # An unconfigured provider is a refused sign-in rather than a 404:
            # answering "we do not support that one" enumerates our setup for
            # anyone asking.
            raise NotAuthenticated(provider=provider)

        identity = await verifier.verify(id_token)

        known = await self._identity(identity)
        if known is not None:
            # Attempted on the returning path too, not only on sign-up. The
            # grant is idempotent, so this costs one indexed read and repairs an
            # account whose creation succeeded while its grant did not.
            await self._ensure_free_minutes(known.user_id)
            return known.user_id

        user_id = await self._linked_by_email(identity)
        if user_id is None:
            user_id = uuid.uuid4()
            self._db.add(Account(user_id=user_id, entitlement_tier=FREE_TIER))
            # Flushed before the identity because the identity references it.
            # SQLAlchemy orders inserts per mapper rather than by dependency,
            # and these two are unrelated as far as it can tell. Still one
            # transaction: a failure after this point rolls the account back
            # with it, so a sign-in cannot leave an account nobody can sign
            # in to.
            await self._db.flush()
            log.info("account_created", user_id=str(user_id), provider=identity.provider)
        else:
            log.info(
                "identity_linked", user_id=str(user_id), provider=identity.provider
            )

        self._db.add(
            AuthIdentity(
                provider=identity.provider,
                subject=identity.subject,
                user_id=user_id,
                email=identity.email,
                email_verified=identity.email_verified,
            )
        )
        try:
            await self._db.commit()
        except IntegrityError as exc:
            if not self._is_identity_violation(exc):
                raise
            # Another device got there first. Everything this transaction wrote
            # rolls back with it — including the account, so a lost race leaves
            # no orphan behind — and the winner's row is now readable.
            await self._db.rollback()
            # Rollback undoes the transaction but leaves the objects we added
            # pending in the session, so the next query autoflushes and tries
            # the same doomed insert again. Everything this attempt built is
            # being abandoned in favour of the winner's row, so it is discarded
            # outright rather than left to resurface.
            self._db.expunge_all()

            winner = await self._identity(identity)
            if winner is None:
                raise

            # Read out as a plain value immediately. Anything below may roll
            # back its own transaction, and a rollback expires every object
            # loaded in it — so a later attribute access would issue a refresh,
            # autoflush on the way, and resurrect the very insert this branch
            # exists to abandon.
            winner_id = winner.user_id

            log.info(
                "sign_in_race_lost",
                user_id=str(winner_id),
                provider=identity.provider,
            )
            await self._ensure_free_minutes(winner_id)
            return winner_id

        await self._ensure_free_minutes(user_id)
        return user_id

    async def _ensure_free_minutes(self, user_id: uuid.UUID) -> None:
        """Product.md §4.4's 15 lifetime minutes, via the owning service.

        Never written here directly: `CLAUDE.md` keeps every ledger movement
        inside `LedgerService`, so that the one place answering "why is this
        balance what it is" stays one place.

        SYSTEM rather than USER. Nobody asked for these minutes — policy granted
        them — and the audit question this actor field answers is "who moved
        this balance", to which "the signup rule did" is the honest reply.
        """
        await LedgerService(
            self._db, actor=ActorContext.system()
        ).grant_signup_free_minutes(user_id=user_id)

    @staticmethod
    def _is_identity_violation(exc: IntegrityError) -> bool:
        """Checked by name, so that any other constraint failing stays a 500.

        Treating every IntegrityError as a lost race would swallow real bugs —
        a broken foreign key would be reported to the user as a successful
        sign-in belonging to somebody else.
        """
        return "uq_auth_identities_provider_subject" in str(getattr(exc, "orig", exc))

    async def _linked_by_email(self, identity: ProviderIdentity) -> uuid.UUID | None:
        """The account this person already has under another provider, if any.

        Both sides must be verified. The incoming claim is worthless unless the
        provider vouched for it, and an existing row whose address was never
        verified is not a safe thing to attach a second sign-in method to —
        that would let an unverified address planted once become a door later.

        Addresses are compared exactly. Apple and Google both return them
        lowercased, and a case mismatch fails to link, which costs a duplicate
        account rather than merging two people — the right direction to fail in.
        """
        if not identity.email or not identity.email_verified:
            return None

        result = await self._db.execute(
            select(AuthIdentity.user_id)
            .where(
                AuthIdentity.email == identity.email,
                AuthIdentity.email_verified.is_(True),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _identity(self, identity: ProviderIdentity) -> AuthIdentity | None:
        result = await self._db.execute(
            select(AuthIdentity).where(
                AuthIdentity.provider == identity.provider,
                AuthIdentity.subject == identity.subject,
            )
        )
        return result.scalar_one_or_none()
