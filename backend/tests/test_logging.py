"""Application logging.

Debugging a live interrogation means reconstructing what happened across the
panel, the Auditor, the ledger and the voice provider for one session. That is
only possible if every line carries the same identifiers, so context is a first
class argument rather than something formatted into the message by hand.

Distinct from the audit trail, which is a database table (CLAUDE.md). Logs are
for debugging and may be sampled or dropped; the audit trail may not.
"""

import logging

from app.core.logging import ConsoleFormatter, get_logger, should_use_colour


def test_a_log_line_carries_its_tag_and_context(caplog):
    """Tag and context travel as fields, not as string interpolation.

    Grepping a session out of the logs has to work on a stable key, so
    `session_id=...` must look the same on every line that mentions one.
    """
    log = get_logger("app.modules.billing.service", tag="billing")

    with caplog.at_level(logging.INFO):
        log.info("tick charged", session_id="abc-123", seconds=15)

    record = caplog.records[-1]
    assert record.tag == "billing"
    assert record.context == {"session_id": "abc-123", "seconds": 15}
    assert record.getMessage() == "tick charged"


def test_sensitive_context_is_redacted_by_key(caplog):
    """A secret must not reach a log even when someone passes it deliberately.

    CLAUDE.md permits zero secrets in logs. Relying on every caller to remember
    that is how keys end up in a log aggregator, so redaction happens here where
    it cannot be forgotten.
    """
    log = get_logger("app.modules.billing.webhooks", tag="billing")

    with caplog.at_level(logging.INFO):
        log.info(
            "webhook received",
            user_id="u-1",
            revenuecat_api_key="sk_live_abc123",
            x_signature="deadbeef",
        )

    context = caplog.records[-1].context
    assert context["user_id"] == "u-1"
    assert context["revenuecat_api_key"] == "[redacted]"
    assert context["x_signature"] == "[redacted]"


def test_colour_is_only_for_an_interactive_terminal():
    """Escape codes in shipped logs and CI output are noise, not colour."""

    class Terminal:
        def isatty(self) -> bool:
            return True

    class Pipe:
        def isatty(self) -> bool:
            return False

    assert should_use_colour(Terminal()) is True
    assert should_use_colour(Pipe()) is False


def test_a_formatted_line_without_colour_has_no_escape_codes():
    record = logging.LogRecord(
        name="app.modules.sessions.service",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="idle timeout reached",
        args=(),
        exc_info=None,
    )
    record.tag = "sessions"
    record.context = {"session_id": "s-9"}

    line = ConsoleFormatter(colour=False).format(record)

    assert "\033[" not in line
    assert "[sessions]" in line
    assert "idle timeout reached" in line
    assert "session_id=s-9" in line


def test_values_containing_spaces_are_quoted():
    """Unquoted spaces break key=value parsing at the point you most need it.

    `claim=margin 62%` reads as `claim=margin` plus a stray token to every log
    parser and to eyeballs scanning a column.
    """
    record = logging.LogRecord(
        name="app.agents.auditor",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="unsupported claim",
        args=(),
        exc_info=None,
    )
    record.tag = "auditor"
    record.context = {"slide": 4, "note": "margin 62%"}

    line = ConsoleFormatter(colour=False).format(record)

    assert 'note="margin 62%"' in line
    assert "slide=4" in line
