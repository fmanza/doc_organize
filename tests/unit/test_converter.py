"""Tests unitarios de DocumentConverter (REQ-003, REQ-004).

Usan Docling real (sin mocks) sobre documentos de fixture generados con
matplotlib/PIL — coherente con la politica del proyecto de no mockear
servicios/componentes reales en tests. Son mas lentos que el resto de la
suite (carga de modelos de Docling), de ahi el marcador `slow`.
"""

import asyncio
import json

from pathlib import Path

import pytest

from doc_organize.converter import DocumentConverter
from doc_organize.core.models import DocumentMetadata


def _read_text(path) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _metadata_for(path) -> DocumentMetadata:
    stat = path.stat()
    return DocumentMetadata(
        full_path=str(path),
        display_name=path.name,
        extension="pdf",
        size_bytes=stat.st_size,
        modified_time=stat.st_mtime,
        sha256_hash="test-hash-not-relevant-here",
    )


def _make_pdf_with_n_charts(path: Path, n: int) -> None:
    """PDF con `n` graficos incrustados (via matplotlib): Docling los extrae como
    `PictureItem` distintos, cada uno con nombre de fichero por hash de contenido."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.1, 0.9, "Documento con graficos de prueba", fontsize=14)
    for i in range(n):
        ax = fig.add_axes((0.1, 0.1 + i * 0.2, 0.3, 0.15))
        ax.plot([1, 2, 3], [i, i + 1, i + 2])
    fig.savefig(path, format="pdf")
    plt.close(fig)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_convert_native_pdf_extracts_text_without_ocr(native_pdf, tmp_path) -> None:
    output_dir = tmp_path / "Conversión"
    doc = _metadata_for(native_pdf)

    async with DocumentConverter() as converter:
        result = await converter.convert_document(doc, output_dir)

    assert result.success is True
    assert result.ocr_required is False
    assert result.error is None

    markdown_text = await asyncio.to_thread(_read_text, result.markdown_path)
    assert "Informe de prueba" in markdown_text

    document_json = json.loads(await asyncio.to_thread(_read_text, result.json_path))
    assert document_json["sha256_hash"] == doc.sha256_hash
    assert document_json["ocr_required"] is False
    assert any("Informe de prueba" in chunk["text"] for chunk in document_json["chunks"])


@pytest.mark.slow
@pytest.mark.asyncio
async def test_convert_scanned_pdf_without_ocr_flags_ocr_required(scanned_pdf, tmp_path) -> None:
    output_dir = tmp_path / "Conversión"
    doc = _metadata_for(scanned_pdf)

    async with DocumentConverter() as converter:
        result = await converter.convert_document(doc, output_dir, use_ocr=False)

    assert result.success is True
    assert result.ocr_required is True


@pytest.mark.slow
@pytest.mark.asyncio
async def test_convert_scanned_pdf_with_ocr_recovers_text(scanned_pdf, tmp_path) -> None:
    output_dir = tmp_path / "Conversión"
    doc = _metadata_for(scanned_pdf)

    async with DocumentConverter() as converter:
        result = await converter.convert_document(doc, output_dir, use_ocr=True)

    assert result.success is True
    markdown_text = await asyncio.to_thread(_read_text, result.markdown_path)
    assert "Informe de prueba" in markdown_text


@pytest.mark.asyncio
async def test_convert_document_reports_error_without_raising(tmp_path) -> None:
    missing = tmp_path / "does-not-exist.pdf"
    doc = DocumentMetadata(
        full_path=str(missing),
        display_name=missing.name,
        extension="pdf",
        size_bytes=0,
        modified_time=0.0,
        sha256_hash="irrelevant",
    )

    async with DocumentConverter() as converter:
        result = await converter.convert_document(doc, tmp_path / "Conversión")

    assert result.success is False
    assert result.error is not None
    assert result.markdown_path is None
    assert result.json_path is None


@pytest.mark.asyncio
async def test_convert_document_error_without_message_gets_fallback_text(monkeypatch, tmp_path) -> None:
    """Regresion (sesion 2026-09-05): una excepcion sin mensaje (`str(exc) == ""`,
    p.ej. una falla interna de bs4/lxml al parsear HTML) no debe dejar
    `ConversionResult.error` vacio -- bug real (informe HTML ZAP terminado en
    error sin ningun texto visible para el usuario)."""
    import doc_organize.converter.converter as converter_module

    html_path = tmp_path / "page.html"
    html_path.write_text("<html><body><p>Texto</p></body></html>", encoding="utf-8")
    stat = html_path.stat()
    doc = DocumentMetadata(
        full_path=str(html_path),
        display_name=html_path.name,
        extension="html",
        size_bytes=stat.st_size,
        modified_time=stat.st_mtime,
        sha256_hash="irrelevant",
    )
    output_dir = tmp_path / "Conversión"

    def _boom(_docling_result: object) -> bool:
        raise Exception()  # noqa: TRY002 -- excepcion deliberadamente sin mensaje

    monkeypatch.setattr(converter_module.DocumentConverter, "_needs_ocr", staticmethod(_boom))

    async with DocumentConverter() as converter:
        result = await converter.convert_document(doc, output_dir)

    assert result.success is False
    assert result.error
    assert "sin mensaje" in result.error


def test_resolve_output_paths_mirrors_source_tree_relative_to_scan_root(tmp_path) -> None:
    scan_root = tmp_path / "input"
    output_dir = tmp_path / "Conversión"
    source = scan_root / "sub" / "informe.pdf"

    markdown_path, json_path = DocumentConverter.resolve_output_paths(str(source), output_dir, scan_roots=(str(scan_root),))
    again_markdown, again_json = DocumentConverter.resolve_output_paths(str(source), output_dir, scan_roots=(str(scan_root),))

    assert markdown_path == again_markdown
    assert json_path == again_json
    assert markdown_path.name == "informe.md"
    assert json_path.name == "informe.json"
    # Replica la jerarquia "sub" del fuente relativa a `scan_root` (no a la raiz del
    # filesystem, ni depende del hash) bajo `output_dir`.
    assert markdown_path == output_dir / "sub" / "informe.md"
    assert markdown_path.is_relative_to(output_dir)


def test_resolve_output_paths_does_not_duplicate_absolute_source_tree(tmp_path) -> None:
    """Regresion (sesion 2026-09-05): un .docx bajo una carpeta escaneada (`scan_root`)
    convertido a un `output_dir` que vive en OTRA rama del arbol de ficheros no debe
    arrastrar la ruta absoluta completa de origen bajo `output_dir` -- eso generaba una
    jerarquia duplicada e inexistente (`[Errno 2] No such file or directory` real al
    extraer imagenes de un .docx con Docling)."""
    scan_root = tmp_path / "DOC_ORGANIZE_04"
    source = scan_root / "Evidencias Auditoría" / "informe.docx"
    output_dir = tmp_path / "prueba_doc" / "organaize" / "Conversión"

    markdown_path, json_path = DocumentConverter.resolve_output_paths(str(source), output_dir, scan_roots=(str(scan_root),))

    assert markdown_path == output_dir / "Evidencias Auditoría" / "informe.md"
    assert json_path == output_dir / "Evidencias Auditoría" / "informe.json"
    # La parte de la ruta relativa a output_dir no debe contener el nombre de la
    # carpeta raiz de origen (antes se duplicaba: output_dir/DOC_ORGANIZE_04/...).
    assert scan_root.name not in markdown_path.relative_to(output_dir).parts


def test_resolve_output_paths_flattens_when_no_scan_root_matches(tmp_path) -> None:
    output_dir = tmp_path / "Conversión"
    source = tmp_path / "outside" / "deep" / "informe.pdf"

    markdown_path, json_path = DocumentConverter.resolve_output_paths(str(source), output_dir)

    assert markdown_path == output_dir / "informe.md"
    assert json_path == output_dir / "informe.json"


def test_resolve_output_paths_namespaces_images_dir_by_stem(tmp_path) -> None:
    """Dos documentos distintos convertidos al mismo `output_dir` deben quedar en
    subcarpetas `img/<stem>` distintas (sesion 'soporte de formatos docling', evita
    que sus imagenes se pisen si ambos usan `extract_images=True`)."""
    output_dir = tmp_path / "Conversión"

    markdown_a, _ = DocumentConverter.resolve_output_paths(str(tmp_path / "input" / "informe_a.pdf"), output_dir)
    markdown_b, _ = DocumentConverter.resolve_output_paths(str(tmp_path / "input" / "informe_b.pdf"), output_dir)

    assert markdown_a.parent == markdown_b.parent  # mismo target_dir (misma carpeta origen)
    images_dir_a = markdown_a.parent / "img" / markdown_a.stem
    images_dir_b = markdown_b.parent / "img" / markdown_b.stem
    assert images_dir_a != images_dir_b


@pytest.mark.asyncio
async def test_extract_images_true_without_pictures_leaves_no_images_dir(native_pdf, tmp_path) -> None:
    """`native_pdf` no tiene imagenes embebidas: `save_as_markdown` crea igualmente
    `img/<stem>/` (comportamiento de docling), pero `_finalize_images_dir` debe
    limpiarla si queda vacia, dejando `images_dir=None`."""
    output_dir = tmp_path / "Conversión"
    doc = _metadata_for(native_pdf)

    async with DocumentConverter() as converter:
        result = await converter.convert_document(doc, output_dir, extract_images=True)

    assert result.success is True
    assert result.images_dir is None
    assert not (Path(result.markdown_path).parent / "img" / Path(result.markdown_path).stem).exists()
    markdown_text = await asyncio.to_thread(_read_text, result.markdown_path)
    assert "Informe de prueba" in markdown_text


@pytest.mark.slow
@pytest.mark.asyncio
async def test_write_outputs_cleanup_failure_reports_error_without_raising(monkeypatch, native_pdf, tmp_path) -> None:
    """AUDIT_CODE: si borrar `img/<stem>/` falla (permiso denegado, fichero
    bloqueado), `convert_document` debe reportar `success=False` — no propagar la
    excepcion y abortar el resto del batch de `ScanCommand._convert_documents`."""
    import doc_organize.converter.converter as converter_module

    doc = _metadata_for(native_pdf)
    output_dir = tmp_path / "Conversión"
    markdown_path, _json_path = DocumentConverter.resolve_output_paths(str(native_pdf), output_dir)
    images_dir = DocumentConverter.resolve_images_dir(markdown_path)
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / "stale.png").write_bytes(b"fake-png-content")

    def _boom(path: Path) -> None:
        raise OSError("simulated permission denied")

    monkeypatch.setattr(converter_module.shutil, "rmtree", _boom)

    async with DocumentConverter() as converter:
        result = await converter.convert_document(doc, output_dir, extract_images=True)

    assert result.success is False
    assert result.error is not None
    assert "simulated permission denied" in result.error
    assert result.markdown_path is None


@pytest.mark.slow
@pytest.mark.asyncio
async def test_extract_images_reconversion_clears_stale_images(tmp_path) -> None:
    """AUDIT_CODE: reconvertir el mismo documento con menos graficos no debe dejar
    ficheros obsoletos en `img/<stem>/`. Docling nombra cada imagen con un sufijo de
    hash de contenido, asi que sin limpiar el directorio antes de escribir, una
    reconversion con imagenes distintas ACUMULABA ficheros en vez de sobrescribirlos.

    Compara contra un "grupo de control" (mismo PDF final, convertido de cero en una
    carpeta limpia) en vez de un numero fijo de imagenes esperadas: cuantas imagenes
    detecta Docling para un PDF con graficos pequenos via matplotlib no es 100%
    determinista, pero el numero SI debe coincidir entre una conversion limpia y una
    reconversion sobre un `img/<stem>/` que ya tenia contenido de antes.
    """
    pdf_path = tmp_path / "doc.pdf"
    output_dir = tmp_path / "Conversión"

    _make_pdf_with_n_charts(pdf_path, 2)
    async with DocumentConverter() as converter:
        first = await converter.convert_document(_metadata_for(pdf_path), output_dir, extract_images=True)
    assert first.images_dir is not None

    _make_pdf_with_n_charts(pdf_path, 1)  # documento editado: un grafico menos

    # Grupo de control: el mismo PDF (ya con 1 grafico) convertido de cero, sin
    # arrastrar ningun `img/<stem>/` previo — su recuento de imagenes es la
    # referencia correcta para la reconversion de abajo.
    async with DocumentConverter() as converter:
        control = await converter.convert_document(_metadata_for(pdf_path), tmp_path / "control", extract_images=True)
    control_count = 0 if control.images_dir is None else len(list(await asyncio.to_thread(lambda: list(Path(control.images_dir).iterdir()))))

    # Reconversion real: MISMO output_dir que `first` (con el `img/<stem>/` del
    # documento anterior, de 2 graficos, ya en disco).
    async with DocumentConverter() as converter:
        second = await converter.convert_document(_metadata_for(pdf_path), output_dir, extract_images=True)
    second_count = 0 if second.images_dir is None else len(list(await asyncio.to_thread(lambda: list(Path(second.images_dir).iterdir()))))

    assert second_count == control_count


@pytest.mark.asyncio
async def test_use_picture_description_not_applied_for_non_pdf_format(tmp_path) -> None:
    """`do_picture_description` solo tiene efecto en el pipeline PDF/imagen
    (`StandardPdfPipeline`); HTML usa `SimplePipeline`, sin ese paso — el flag se
    acepta sin error pero `picture_description_applied` debe quedar en `False`."""
    html_path = tmp_path / "page.html"
    html_path.write_text("<html><body><h1>Hola</h1><p>Texto de prueba</p></body></html>", encoding="utf-8")
    stat = html_path.stat()
    doc = DocumentMetadata(
        full_path=str(html_path),
        display_name=html_path.name,
        extension="html",
        size_bytes=stat.st_size,
        modified_time=stat.st_mtime,
        sha256_hash="test-hash-not-relevant-here",
    )
    output_dir = tmp_path / "Conversión"

    async with DocumentConverter() as converter:
        result = await converter.convert_document(doc, output_dir, use_picture_description=True)

    assert result.success is True
    assert result.picture_description_applied is False
    markdown_text = await asyncio.to_thread(_read_text, result.markdown_path)
    assert "Hola" in markdown_text


@pytest.mark.asyncio
async def test_using_outside_context_manager_raises(tmp_path) -> None:
    from doc_organize.core.exceptions import ConversionError

    converter = DocumentConverter()
    doc = DocumentMetadata(
        full_path=str(tmp_path / "x.pdf"),
        display_name="x.pdf",
        extension="pdf",
        size_bytes=0,
        modified_time=0.0,
        sha256_hash="irrelevant",
    )
    with pytest.raises(ConversionError):
        await converter.convert_document(doc, tmp_path)
