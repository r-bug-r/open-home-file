"""Runtime configuration.

Defaults are local-only and cost zero: a fake provider, no network, and
hard caps set so that no paid call can happen unless explicitly configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_PAGES = 200
DEFAULT_MAX_PAGE_CHARS = 200_000
DEFAULT_CONFIRM_BELOW = 0.8
DEFAULT_RUN_REQUEST_CAP = 20
DEFAULT_RUN_TOKEN_CAP = 20_000


def default_data_dir() -> Path:
    """Return the per-user data directory for this platform."""
    override = os.environ.get("HOMEFILE_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        windows_base = os.environ.get("LOCALAPPDATA")
        root = Path(windows_base) if windows_base else Path.home() / "AppData" / "Local"
        return root / "homefile"
    xdg = os.environ.get("XDG_DATA_HOME")
    posix_root = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return posix_root / "homefile"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _env_decimal(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return Decimal(raw.strip())
    except InvalidOperation as exc:  # pragma: no cover - configuration error
        raise ValueError(f"{name} must be a decimal number") from exc


def _env_optional_decimal(name: str) -> Decimal | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return Decimal(raw.strip())
    except InvalidOperation as exc:  # pragma: no cover - configuration error
        raise ValueError(f"{name} must be a decimal number") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable runtime settings."""

    data_dir: Path
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_pages: int = DEFAULT_MAX_PAGES
    max_page_chars: int = DEFAULT_MAX_PAGE_CHARS
    confirm_below: float = DEFAULT_CONFIRM_BELOW
    allow_network: bool = False
    provider: str = "fake"
    run_request_cap: int = DEFAULT_RUN_REQUEST_CAP
    run_token_cap: int = DEFAULT_RUN_TOKEN_CAP
    run_cost_cap_usd: Decimal = Decimal("0")
    daily_cost_cap_usd: Decimal = Decimal("0")
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"
    cloud_base_url: str = ""
    cloud_model: str = ""
    cloud_input_price_per_1k: Decimal | None = None
    cloud_output_price_per_1k: Decimal | None = None
    cloud_api_key_env: str = "HOMEFILE_CLOUD_API_KEY"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "homefile.sqlite3"

    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"

    @property
    def key_path(self) -> Path:
        return self.data_dir / "key.bin"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    def with_data_dir(self, data_dir: Path) -> Settings:
        return replace(self, data_dir=Path(data_dir))

    @classmethod
    def from_env(cls, data_dir: Path | None = None) -> Settings:
        return cls(
            data_dir=Path(data_dir) if data_dir is not None else default_data_dir(),
            max_file_bytes=_env_int("HOMEFILE_MAX_FILE_MB", 25) * 1024 * 1024,
            max_pages=_env_int("HOMEFILE_MAX_PAGES", DEFAULT_MAX_PAGES),
            max_page_chars=_env_int("HOMEFILE_MAX_PAGE_CHARS", DEFAULT_MAX_PAGE_CHARS),
            confirm_below=float(os.environ.get("HOMEFILE_CONFIRM_BELOW", DEFAULT_CONFIRM_BELOW)),
            allow_network=_env_bool("HOMEFILE_ALLOW_NETWORK", False),
            provider=os.environ.get("HOMEFILE_PROVIDER", "fake").strip().lower() or "fake",
            run_request_cap=_env_int("HOMEFILE_RUN_REQUEST_CAP", DEFAULT_RUN_REQUEST_CAP),
            run_token_cap=_env_int("HOMEFILE_RUN_TOKEN_CAP", DEFAULT_RUN_TOKEN_CAP),
            run_cost_cap_usd=_env_decimal("HOMEFILE_RUN_COST_CAP_USD", Decimal("0")),
            daily_cost_cap_usd=_env_decimal("HOMEFILE_DAILY_COST_CAP_USD", Decimal("0")),
            ollama_url=os.environ.get("HOMEFILE_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            ollama_model=os.environ.get("HOMEFILE_OLLAMA_MODEL", "llama3.2"),
            cloud_base_url=os.environ.get("HOMEFILE_CLOUD_BASE_URL", "").rstrip("/"),
            cloud_model=os.environ.get("HOMEFILE_CLOUD_MODEL", ""),
            cloud_input_price_per_1k=_env_optional_decimal("HOMEFILE_CLOUD_INPUT_PRICE_PER_1K"),
            cloud_output_price_per_1k=_env_optional_decimal("HOMEFILE_CLOUD_OUTPUT_PRICE_PER_1K"),
            cloud_api_key_env=os.environ.get(
                "HOMEFILE_CLOUD_API_KEY_ENV", "HOMEFILE_CLOUD_API_KEY"
            ),
        )
