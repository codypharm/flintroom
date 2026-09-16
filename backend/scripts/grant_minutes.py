"""Give minutes to people by hand: a promo, the closed test, a complaint made good.

Everything that matters lives in `app/modules/billing/grants.py`, where it is
tested. This file reads a terminal and prints a report.

A script rather than an endpoint, for the reason `dev_token.py` gives: nothing a
deployed process serves, nothing a client can call. Whoever can run this already
holds the production database URL.

Always dry-run first. It prints the database host it is about to write to, which
is how a run meant for production is caught pointing at a laptop, or the reverse:

    railway run uv run python -m scripts.grant_minutes \\
        --email williamikeji@gmail.com --minutes 60 \\
        --campaign demo-video --operator nonso --dry-run

A promo list is one address per line; blank lines and `#` comments are ignored:

    railway run uv run python -m scripts.grant_minutes \\
        --file promo.txt --minutes 30 --campaign launch-week --operator nonso

Re-running the same campaign grants only the people who do not have it yet.

An address on two accounts is skipped, and the report describes both. Name the
right one directly, in the same campaign:

    railway run uv run python -m scripts.grant_minutes \\
        --user-id 3f2c... --minutes 30 --campaign launch-week --operator nonso
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys
import uuid
from datetime import datetime

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.errors import GrantInputInvalid
from app.modules.billing.grants import GrantReport, OperatorGrants


async def grant(
    *,
    emails: list[str],
    user_ids: list[uuid.UUID],
    minutes: int,
    campaign: str,
    operator: str,
    dry_run: bool,
) -> GrantReport:
    settings = get_settings()
    print(f"database: {make_url(settings.database_url).host}", file=sys.stderr)

    engine = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await OperatorGrants(db, operator=operator).run(
                emails=emails,
                user_ids=user_ids,
                minutes=minutes,
                campaign=campaign,
                dry_run=dry_run,
            )
    finally:
        await engine.dispose()


def _emails(args: argparse.Namespace) -> list[str]:
    emails = list(args.email or [])
    if args.file:
        for line in pathlib.Path(args.file).read_text().splitlines():
            if not line.strip().startswith("#"):
                emails.append(line)
    return emails


def _print(report: GrantReport, *, minutes: int, dry_run: bool) -> None:
    verb = "would grant" if dry_run else "granted"
    sections = (
        (f"{verb} {minutes} min", report.granted),
        ("already had this campaign, skipped", report.already_granted),
        ("no account found, skipped", report.not_found),
    )
    for title, labels in sections:
        if labels:
            print(f"\n{title} ({len(labels)}):")
            for label in labels:
                print(f"  {label}")

    if report.ambiguous:
        print(
            f"\naddress on more than one account, skipped ({len(report.ambiguous)}):"
            "\n  pick one and re-run with --user-id, same campaign"
        )
        for email in report.ambiguous:
            print(f"  {email}")
            for c in report.candidates[email]:
                last = _day(c.last_room_at) if c.last_room_at else "never"
                print(
                    f"    {c.user_id}  signs in with {', '.join(c.providers)}; "
                    f"joined {_day(c.joined_at)}; {c.rooms} room(s), last {last}"
                )
    if dry_run:
        print("\ndry run: nothing was written")


def _day(moment: datetime | None) -> str:
    return moment.date().isoformat() if moment else "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--email", action="append", help="An address. Repeatable.")
    parser.add_argument("--file", help="A file of addresses, one per line.")
    parser.add_argument(
        "--user-id",
        action="append",
        type=uuid.UUID,
        help="An account id, for an address on two accounts. Repeatable.",
    )
    parser.add_argument("--minutes", type=int, required=True, help="Per person.")
    parser.add_argument(
        "--campaign",
        required=True,
        help="Names this grant, e.g. launch-week. One grant per person per campaign.",
    )
    parser.add_argument(
        "--operator", required=True, help="Who is giving these. Recorded on every entry."
    )
    parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")
    args = parser.parse_args()

    emails = _emails(args)
    user_ids = list(args.user_id or [])
    if not emails and not user_ids:
        parser.error("give --email, --file or --user-id")

    try:
        report = asyncio.run(
            grant(
                emails=emails,
                user_ids=user_ids,
                minutes=args.minutes,
                campaign=args.campaign,
                operator=args.operator,
                dry_run=args.dry_run,
            )
        )
    except GrantInputInvalid as exc:
        raise SystemExit(exc.message) from None

    _print(report, minutes=args.minutes, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
