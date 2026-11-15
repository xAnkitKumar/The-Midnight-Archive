"""Exception hierarchy for The Midnight Archive.

Every failure the CLI can recover from is a ``TmaError`` subclass, so the CLI
can report a clean message instead of a traceback.
"""

from __future__ import annotations


class TmaError(RuntimeError):
    """Base class for expected, user-facing failures."""


class ConfigError(TmaError):
    """Configuration files are missing or malformed."""


class NotFoundError(TmaError):
    """A requested video, idea or file does not exist."""


class DuplicateError(TmaError):
    """An item would duplicate an existing idea, title or script."""


class StatusTransitionError(TmaError):
    """A video was asked to move to a status that is not reachable."""


class PipelineError(TmaError):
    """A production stage cannot run given the video's current state."""


class ProviderError(TmaError):
    """An idea/LLM provider failed or is not configured."""


class ValidationRejected(TmaError):
    """Structured handoff data failed validation."""

    def __init__(self, message: str, issues: list[object] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []
