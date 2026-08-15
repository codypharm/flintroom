"""Process configuration.

Two properties matter here and neither is about parsing.

The first is that `.env` configures the whole process. Every variable read
through a second mechanism is a variable that appears to be set and is not —
which is indistinguishable, from the outside, from having set it wrong.

The second is that a misconfigured process fails without saying what the
configuration was. Pydantic's own `ValidationError` prints `input_value=`, and
for a missing field that is the entire settings dict — so the default behaviour
puts the signing key and the provider API key into whatever collects stdout, at
exactly the moment an operator is most likely to be reading it.
"""

from __future__ import annotations

import traceback

import pytest

from app.core.config import ConfigurationError, Settings, get_settings

#: A complete, valid environment. Tests remove from it rather than add to it, so
#: that a new required field breaks every test until it is accounted for here —
#: rather than silently being satisfied by whatever is in the developer's `.env`.
COMPLETE = {
    "DATABASE_URL": "postgresql+asyncpg://user:pw@localhost:5432/flintroom",
    "JWT_SECRET": "x" * 48,
    "GOOGLE_CLIENT_ID": "297.apps.googleusercontent.com",
    "APPLE_CLIENT_ID": "com.flintroom.app",
}


@pytest.fixture
def environment(monkeypatch):
    """The process environment, under the test's control and nobody else's.

    `_env_file=None` on every construction below matters as much as this fixture
    does: the real `.env` sits next to these tests, and a `Settings` that reads
    it would make the suite pass or fail according to what a developer happens
    to have configured locally.
    """
    for key in (*COMPLETE, "ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID"):
        monkeypatch.delenv(key, raising=False)

    def apply(**overrides: str | None) -> None:
        for key, value in {**COMPLETE, **overrides}.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)

    return apply


def test_the_database_url_is_configuration_like_everything_else(environment):
    """The connection string is a settings field, not a separate lookup.

    It used to be read by `create_engine` through `os.getenv`, which never sees
    `.env` — pydantic reads that file only for fields declared here. So a
    `DATABASE_URL=` line in `.env` was accepted by the file, ignored by the
    code, and reported at startup as simply not set.
    """
    environment()

    assert (
        Settings(_env_file=None).database_url
        == "postgresql+asyncpg://user:pw@localhost:5432/flintroom"
    )


def test_a_process_without_a_database_refuses_to_start(environment):
    """No default, for the reason `create_engine` used to give itself.

    A process that boots without a database and discovers it on the first sweep
    looks healthy to every deploy check while silently billing nobody.
    """
    environment(DATABASE_URL=None)

    with pytest.raises(ConfigurationError):
        Settings(_env_file=None)


def test_a_misconfigured_process_names_the_field_it_is_missing(environment):
    """The message has to be actionable, or redaction just makes it useless."""
    environment(JWT_SECRET=None)

    with pytest.raises(ConfigurationError, match="jwt_secret"):
        Settings(_env_file=None)


def test_the_failure_never_carries_the_values_it_was_given(environment):
    """The whole point, and the traceback is where it is easiest to get wrong.

    Raising a redacted error while leaving the `ValidationError` chained prints
    the original underneath it — so the values leak anyway, one frame further
    down, where nobody looks until it is in a log aggregator.
    """
    environment(GOOGLE_CLIENT_ID=None)

    with pytest.raises(ConfigurationError) as caught:
        Settings(_env_file=None)

    rendered = "".join(
        traceback.format_exception(type(caught.value), caught.value, caught.value.__traceback__)
    )

    assert COMPLETE["JWT_SECRET"] not in rendered
    assert "pw@localhost" not in rendered
    # And nothing chained underneath carrying them.
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_get_settings_reports_the_same_failure(environment, monkeypatch, tmp_path):
    """The path the application actually takes, which is the cached one.

    Run from an empty directory. `get_settings` constructs `Settings` with no
    `_env_file` override — by design, that is the whole point of the class — and
    the file it looks for is `.env` relative to the working directory, which in
    this suite is `backend/` and contains a real one. Somewhere else, there is
    nothing to find, and the environment is the only source.
    """
    monkeypatch.chdir(tmp_path)
    environment(APPLE_CLIENT_ID=None)
    get_settings.cache_clear()

    try:
        with pytest.raises(ConfigurationError, match="apple_client_id"):
            get_settings()
    finally:
        get_settings.cache_clear()
