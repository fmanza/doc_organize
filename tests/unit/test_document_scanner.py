"""Tests unitarios de DocumentScanner (REQ-002)."""

import hashlib

import pytest

from doc_organize.scanner import DocumentScanner


def _sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.mark.asyncio
async def test_scan_discovers_supported_documents(tmp_path) -> None:
    (tmp_path / "report.pdf").write_bytes(b"pdf-content")
    (tmp_path / "notes.txt").write_text("ignored: unsupported extension")

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(tmp_path)])

    assert result.summary == {"pdf": 1}
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.display_name == "report.pdf"
    assert doc.sha256_hash == _sha256_of(b"pdf-content")


@pytest.mark.asyncio
async def test_scan_ignores_hidden_and_cache_dirs(tmp_path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config.pdf").write_bytes(b"should-be-ignored")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.pdf").write_bytes(b"should-be-ignored-too")
    (tmp_path / "real.pdf").write_bytes(b"real-content")

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(tmp_path)])

    assert result.summary == {"pdf": 1}
    assert result.documents[0].display_name == "real.pdf"


@pytest.mark.asyncio
async def test_scan_recurses_into_subfolders(tmp_path) -> None:
    sub = tmp_path / "nested" / "deeper"
    sub.mkdir(parents=True)
    (sub / "deep.docx").write_bytes(b"deep-content")

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(tmp_path)])

    assert result.summary == {"docx": 1}
    assert result.tree.total_files == 1


@pytest.mark.asyncio
async def test_scan_does_not_follow_symlinks(tmp_path) -> None:
    target_dir = tmp_path / "outside"
    target_dir.mkdir()
    (target_dir / "leaked.pdf").write_bytes(b"should-not-be-hashed")

    scan_root = tmp_path / "scan_root"
    scan_root.mkdir()
    symlink_path = scan_root / "link_to_outside"
    try:
        symlink_path.symlink_to(target_dir, target_is_directory=True)
    except OSError:
        pytest.skip("El entorno no permite crear symlinks (privilegios insuficientes en Windows).")

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(scan_root)])

    assert result.documents == []


@pytest.mark.asyncio
async def test_scan_multiple_roots(tmp_path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "a.pdf").write_bytes(b"a")
    (root_b / "b.xlsx").write_bytes(b"b")

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(root_a), str(root_b)])

    assert result.summary == {"pdf": 1, "xlsx": 1}
