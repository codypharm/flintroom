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
