"""Tests unitarios de `utils/hash_utils.py` (única fuente de verdad de SHA-256).

Antes solo se ejercitaba indirectamente (comparación de igualdad en
`test_cache_manager.py`, o de paso en tests de conversión) — sin ningún test
directo de sus casos de error documentados (maturity-assessment, sesión
2026-09-03/04)."""

import hashlib

import pytest

from doc_organize.utils.hash_utils import hash_file


@pytest.mark.asyncio
async def test_hash_file_computes_correct_sha256(tmp_path) -> None:
    content = b"contenido de prueba para el hash"
    file_path = tmp_path / "documento.pdf"
    file_path.write_bytes(content)

    digest = await hash_file(str(file_path))

    assert digest == hashlib.sha256(content).hexdigest()
    assert len(digest) == 64


@pytest.mark.asyncio
async def test_hash_file_computes_correct_sha256_across_multiple_chunks(tmp_path) -> None:
    """`chunk_size` pequeño fuerza varias iteraciones de lectura -- el hash debe
    coincidir igual que con el `chunk_size` por defecto (64KB, una sola pasada
    para un fichero de prueba pequeño)."""
    content = b"contenido bastante mas largo que el chunk_size elegido a proposito" * 10
    file_path = tmp_path / "documento_grande.pdf"
    file_path.write_bytes(content)

    digest = await hash_file(str(file_path), chunk_size=16)

    assert digest == hashlib.sha256(content).hexdigest()


@pytest.mark.asyncio
async def test_hash_file_empty_file_matches_known_sha256(tmp_path) -> None:
    file_path = tmp_path / "vacio.pdf"
    file_path.write_bytes(b"")

    digest = await hash_file(str(file_path))

    assert digest == hashlib.sha256(b"").hexdigest()


@pytest.mark.asyncio
async def test_hash_file_raises_file_not_found_for_missing_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        await hash_file(str(tmp_path / "no-existe.pdf"))


@pytest.mark.asyncio
async def test_hash_file_raises_oserror_when_path_is_a_directory(tmp_path) -> None:
    directory = tmp_path / "una-carpeta"
    directory.mkdir()

    with pytest.raises(OSError):
        await hash_file(str(directory))
