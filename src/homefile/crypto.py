"""Encryption primitives.

Two independent formats:

``HBF1`` - at-rest blob format. AES-256-GCM with a random 96-bit nonce per
blob and the content hash bound as associated data, so a blob cannot be
swapped for another without failing authentication.

``HFE1`` - passphrase-protected export container. AES-256-GCM with a key
derived by scrypt and a random salt; the header is authenticated.

Keys are generated locally and never logged.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import stat
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .errors import StorageError

BLOB_MAGIC = b"HBF1"
EXPORT_MAGIC = b"HFE1"
KEY_BYTES = 32
NONCE_BYTES = 12
SALT_BYTES = 16
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


def generate_key() -> bytes:
    return os.urandom(KEY_BYTES)


def _restrict_permissions(path: Path) -> None:
    """Best-effort owner-only permissions.

    On POSIX this is a real 0600. On Windows ``os.chmod`` only toggles the
    read-only bit; the default data directory lives under the per-user
    profile (``%LOCALAPPDATA%``), which is already ACL-restricted.
    """
    with contextlib.suppress(OSError):  # pragma: no cover - filesystem dependent
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def load_or_create_key(path: Path) -> bytes:
    """Load the master key, creating it with owner-only permissions if absent."""
    path = Path(path)
    if path.exists():
        data = path.read_bytes()
        if len(data) != KEY_BYTES:
            raise StorageError(f"key file {path} is malformed; refusing to continue")
        return data
    path.parent.mkdir(parents=True, exist_ok=True)
    key = generate_key()
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _restrict_permissions(path)
    return key


def seal(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    return BLOB_MAGIC + nonce + ciphertext


def open_sealed(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if not blob.startswith(BLOB_MAGIC) or len(blob) < len(BLOB_MAGIC) + NONCE_BYTES + 16:
        raise StorageError("blob header is invalid")
    nonce = blob[len(BLOB_MAGIC) : len(BLOB_MAGIC) + NONCE_BYTES]
    ciphertext = blob[len(BLOB_MAGIC) + NONCE_BYTES :]
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise StorageError(
            "blob authentication failed; it was modified or the key is wrong"
        ) from exc


def derive_key(passphrase: str, salt: bytes) -> bytes:
    if not passphrase:
        raise StorageError("a non-empty passphrase is required")
    return hashlib.scrypt(
        passphrase.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_BYTES
    )


def seal_with_passphrase(passphrase: str, plaintext: bytes) -> bytes:
    salt = os.urandom(SALT_BYTES)
    key = derive_key(passphrase, salt)
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, EXPORT_MAGIC + salt)
    return EXPORT_MAGIC + salt + nonce + ciphertext


def open_with_passphrase(passphrase: str, blob: bytes) -> bytes:
    header = len(EXPORT_MAGIC) + SALT_BYTES + NONCE_BYTES
    if not blob.startswith(EXPORT_MAGIC) or len(blob) < header + 16:
        raise StorageError("export container header is invalid")
    salt = blob[len(EXPORT_MAGIC) : len(EXPORT_MAGIC) + SALT_BYTES]
    nonce = blob[len(EXPORT_MAGIC) + SALT_BYTES : header]
    ciphertext = blob[header:]
    key = derive_key(passphrase, salt)
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, EXPORT_MAGIC + salt)
    except InvalidTag as exc:
        raise StorageError("export decryption failed: wrong passphrase or modified file") from exc
