"""Tagged, coloured application logging.

Built on the standard library rather than a logging framework: the only thing
needed beyond `logging` is a tag, structured context, and colour, and none of
those justify a dependency.

Two rules this module enforces rather than trusts callers to remember:

- **Secrets and PII never reach a log.** Known-sensitive keys are redacted by
  key name, and raw audio, transcripts and material contents must never be
  passed as context at all — CLAUDE.md forbids them leaving the system.
- **Colour is for humans.** It is emitted only to an interactive terminal, so
  captured or shipped logs stay free of escape codes.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from app.core.request_context import current_request_id

#: Redacted by key name wherever they appear in log context. Substring match, so
#: `revenuecat_api_key` and `authorization_header` are both caught.
SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "signature",
)

REDACTED = "[redacted]"

_LEVEL_COLOURS = {
    logging.DEBUG: "\033[38;5;245m",
    logging.INFO: "\033[38;5;39m",
    logging.WARNING: "\033[38;5;214m",
    logging.ERROR: "\033[38;5;203m",
    logging.CRITICAL: "\033[1;38;5;197m",
}
_TAG_COLOUR = "\033[38;5;79m"
_CONTEXT_COLOUR = "\033[38;5;245m"
_RESET = "\033[0m"


def redact(context: dict[str, Any]) -> dict[str, Any]:
    """Replace values whose key looks sensitive."""
    return {
        key: REDACTED
        if any(fragment in key.lower() for fragment in SENSITIVE_KEY_FRAGMENTS)
        else value
        for key, value in context.items()
    }


class TaggedLogger:
    """A logger that takes context as keyword arguments.

    `log.info("tick charged", session_id=..., seconds=15)` rather than an
    f-string, so the identifiers stay machine-greppable and consistently named
    across every line that mentions them.
    """

    def __init__(self, logger: logging.Logger, tag: str) -> None:
        self._logger = logger
        self._tag = tag

    def debug(self, message: str, **context: Any) -> None:
        self._log(logging.DEBUG, message, context)

    def info(self, message: str, **context: Any) -> None:
        self._log(logging.INFO, message, context)

    def warning(self, message: str, **context: Any) -> None:
        self._log(logging.WARNING, message, context)

    def error(self, message: str, **context: Any) -> None:
        self._log(logging.ERROR, message, context)

    def exception(self, message: str, **context: Any) -> None:
        """Log an error with the active traceback. Only valid inside `except`."""
        self._log(logging.ERROR, message, context, exc_info=True)

    def critical(self, message: str, **context: Any) -> None:
        self._log(logging.CRITICAL, message, context)

    def _log(
        self,
        level: int,
        message: str,
        context: dict[str, Any],
        *,
        exc_info: bool = False,
    ) -> None:
        if not self._logger.isEnabledFor(level):
            return
        # Added here rather than passed at each call site. A rule every caller
        # has to remember is one some caller will forget, and the lines that
        # get forgotten are those on unusual paths — the only ones anybody is
        # chasing a request id to find. Absent outside a request, which is
        # honest: the sweep loop is not one.
        if (request_id := current_request_id()) is not None:
            context = {"request_id": request_id, **context}
        self._logger.log(
            level,
            message,
            exc_info=exc_info,
            extra={"tag": self._tag, "context": redact(context)},
            stacklevel=3,
        )


def _render_value(value: Any) -> str:
    """Render one context value as a parseable token.

    Values containing whitespace are quoted, or `key=two words` reads as a key
    plus a stray token to every log parser and to anyone scanning the column.
    """
    text = str(value)
    if not text:
        return '""'
    return f'"{text}"' if any(char.isspace() for char in text) else text


class ConsoleFormatter(logging.Formatter):
    """Human-readable single-line output, coloured when attached to a terminal."""

    def __init__(self, *, colour: bool) -> None:
        super().__init__(datefmt="%H:%M:%S")
        self._colour = colour

    def format(self, record: logging.LogRecord) -> str:
        tag = getattr(record, "tag", record.name.split(".")[-1])
        context = getattr(record, "context", {})

        level = f"{record.levelname:<8}"
        tag_text = f"[{tag}]"
        context_text = " ".join(
            f"{key}={_render_value(value)}" for key, value in context.items()
        )

        if self._colour:
            level = f"{_LEVEL_COLOURS.get(record.levelno, '')}{level}{_RESET}"
            tag_text = f"{_TAG_COLOUR}{tag_text}{_RESET}"
            if context_text:
                context_text = f"{_CONTEXT_COLOUR}{context_text}{_RESET}"

        line = f"{self.formatTime(record, self.datefmt)} {level} {tag_text} {record.getMessage()}"
        if context_text:
            line = f"{line}  {context_text}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def should_use_colour(stream: Any = None) -> bool:
    """Colour only for an interactive terminal.

    Respects NO_COLOR (https://no-color.org) and FORCE_COLOR. Without this,
    escape codes end up in shipped logs and in CI output where they are noise.
    """
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("FORCE_COLOR"):
        return True
    stream = stream or sys.stderr
    return bool(getattr(stream, "isatty", lambda: False)())


def configure_logging(level: int | str = logging.INFO) -> None:
    """Install the console handler. Call once, at application startup."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(ConsoleFormatter(colour=should_use_colour(sys.stderr)))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str, *, tag: str) -> TaggedLogger:
    """A logger for one module.

    The tag names the subsystem — `billing`, `sessions`, `voice`, `auditor` —
    so a live session can be followed across modules by filtering on it.
    """
    return TaggedLogger(logging.getLogger(name), tag)
