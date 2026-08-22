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
    for key in (*COMPLETE, "ELEVENLABS_API_KEY"):
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


def test_the_converter_path_has_one_default_in_two_places():
    """`Settings` holds the literal; `parsing` holds the constant it defaults to.

    Split on purpose — importing `parsing` from `config` would pull pdfium,
    Pillow and python-pptx into alembic and every script that reads a setting.
    The cost of the split is that the two can disagree, and a disagreement is
    silent: PPTX would fail as unreadable on a machine where the binary is
    present, and PDFs would carry on working, so nothing would look broken.
    """
    from app.modules.ingestion.parsing import DEFAULT_LIBREOFFICE_BINARY

    assert (
        Settings.model_fields["libreoffice_binary"].default
        == DEFAULT_LIBREOFFICE_BINARY
    )


def test_one_backend_serves_every_client_of_one_project(environment):
    """Three clients, one token, one `aud` — so the pin has to be a set.

    Google addresses an ID token to whichever client asked for it, and the
    native SDK asks with a different client on each platform. A single pinned
    value cannot serve both, and the resulting 401 names nothing: `sign_in`
    refuses to say which check failed, deliberately, because saying so
    enumerates our configuration.

    Comma-separated rather than JSON because this is written by hand in a
    `.env`, and `GOOGLE_CLIENT_ID=["a","b"]` is a shape every deployment note
    would have to explain.
    """
    environment(GOOGLE_CLIENT_ID="web.example, ios.example")

    assert Settings(_env_file=None).google_audiences == ("web.example", "ios.example")


def test_a_blank_entry_never_becomes_an_audience(environment):
    """A trailing comma is the normal shape of a hand-edited file.

    An empty string surviving into the tuple would be an audience matching a
    token that carries no `aud` at all — the one value the pin exists to refuse.
    """
    environment(GOOGLE_CLIENT_ID="web.example,, ")

    assert Settings(_env_file=None).google_audiences == ("web.example",)


def test_a_single_client_still_works_unchanged(environment):
    """Every deployment today holds one value, and must keep working."""
    environment(APPLE_CLIENT_ID="com.flintroom.app")

    assert Settings(_env_file=None).apple_audiences == ("com.flintroom.app",)


#: Field names whose value must never reach a traceback, a log or a repr.
#:
#: Matched on the name rather than listed by hand, so a credential added next
#: year is covered by the guard that already exists rather than by somebody
#: remembering to extend a list.
SECRET_ISH = ("secret", "key", "password", "token", "database_url")


def test_settings_never_print_what_they_hold():
    """A real leak, on 2026-08-20, and not a hypothetical one.

    `create_engine(url: str)` was handed the whole `Settings` object by mistake.
    SQLAlchemy's `ArgumentError` reprs what it was given, so the traceback
    printed the JWT secret, three provider API keys and the database password
    into a terminal — and would do the same into any log aggregator.

    #28 was "stop boot from leaking secrets" and covered the values a *successful*
    boot logs. This is the other path: the values an *unsuccessful* anything
    carries. `repr` is what tracebacks, logging's `%r`, and most debuggers reach
    for, so the guard belongs there rather than at each call site.
    """
    settings = Settings(
        database_url="postgresql+asyncpg://u:hunter2@localhost/db",
        jwt_secret="a-real-signing-secret-of-at-least-32-chars",
        google_client_id="public.apps.googleusercontent.com",
        apple_client_id="com.flintroom.app",
        elevenlabs_api_key="sk_a_real_key",
        anthropic_api_key="sk-ant-a-real-key",
        gemini_api_key="a-real-gemini-key",
    )

    printed = repr(settings)

    for leaked in (
        "hunter2",
        "a-real-signing-secret-of-at-least-32-chars",
        "sk_a_real_key",
        "sk-ant-a-real-key",
        "a-real-gemini-key",
    ):
        assert leaked not in printed, printed
    assert leaked not in str(settings)


def test_a_redacted_setting_still_says_which_one_it_is():
    """Redaction that hides the field name too is a debugging dead end.

    The point is to know that `jwt_secret` is set and wrong, without learning
    what it is.
    """
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        jwt_secret="x" * 32,
        google_client_id="g",
        apple_client_id="a",
        elevenlabs_api_key="e",
    )

    printed = repr(settings)

    assert "jwt_secret" in printed
    assert "google_client_id='g'" in printed, "a public identifier is not a secret"


def test_every_secret_shaped_field_is_covered_by_the_guard():
    """The list of what to hide is derived, not maintained.

    A credential added next year is redacted because its *name* looks like one,
    rather than because somebody remembered to add it — which is the failure
    mode of every hand-kept list of sensitive fields.
    """
    from app.core.config import _is_secret

    for name in Settings.model_fields:
        if any(hint in name for hint in SECRET_ISH):
            assert _is_secret(name), name


def test_an_empty_value_means_unset_not_an_empty_credential(environment):
    """`KEY=` in a `.env` is a blank left to fill, not a value.

    The distinction is load-bearing for `ELEVENLABS_DEFAULT_VOICE_ID`: the
    speaker uses it as the fallback in a dict lookup, so an empty *string*
    would be sent to the vendor as a real voice id mid-room, where `None`
    means "no fallback voice" and fails the turn cleanly. And for the typed
    fields it is the difference between booting and a validation error about
    a float that was never meant to be set.
    """
    environment(
        ELEVENLABS_DEFAULT_VOICE_ID="",
        VAD_SILENCE_THRESHOLD_SECS="",
        EXTRACTION_PROVIDER="",
    )

    settings = Settings(_env_file=None)

    assert settings.elevenlabs_default_voice_id is None
    assert settings.vad_silence_threshold_secs is None
    assert settings.extraction_provider == "gemini"
