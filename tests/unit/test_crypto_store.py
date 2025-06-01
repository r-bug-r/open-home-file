"""Encryption, key handling, and content-addressed storage tests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from homefile import crypto
from homefile.config import Settings
from homefile.errors import IntegrityError, StorageError
from homefile.store import BlobStore

SECRET = b"%PDF-1.4 synthetic document bytes for the encryption test"
SECRET_SHA = hashlib.sha256(SECRET).hexdigest()


def test_seal_round_trip() -> None:
    key = crypto.generate_key()
    sealed = crypto.seal(key, SECRET, b"doc-1")
    assert SECRET not in sealed
    assert crypto.open_sealed(key, sealed, b"doc-1") == SECRET


def test_seal_binds_associated_data() -> None:
    key = crypto.generate_key()
    sealed = crypto.seal(key, SECRET, b"doc-1")
    with pytest.raises(StorageError):
        crypto.open_sealed(key, sealed, b"doc-2")


def test_seal_detects_tampering() -> None:
    key = crypto.generate_key()
    sealed = bytearray(crypto.seal(key, SECRET, b"doc-1"))
    sealed[-1] ^= 0x01
    with pytest.raises(StorageError):
        crypto.open_sealed(key, bytes(sealed), b"doc-1")


def test_wrong_key_cannot_open() -> None:
    sealed = crypto.seal(crypto.generate_key(), SECRET, b"aad")
    with pytest.raises(StorageError):
        crypto.open_sealed(crypto.generate_key(), sealed, b"aad")


def test_key_file_is_created_once_and_restricted(tmp_path: Path) -> None:
    path = tmp_path / "key.bin"
    first = crypto.load_or_create_key(path)
    second = crypto.load_or_create_key(path)
    assert first == second
    assert len(first) == 32
    if os.name == "posix":
        assert path.stat().st_mode & 0o077 == 0


def test_passphrase_round_trip_and_wrong_passphrase() -> None:
    sealed = crypto.seal_with_passphrase("correct horse battery staple", SECRET)
    assert crypto.open_with_passphrase("correct horse battery staple", sealed) == SECRET
    with pytest.raises(StorageError):
        crypto.open_with_passphrase("wrong passphrase", sealed)


def test_passphrase_uses_a_fresh_salt() -> None:
    first = crypto.seal_with_passphrase("same passphrase", SECRET)
    second = crypto.seal_with_passphrase("same passphrase", SECRET)
    assert first != second


def test_store_round_trip(settings: Settings) -> None:
    store = BlobStore(settings)
    sha = SECRET_SHA
    store.put(SECRET, sha)
    assert store.exists(sha)
    assert store.get(sha) == SECRET
    assert store.leftover_files() == [f"{sha}.hbf"]
    assert store.delete(sha) is True
    assert store.delete(sha) is False
    assert store.leftover_files() == []


def test_store_blob_is_not_plaintext(settings: Settings) -> None:
    store = BlobStore(settings)
    sha = SECRET_SHA
    path = store.put(SECRET, sha)
    assert SECRET not in path.read_bytes()


def test_store_rejects_short_hash(settings: Settings) -> None:
    store = BlobStore(settings)
    with pytest.raises(StorageError):
        store.put(SECRET, "not-a-hash")


def test_store_rejects_mismatched_hash(settings: Settings) -> None:
    store = BlobStore(settings)
    with pytest.raises(IntegrityError):
        store.put(SECRET, "a" * 64)


def test_store_detects_corrupted_blob(settings: Settings) -> None:
    store = BlobStore(settings)
    sha = SECRET_SHA
    path = store.put(SECRET, sha)
    path.write_bytes(path.read_bytes()[:-8])
    with pytest.raises((IntegrityError, StorageError)):
        store.get(sha)


def test_store_lists_every_stored_blob(settings: Settings) -> None:
    store = BlobStore(settings)
    store.put(SECRET, SECRET_SHA)
    stray = settings.blob_dir / "stray.bin"
    stray.write_bytes(b"unexpected")
    assert store.leftover_files() == sorted([f"{SECRET_SHA}.hbf", "stray.bin"])
