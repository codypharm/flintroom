"""Process configuration.

`database.py` deferred this deliberately — inventing a settings module meant
choosing a configuration library, which is a dependency decision. That choice is
already made: `pydantic-settings` has been a declared dependency since the
project was scaffolded, so this adds nothing new.

Fields arrive as the code that needs them arrives. A settings class listing
everything the product might eventually want is a list of things nobody can
delete, because nobody can tell which entries are still load-bearing.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Configuration that cannot be used, described without being quoted.

    Raised instead of letting pydantic's own `ValidationError` reach a terminal.
    That one renders `input_value=`, and for a missing field the input value is
    the *entire* settings dict — so the default behaviour prints the signing key
    and the provider API key at the moment an operator is most likely to be
    watching the logs, and into whatever aggregates them afterwards.
    """


def _describe(error: ValidationError) -> str:
    """Which fields are wrong and how, and nothing about what they contain.

    `loc` and `msg` only. Pydantic also offers the offending input, which is the
    part that must never be repeated — a message that quotes the value is a
    message that cannot be logged, and one that names no field cannot be acted
    on. Both halves of that are required at once.
    """
    problems = ", ".join(
        f"{'.'.join(str(part) for part in item['loc'])} ({item['msg']})"
        for item in error.errors(include_url=False, include_input=False)
    )
    return f"configuration is invalid: {problems}"


class Settings(BaseSettings):
    """Read from the environment, and from a local `.env` that is never committed."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    #: Where the database is. Declared here rather than read by `create_engine`
    #: through `os.getenv`, which is what it used to do — and which never saw
    #: `.env`, because pydantic reads that file only for the fields on this
    #: class. A `DATABASE_URL=` line was therefore accepted by the file, ignored
    #: by the code, and reported at startup as simply not set.
    #:
    #: No default. A process that boots without a database and discovers it on
    #: the first sweep looks healthy to every deploy check while silently
    #: billing nobody.
    database_url: str = Field(min_length=1)

    #: Signs our own access tokens. Required, with no default — a signing key
    #: that falls back to a literal is a key that ships, and every deployment
    #: that forgot to set one can then forge tokens for every other.
    #:
    #: 32 bytes is the floor RFC 7518 sets for HMAC-SHA256: below it the key is
    #: weaker than the hash and becomes brute-forceable offline by anyone
    #: holding one token. Enforced here so a short key is a process that refuses
    #: to boot rather than a warning nobody reads.
    jwt_secret: str = Field(min_length=32)

    #: The client IDs our provider tokens must be addressed to. These are the
    #: `aud` values `OidcVerifier` pins, and pinning them is what stops a
    #: genuine Google token minted for somebody else's app signing in here.
    #: Required, because a blank audience is a verifier that checks nothing.
    google_client_id: str = Field(min_length=1)
    apple_client_id: str = Field(min_length=1)

    #: The voice provider. Optional, unlike the secrets above, and the
    #: difference is deliberate: a missing signing key is an insecure default
    #: that must never boot, whereas a missing voice key is an unconfigured
    #: integration. Auth, balances and session bookkeeping all work without it,
    #: so refusing to start would take four working routers down with the one
    #: that is not ready.
    #:
    #: It fails closed instead, loudly and typed, at the moment a room tries to
    #: open — see `voice.dependencies.get_voice_provider`. The trade is that a
    #: deployment missing the key learns at the first session rather than at
    #: boot; if that becomes the more expensive end, make these required.
    elevenlabs_api_key: str | None = None
    elevenlabs_agent_id: str | None = None

    #: Which voice speaks for an archetype that has not been assigned one.
    #:
    #: The library ships with `voice_id=None` on every archetype, so without this
    #: an orchestrated room is silent. A configured fallback means synthesis can
    #: be wired and heard before the eight voices have been chosen — and choosing
    #: them is a casting decision with a taste component, not a deployment step.
    #:
    #: Optional, on the same grounds as the keys above: a deployment without it
    #: still signs in users and runs rooms. What it loses is the panel's voice,
    #: which fails audibly rather than silently.
    elevenlabs_default_voice_id: str | None = None

    #: What RevenueCat signs its callbacks with, from the webhook integration's
    #: HMAC settings.
    #:
    #: Optional on the same grounds as the keys above — a deployment without it
    #: still signs in users, runs rooms and spends minutes — but the failure is
    #: the opposite shape and worth knowing: the callback endpoint refuses
    #: *everything* rather than accepting it. Purchases stop being credited,
    #: loudly, and RevenueCat's five retries then deliver whatever arrived in the
    #: gap once the secret is set.
    #:
    #: The alternative was an endpoint that grants minutes to anyone who finds
    #: it while looking perfectly healthy, which is not a trade.
    revenuecat_webhook_secret: str | None = None

    #: Where material lives. Optional on the same grounds as the voice keys —
    #: a deployment without a bucket still signs in users, tracks balances and
    #: runs the voice loop, and `docs/auditor-grounding.md` makes the deckless
    #: path first-class rather than degraded. Absent means ingestion refuses.
    #:
    #: The endpoint is what makes this portable: MinIO in development, and AWS
    #: S3, Cloudflare R2 or Backblaze B2 in production, with no code change.
    #: It is required rather than defaulted to AWS, because a blank endpoint
    #: that silently means "the real S3" is a credential sent to the wrong host.
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket: str | None = None

    #: SigV4 signs over a region whether or not the store has regions. MinIO
    #: accepts any value; S3 does not, so this is a real setting with a default
    #: that happens to be right for development.
    s3_region: str = "us-east-1"

    #: Where the bucket name goes — in the hostname, or in the path.
    #:
    #: Defaults to the hostname because AWS has said path-style URLs *"will be
    #: discontinued in the future"*. That deprecation was delayed indefinitely
    #: in September 2020 and carries a promise of a year's notice, so path-style
    #: works everywhere today; it is still the wrong thing to bake into a
    #: production deployment when the alternative is a default.
    #:
    #: `path` is for stores with no DNS to put a bucket in front of — MinIO in
    #: development, and Cloudflare R2, which documents it. A `Literal`, so a
    #: typo is a process that refuses to boot rather than a signature the store
    #: rejects at upload time.
    s3_addressing_style: Literal["virtual", "path", "auto"] = "virtual"

    #: Which vendor reads a deck. A `Literal` rather than a free string, so a
    #: typo is a process that refuses to boot — the alternative failure is a
    #: deployment that starts, signs people in, accepts uploads, and grounds
    #: nothing, because `EXTRACTION_PROVIDER=cluade` silently meant "none".
    #:
    #: Decided independently of the panel LLM (task #13). The two jobs have
    #: opposite requirements: extraction is batch, latency-insensitive and
    #: structured-output; the panel is conversational and dies above ~1.5s.
    extraction_provider: Literal["claude"] = "claude"

    #: Optional, on the same grounds as the voice keys and the bucket. Absent
    #: means material cannot be read; it does not mean the process should refuse
    #: to start, because the deckless path is first-class rather than degraded
    #: (`docs/auditor-grounding.md`).
    #:
    #: Shared by extraction and — once it exists — the panel. One vendor, one
    #: credential: splitting them would mean two keys to rotate and two places to
    #: look when a 401 arrives, for no isolation that matters, since both bill the
    #: same organisation.
    anthropic_api_key: str | None = None

    #: Which vendor writes the panel's lines. A `Literal` for the same reason
    #: `extraction_provider` is one: a typo should refuse to boot rather than
    #: produce a deployment that signs people in, opens rooms, and has nobody in
    #: them.
    #:
    #: Gemini first because it has a free tier and the Anthropic account does
    #: not yet have credit — the adapter that can be measured rather than only
    #: stubbed. `docs/panel-orchestration.md` puts both behind one interface so
    #: that ordering costs nothing.
    panel_provider: Literal["gemini"] = "gemini"

    #: Which model writes the line. **Measured, the cheap one wins** — 0.82s
    #: against 2.11s, and a sharper line, because a panelist says one short thing
    #: and a reasoning model produces a considered paragraph. The assumption going
    #: in was the opposite; see `panel_models/gemini.py` for the transcript.
    #:
    #: Stable rather than preview, deliberately: a room somebody is paying for by
    #: the minute is the wrong place for a model that can be withdrawn. Both are
    #: settings rather than constants because the panel runs on *every turn of a
    #: metered session*, which puts them inside the §4.4 margins that Open Risk
    #: #4 already says rest on an unverified number.
    panel_composition_model: str = "gemini-3.5-flash-lite"

    #: The second panel vendor, held for comparison rather than for failover.
    #:
    #: `docs/panel-orchestration.md` puts the panel model behind an interface
    #: precisely so Claude and Gemini can be measured against each other on cost
    #: and latency per turn — the panel runs on every turn of a *metered* session,
    #: so it lands inside the §4.4 margins that Open Risk #4 already flags.
    #:
    #: Inert until the Gemini adapter is written. Setting it early is harmless
    #: and costs nothing; nothing reads it yet.
    gemini_api_key: str | None = None

    #: Which model, within that vendor. A setting rather than a constant because
    #: it is the largest single lever on extraction cost, and every figure in
    #: `docs/ingestion.md` rests on an unverified ~$0.01 per page. Changing it is
    #: a cost decision that belongs to a human holding measured numbers from
    #: `extraction_costs` — not to whoever is editing the adapter.
    extraction_model: str = "claude-sonnet-5"

    #: How many model calls one deck may have in flight at once.
    #:
    #: A setting rather than a constant because the right value depends on a
    #: number invisible from code — the deployment's input-tokens-per-minute
    #: allowance, which is per *organisation* and shared by every user, not per
    #: account. One call held continuously costs `tokens_per_call × 60 /
    #: call_seconds` tokens a minute, so the ceiling moves with the tier and
    #: with how long a call takes.
    #:
    #: Four is a bet, not a derivation: at a low allowance and a fast call it is
    #: already too high, and at a generous one it wastes capacity. It stays a
    #: bet until a real deck has been timed, and the point of the setting is
    #: that losing the bet is a config change on the evening it starts
    #: rate-limiting rather than a deploy.
    #:
    #: Deriving it from a declared allowance was considered and refused: the
    #: arithmetic needs seconds-per-call, which nothing can currently measure,
    #: so it would launder one guess into a formula that reads as computed. The
    #: closed-loop answer is to throttle on the rate-limit headers the provider
    #: already returns, and that needs traffic to be worth building.
    extraction_concurrent_calls: int = Field(default=4, ge=1, le=64)

    #: Pages one account may have extracted in a rolling twenty-four hours.
    #:
    #: A circuit breaker, not an entitlement — the same category as §4.7's
    #: per-account daily spend ceiling, and uniform across tiers on purpose. The
    #: per-tier budget in `billing/tiers.py` protects margin over a month; this
    #: one exists for the failure that has nothing to do with plans, where a
    #: loop, a bug or a script spends a month's budget in an afternoon.
    #:
    #: Here rather than in the tier table because it is not a pricing figure and
    #: must not read as one. It is a number to turn down at 3am by setting an
    #: environment variable and restarting, rather than by shipping a release.
    #:
    #: **The floor is the largest per-file cap, and it is structural.** Below
    #: that, a plan refuses to extract a file it sold: pro sells 300 pages per
    #: file, so a 200-page ceiling blocked the second upload of a deck somebody
    #: had just re-exported to fix a typo — the most ordinary thing a user of
    #: this product does, read as a runaway. `test_material_limits.py` holds the
    #: invariant so the two numbers cannot drift back into contradiction.
    #:
    #: 600 clears pro's cap twice over. It is calibrated against *peak*
    #: legitimate use rather than typical use (~40–80 pages a month), because a
    #: circuit breaker set just above the average trips on the users it was
    #: never meant to catch. The monthly budget is what actually caps spend;
    #: this only has to stop a loop from eating the whole month before anyone
    #: notices, and at pro it still takes two days to get there.
    daily_page_ceiling: int = Field(default=600, ge=1)

    #: Where headless LibreOffice is. A fact about the machine, not a knob.
    #:
    #: Reached only for PPTX, and only to convert the file to PDF so it rejoins
    #: the PDF path — which is where the thumbnail and the page images come from,
    #: and the only way to see a chart pasted into a slide as a screenshot.
    #:
    #: A `Settings` field rather than an `os.getenv` in `parsing.py`, because
    #: `.env` is not loaded into the process environment: a variable read that way
    #: is present in the file and absent from the process, which is the failure
    #: `docs/deployment.md` calls the worst available one.
    #:
    #: Without the binary, PPTX fails as unreadable while PDFs and photographs
    #: carry on working. That is the right way round and not one anybody diagnoses
    #: quickly, so `libreoffice_missing` is logged with the path that was tried.
    #: The literal rather than an import from `parsing`, which would pull
    #: pdfium, Pillow and python-pptx into everything that reads a setting —
    #: alembic and the scripts included. Same split as `daily_page_ceiling`, and
    #: guarded the same way: `tests/test_config.py` fails if the two disagree.
    libreoffice_binary: str = Field(default="soffice")

    def __init__(self, **values: object) -> None:
        """Fail as `ConfigurationError`, carrying nothing underneath it.

        The re-raise deliberately happens *after* the `except` block rather than
        inside it. Inside, Python would attach the original as `__context__`
        even with `from None` — suppressed in a printed traceback, but still
        reachable by anything that walks the chain itself, which log formatters
        do. Outside, there is no exception being handled and nothing to attach.
        """
        problems: str | None = None

        try:
            super().__init__(**values)
        except ValidationError as error:
            problems = _describe(error)

        if problems is not None:
            raise ConfigurationError(problems)


@lru_cache
def get_settings() -> Settings:
    """Cached, because reading and validating the environment per request is waste.

    Injected as a dependency rather than imported as a module global so tests
    can substitute one without touching the process environment.
    """
    return Settings()
