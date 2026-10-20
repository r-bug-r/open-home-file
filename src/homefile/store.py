"""Encrypted, content-addressed blob store.

Original bytes are stored exactly as imported, sealed with AES-GCM under a key
bound to the SHA-256 of the content. Storing by hash makes duplicate imports
free and makes the deletion audit exact: the blob filename *is* the identity.

The store never rewrites or normalizes the original bytes.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import crypto
from .config import Settings
from .errors import IntegrityError, StorageError


class BlobStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.blob_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self._key = crypto.load_or_create_key(settings.key_path)

    def path_for(self, sha256: str) -> Path:
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise StorageError("invalid content hash")
        return self.root / f"{sha256}.hbf"

    def put(self, data: bytes, sha256: str) -> Path:
        target = self.path_for(sha256)
        actual = hashlib.sha256(data).hexdigest()
        if actual != sha256:
            raise IntegrityError(f"data hashes to {actual}, expected {sha256}")
        if target.exists():
            # Re-importing identical bytes must remain byte-identical.
            if self.get(sha256) != data:
                raise IntegrityError("existing blob does not match its content hash")
            return target
        sealed = crypto.seal(self._key, data, sha256.encode("ascii"))
        tmp = target.with_name(f".{target.name}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(sealed)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return target

    def get(self, sha256: str) -> bytes:
        path = self.path_for(sha256)
        if not path.exists():
            raise StorageError(f"original for {sha256} is missing")
        data = crypto.open_sealed(self._key, path.read_bytes(), sha256.encode("ascii"))
        actual = hashlib.sha256(data).hexdigest()
        if actual != sha256:
            raise IntegrityError(f"stored bytes hash to {actual}, expected {sha256}")
        return data

    def exists(self, sha256: str) -> bool:
        return self.path_for(sha256).exists()

    def delete(self, sha256: str) -> bool:
        path = self.path_for(sha256)
        if not path.exists():
            return False
        path.unlink()
        return True

    def leftover_files(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_file())
