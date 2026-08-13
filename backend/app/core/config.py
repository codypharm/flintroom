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

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from the environment, and from a local `.env` that is never committed."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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


@lru_cache
def get_settings() -> Settings:
    """Cached, because reading and validating the environment per request is waste.

    Injected as a dependency rather than imported as a module global so tests
    can substitute one without touching the process environment.
    """
    return Settings()
