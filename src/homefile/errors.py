"""Error taxonomy.

Failures are classified so callers can distinguish user input problems,
integrity failures, and provider/budget refusals without string matching.
"""

from __future__ import annotations


class HomeFileError(Exception):
    """Base class for expected, user-visible failures."""


class ValidationError(HomeFileError):
    """The input file or request is not acceptable."""


class UnsupportedFile(ValidationError):
    """The file type is not supported."""


class FileTooLarge(ValidationError):
    """The file exceeds the configured import limit."""


class UnsafeContent(ValidationError):
    """The file contains active content or otherwise unsafe features."""


class StorageError(HomeFileError):
    """Local storage could not be written or read."""


class IntegrityError(HomeFileError):
    """Stored bytes do not match their recorded hash."""


class DeletionError(HomeFileError):
    """Deletion could not be verified as complete."""


class NotFound(HomeFileError):
    """The requested document, field, or reminder does not exist."""


class ProviderDisabled(HomeFileError):
    """A provider was requested but is not permitted by configuration."""


class BudgetExceeded(HomeFileError):
    """A provider call would exceed a configured hard limit."""


class ProviderError(HomeFileError):
    """A provider call failed in a way the caller must handle."""
