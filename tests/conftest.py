"""Shared test fixtures.

Every test runs with sockets disabled and with ``HOMEFILE_*`` variables cleared,
so a developer's shell configuration can never change what the suite proves.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from homefile import fixtures
from homefile.config import Settings
from homefile.service import Library


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in list(os.environ):
        if name.startswith("HOMEFILE_"):
            monkeypatch.delenv(name, raising=False)

    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "library")


@pytest.fixture
def library(settings: Settings) -> Library:
    return Library(settings)


@pytest.fixture
def sample_paths(tmp_path: Path) -> dict[str, Path]:
    return fixtures.write_samples(tmp_path / "samples")
