"""fnOS encrypted package processing using maintained crypto libraries."""

from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterable

from cryptography.hazmat.decrepit.ciphers import modes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

from fnos_store_errors import StoreError

KEY_LABEL = "trimAppCenter"
SEPARATOR = "`"
TAR_BLOCK_SIZE = 512
TAR_ZERO_BLOCK = b"\0" * TAR_BLOCK_SIZE
TAR_END = TAR_ZERO_BLOCK * 2


def derive_key(app_name: str, version: str, encrypt_block: str) -> bytes:
    material = SEPARATOR.join((app_name, version, encrypt_block, KEY_LABEL))
    return hashlib.sha256(material.encode("utf-8")).digest()


def decrypt_stream(chunks: Iterable[bytes], destination: Path, key: bytes) -> None:
    """Decrypt an AES-CFB package stream into a file."""
    decryptor = Cipher(algorithms.AES(key), modes.CFB(key[:16])).decryptor()
    with destination.open("wb") as output:
        for chunk in chunks:
            if not chunk:
                continue
            output.write(decryptor.update(chunk))
        tail = decryptor.finalize()
        if tail:
            output.write(tail)


def is_ustar(prefix: bytes) -> bool:
    return len(prefix) >= 262 and prefix[257:262] == b"ustar"


def ensure_tar_end(path: Path) -> None:
    """Add the standard tar end blocks to packages that omit them.

    Some packages in the public store contain all of their members but stop
    immediately after the last member's data.  That is enough for the fnOS
    installer, but tools such as GNU tar report ``unexpected EOF`` because a
    tar archive must end with two zero blocks.  Check member boundaries before
    repairing the trailer so a genuinely truncated member is not hidden by
    the added zero bytes.
    """
    try:
        file_size = path.stat().st_size
        offset = 0
        padding = 0
        with path.open("rb") as source:
            while offset < file_size:
                header = source.read(TAR_BLOCK_SIZE)
                if len(header) < TAR_BLOCK_SIZE:
                    if not header or not all(byte == 0 for byte in header):
                        raise ValueError("truncated tar header")
                    padding = TAR_BLOCK_SIZE - len(header) + len(TAR_END)
                    break

                if header == TAR_ZERO_BLOCK:
                    remainder = source.read(TAR_BLOCK_SIZE)
                    if remainder == TAR_ZERO_BLOCK:
                        return
                    if not remainder or all(byte == 0 for byte in remainder):
                        padding = TAR_BLOCK_SIZE - len(remainder)
                        break
                    raise ValueError("invalid tar end blocks")

                size_field = header[124:136].rstrip(b"\0 ")
                try:
                    member_size = int(size_field or b"0", 8)
                except ValueError as exc:
                    raise ValueError("invalid tar member size") from exc
                if member_size < 0:
                    raise ValueError("invalid tar member size")

                member_end = offset + TAR_BLOCK_SIZE + member_size
                if member_end > file_size:
                    raise ValueError("truncated tar member")
                aligned_end = (member_end + TAR_BLOCK_SIZE - 1) // TAR_BLOCK_SIZE * TAR_BLOCK_SIZE
                if aligned_end > file_size:
                    source.seek(member_end)
                    if any(source.read(file_size - member_end)):
                        raise ValueError("invalid tar member padding")
                    padding = aligned_end - file_size + len(TAR_END)
                    break
                offset = aligned_end
                source.seek(offset)
            else:
                padding = len(TAR_END)

        if padding:
            with path.open("ab") as output:
                output.write(b"\0" * padding)
    except OSError:
        raise
    except ValueError as exc:
        raise StoreError("decrypt_failed", "The decrypted payload is a truncated tar archive.") from exc


def write_fpk(tar_path: Path, destination: Path) -> None:
    """Build an FPK before atomically replacing its destination."""
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".gzpart",
            dir=destination.parent,
        )
        os.close(descriptor)
        temporary = Path(name)
        with tar_path.open("rb") as source, temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as output:
                shutil.copyfileobj(source, output)
        temporary.replace(destination)
    except OSError as exc:
        raise StoreError("invalid_params", f"Cannot write {destination}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
