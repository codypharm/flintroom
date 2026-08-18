import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Situation(Base):
    """One real meeting somebody is preparing for.

    **A row per occasion, not a field on the account**, and the reason is
    lifetime. Role and audience describe how this person is usually received and
    outlive any one meeting, so they sit on `user_preferences`. "Board review,
    the 1st" is true this week and false next — a column would have to be
    overwritten, and overwriting is how a countdown ends up pointing at a
    meeting that happened in March.

    It is also what makes re-onboarding a second row rather than an edit, which
    `docs/onboarding.md` leaves open under *Out of scope → Re-onboarding* and
    will need when somebody comes back after their event has passed.

    This is what replaced streaks. `docs/onboarding.md` rejected them for
    punishing the bursty rehearsal pattern the product exists to serve, and put
    the event countdown in their place — *"urgency drawn from the user's actual
    stakes rather than our engagement metrics"*. That countdown reads from here.
    """

    __tablename__ = "situations"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    #: Plain UUID, never a foreign key to `auth.users` — see CLAUDE.md
    #: → Database portability.
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    #: What kind of room this is, as the client named it.
    #:
    #: A plain string rather than an enum, on the same reasoning
    #: `auth/schemas.py` gives for `provider`: a closed set answers an
    #: unrecognised value by listing the ones we accept, which enumerates our
    #: configuration. It also means adding a situation to the survey is an app
    #: release rather than a migration.
    #:
    #: `other` is a real and expected value, and it is the one this column was
    #: worth adding for: it is the demand signal for the v2 expansion Product.md
    #: §2 wants *"justified by usage data"* rather than enthusiasm. Nothing else
    #: in the product counts how many people arrived for a room we do not build.
    kind: Mapped[str] = mapped_column(String(64), nullable=False)

    #: When it happens, or null.
    #:
    #: Nullable because "I don't know yet" is a true answer and a common one —
    #: a bid goes in when the client schedules it. A required date would be
    #: answered with a guess, and a guessed date is worse than none: the
    #: countdown would be confidently wrong rather than absent.
    #:
    #: A date and not a timestamp. Nobody rehearsing knows the minute, the
    #: countdown is in days, and a timestamp would invent a timezone question
    #: that the product never has to answer.
    happens_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # The countdown asks one question — "what is this person's next room" —
        # and asks it on every launch. Newest first is the answer's own order.
        Index("ix_situations_user_created", "user_id", "created_at"),
    )
