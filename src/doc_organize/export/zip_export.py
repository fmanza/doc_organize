"""ZIP de un proyecto en *streaming* y su vista previa exacta (L-7, hueco G8 de doc_organize_web).

El ZIP contiene, en este orden:

1. Todos los ficheros de `Conversión/` como `Conversión/<ruta relativa>` (recorrido alfabético estable, sin seguir
   enlaces simbólicos).
2. `cache_export.json`: instantánea `CacheExportSnapshot` de todas las entradas, ordenadas por `file_path`.
3. `duplicados/DEDUP_REPORT.json`, si existe.

Se escribe directamente en el destino (ruta o fichero binario), copiando por bloques: ni el ZIP ni ningún fichero se
cargan enteros en memoria, y no se crean temporales. La vista previa recorre las mismas fuentes y genera el mismo JSON,
así que coincide con el ZIP mientras el disco no cambie entre las dos llamadas.
"""

import json
import os
import textwrap
import time
import zipfile

from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from pydantic import BaseModel, ConfigDict, Field

from doc_organize.core.exceptions import InvalidPathError
from doc_organize.core.models import CacheEntry, DocumentStatus
from doc_organize.core.progress import CancelToken, ProgressCallback, checkpoint
from doc_organize.export._progress import ExportProgress
from doc_organize.projects.layout import ProjectLayout
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

#: Nombre de la instantánea de la caché dentro del ZIP.
CACHE_SNAPSHOT_NAME = "cache_export.json"

_CHUNK_SIZE = 1024 * 1024
# Mismo umbral que `ZipFile.write` para forzar ZIP64 en un fichero que puede pasar de 2 GiB al escribirse.
_ZIP64_LIMIT = (1 << 31) - 1
_FILE_MODE = 0o600 << 16


class ExportStats(BaseModel):
    """Ficheros y bytes (sin comprimir) de un ZIP de exportación.

    Lo devuelven `preview_project_zip` (lo que incluiría) y `write_project_zip` (lo que ha escrito); coincide con
    `len(ZipFile.infolist())` y la suma de `ZipInfo.file_size`.

    Attributes:
        file_count: Ficheros dentro del ZIP.
        total_size_bytes: Suma de sus tamaños sin comprimir.

    Example:
        >>> ExportStats(file_count=1, total_size_bytes=120).file_count
        1
    """

    model_config = ConfigDict(frozen=True)

    file_count: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)


def preview_project_zip(
    entries: Iterable[CacheEntry],
    *,
    layout: ProjectLayout | None = None,
    conversion_dir: Path | None = None,
    dedup_report: Path | None = None,
) -> ExportStats:
    """Cuenta ficheros y bytes de lo que escribiría `write_project_zip` con los mismos argumentos, sin escribirlo.

    Args:
        entries: Entradas de caché (de una o varias cachés, ver `load_cache_entries`).
        layout: Rutas del proyecto; alternativa a `conversion_dir` + `dedup_report`.
        conversion_dir: Carpeta `Conversión/` (si no existe, el ZIP no lleva ficheros convertidos).
        dedup_report: `DEDUP_REPORT.json` (se incluye si existe).

    Returns:
        Lo que incluiría el ZIP. Es una instantánea: si el proyecto cambia antes de escribirlo, puede diferir.

    Raises:
        ValueError: Se pasó `layout` junto con `conversion_dir` o `dedup_report`.

    Example:
        >>> import tempfile
        >>> from pathlib import Path
        >>> preview_project_zip([], conversion_dir=Path(tempfile.mkdtemp())).file_count  # solo cache_export.json
        1
    """
    conversion_dir, dedup_report = _resolve_sources(layout, conversion_dir, dedup_report)
    members = _conversion_members(conversion_dir)
    report = _report_member(dedup_report)
    if report is not None:
        members.append(report)
    snapshot_size = sum(len(chunk.encode("utf-8")) for chunk in _snapshot_chunks(_sorted(entries), _export_timestamp()))
    return ExportStats(
        file_count=len(members) + 1,
        total_size_bytes=sum(source.stat().st_size for source, _ in members) + snapshot_size,
    )


def write_project_zip(
    destination: str | Path | BinaryIO,
    entries: Iterable[CacheEntry],
    *,
    layout: ProjectLayout | None = None,
    conversion_dir: Path | None = None,
    dedup_report: Path | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_token: CancelToken | None = None,
) -> ExportStats:
    """Escribe el ZIP del proyecto en `destination`, en *streaming*.

    Síncrona (`zipfile` no es async): un consumidor async la llama con `asyncio.to_thread`; `CancelToken` es seguro
    entre hilos.

    Args:
        destination: Ruta del ZIP (se crea o sobrescribe) o fichero binario abierto para escritura (no hace falta que
            admita `seek`; no se cierra).
        entries: Entradas de caché (de una o varias cachés, ver `load_cache_entries`).
        layout: Rutas del proyecto; alternativa a `conversion_dir` + `dedup_report`.
        conversion_dir: Carpeta `Conversión/`.
        dedup_report: `DEDUP_REPORT.json` (se incluye si existe).
        on_progress: Recibe `ProgressEvent(operation="export")`: `started`, uno de fase `export` por fichero escrito
            (`current` = nombre dentro del ZIP) y `done`. Un fallo del callback no para la exportación. Se llama
            desde el hilo que escribe.
        cancel_token: Si se cancela, para entre dos bloques de 1 MiB.

    Returns:
        Ficheros y bytes escritos (igual que `preview_project_zip` si el disco no cambió).

    Raises:
        OperationCancelledError: Se canceló. Si `destination` es una ruta, el fichero parcial se borra; si es un
            fichero abierto, descartarlo es cosa del llamador.
        InvalidPathError: `destination` está dentro de `conversion_dir` (el ZIP se incluiría a sí mismo).
        ValueError: Se pasó `layout` junto con `conversion_dir` o `dedup_report`.

    Example:
        >>> import io, tempfile, zipfile
        >>> from pathlib import Path
        >>> buffer = io.BytesIO()
        >>> write_project_zip(buffer, [], conversion_dir=Path(tempfile.mkdtemp())).file_count
        1
        >>> zipfile.ZipFile(buffer).namelist()
        ['cache_export.json']
    """
    conversion_dir, dedup_report = _resolve_sources(layout, conversion_dir, dedup_report)
    if not isinstance(destination, str | os.PathLike):
        return _write_zip(destination, entries, conversion_dir, dedup_report, on_progress, cancel_token)

    path = Path(destination)
    if conversion_dir is not None and path.resolve().is_relative_to(conversion_dir.resolve()):
        raise InvalidPathError(f"El ZIP no puede escribirse dentro de '{conversion_dir}': se incluiría a sí mismo.")
    try:
        with path.open("wb") as stream:
            return _write_zip(stream, entries, conversion_dir, dedup_report, on_progress, cancel_token)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _write_zip(
    stream: BinaryIO,
    entries: Iterable[CacheEntry],
    conversion_dir: Path | None,
    dedup_report: Path | None,
    on_progress: ProgressCallback | None,
    cancel_token: CancelToken | None,
) -> ExportStats:
    members = _conversion_members(conversion_dir)
    report_member = _report_member(dedup_report)
    progress = ExportProgress(on_progress, len(members) + 1 + (report_member is not None), logger)
    progress.emit("started", 0)
    written = 0

    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for source, arcname in members:
            _write_file(zip_file, source, arcname, cancel_token)
            written += 1
            progress.emit("export", written, arcname)

        checkpoint(cancel_token)
        snapshot_info = _new_info(CACHE_SNAPSHOT_NAME)
        with zip_file.open(snapshot_info, mode="w") as target:
            for chunk in _snapshot_chunks(_sorted(entries), _export_timestamp()):
                target.write(chunk.encode("utf-8"))
        written += 1
        progress.emit("export", written, CACHE_SNAPSHOT_NAME)

        if report_member is not None:
            _write_file(zip_file, *report_member, cancel_token)
            written += 1
            progress.emit("export", written, report_member[1])

        infos = zip_file.infolist()

    progress.emit("done", written)
    return ExportStats(file_count=len(infos), total_size_bytes=sum(info.file_size for info in infos))


def _write_file(zip_file: zipfile.ZipFile, source: Path, arcname: str, cancel_token: CancelToken | None) -> None:
    """Copia `source` al ZIP por bloques, consultando `cancel_token` antes de cada uno."""
    checkpoint(cancel_token)
    info = zipfile.ZipInfo.from_file(source, arcname, strict_timestamps=False)
    info.compress_type = zipfile.ZIP_DEFLATED
    with source.open("rb") as origin, zip_file.open(info, mode="w", force_zip64=info.file_size * 1.05 > _ZIP64_LIMIT) as target:
        while chunk := origin.read(_CHUNK_SIZE):
            checkpoint(cancel_token)
            target.write(chunk)


def _new_info(arcname: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(arcname, date_time=time.localtime()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = _FILE_MODE
    return info


def _resolve_sources(layout: ProjectLayout | None, conversion_dir: Path | None, dedup_report: Path | None) -> tuple[Path | None, Path | None]:
    if layout is None:
        return conversion_dir, dedup_report
    if conversion_dir is not None or dedup_report is not None:
        raise ValueError("Indica `layout` o `conversion_dir`/`dedup_report`, no ambos.")
    return layout.conversion_dir, layout.dedup_report


def _conversion_members(conversion_dir: Path | None) -> list[tuple[Path, str]]:
    """(fichero, nombre en el ZIP) de cada fichero de `Conversión/`, en orden alfabético estable."""
    members: list[tuple[Path, str]] = []
    if conversion_dir is None or not conversion_dir.is_dir():
        return members
    # followlinks=False y se omiten los ficheros enlace: un symlink no puede colar en el ZIP nada de fuera.
    for dirpath, dirnames, filenames in os.walk(conversion_dir):
        dirnames.sort()
        folder = Path(dirpath)
        for name in sorted(filenames):
            source = folder / name
            if source.is_symlink() or not source.is_file():
                continue
            members.append((source, f"{conversion_dir.name}/{source.relative_to(conversion_dir).as_posix()}"))
    return members


def _report_member(dedup_report: Path | None) -> tuple[Path, str] | None:
    """(fichero, nombre en el ZIP) del informe de duplicados, si existe."""
    if dedup_report is None or not dedup_report.is_file() or dedup_report.is_symlink():
        return None
    return dedup_report, f"{dedup_report.parent.name}/{dedup_report.name}"


def _sorted(entries: Iterable[CacheEntry]) -> list[CacheEntry]:
    return sorted(entries, key=lambda entry: entry.file_path)


def _export_timestamp() -> str:
    # Microsegundos siempre presentes: `isoformat()` los omite cuando valen 0 y la longitud del JSON variaría.
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _snapshot_chunks(entries: list[CacheEntry], timestamp: str) -> Iterator[str]:
    """`CacheExportSnapshot` en JSON con sangría de 2, por trozos (no se construye el documento entero en memoria)."""
    yield "{\n"
    yield f'  "export_timestamp": {json.dumps(timestamp)},\n'
    yield f'  "total_entries": {len(entries)},\n'
    for key, status in (
        ("new_files", DocumentStatus.NEW),
        ("modified_files", DocumentStatus.MODIFIED),
        ("unchanged_files", DocumentStatus.UNCHANGED),
    ):
        yield f'  "{key}": '
        yield from _json_array((json.dumps(entry.file_path, ensure_ascii=False) for entry in entries if entry.status is status), "  ")
        yield ",\n"
    yield '  "entries": '
    yield from _json_array((json.dumps(entry.model_dump(mode="json"), ensure_ascii=False, indent=2) for entry in entries), "  ")
    yield "\n}"


def _json_array(items: Iterator[str], indent: str) -> Iterator[str]:
    separator = "[\n"
    for item in items:
        yield separator
        yield textwrap.indent(item, indent + "  ")
        separator = ",\n"
    yield "[]" if separator == "[\n" else f"\n{indent}]"


__all__ = ["CACHE_SNAPSHOT_NAME", "ExportStats", "preview_project_zip", "write_project_zip"]
