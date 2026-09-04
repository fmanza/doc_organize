"""
Utilities for file hashing with SHA-256.

This module provides the **single source of truth** for SHA-256 computation.
Both DocumentScanner and CacheManager delegate to hash_file() here.

Implements async I/O to avoid blocking the event loop during large file reads.
"""

import hashlib

from pathlib import Path

import aiofiles

__all__ = ["hash_file"]


async def hash_file(file_path: str, chunk_size: int = 65536) -> str:
    """
    Compute SHA-256 hash of a file asynchronously.

    Reads the file in chunks via aiofiles to avoid blocking the event loop.
    This is the **unique source of truth** for hashing across doc_organize.

    Args:
        file_path: Absolute or relative path to the file.
        chunk_size: Number of bytes to read per iteration (default: 64KB).

    Returns:
        Hex-encoded SHA-256 digest (lowercase, 64 characters).

    Raises:
        FileNotFoundError: If the file does not exist.
        IOError: If the file cannot be read.

    Example:
        >>> import asyncio, hashlib, tempfile
        >>> from pathlib import Path
        >>> async def main():
        ...     file_path = Path(tempfile.mkdtemp()) / "documento.pdf"
        ...     file_path.write_bytes(b"contenido")
        ...     digest = await hash_file(str(file_path))
        ...     return digest == hashlib.sha256(b"contenido").hexdigest()
        >>> asyncio.run(main())
        True
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if not path.is_file():
        raise OSError(f"Path is not a file: {file_path}")

    sha256_hash = hashlib.sha256()

    try:
        async with aiofiles.open(path, "rb") as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                sha256_hash.update(chunk)
    except OSError as e:
        raise OSError(f"Cannot read file {file_path}: {e}") from e

    return sha256_hash.hexdigest()
