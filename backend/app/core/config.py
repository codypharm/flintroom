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


def _client_ids(given: str) -> tuple[str, ...]:
    """Split a comma-separated list of client IDs, dropping blanks.

    Trailing commas and stray spaces are the normal shape of a hand-edited
    `.env`. An empty entry surviving into the tuple would be an audience that
    matches a token carrying no `aud` at all, which is the one value the pin
    exists to refuse.
    """
    return tuple(entry.strip() for entry in given.split(",") if entry.strip())


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
    #:
    #: **A comma-separated list, because one project has several clients and a
    #: token carries exactly one `aud`.** Google mints the token against
    #: whichever client asked: the native SDK on Android asks with the *web*
    #: client — that is what `webClientId` is, "the client ID of type WEB for
    #: your server" — while iOS can ask with its own. A single pinned value
    #: therefore cannot serve both platforms, and the failure is a 401 that
    #: names nothing, because `sign_in` deliberately refuses to say which check
    #: failed.
    #:
    #: Widening the set does not weaken it. Every value here is a client in our
    #: own project, so a token minted for our iOS app is exactly as trustworthy
    #: as one minted for our web client — and a stranger's client ID is still
    #: not in the set, which is the whole attack the pin exists to stop. It is
    #: also Google's own guidance for backend verification: compare `aud`
    #: against your client IDs, plural.
    #:
    #: A single value still parses to a one-item tuple, so an existing
    #: deployment needs no change to keep working.
    #: Held as the raw string and split by the properties below, rather than
    #: typed as a tuple. `pydantic-settings` JSON-decodes an environment value
    #: whose field is a complex type, so a tuple field would demand
    #: `GOOGLE_CLIENT_ID=["a","b"]` in a `.env` file — a shape nobody writes by
    #: hand and every deployment guide would have to explain.
    google_client_id: str = Field(min_length=1)
    apple_client_id: str = Field(min_length=1)

    @property
    def google_audiences(self) -> tuple[str, ...]:
        """Every Google client whose tokens we accept."""
        return _client_ids(self.google_client_id)

    @property
    def apple_audiences(self) -> tuple[str, ...]:
        """Every Apple client whose tokens we accept.

        Usually one — a native iOS sign-in is addressed to the app's *bundle
        identifier*, not to a Services ID, and Services IDs are for the web
        flow this product does not have. The list exists so adding one later
        is configuration rather than a code change.
        """
        return _client_ids(self.apple_client_id)

    #: The voice vendor, for both halves of a room: Scribe hears it and their
    #: text-to-speech answers in eight cast voices. One key, two adapters —
    #: `voice/transcribers/` and `voice/speakers/`.
    #:
    #: Optional, unlike the secrets above, and the difference is deliberate: a
    #: missing signing key is an insecure default that must never boot, whereas
    #: a missing voice key is an unconfigured integration. Auth, balances,
    #: ingestion and session bookkeeping all work without it, so refusing to
    #: start would take four working routers down with the one that is not
    #: ready.
    #:
    #: It fails closed instead, loudly and typed, at the moment a room is built
    #: — see `voice/room.py`. Missing the transcriber ends the room before a
    #: second is metered; missing only the synthesiser leaves it silent but
    #: captioned, which is a legitimate deployment. The trade is that a
    #: deployment without the key learns at the first session rather than at
    #: boot; if that becomes the more expensive end, make it required.
    elevenlabs_api_key: str | None = None

    #: Which voice speaks for an archetype that has not been assigned one.
    #:
    #: Covers a panelist an adapter cannot cast: a custom archetype that arrived
    #: without a voice, or a character named in `agents/voices.py` that this
    #: vendor's table has not learned yet. Without it those panelists are silent
    #: rather than merely generic, which is the worse of the two failures.
    #:
    #: Optional, on the same grounds as the keys above: a deployment without it
    #: still signs in users and runs rooms. What it loses is the panel's voice,
    #: which fails audibly rather than silently.
    elevenlabs_default_voice_id: str | None = None

    #: What the panel is synthesised with while somebody is waiting on it.
    #:
    #: Flash v2.5, measured at 0.887s to first byte. The turn already costs
    #: 1.38s and the transcriber's silence threshold adds 0.7s before that, so
    #: a listener waits ~2.1s against the ~1.5s at which `CLAUDE.md` says the
    #: illusion breaks. There is nothing here to spend.
    speech_model: str = "eleven_flash_v2_5"

    #: What the room uses for lines nobody is waiting on.
    #:
    #: Eleven v3, measured 2026-08-19: it **performs** audio tags where Flash
    #: reads them aloud, and costs 1.280s to first byte and exactly twice as
    #: many credits per character (`docs/voice-cost.md`). Both prices are real,
    #: and the latency one is only survivable where there is no listener on the
    #: clock — the opening line, spoken before anybody has said anything, and
    #: the debrief coach, which is turn-based and unmetered.
    #:
    #: Set to the same value as `speech_model` to turn the split off entirely.
    expressive_speech_model: str = "eleven_v3"

    #: How long the user must be quiet before the engine calls their turn over.
    #:
    #: **Settable because it cannot be measured.** It sits directly inside
    #: perceived latency — 0.77s of a ~2.15s room, the largest term after
    #: composition — so lowering it is the cheapest latency left. What bounds it
    #: from below is not a number anyone can compute: too low and the panel
    #: talks over somebody drawing breath mid-answer, and a room that interrupts
    #: you cannot be argued with. Synthetic speech has no mid-sentence
    #: hesitations, so no spike and no test can find that floor — only a person
    #: pausing the way people actually pause.
    #:
    #: A judgement that costs an edit and a redeploy per trial is a judgement
    #: nobody makes twice, so this is `.env` rather than a constant.
    #:
    #: `None` means "whatever the adapter chose", rather than repeating its
    #: number here. Two copies of one float in two layers drift silently, and
    #: the reasoning behind the value lives with the vendor it was measured
    #: against — `voice/transcribers/elevenlabs.SILENCE_THRESHOLD_SECS`.
    vad_silence_threshold_secs: float | None = None

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
    #: Two values since #61. It was `Literal["claude"]` alone, which made
    #: switching vendors a missing adapter rather than a setting — discovered
    #: when the Anthropic account could not be funded and a shipped feature
    #: turned out to be unrunnable.
    #:
    #: The failure that produced was the polite kind, and worth remembering:
    #: `build_extraction_model` returns `None` without a key *by design*, so the
    #: process booted, signed people in, accepted uploads, and grounded nothing.
    extraction_provider: Literal["gemini", "claude"] = "gemini"

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
    #: Set alongside `extraction_provider`; the two move together, and a model
    #: name from the wrong vendor is a 404 on every deck.
    #:
    #: A vision model rather than a reasoning one either way. Extraction is not
    #: a judgement — the model pulls what a page says into a typed claim, and
    #: every derived figure is arithmetic computed elsewhere — so there is
    #: nothing here for thinking to improve, and `docs/ingestion.md`'s
    #: ~$0.01/page rests on this line more than on any other.
    extraction_model: str = "gemini-3.5-flash"

    #: Which vendor reads a finished room for the debrief.
    #:
    #: **Two values, and this is the first setting in the codebase that has
    #: any.** The other providers are single-valued `Literal`s because only one
    #: adapter exists for each; here both are written, which is what makes the
    #: model-agnostic claim in `CLAUDE.md` something other than an aspiration.
    #:
    #: Gemini is the default on availability rather than on merit. The Claude
    #: reader was built first — the SDK and tool-use pattern were already here
    #: for extraction — and the Anthropic account cannot currently be funded.
    #: Neither has been measured against a real room yet, so nothing here is a
    #: quality judgement; see `scripts/weakness.py`.
    debrief_provider: Literal["gemini", "claude"] = "gemini"

    #: Which model does that reading, **and here the reasoning model wins** —
    #: the opposite of the measured result recorded above for panel composition,
    #: for reasons that are about the job rather than the vendor.
    #:
    #: A panelist says one short hostile thing under a ~1.5s ceiling, and a
    #: reasoning model answered that with a considered paragraph, slower. The
    #: debrief runs **once, offline, after the room closed**, against no clock at
    #: all, and what it is being asked for is the thing thinking is for: seeing a
    #: fluent, specific, confidently *wrong* answer, which no rule in code can.
    #:
    #: Cost sits differently too. Panel composition runs on every turn of a
    #: *metered* session and lands inside the §4.4 margins Open Risk #4 flags.
    #: This is one call per session on an unmetered phase — a few thousand input
    #: tokens against a room that cost roughly $0.48 to hold.
    #:
    #: Still a setting rather than a constant, because it is the only lever on
    #: debrief quality *and* on debrief cost, and §4.3 wants both measured before
    #: either is defended.
    #: `gemini-3.7-flash` is the model `scripts/panel_spike.py` measured at 2.11s
    #: with 383 thinking tokens — disqualifying for a panelist and exactly right
    #: here. Set alongside `debrief_provider`; the two move together.
    debrief_model: str = "gemini-3.7-flash"

    #: Which model holds the coaching conversation — and **not** the same one
    #: that reads the room, deliberately.
    #:
    #: `debrief_model` thinks, because finding a fluent wrong answer in a whole
    #: transcript is what thinking is for. This is the opposite job: a turn in a
    #: conversation, where a considered paragraph is worse than one sharp
    #: sentence — the result `scripts/panel_spike.py` already measured for the
    #: panel, arriving again for the same reason.
    #:
    #: There is a clock here too, gentler than the room's. Nobody is being
    #: interrogated, but a coach that takes four seconds to answer a follow-up
    #: stops being a conversation and starts being a form, which is §3.5's
    #: "static dashboard" arriving through latency rather than layout.
    coach_model: str = "gemini-3.5-flash"

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
