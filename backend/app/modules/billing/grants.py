"""Minutes given by an operator to a list of people.

A promo, the closed-test cohort, a complaint made good. Every grant goes through
`LedgerService.grant_admin`, so the ledger records it once, with the operator's
name, and the reconciliation test covers it like any other movement.

**A campaign is the unit of idempotency, not a run.** Each person's key is
`grant_admin:{campaign}:{user_id}`, so a run that died at the 140th address is
re-run whole and grants the remaining ones only, and the same person can still
receive a second, differently named campaign.

**Unmatched addresses are reported, never guessed.** No account, an unverified
address, or one address on two accounts: each is listed and skipped, because a
typo on line 12 should not cost the other 299 their minutes, and a gift to the
wrong account cannot be taken back without a second hand-written entry.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actors import ActorContext
from app.core.errors import GrantInputInvalid
from app.modules.auth.models import AuthIdentity
from app.modules.billing.service import LedgerService

#: A typo guard, not a policy. Ten hours is more than any promo gives, and a
#: `--minutes 6000` meant as sixty is paid for by every address on the list.
MAX_MINUTES = 600

#: Lowercase, digits and hyphens. It becomes part of an idempotency key (128
#: characters, 49 already spoken for) and a name somebody greps for later.
_CAMPAIGN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass
class GrantReport:
    granted: list[str] = field(default_factory=list)
    already_granted: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)


class OperatorGrants:
    def __init__(self, db: AsyncSession, *, operator: str) -> None:
        if not operator.strip():
            raise GrantInputInvalid("name the operator making this grant")
        self._db = db
        self._ledger = LedgerService(db, actor=ActorContext.admin(operator))

    async def run(
        self,
        *,
        emails: list[str],
        minutes: int,
        campaign: str,
        dry_run: bool = False,
    ) -> GrantReport:
        if not 0 < minutes <= MAX_MINUTES:
            raise GrantInputInvalid(f"minutes must be between 1 and {MAX_MINUTES}")
        if not _CAMPAIGN.match(campaign):
            raise GrantInputInvalid(
                "campaign must be lowercase letters, digits and hyphens, at most 64"
            )

        report = GrantReport()
        for email in _normalised(emails):
            accounts = await self._accounts_for(email)
            if not accounts:
                report.not_found.append(email)
                continue
            if len(accounts) > 1:
                report.ambiguous.append(email)
                continue

            key = f"grant_admin:{campaign}:{accounts[0]}"
            if dry_run:
                # Reads only, so a dry run can say who a real one would skip.
                exists = await self._ledger.has_entry(idempotency_key=key)
                (report.already_granted if exists else report.granted).append(email)
                continue

            granted = await self._ledger.grant_admin(
                user_id=accounts[0], seconds=minutes * 60, idempotency_key=key
            )
            (report.granted if granted else report.already_granted).append(email)

        return report

    async def _accounts_for(self, email: str) -> list[uuid.UUID]:
        """Distinct accounts holding this verified address.

        Verified only, for the reason sign-in linking gives: an unverified
        address is a claim somebody made. Distinct, because one person signed
        in with both Apple and Google is two identities and one account.
        """
        rows = await self._db.scalars(
            select(AuthIdentity.user_id)
            .where(
                AuthIdentity.email == email,
                AuthIdentity.email_verified.is_(True),
            )
            .distinct()
        )
        return list(rows)


def _normalised(emails: list[str]) -> list[str]:
    """Trimmed, lowercased, blank lines dropped, first occurrence kept.

    Lowercased because Apple and Google both return addresses lowercased, and a
    list pasted from a spreadsheet will not be.
    """
    seen: dict[str, None] = {}
    for raw in emails:
        email = raw.strip().lower()
        if email:
            seen.setdefault(email)
    return list(seen)
