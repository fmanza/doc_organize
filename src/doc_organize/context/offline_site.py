"""
Sitio del contexto sin conexión (2.0.0, F3): comprobación antes de entregarlo.

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

Example:
    ```python
    result = await SiteGenerator().generate(project, context, offline=True)
    report = check_site_offline(result.site_dir)
    if not report.ok:
        print(report.problems())
    ```
"""

from __future__ import annotations

import re

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, Field

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


__all__ = ["OfflineIssue", "OfflineSiteReport", "check_site_offline"]
