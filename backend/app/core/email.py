"""The contract for sending one transactional email.

The same split `core/storage.py` draws: the contract is "send this message",
and the vendor is a sibling adapter (`email_resend.py`). What this seam is
*for* was decided before it was built, and it is one thing: the
account-deletion confirmation — the date a person's seven-day window closes,
in their inbox, because a person who deletes and closes the app has no other
record of it.

What it is deliberately not for, checked case by case in #101:

- Purchase receipts. Google and Apple email store receipts already; a second
  copy from us would be a worse duplicate of a document we are not the
  authority on.
- Balance and period mail. "You are running low" is the rationing pressure
  the metering rules refuse on screen, and it does not become acceptable by
  arriving in an inbox.
- Launch and waitlist mail. That is marketing, it lives in the web waitlist's
  own audience tooling, and this backend never holds those addresses.

Plain text only, deliberately. One email exists; a template engine, HTML
layout and a brand header are machinery for a fleet of messages this product
has refused to have.
"""

from __future__ import annotations

from typing import Protocol


class EmailSender(Protocol):
    """Sends one message to one person. The adapter owns the vendor."""

    async def send(self, *, to: str, subject: str, text: str) -> None:
        """Deliver, or raise.

        Raising is the contract, absorbing is the caller's job: the one
        consumer confirms an action that has already committed, so it catches
        narrowly and logs rather than failing a deletion over a lost email —
        but that is *its* decision to make, and an adapter that swallowed
        failures would make every send look successful to whoever decides
        what to log.
        """
        ...
