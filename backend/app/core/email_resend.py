"""Resend, behind the `EmailSender` contract.

Plain httpx over their one endpoint rather than their SDK, for the reason the
voice adapters already settled: a dependency is a cost, and this is a single
authenticated POST. The vendor never reaches a caller — swapping providers is
this file and the two settings, which is the property every other adapter in
`core/` was built to keep.
"""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__, tag="email")

_ENDPOINT = "https://api.resend.com/emails"

#: Generous for one small POST, tight enough that the caller — a request
#: handler confirming a deletion that has already committed — is never held
#: hostage by a slow vendor.
_TIMEOUT_SECONDS = 10.0


class ResendEmailSender:
    """Sends through Resend. See `core/email.py` for what may be sent."""

    def __init__(self, http: httpx.AsyncClient, *, api_key: str, sender: str) -> None:
        self._http = http
        self._api_key = api_key
        self._sender = sender

    async def send(self, *, to: str, subject: str, text: str) -> None:
        response = await self._http.post(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "from": self._sender,
                "to": [to],
                "subject": subject,
                "text": text,
            },
            timeout=_TIMEOUT_SECONDS,
        )
        # Raised, not absorbed — the contract in `core/email.py`. Never log
        # the address or the text: an email body is the recipient's business,
        # and the address is PII a log line has no need of.
        response.raise_for_status()
        log.info("email_sent", subject=subject)


def build_email_sender(
    settings: Settings, http: httpx.AsyncClient
) -> ResendEmailSender | None:
    """The configured sender, or nothing if this deployment sends no mail.

    Both settings or neither, like the object store: a key without a
    from-address would send mail Resend rejects for an unverified sender —
    surfacing at the one moment somebody is deleting their account, instead
    of as a missing variable at boot.
    """
    if not (settings.resend_api_key and settings.email_from):
        return None

    return ResendEmailSender(
        http, api_key=settings.resend_api_key, sender=settings.email_from
    )
