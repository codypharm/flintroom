import asyncio
import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from app.core.database import Base, get_db
from app.core.errors import NotAuthenticated
from app.core.storage_s3 import S3ObjectStorage
from app.main import create_app
from app.modules.auth.dependencies import get_access_tokens, get_verifiers
from app.modules.auth.oidc import ProviderIdentity
from app.modules.auth.service import AuthService
from app.modules.auth.tokens import AccessTokens
from app.modules.audit_log.models import AuditEvent  # noqa: F401  (registers the table)
from app.modules.auth.models import (  # noqa: F401  (registers the tables)
    AuthIdentity,
    RateLimitCounter,
    RefreshToken,
)
from app.modules.billing.models import Account
from app.modules.billing.dependencies import get_webhook_secret
from app.modules.ingestion.dependencies import get_object_storage
from app.modules.ingestion.models import (  # noqa: F401  (registers the tables)
    ExtractionCost,
    Material,
    MaterialClaim,
)
from app.modules.ingestion.service import IngestionService
from app.modules.audit_log.admin import AdminService
from app.modules.audit_log.service import AuditService
from app.modules.billing.schemas import Bucket, EntryReason
from app.modules.billing.service import LedgerService
from app.modules.billing.tiers import FREE_TIER_LIFETIME_SECONDS
from app.modules.sessions.models import (  # noqa: F401  (registers the tables)
    Session,
    SessionPhaseSpan,
)
from app.modules.voice.costs import SessionCost  # noqa: F401  (registers the table)
from app.modules.voice.models import VoiceTicket  # noqa: F401  (registers the table)
from app.modules.sessions.meter import MeterService
from app.modules.sessions.reaper import ReaperService
from app.modules.sessions.service import SessionService
from app.modules.sessions.settlement import SettlementService

BACKEND_ROOT = Path(__file__).resolve().parent.parent

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://flintroom:flintroom@localhost:55432/flintroom_test",
)

TEST_S3_ENDPOINT_URL = os.getenv("TEST_S3_ENDPOINT_URL", "http://localhost:59000")
TEST_S3_BUCKET = os.getenv("TEST_S3_BUCKET", "flintroom-material")


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Build the schema by running the migrations, not from model metadata.

    `create_all` would test the models against themselves and never execute a
    migration, so a missing or wrong migration would pass every test and fail
    on deploy. Running them here means the migration chain is exercised on every
    test run, and a model change without a migration shows up as a failure.
    """
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    await asyncio.to_thread(_upgrade_to_head)

    yield engine
    await engine.dispose()


def _upgrade_to_head() -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    """A session per test, with every table emptied first."""
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def session_factory(db, engine):
    """A factory, for the callers that need a session of their own.

    Depends on `db` so the truncation that fixture performs has already happened
    — a factory handed out before it would open sessions onto the previous
    test's rows.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def ledger(db) -> LedgerService:
    return LedgerService(db)


@pytest.fixture
def audit(db) -> AuditService:
    return AuditService(db)


@pytest.fixture
def admin(db) -> AdminService:
    return AdminService(db)


@pytest.fixture
def sessions(db) -> SessionService:
    return SessionService(db)


@pytest.fixture
def storage() -> S3ObjectStorage:
    """The MinIO in `docker-compose.yml`, not a stub.

    `docs/ingestion.md` refused a filesystem shim for development because a
    filesystem cannot do direct-to-storage PUT without proxying — so a shim
    would leave the presigned path unexercised until deploy. The same argument
    applies to the service tests: the byte cap is enforced by the signature, and
    a fake that returns a plausible URL would prove nothing about it.
    """
    return S3ObjectStorage(
        endpoint_url=TEST_S3_ENDPOINT_URL,
        access_key_id="flintroom",
        secret_access_key="flintroom",
        bucket=TEST_S3_BUCKET,
        region="us-east-1",
        addressing_style="path",
    )


@pytest.fixture
def ingestion(db, storage) -> IngestionService:
    return IngestionService(db, storage=storage)


@pytest_asyncio.fixture
async def account(db) -> Account:
    """An account with every bucket empty. Minutes arrive only via grants."""
    account = Account(user_id=uuid.uuid4(), entitlement_tier="free")
    db.add(account)
    await db.commit()
    return account


@pytest_asyncio.fixture
async def funded_account(db, ledger) -> Account:
    """An account as a real one exists: signed up, holding its free minutes.

    Starting a session requires a balance, so any test that opens a room needs
    this rather than the empty account above. The empty one stays for the ledger
    tests, which care precisely about a balance built up from nothing.
    """
    return await create_funded_account(db, ledger)


async def create_funded_account(db, ledger) -> Account:
    """An account as a real one exists: signed up, with its free minutes.

    Starting a session requires a balance, so the modules that exercise the
    session lifecycle need this rather than the empty account above. Kept as a
    helper called by a per-module `account` override, so that the ledger tests —
    which care precisely about a balance built from nothing — keep the empty one.
    """
    account = Account(user_id=uuid.uuid4(), entitlement_tier="free")
    db.add(account)
    await db.commit()

    await ledger.grant(
        user_id=account.user_id,
        bucket=Bucket.FREE,
        seconds=FREE_TIER_LIFETIME_SECONDS,
        reason=EntryReason.GRANT_FREE,
        idempotency_key=f"grant_free:{account.user_id}",
    )
    return account


@pytest.fixture
def settlement(db) -> SettlementService:
    return SettlementService(db)


@pytest.fixture
def reaper(db) -> ReaperService:
    return ReaperService(db)


@pytest.fixture
def meter(db) -> MeterService:
    return MeterService(db)


# --- HTTP harness ---------------------------------------------------------
#
# Shared because three test modules need it, and a per-module copy drifts: the
# one that forgets an override fails for a reason unrelated to what it tests.

SECRET = "test-signing-key-with-no-production-counterpart"


@pytest.fixture
def bearer():
    """Headers that authenticate as a given user.

    Minted rather than obtained by signing in. Every module with an HTTP test
    needs a credential, and routing all of them through the provider stub would
    make one sign-in regression fail in six places that have nothing to say
    about sign-in.

    Here rather than copied per module, which is what it was until six copies
    existed and had already drifted. Nothing asserts anything about the token's
    shape, so a change to how one is issued — an audience claim, a key id, a
    rotation — would be missed in whichever copy nobody edited, and those tests
    would keep passing while quietly authenticating nothing.
    """

    def headers(user_id: uuid.UUID) -> dict[str, str]:
        token = AccessTokens(secret=SECRET).issue(user_id=user_id)
        return {"Authorization": f"Bearer {token}"}

    return headers


class StubProvider:
    """A provider that vouches for whatever it was told to vouch for."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._tokens: dict[str, ProviderIdentity] = {}

    def token_for(
        self, *, subject: str, email: str | None = None, email_verified: bool = True
    ) -> str:
        token = f"{self.name}:{subject}"
        self._tokens[token] = ProviderIdentity(
            provider=self.name,
            subject=subject,
            email=email,
            email_verified=email_verified,
        )
        return token

    async def verify(self, id_token: str) -> ProviderIdentity:
        try:
            return self._tokens[id_token]
        except KeyError:
            raise NotAuthenticated() from None


@pytest.fixture
def google() -> StubProvider:
    return StubProvider("google")


@pytest.fixture
def apple() -> StubProvider:
    return StubProvider("apple")


@pytest_asyncio.fixture
async def auth(db, google, apple) -> AuthService:
    return AuthService(db, verifiers={"google": google, "apple": apple})




#: What the test app verifies store callbacks against. A separate secret from
#: `SECRET` on purpose: they authenticate different things, and a test that
#: passed because the two happened to be equal would prove nothing.
WEBHOOK_SECRET = "rc-signing-secret-with-no-production-counterpart"


def _configured_app(db, google, apple, storage, *, webhook_secret: str | None):
    """The app with every external edge substituted, and nothing else changed.

    The lifespan is deliberately not run: it starts the sweep loops and opens a
    second connection pool, neither of which any HTTP test here is about.
    """
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    # Substituted rather than read from the environment. The real settings are
    # required fields with no defaults — a process must not boot without a
    # signing key — which also means a test cannot rely on ambient env.
    app.dependency_overrides[get_access_tokens] = lambda: AccessTokens(secret=SECRET)
    app.dependency_overrides[get_verifiers] = lambda: {"google": google, "apple": apple}
    # The real store, not a fake. Substituted rather than read off app state
    # because that is populated by the lifespan, which is deliberately not run.
    app.dependency_overrides[get_object_storage] = lambda: storage
    app.dependency_overrides[get_webhook_secret] = lambda: webhook_secret
    return app


@pytest_asyncio.fixture
async def client(db, google, apple, storage):
    """The app as a deployment that is configured properly."""
    async with AsyncClient(
        transport=ASGITransport(
            app=_configured_app(db, google, apple, storage, webhook_secret=WEBHOOK_SECRET)
        ),
        base_url="http://test",
    ) as client:
        yield client


@pytest_asyncio.fixture
async def client_without_webhook_secret(db, google, apple, storage):
    """The app as a deployment that came up missing one variable.

    Worth a whole fixture because the failure is the interesting one: this
    endpoint is the only place where "not configured" and "accepts anything"
    are one refactor apart, and the difference is minutes granted to whoever
    finds the URL.
    """
    async with AsyncClient(
        transport=ASGITransport(
            app=_configured_app(db, google, apple, storage, webhook_secret=None)
        ),
        base_url="http://test",
    ) as client:
        yield client
