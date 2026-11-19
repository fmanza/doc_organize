"""
Sitio del contexto sin conexión (2.0.0, F3): comprobación y ZIP reproducible para entregarlo.

`SiteGenerator.generate(offline=True)` construye un sitio pensado para abrirse desde el disco (`file://`) o con
`start_server.py`, fuera de la web y de su CSP `sandbox`. `check_site_offline` comprueba un `site/` ya construido:

- **sin recursos de terceros** en las páginas: ningún `<script src>`, hoja de estilos, imagen, `iframe` u objeto que
  apunte a `http(s)://` o `//` (los enlaces `<a href>` externos sí valen: no se cargan solos). El JavaScript del tema de
  Zensical lleva URLs de unpkg y jsDelivr que solo usa **bajo demanda** para funciones que el sitio no activa (Pyodide,
  ACE, lightbox, el polyfill de `ResizeObserver` para navegadores antiguos, y Mermaid si no está ya cargado: va
  empaquetado). Se listan en `script_references`, informativas: sin CSP (D6 b no se incluye) no se pueden bloquear;
- **enlaces internos a ficheros**: desde `file://` un enlace a una carpeta no abre su `index.html` (caso real de doc_ia
  con el logo); y que existan;
- **índice de búsqueda en JavaScript** (`search.js`), que es lo que funciona desde `file://`;
- **nada activo de los documentos** (D6): enlaces `javascript:` y atributos `on*` en el HTML.

`write_site_zip` empaqueta un `site/` que pasa la comprobación en un ZIP **reproducible** (mismo `site/` → mismo
SHA-256), con `start_server.py` y `VER_SITIO.md`.

Example:
    ```python
    result = await SiteGenerator().generate(project, context, offline=True)
    report = check_site_offline(result.site_dir)
    if not report.ok:
        print(report.problems())
    zipped = await asyncio.to_thread(write_site_zip, "sitio.zip", result.site_dir, project_name=project.name)
    print(zipped.sha256)
    ```
"""

from __future__ import annotations

import hashlib
import os
import re
import string
import zipfile

from html.parser import HTMLParser
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, Field

from doc_organize.core.exceptions import InvalidPathError, OfflineSiteError
from doc_organize.core.progress import CancelToken, ProgressCallback, checkpoint
from doc_organize.export._progress import ExportProgress
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

#: Etiquetas y atributos que cargan un recurso al abrir la página.
_LOADING = {
    "script": "src",
    "img": "src",
    "iframe": "src",
    "embed": "src",
    "object": "data",
    "source": "src",
    "audio": "src",
    "video": "src",
    "frame": "src",
}
_REMOTE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//", re.IGNORECASE)
_THIRD_PARTY_JS = re.compile(r"https?://(?:unpkg\.com|cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com)[^\"'`\s)]*", re.IGNORECASE)
#: Esquemas que no son ficheros del sitio.
_EXTERNAL_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
_MAX_LISTED = 50


class OfflineIssue(BaseModel):
    """Un problema de un fichero del sitio."""

    file: str = Field(..., description="Fichero, relativo al sitio")
    detail: str = Field(..., description="Qué: la URL, el enlace o el atributo")


class OfflineSiteReport(BaseModel):
    """Resultado de `check_site_offline`.

    Attributes:
        pages (int): Páginas HTML revisadas.
        remote_resources (list[OfflineIssue]): Recursos que se cargarían de terceros.
        folder_links (list[OfflineIssue]): Enlaces internos a carpetas (no abren desde `file://`).
        broken_links (list[OfflineIssue]): Enlaces internos a ficheros que no existen.
        active_content (list[OfflineIssue]): Enlaces `javascript:` o atributos `on*` (contenido activo).
        search_index_js (bool): Si está el índice de búsqueda en JavaScript.
        script_references (list[OfflineIssue]): URLs de terceros dentro del JavaScript (las del tema, bajo demanda);
            informativas, no impiden entregar el sitio.
    """

    pages: int = 0
    remote_resources: list[OfflineIssue] = Field(default_factory=list)
    folder_links: list[OfflineIssue] = Field(default_factory=list)
    broken_links: list[OfflineIssue] = Field(default_factory=list)
    active_content: list[OfflineIssue] = Field(default_factory=list)
    search_index_js: bool = False
    script_references: list[OfflineIssue] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Si el sitio se puede entregar para verse sin conexión."""
        return (
            bool(self.pages) and self.search_index_js and not (self.remote_resources or self.folder_links or self.broken_links or self.active_content)
        )

    def problems(self) -> list[str]:
        """Los problemas, en texto (como mucho 50 de cada tipo).

        Example:
            >>> OfflineSiteReport(pages=1, search_index_js=True).problems()
            []
        """
        lines = [] if self.pages else ["El sitio no tiene páginas"]
        if self.pages and not self.search_index_js:
            lines.append("Falta el índice de búsqueda en JavaScript (search.js): ¿se construyó con offline=True?")
        for label, issues in (
            ("Recurso de terceros", self.remote_resources),
            ("Enlace a una carpeta", self.folder_links),
            ("Enlace roto", self.broken_links),
            ("Contenido activo", self.active_content),
        ):
            lines.extend(f"{label} en {issue.file}: {issue.detail}" for issue in issues[:_MAX_LISTED])
        return lines


def check_site_offline(site_dir: str | Path) -> OfflineSiteReport:
    """Comprueba que el sitio de `site_dir` se puede ver sin conexión y sin nada de terceros (ver el módulo).

    Raises:
        FileNotFoundError: `site_dir` no existe o no es una carpeta.
    """
    root = Path(site_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"No existe el sitio: {root}")
    report = OfflineSiteReport()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix == ".html":
            report.pages += 1
            _check_page(root, path, relative, report)
        elif path.suffix == ".js":
            if path.name == "search.js" or (path.name.startswith("search") and path.name.endswith(".js")):
                report.search_index_js = True
            text = path.read_text(encoding="utf-8", errors="replace")
            report.script_references.extend(OfflineIssue(file=relative, detail=url) for url in sorted(set(_THIRD_PARTY_JS.findall(text))))
    return report


def _check_page(root: Path, path: Path, relative: str, report: OfflineSiteReport) -> None:
    parser = _PageParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    for tag, attribute, value in parser.found:
        url = value.strip()
        if attribute.startswith("on"):
            report.active_content.append(OfflineIssue(file=relative, detail=f"<{tag} {attribute}=…>"))
            continue
        if re.sub(r"[\x00-\x20]", "", url).lower().startswith(("javascript:", "vbscript:")):
            report.active_content.append(OfflineIssue(file=relative, detail=f"<{tag} {attribute}={url[:80]}>"))
            continue
        loads = _LOADING.get(tag) == attribute or (tag == "link" and attribute == "href" and parser.stylesheet(value))
        if _REMOTE.match(url):
            if loads:
                report.remote_resources.append(OfflineIssue(file=relative, detail=url[:200]))
            continue
        if tag in ("a", "link", "script", "img") and attribute in ("href", "src"):
            _check_internal(root, path, relative, url, report)


def _check_internal(root: Path, path: Path, relative: str, url: str, report: OfflineSiteReport) -> None:
    if not url or url.startswith(("#", "?")) or _EXTERNAL_SCHEME.match(url):
        return
    target_text = unquote(urlsplit(url).path)
    if not target_text:
        return
    target = (root / target_text.lstrip("/")) if target_text.startswith("/") else (path.parent / target_text)
    if target_text.endswith("/") or target.is_dir():
        report.folder_links.append(OfflineIssue(file=relative, detail=url))
    elif not target.exists():
        report.broken_links.append(OfflineIssue(file=relative, detail=url))


class _PageParser(HTMLParser):
    """Atributos con URL y manejadores `on*` de una página."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, str, str]] = []
        self._stylesheets: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): value or "" for name, value in attrs}
        if tag == "link" and "stylesheet" in values.get("rel", "").lower():
            self._stylesheets.add(values.get("href", ""))
        for name, value in values.items():
            if name.startswith("on") or name in ("href", "src", "data", "srcset", "action", "formaction", "poster"):
                self.found.append((tag, name, value))

    handle_startendtag = handle_starttag

    def stylesheet(self, href: str) -> bool:
        return href in self._stylesheets


# --- ZIP reproducible ------------------------------------------------------------------------------------------------

#: Carpeta del sitio dentro del ZIP.
SITE_ZIP_FOLDER = "sitio"
#: Fecha de todas las entradas (la mínima de ZIP): sin ella, el ZIP cambiaría con la hora.
_FIXED_DATE = (1980, 1, 1, 0, 0, 0)
_FILE_MODE = 0o644 << 16
_CHUNK_SIZE = 1024 * 1024
_ZIP64_LIMIT = (1 << 31) - 1
_TEMPLATES = Path(__file__).parent / "site_assets" / "zip"


class SiteZipResult(BaseModel):
    """Resultado de `write_site_zip`.

    Attributes:
        file_count (int): Ficheros del ZIP (el sitio, `start_server.py` y `VER_SITIO.md`).
        total_size_bytes (int): Bytes sin comprimir.
        zip_size_bytes (int): Bytes del ZIP.
        sha256 (str): SHA-256 del ZIP: el mismo `site/` da el mismo valor.
    """

    file_count: int
    total_size_bytes: int
    zip_size_bytes: int
    sha256: str


def write_site_zip(
    destination: str | Path | BinaryIO,
    site_dir: str | Path,
    *,
    project_name: str = "",
    on_progress: ProgressCallback | None = None,
    cancel_token: CancelToken | None = None,
) -> SiteZipResult:
    """Empaqueta el sitio sin conexión de `site_dir` en un ZIP reproducible y en *streaming*.

    El ZIP lleva el sitio en `sitio/`, `start_server.py` (servidor local solo en `127.0.0.1`, puerto libre) y
    `VER_SITIO.md` (cómo abrirlo en Windows, macOS y Linux, y el aviso de contenido de terceros). Es **reproducible**:
    orden alfabético, fecha y permisos fijos y la misma compresión, así que el mismo `site/` da el mismo SHA-256 (también
    si se escribe en un fichero abierto en lugar de una ruta).

    Síncrona (`zipfile` no es async): un consumidor async la llama con `asyncio.to_thread`.

    Args:
        destination: Ruta del ZIP (se crea o sobrescribe) o fichero binario abierto para escritura (no se cierra).
        site_dir: El `site/` construido con `SiteGenerator.generate(offline=True)`.
        project_name: Nombre del proyecto para `VER_SITIO.md`.
        on_progress: Recibe `ProgressEvent(operation="export")` como `write_project_zip`.
        cancel_token: Si se cancela, para entre dos bloques de 1 MiB.

    Raises:
        OfflineSiteError: El sitio no pasa `check_site_offline` (`problems` dice por qué): no se escribe nada.
        InvalidPathError: `destination` está dentro de `site_dir`.
        OperationCancelledError: Se canceló; si `destination` es una ruta, el fichero parcial se borra.
        FileNotFoundError: `site_dir` no existe.
    """
    root = Path(site_dir)
    report = check_site_offline(root)
    if not report.ok:
        raise OfflineSiteError(f"El sitio de '{root}' no se puede entregar sin conexión", problems=report.problems())
    members = sorted(
        ((path, f"{SITE_ZIP_FOLDER}/{path.relative_to(root).as_posix()}") for path in root.rglob("*") if path.is_file() and not path.is_symlink()),
        key=lambda member: member[1],
    )
    extras = _extras(project_name)
    if not isinstance(destination, str | os.PathLike):
        return _write_site_zip(destination, members, extras, on_progress, cancel_token)
    path = Path(destination)
    if path.resolve().is_relative_to(root.resolve()):
        raise InvalidPathError(f"El ZIP no puede escribirse dentro del sitio '{root}': se incluiría a sí mismo.")
    try:
        with path.open("wb") as stream:
            return _write_site_zip(stream, members, extras, on_progress, cancel_token)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class _HashingWriter:
    """Escritura en *streaming* que calcula el SHA-256. Sin `seek`: `zipfile` escribe siempre igual, se escriba en una
    ruta o en un fichero abierto (si no, un ZIP en un fichero con `seek` tendría otros bytes)."""

    def __init__(self, target: BinaryIO) -> None:
        self._target = target
        self.digest = hashlib.sha256()
        self.size = 0

    def write(self, data: bytes) -> int:
        self._target.write(data)
        self.digest.update(data)
        self.size += len(data)
        return len(data)

    def flush(self) -> None:
        self._target.flush()


def _write_site_zip(
    stream: BinaryIO,
    members: list[tuple[Path, str]],
    extras: list[tuple[str, bytes]],
    on_progress: ProgressCallback | None,
    cancel_token: CancelToken | None,
) -> SiteZipResult:
    writer = _HashingWriter(stream)
    progress = ExportProgress(on_progress, len(members) + len(extras), logger)
    progress.emit("started", 0)
    written = 0
    total = 0
    with zipfile.ZipFile(writer, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zip_file:  # type: ignore[call-overload]  # escritor sin seek (ver _HashingWriter)
        for arcname, data in extras:
            checkpoint(cancel_token)
            zip_file.writestr(_info(arcname), data)
            total += len(data)
            written += 1
            progress.emit("export", written, arcname)
        for source, arcname in members:
            total += _write_member(zip_file, source, arcname, cancel_token)
            written += 1
            progress.emit("export", written, arcname)
    progress.emit("done", written)
    return SiteZipResult(file_count=written, total_size_bytes=total, zip_size_bytes=writer.size, sha256=writer.digest.hexdigest())


def _write_member(zip_file: zipfile.ZipFile, source: Path, arcname: str, cancel_token: CancelToken | None) -> int:
    checkpoint(cancel_token)
    size = source.stat().st_size
    with source.open("rb") as origin, zip_file.open(_info(arcname), mode="w", force_zip64=size * 1.05 > _ZIP64_LIMIT) as target:
        while chunk := origin.read(_CHUNK_SIZE):
            checkpoint(cancel_token)
            target.write(chunk)
    return size


def _info(arcname: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(arcname, date_time=_FIXED_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = _FILE_MODE
    info.create_system = 3  # Unix: los mismos bytes en Windows y en Linux
    return info


def _extras(project_name: str) -> list[tuple[str, bytes]]:
    guide = string.Template((_TEMPLATES / "VER_SITIO.md").read_text(encoding="utf-8")).safe_substitute(project=project_name or "sin nombre")
    server = (_TEMPLATES / "start_server.py").read_bytes()
    return [("VER_SITIO.md", guide.encode("utf-8")), ("start_server.py", server.replace(b"\r\n", b"\n"))]


__all__ = ["SITE_ZIP_FOLDER", "OfflineIssue", "OfflineSiteReport", "SiteZipResult", "check_site_offline", "write_site_zip"]
