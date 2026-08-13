"""What a provider told us about a person, and who that person is here.

Deliberately not a `users` table. `user_id` is a plain UUID minted by us, per
the portability rule in `CLAUDE.md` — never a foreign key into an auth
provider's schema, which is the single decision separating a weekend migration
from a quarter-long one.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuthIdentity(Base):
    """One way one person signs in.

    A person may have several: signing in with Apple and with Google produces
    two rows pointing at one `user_id`, which is what makes them one account.
    """

    __tablename__ = "auth_identities"
    __table_args__ = (
        # The identity itself. A provider's subject is unique only within that
        # provider, so neither column identifies anyone alone — and this pair is
        # what stops a second sign-in minting a second account, including when
        # two devices race.
        UniqueConstraint(
            "provider", "subject", name="uq_auth_identities_provider_subject"
        ),
        # Read on every sign-in that finds no existing identity, to decide
        # whether this is a new person or a known one arriving by another door.
        Index("ix_auth_identities_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)

    #: The provider's stable identifier for this person. Opaque, and the only
    #: field here that never changes — an email can be changed at the provider,
    #: this cannot.
    subject: Mapped[str] = mapped_column(String(255), nullable=False)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.user_id"), nullable=False, index=True
    )

    #: Nullable because a provider need not supply one, and Apple's Hide My
    #: Email supplies a relay address instead. Stored for linking, not display.
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    #: Whether the *provider* vouched for the address. Linking reads this and
    #: nothing else — an unverified email is an attacker's claim, not a fact.
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RefreshToken(Base):
    """A long-lived credential, stored as a hash and spent when used.

    The access token cannot be revoked — nothing is looked up to verify one —
    so this row is where a session can actually be ended. Everything about the
    shape follows from that: it is a row rather than a signed blob precisely so
    that deleting it means something.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    #: SHA-256 of the token, never the token. A database dump, a leaked backup
    #: or an over-broad SELECT then yields nothing usable — which is the whole
    #: reason this table is worth less to an attacker than it looks.
    #:
    #: A plain hash rather than bcrypt/argon2 because the input is 32 bytes of
    #: `secrets` output, not a human-chosen password: there is no dictionary to
    #: run and nothing for a slow KDF to buy.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.user_id"), nullable=False, index=True
    )

    #: Every token descended from one sign-in shares this. Rotation means the
    #: thief and the victim end up holding two tokens from the same family, so
    #: revoking the family is what turns "someone replayed a spent token" into
    #: "that session is over for both of them".
    family_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )

    #: Set when the token is exchanged. A second exchange of the same row is
    #: the signal that a copy exists somewhere it should not.
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
