"""Open Home File: a local-first household document index.

Public surface is intentionally small. Everything that touches documents goes
through :class:`homefile.service.Library`, and every failure is one of the
exceptions in :mod:`homefile.errors`.
"""

from __future__ import annotations

from .config import Settings
from .errors import (
    BudgetExceeded,
    DeletionError,
    HomeFileError,
    IntegrityError,
    NotFound,
    ProviderDisabled,
    ProviderError,
    StorageError,
    UnsafeContent,
    UnsupportedFile,
    ValidationError,
)
from .service import Library

__version__ = "0.1.0"

__all__ = [
    "BudgetExceeded",
    "DeletionError",
    "HomeFileError",
    "IntegrityError",
    "Library",
    "NotFound",
    "ProviderDisabled",
    "ProviderError",
    "Settings",
    "StorageError",
    "UnsafeContent",
    "UnsupportedFile",
    "ValidationError",
    "__version__",
]
