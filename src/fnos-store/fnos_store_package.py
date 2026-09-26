"""fnOS encrypted package processing using maintained crypto libraries."""

from __future__ import annotations

import gzip
import hashlib
import shutil
import tarfile
from pathlib import Path
from typing import Iterable

from cryptography.hazmat.decrepit.ciphers import modes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

from fnos_store_errors import StoreError

KEY_LABEL = "trimAppCenter"
SEPARATOR = "`"


def derive_key(app_name: str, version: str, encrypt_block: str) -> bytes:
    material = SEPARATOR.join((app_name, version, encrypt_block, KEY_LABEL))
    return hashlib.sha256(material.encode("utf-8")).digest()


def decrypt_stream(chunks: Iterable[bytes], destination: Path, key: bytes) -> tuple[int, bytes]:
    decryptor = Cipher(algorithms.AES(key), modes.CFB(key[:16])).decryptor()
    prefix = bytearray()
    plain_size = 0
    with destination.open("wb") as output:
        for chunk in chunks:
            if not chunk:
                continue
            plain = decryptor.update(chunk)
            output.write(plain)
            plain_size += len(plain)
            if len(prefix) < 512:
                prefix.extend(plain[: 512 - len(prefix)])
        tail = decryptor.finalize()
        if tail:
            output.write(tail)
            plain_size += len(tail)
            if len(prefix) < 512:
                prefix.extend(tail[: 512 - len(prefix)])
    return plain_size, bytes(prefix)


def is_ustar(prefix: bytes) -> bool:
    return len(prefix) >= 262 and prefix[257:262] == b"ustar"


def tar_entries(path: Path, limit: int = 20) -> list[str]:
    try:
        with path.open("rb") as probe:
            mode = "r:gz" if probe.read(2) == b"\x1f\x8b" else "r:"
        with tarfile.open(path, mode=mode) as archive:
            names = [member.name for _, member in zip(range(limit), archive)]
    except (OSError, tarfile.TarError) as exc:
        raise StoreError("decrypt_failed", "The decrypted payload is not a readable ustar archive.") from exc
    if not names:
        raise StoreError("decrypt_failed", "The decrypted archive contains no files.")
    return names


def write_fpk(tar_path: Path, destination: Path) -> None:
    temporary = destination.with_name(destination.name + ".gzpart")
    try:
        with tar_path.open("rb") as source, temporary.open("wb") as raw:
            with gzip.GzipFile(filename=destination.name, mode="wb", fileobj=raw, mtime=0) as output:
                shutil.copyfileobj(source, output)
        temporary.replace(destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise StoreError("invalid_params", f"Cannot write {destination}: {exc}") from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
