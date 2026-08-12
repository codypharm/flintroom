"""Row-level security — the wall behind the wall.

`CLAUDE.md` is explicit that service-role access through FastAPI is the real
boundary and RLS is defense-in-depth. That makes the threat model here specific:
not "a bug in our API", but *a credential that is not ours reaching the database
directly* — a leaked Supabase key, PostgREST left enabled, an analytics user
granted more than intended.

Which is why the intruder below is deliberately **granted** SELECT and INSERT.
A role with no grants cannot read these tables whether or not RLS exists, so a
test built on one would pass against a database with no policies at all. Granting
first removes every other explanation for the denial, leaving only the thing
under test. It also matches the real shape of the threat: Supabase's `anon` and
`authenticated` roles carry grants.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import Base
from app.modules.billing.schemas import Bucket, EntryReason

from .conftest import TEST_DATABASE_URL

INTRUDER = "flintroom_intruder"
INTRUDER_PASSWORD = "intruder"


async def _drop_intruder(conn) -> None:
    """Remove the role and everything granted to it.

    Roles are cluster-level rather than per-database, so a run killed mid-test
    leaves one behind. `DROP OWNED BY` first because a role holding grants
    cannot be dropped.
    """
    await conn.execute(
        text(f"""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{INTRUDER}') THEN
                EXECUTE 'DROP OWNED BY {INTRUDER}';
                EXECUTE 'DROP ROLE {INTRUDER}';
            END IF;
        END $$;
        """)
    )


@pytest_asyncio.fixture
async def intruder(engine):
    """A logged-in role holding real grants and no legitimate business here."""
    async with engine.begin() as conn:
        await _drop_intruder(conn)
        await conn.execute(
            text(f"CREATE ROLE {INTRUDER} LOGIN PASSWORD '{INTRUDER_PASSWORD}'")
        )
        await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {INTRUDER}"))
        await conn.execute(
            text(
                "GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public "
                f"TO {INTRUDER}"
            )
        )
        # Without this an INSERT is refused for want of sequence usage, which
        # looks like a denial but is not the one under test — and would still
        # be refused with RLS switched off entirely.
        await conn.execute(
            text(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {INTRUDER}")
        )

    url = make_url(TEST_DATABASE_URL).set(
        username=INTRUDER, password=INTRUDER_PASSWORD
    )
    intruder_engine = create_async_engine(url, poolclass=None)
    try:
        yield intruder_engine
    finally:
        await intruder_engine.dispose()
        async with engine.begin() as conn:
            await _drop_intruder(conn)


async def test_a_leaked_credential_cannot_read_the_ledger(
    intruder, ledger, account
):
    """The tracer: real money is in the table and the wrong role sees none of it.

    `ledger_entries` is the most sensitive table in the product — it is the
    complete record of what every user paid for and when. The entry is written
    and committed through the ordinary service first, so the denial is about who
    is asking rather than about an empty table.
    """
    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.ALLOWANCE,
        seconds=600,
        reason=EntryReason.GRANT_ALLOWANCE,
        idempotency_key="grant-1",
    )

    async with intruder.connect() as conn:
        visible = await conn.execute(text("SELECT count(*) FROM ledger_entries"))

    assert visible.scalar_one() == 0


async def test_a_leaked_credential_cannot_forge_a_ledger_entry(intruder, account):
    """Reading the ledger is a privacy breach; writing it is free minutes.

    The forged row is deliberately valid — every NOT NULL column filled and a
    real account referenced — so that nothing but the policy can reject it. A
    row missing a column would be refused by the constraint instead, and the
    test would pass against a database with no RLS at all.

    The assertion pins the *reason* for the same purpose: 'denied' and 'denied
    because of row-level security' are different results, and only one of them
    means this migration works.
    """
    forged = text("""
        INSERT INTO ledger_entries
            (user_id, bucket, delta_seconds, reason, idempotency_key)
        VALUES
            (:user_id, 'allowance', 3600, 'grant_allowance', 'forged-1')
    """).bindparams(user_id=account.user_id)

    with pytest.raises(DBAPIError) as refused:
        async with intruder.begin() as conn:
            await conn.execute(forged)

    assert "row-level security" in str(refused.value).lower()


async def test_every_table_is_behind_row_level_security(db):
    """The guard that outlives this change.

    The two tests above prove the wall works on one table. This one proves it
    is in front of all of them, and keeps proving it — the list comes from the
    model metadata rather than being written out here, so a table added next
    month without a policy fails this test instead of quietly shipping.

    That is the realistic failure. Nobody forgets RLS on the table they are
    thinking about; they forget it on the fourth one, months later, under
    deadline.
    """
    declared = {table.name for table in Base.metadata.sorted_tables}

    result = await db.execute(
        text("""
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public' AND rowsecurity IS TRUE
        """)
    )
    protected = {row[0] for row in result.all()}

    assert declared - protected == set()


async def test_no_policy_depends_on_supabase_auth(db):
    """The policies have to survive leaving Supabase.

    `CLAUDE.md` keeps Supabase as managed Postgres and nothing else, so that a
    move to RDS or Cloud SQL is a `pg_dump` and a connection string. A policy
    calling `auth.uid()` breaks that quietly: it is valid here and a syntax
    error there, and it is discovered during the migration rather than before
    one is contemplated.

    Matching the whole `auth.` schema rather than `uid()` alone catches `jwt()`
    and `role()` too — the trap is the dependency, not the one function.
    """
    result = await db.execute(
        text("""
        SELECT tablename, policyname
        FROM pg_policies
        WHERE schemaname = 'public'
          AND (COALESCE(qual, '') || COALESCE(with_check, '')) ILIKE '%auth.%'
        """)
    )

    assert result.all() == []
