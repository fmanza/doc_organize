"""
Paquete del contexto para IA (2.0.0, F7): `write_ai_context_bundle` y `render_llms_txt`.

El uso más habitual del contexto fuera de la web es dárselo a un chat o un agente de IA (un proyecto de Claude,
NotebookLM, Copilot). El paquete es un ZIP pensado para subirlo tal cual:

- `llms.txt` (formato de llmstxt.org): el proyecto, una sección por dominio y una línea por documento con su enlace y su
  descripción. No es para buscadores: es el índice que lee el modelo.
- `documentos/<dominio>/<tipo>/<carpeta>/<doc>.md`: el texto de cada documento con un front matter YAML (título,
  dominio, tipo de material, valores de cada eje, versión, ruta relativa del original, huella y quién clasificó).
- `context.json`: el contexto reducido, sin rutas absolutas.
- `llms-full.txt` (opcional, con tope): todo el texto en un fichero.

**Redactado por defecto** (`redact=True`, F1): títulos, descripciones y textos salen sin credenciales. **Solo las
versiones vigentes** por defecto (`current_only=True`, F5). El ZIP es reproducible (mismo contexto y textos → mismo
SHA-256).

Example:
    ```python
    stats = await asyncio.to_thread(write_ai_context_bundle, "contexto_ia.zip", project, context)
    print(stats.documents, stats.redacted_documents, stats.sha256)
    ```
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile

from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

import yaml

from pydantic import BaseModel

from doc_organize import __version__
from doc_organize.context.llms_txt import LlmsEntry, llms_entries, one_line, render_llms_txt
from doc_organize.core.models import Context, DomainDocument, Project
from doc_organize.core.progress import CancelToken, ProgressCallback, checkpoint
from doc_organize.export._progress import ExportProgress
from doc_organize.security.credentials import redact_credentials
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

#: Carpeta de los documentos dentro del paquete.
BUNDLE_DOCUMENTS_FOLDER = "documentos"
_FIXED_DATE = (1980, 1, 1, 0, 0, 0)
_FILE_MODE = 0o644 << 16


class AiBundleStats(BaseModel):
    """Resultado de `write_ai_context_bundle`.

    Attributes:
        file_count (int): Ficheros del ZIP.
        total_size_bytes (int): Bytes sin comprimir.
        documents (int): Documentos incluidos.
        superseded_skipped (int): Versiones antiguas que no entraron (`current_only`).
        missing_text (int): Documentos cuyo `.md` no se pudo leer (entran sin texto).
        redacted_documents (int): Documentos en los que se redactó alguna credencial.
        full_text_truncated (bool): Si `llms-full.txt` se cortó por `max_full_chars`.
        sha256 (str): SHA-256 del ZIP.
    """

    file_count: int
    total_size_bytes: int
    documents: int
    superseded_skipped: int = 0
    missing_text: int = 0
    redacted_documents: int = 0
    full_text_truncated: bool = False
    sha256: str


def write_ai_context_bundle(
    destination: str | Path | BinaryIO,
    project: Project,
    context: Context,
    *,
    include_text: bool = True,
    current_only: bool = True,
    redact: bool = True,
    max_file_chars: int | None = None,
    max_full_chars: int | None = None,
    roots: Sequence[str] | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_token: CancelToken | None = None,
) -> AiBundleStats:
    """Escribe el paquete para IA de `context` (ver el módulo) en `destination`, en *streaming*.

    Síncrona (`zipfile` no es async): un consumidor async la llama con `asyncio.to_thread`.

    Args:
        destination: Ruta del ZIP (se crea o sobrescribe) o fichero binario abierto para escritura (no se cierra).
        project: Proyecto (nombre).
        context: Contexto construido.
        include_text: Incluir el texto de cada documento (si no, solo su ficha).
        current_only: Solo las versiones vigentes (F5): sin las de `context.superseded_documents` ni las marcadas como
            no vigentes.
        redact: Redactar credenciales de títulos, descripciones y textos (F1). Desactivarlo saca valores secretos.
        max_file_chars: Caracteres como mucho del texto de cada documento (se avisa del corte); `None` = sin tope.
        max_full_chars: Con un valor, añade `llms-full.txt` con todo el texto hasta ese tope; `None` = no se añade.
        roots: Raíces de escaneo para las rutas relativas de los originales (por defecto, la carpeta común).
        on_progress: Recibe `ProgressEvent(operation="export")` como `write_project_zip`.
        cancel_token: Si se cancela, para entre dos documentos.

    Raises:
        OperationCancelledError: Se canceló; si `destination` es una ruta, el fichero parcial se borra.
    """
    if not isinstance(destination, str | os.PathLike):
        return _write(
            destination, project, context, include_text, current_only, redact, max_file_chars, max_full_chars, roots, on_progress, cancel_token
        )
    path = Path(destination)
    try:
        with path.open("wb") as stream:
            return _write(
                stream, project, context, include_text, current_only, redact, max_file_chars, max_full_chars, roots, on_progress, cancel_token
            )
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class _HashingWriter:
    def __init__(self, target: BinaryIO) -> None:
        self._target = target
        self.digest = hashlib.sha256()

    def write(self, data: bytes) -> int:
        self._target.write(data)
        self.digest.update(data)
        return len(data)

    def flush(self) -> None:
        self._target.flush()


def _write(
    stream: BinaryIO,
    project: Project,
    context: Context,
    include_text: bool,
    current_only: bool,
    redact: bool,
    max_file_chars: int | None,
    max_full_chars: int | None,
    roots: Sequence[str] | None,
    on_progress: ProgressCallback | None,
    cancel_token: CancelToken | None,
) -> AiBundleStats:
    entries, superseded = llms_entries(context, project.root_path, current_only=current_only, roots=roots)
    progress = ExportProgress(on_progress, len(entries) + 2 + (max_full_chars is not None), logger)
    progress.emit("started", 0)
    writer = _HashingWriter(stream)
    stats: dict[str, Any] = {"missing_text": 0, "redacted_documents": 0, "full_text_truncated": False}
    full: list[str] = []
    full_size = 0
    total = 0
    written = 0
    index_rows = []

    with zipfile.ZipFile(writer, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:  # type: ignore[call-overload]  # sin seek: mismos bytes siempre

        def add(name: str, text: str) -> None:
            nonlocal total, written
            data = text.encode("utf-8")
            archive.writestr(_info(name), data)
            total += len(data)
            written += 1
            progress.emit("export", written, name)

        llms = render_llms_txt(
            project.name,
            context,
            lambda organized: f"{BUNDLE_DOCUMENTS_FOLDER}/{organized}",
            project_root=project.root_path,
            redact=redact,
            current_only=current_only,
        )
        add("llms.txt", llms)
        for entry in entries:
            checkpoint(cancel_token)
            text, redacted = _document_text(entry.document, include_text, redact, stats)
            if max_file_chars is not None and len(text) > max_file_chars:
                text = text[:max_file_chars] + f"\n\n[… texto cortado: {len(text) - max_file_chars} caracteres más]\n"
            stats["redacted_documents"] += redacted
            front = _front_matter(entry, redact)
            add(f"{BUNDLE_DOCUMENTS_FOLDER}/{entry.organized}", f"---\n{front}---\n\n{text}")
            index_rows.append({"path": f"{BUNDLE_DOCUMENTS_FOLDER}/{entry.organized}", **_metadata(entry, redact)})
            if max_full_chars is not None and include_text and not stats["full_text_truncated"]:
                section = f"\n\n# {one_line(entry.document.title, redact)}\n\n{text}"
                if full_size + len(section) > max_full_chars:
                    stats["full_text_truncated"] = True
                else:
                    full.append(section)
                    full_size += len(section)
        add("context.json", json.dumps(_reduced_context(project, context, index_rows, redact), ensure_ascii=False, indent=2) + "\n")
        if max_full_chars is not None:
            note = "\n\n[… se alcanzó el tope de llms-full.txt: el resto está en documentos/]\n" if stats["full_text_truncated"] else "\n"
            add("llms-full.txt", f"# {one_line(project.name, redact)}" + "".join(full) + note)
    progress.emit("done", written)
    return AiBundleStats(
        file_count=written, total_size_bytes=total, documents=len(entries), superseded_skipped=superseded, sha256=writer.digest.hexdigest(), **stats
    )


def _document_text(document: DomainDocument, include_text: bool, redact: bool, stats: dict[str, Any]) -> tuple[str, int]:
    if not include_text:
        return "", 0
    try:
        text = Path(document.markdown_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        stats["missing_text"] += 1
        logger.warning(f"Paquete para IA: no se pudo leer el texto de '{document.markdown_path}'; entra sin texto")
        return "(no se pudo leer el texto de este documento)\n", 0
    if not redact:
        return text, 0
    result = redact_credentials(text)
    return result.text, int(bool(result.findings))


def _metadata(entry: LlmsEntry, redact: bool) -> dict[str, Any]:
    document = entry.document
    data: dict[str, Any] = {
        "title": one_line(document.title, redact),
        "domain": entry.domain.slug,
        "material_type": document.material_type,
        "axes": {axis: [value.slug for value in values] for axis, values in sorted(document.classification.axes.items()) if values},
        "classified_by": document.classified_by,
        "source": entry.key,
        "source_sha256": document.source_sha256,
    }
    if document.version:
        data["version"] = document.version
        data["is_current"] = document.is_current
    if document.description:
        data["description"] = one_line(document.description, redact)
    if document.keywords:
        data["keywords"] = [one_line(keyword, redact) for keyword in document.keywords]
    return {key: value for key, value in data.items() if value not in (None, {}, [])}


def _front_matter(entry: LlmsEntry, redact: bool) -> str:
    return yaml.safe_dump(_metadata(entry, redact), allow_unicode=True, sort_keys=False, width=1000)


def _reduced_context(project: Project, context: Context, documents: list[dict[str, Any]], redact: bool) -> dict[str, Any]:
    return {
        "project": one_line(project.name, redact),
        "generated_by": f"doc_organize {__version__}",
        "context_updated_at": context.updated_at,
        "domains": [{"slug": domain.slug, "name": one_line(domain.name, redact)} for domain in context.domains],
        "taxonomy_axes": [
            {
                "key": axis.key,
                "name": axis.name,
                "organizes": axis.organizes,
                "entries": [{"slug": entry.slug, "name": entry.name} for entry in axis.entries],
            }
            for axis in context.taxonomy_axes
        ],
        "documents": documents,
    }


def _info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(PurePosixPath(name).as_posix(), date_time=_FIXED_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = _FILE_MODE
    info.create_system = 3
    return info


__all__ = ["BUNDLE_DOCUMENTS_FOLDER", "AiBundleStats", "render_llms_txt", "write_ai_context_bundle"]
