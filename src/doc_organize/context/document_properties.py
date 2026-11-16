"""Propiedades que el autor declaró dentro del propio documento: autor, descripción y palabras clave (1.5.0).

PDF: diccionario `Info` (`/Author`, `/Subject`, `/Keywords`), leído con pypdfium2 (ya lo usa Docling). Office OOXML
(`.docx`, `.xlsx`, `.pptx` y sus variantes con macros): `docProps/core.xml` (`dc:creator`, `dc:description` o
`dc:subject`, `cp:keywords`), leído con la librería estándar. `/Creator` y `/Producer` de un PDF no se usan como autor:
nombran el programa que generó el fichero ("Microsoft Word"), no a una persona.

Segura entre hilos (1.6.0): PDFium no lo es, así que todas las llamadas a PDFium de este módulo pasan por un cerrojo,
**el mismo que usa Docling** (`docling.utils.locks.pypdfium2_lock`): leer propiedades mientras otro hilo del mismo
proceso convierte un PDF tampoco llama a PDFium dos veces a la vez. Si esa versión de Docling no lo tiene, se usa un
cerrojo propio, que solo protege las llamadas de este módulo. Los bytes del PDF se leen antes, fuera del cerrojo, porque en una carpeta de red esa lectura es lo caro; solo se
serializa el análisis (unos milisegundos). Un PDF de más de 16 MB se abre por ruta, también bajo el cerrojo, para no
cargarlo entero en memoria.
"""

import functools
import os
import threading
import zipfile

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from doc_organize.utils.logging import get_logger
from doc_organize.utils.text_clean import clean_keywords, clean_text

_logger = get_logger(__name__)

_OOXML_EXTENSIONS = frozenset({"docx", "docm", "xlsx", "xlsm", "pptx", "pptm"})
_CORE_XML = "docProps/core.xml"
#: Un `core.xml` real ocupa ~1 KB; uno mucho mayor es un fichero manipulado y no se descomprime.
_MAX_CORE_XML_BYTES = 1_000_000
#: Mayor que esto, el PDF se abre por ruta (bajo el cerrojo) en vez de leerse entero en memoria.
_MAX_PDF_BYTES_IN_MEMORY = 16_000_000
_NAMESPACES = {
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
}


@dataclass(frozen=True)
class DocumentProperties:
    """Autor, descripción y palabras clave declarados en el documento; vacíos si no los declara."""

    author: str | None = None
    description: str | None = None
    keywords: list[str] = field(default_factory=list)


def read_document_properties(path: str | Path) -> DocumentProperties:
    """Propiedades declaradas en `path`; vacías si el formato no las tiene o el fichero no se puede leer.

    Nunca lanza por un fichero concreto (dañado, cifrado, borrado, sin permisos): lo registra en `debug` y devuelve
    `DocumentProperties()`. Se puede llamar desde varios hilos a la vez (1.6.0): PDFium se usa bajo un cerrojo.
    """
    path = Path(path)
    extension = path.suffix.lower().lstrip(".")
    try:
        if extension == "pdf":
            return _read_pdf(path)
        if extension in _OOXML_EXTENSIONS:
            return _read_ooxml(path)
    except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        _logger.debug(f"No se pudieron leer las propiedades de '{path}': {exc}")
    return DocumentProperties()


@functools.cache
def _pdfium_lock() -> AbstractContextManager[bool]:
    """Cerrojo de PDFium compartido con Docling; uno propio si Docling no lo ofrece.

    PDFium no es thread-safe (pypdfium2, «Incompatibility with Threading»): nunca dos llamadas a la vez en el proceso.
    Se resuelve la primera vez que se lee un PDF, para no importar Docling al importar este módulo. `functools.cache`
    garantiza que todas las llamadas usan el mismo objeto.
    """
    try:
        from docling.utils.locks import pypdfium2_lock
    except ImportError:
        _logger.debug("Docling no ofrece 'docling.utils.locks.pypdfium2_lock': se usa un cerrojo propio para PDFium")
        return threading.Lock()
    lock: AbstractContextManager[bool] = pypdfium2_lock
    return lock


def _read_pdf(path: Path) -> DocumentProperties:
    import pypdfium2 as pdfium

    source = _pdf_bytes_or_path(path)  # E/S fuera del cerrojo
    with _pdfium_lock():
        try:
            pdf = pdfium.PdfDocument(source)
        except pdfium.PdfiumError as exc:  # dañado o cifrado
            _logger.debug(f"PDFium no pudo abrir '{path}': {exc}")
            return DocumentProperties()
        try:
            info = pdf.get_metadata_dict(skip_empty=True)
        finally:
            pdf.close()
    return DocumentProperties(
        author=clean_text(info.get("Author")),
        description=clean_text(info.get("Subject")),
        keywords=clean_keywords(info.get("Keywords")),
    )


def _pdf_bytes_or_path(path: Path) -> bytes | Path:
    """El PDF entero si cabe en `_MAX_PDF_BYTES_IN_MEMORY`; si no, la ruta (PDFium leerá solo lo que necesite)."""
    with path.open("rb") as handle:
        if os.fstat(handle.fileno()).st_size > _MAX_PDF_BYTES_IN_MEMORY:
            return path
        data = handle.read(_MAX_PDF_BYTES_IN_MEMORY + 1)  # acotado aunque el fichero crezca mientras se lee
    return data if len(data) <= _MAX_PDF_BYTES_IN_MEMORY else path


def _read_ooxml(path: Path) -> DocumentProperties:
    with zipfile.ZipFile(path) as archive:
        try:
            member = archive.getinfo(_CORE_XML)
        except KeyError:
            return DocumentProperties()
        if member.file_size > _MAX_CORE_XML_BYTES:
            _logger.debug(f"'{_CORE_XML}' de '{path}' ocupa {member.file_size} bytes: se ignora")
            return DocumentProperties()
        root = ElementTree.fromstring(archive.read(member))
    description = root.findtext("dc:description", namespaces=_NAMESPACES) or root.findtext("dc:subject", namespaces=_NAMESPACES)
    return DocumentProperties(
        author=clean_text(root.findtext("dc:creator", namespaces=_NAMESPACES)),
        description=clean_text(description),
        keywords=clean_keywords(root.findtext("cp:keywords", namespaces=_NAMESPACES)),
    )


__all__ = ["DocumentProperties", "read_document_properties"]
