"""Tests unitarios de DocumentScanner (REQ-002)."""

import hashlib

from pathlib import Path

import pytest

import doc_organize.scanner.document_scanner as document_scanner_module

from doc_organize.scanner import DocumentScanner


def _sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.mark.asyncio
async def test_scan_discovers_supported_documents(tmp_path) -> None:
    (tmp_path / "report.pdf").write_bytes(b"pdf-content")
    (tmp_path / "notes.log").write_text("ignored: unsupported extension")

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


@pytest.mark.asyncio
async def test_scan_discovers_new_base_formats(tmp_path) -> None:
    """Formatos ampliados (sesion 'soporte de formatos docling') activos por
    defecto — incluido `.txt`, que no depende de `include_audio_video`."""
    (tmp_path / "page.html").write_bytes(b"<html></html>")
    (tmp_path / "data.csv").write_bytes(b"a,b\n1,2")
    (tmp_path / "doc.odt").write_bytes(b"odt-content")
    (tmp_path / "book.epub").write_bytes(b"epub-content")
    (tmp_path / "notes.txt").write_bytes(b"plain text notes")

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(tmp_path)])

    assert result.summary == {"html": 1, "csv": 1, "odt": 1, "epub": 1, "txt": 1}


@pytest.mark.asyncio
async def test_scan_ignores_audio_video_by_default(tmp_path) -> None:
    (tmp_path / "clip.mp3").write_bytes(b"audio-content")
    (tmp_path / "report.pdf").write_bytes(b"pdf-content")

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(tmp_path)])

    assert result.summary == {"pdf": 1}


@pytest.mark.asyncio
async def test_scan_includes_audio_video_when_opted_in(tmp_path) -> None:
    (tmp_path / "clip.mp3").write_bytes(b"audio-content")
    (tmp_path / "report.pdf").write_bytes(b"pdf-content")

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(tmp_path)], include_audio_video=True)

    assert result.summary == {"pdf": 1, "mp3": 1}


@pytest.mark.asyncio
async def test_scan_excludes_output_dir(tmp_path) -> None:
    """`exclude_dir` evita redescubrir la salida del propio proyecto como fuente.

    Reproduce el escenario real: `output_dir` ("Conversión/") cuelga de una de
    las carpetas escaneadas y contiene imagenes ya extraidas por una conversion
    previa (`img/<stem>/*.png`, ver `DocumentConverter._write_outputs`). Sin
    `exclude_dir`, el escaner las trataria como documentos nuevos y una
    reconversion posterior del documento original (que borra y regenera esa
    carpeta) haria fallar su "conversion" con FileNotFoundError.
    """
    output_dir = tmp_path / "Conversión"
    images_dir = output_dir / "sub" / "img" / "documento"
    images_dir.mkdir(parents=True)
    (images_dir / "image_000000_abc123.png").write_bytes(b"extracted-image")
    (tmp_path / "sub" / "documento.docx").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "sub" / "documento.docx").write_bytes(b"real-source-document")

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(tmp_path)], exclude_dir=output_dir.resolve())

    assert result.summary == {"docx": 1}
    assert [doc.display_name for doc in result.documents] == ["documento.docx"]


@pytest.mark.asyncio
async def test_scan_skips_file_that_disappears_before_stat(tmp_path, monkeypatch) -> None:
    """AUDIT_CODE (sesión 2026-09-03): un fichero borrado entre `iterdir()` y
    `stat()` (TOCTOU -- fichero temporal de otra app, borrado por el usuario a
    mitad de un escaneo grande) abortaba antes el escaneo ENTERO con un
    `OSError` sin capturar. Ahora se omite ese fichero y el resto continúa."""
    (tmp_path / "vanishes.pdf").write_bytes(b"contenido-a-punto-de-desaparecer")
    (tmp_path / "survives.pdf").write_bytes(b"contenido-real")

    original_stat = Path.stat

    def _flaky_stat(self: Path, *args: object, **kwargs: object) -> object:
        if self.name == "vanishes.pdf":
            raise FileNotFoundError(f"simulado: '{self}' desapareció durante el escaneo")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _flaky_stat)

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(tmp_path)])

    assert result.summary == {"pdf": 1}
    assert result.documents[0].display_name == "survives.pdf"


@pytest.mark.asyncio
async def test_scan_skips_file_that_disappears_before_hashing(tmp_path, monkeypatch) -> None:
    """Mismo caso que el anterior (AUDIT_CODE, sesión 2026-09-03), pero la
    desaparición ocurre en la segunda fase (hashing), no durante el recorrido
    de directorios -- una ventana aún mayor, ya que el hashing solo empieza
    tras recorrer TODAS las carpetas seleccionadas."""
    (tmp_path / "vanishes.pdf").write_bytes(b"contenido-a-punto-de-desaparecer")
    (tmp_path / "survives.pdf").write_bytes(b"contenido-real")

    original_hash_file = document_scanner_module.hash_file

    async def _flaky_hash_file(file_path: str, *args: object, **kwargs: object) -> str:
        if Path(file_path).name == "vanishes.pdf":
            raise FileNotFoundError(f"simulado: '{file_path}' desapareció antes del hashing")
        return await original_hash_file(file_path, *args, **kwargs)

    monkeypatch.setattr(document_scanner_module, "hash_file", _flaky_hash_file)

    async with DocumentScanner() as scanner:
        result = await scanner.scan_folders([str(tmp_path)])

    assert result.summary == {"pdf": 1}
    assert result.documents[0].display_name == "survives.pdf"
