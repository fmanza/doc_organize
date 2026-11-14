"""
Sitio de contexto de un proyecto con Zensical (L-8, G10; sustituye a MkDocs desde 0.13.0).
"""

import asyncio
import html
import importlib.util
import math
import os
import re
import shutil
import subprocess
import sys

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from doc_organize.context.reorganizer import Reorganizer, _remove_dir_or_link, resolve_organized_paths
from doc_organize.core.constants import SITE_FOLDER_NAME
from doc_organize.core.exceptions import InvalidPathError, SiteBuildError
from doc_organize.core.models import Context, Domain, DomainDocument, Project
from doc_organize.projects.layout import RESERVED_OUTPUT_FOLDER_NAMES, ProjectLayout, _folder_key, validate_output_folder_name
from doc_organize.utils.atomic_write import write_text_atomic
from doc_organize.utils.logging import get_logger
from doc_organize.utils.path_utils import ensure_no_symlinks

logger = get_logger(__name__)

_INDEX_MD_NAME = "index.md"
_CONFIG_HEADER = "# Generado por doc_organize (SiteGenerator): se reescribe en cada reconstrucción del contexto.\n"
#: Máximo de caracteres de la salida de error de `zensical build` que se incluyen en `SiteBuildError`.
_STDERR_TAIL = 2000


@dataclass(frozen=True)
class SiteResult:
    """Resultado de `SiteGenerator.generate`.

    Attributes:
        config_path (Path): `zensical.toml` escrito en la raíz del proyecto.
        index_path (Path): `index.md` escrito en la carpeta reorganizada.
        site_dir (Path): Carpeta del sitio (destino de `zensical build`).
        site_built (bool): Si se construyó el sitio (`build=True`). Un build que falla lanza `SiteBuildError`, nunca
            deja este campo en `False` en silencio.
        search_excluded (tuple[str, ...]): Páginas que se sacaron del buscador del sitio porque una de sus secciones
            supera el límite del índice de Zensical (ver `SiteGenerator`), como rutas relativas a la carpeta
            reorganizada (las del `nav`, `DomainDocument.organized_path`). Se siguen pudiendo navegar. Desde 1.4.0.
    """

    config_path: Path
    index_path: Path
    site_dir: Path
    site_built: bool
    search_excluded: tuple[str, ...] = ()


class SiteGenerator:
    """Genera `zensical.toml` + `index.md` para navegar el contenido ya reorganizado de un proyecto y, si se pide,
    construye el sitio con `zensical build`.

    Usa directamente `<output_folder_name>/` (ya poblada por `Reorganizer`) como `docs_dir` — no copia el contenido una
    segunda vez. El `nav` agrupa por dominio (y por tipo de material si el contexto usó un manifiesto de taxonomía);
    cada entrada apunta al `.md` ya copiado. `zensical.toml` vive en la raíz del proyecto porque Zensical exige que
    `docs_dir` y `site_dir` cuelguen de la carpeta de su configuración; también crea ahí su caché (`.cache/`).

    La configuración generada solo fija nombre, carpetas, `nav`, idioma y `font = false` (sin peticiones a Google
    Fonts): ni JavaScript propio, ni `extra_javascript`, ni plugins, ni extensiones Markdown distintas de las que
    Zensical activa por defecto.

    **Contenido no confiable**: los `.md` salen de documentos de terceros. Zensical (Python-Markdown) deja pasar tal
    cual el HTML incrustado en el Markdown (`<script>`, atributos `on*`, enlaces `javascript:`), igual que MkDocs; esta
    clase no lo filtra. Quien sirva el sitio debe aislarlo (otro origen, o una cabecera
    `Content-Security-Policy` restrictiva, p. ej. `sandbox`). Lo que esta clase escribe sí se escapa: Zensical inserta
    sin escapar las etiquetas del `nav` y `site_name` (títulos de documento, nombres de dominio y de proyecto), así que
    se escriben ya escapadas, igual que los nombres de dominio de `index.md`. Además, el tema por defecto carga Mermaid
    desde unpkg.com si una página tiene un bloque ```` ```mermaid ````. Ver `docs/functional/context.md`.

    **Límite del buscador** (desde 1.4.0): Zensical falla el build entero si una sección indexada (el texto entre dos
    títulos) tiene más posiciones de token de las que admite su índice, y ese máximo baja cuantas más secciones tiene
    el sitio (65 536 a partir de 8 193). Un documento convertido sin títulos (p. ej. una hoja de cálculo grande) es
    una sola sección. Antes de construir, `generate` estima ambos valores y añade `search: exclude: true` a la
    cabecera de las páginas que lo superarían: el sitio se construye, esas páginas se navegan pero no aparecen en el
    buscador, y se devuelven en `SiteResult.search_excluded`. Solo modifica la copia de la carpeta reorganizada.

    Requiere el extra `doc_organize[site]` (`zensical`) para construir; sin construir (`build=False`) no hace falta.

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio, tempfile
        >>> from datetime import UTC, datetime
        >>> async def main():
        ...     root = tempfile.mkdtemp()
        ...     project = Project(name="Demo", root_path=root, created_at=datetime.now(UTC).isoformat())
        ...     context = Context(project_name="Demo", created_at="2026-01-01", updated_at="2026-01-01")
        ...     result = await SiteGenerator().generate(project, context, build=False)
        ...     return result.config_path.name, result.site_built
        >>> asyncio.run(main())
        ('zensical.toml', False)
    """

    def __init__(self) -> None:
        self.logger = logger

    async def generate(
        self, project: Project, context: Context, *, build: bool = True, site_dir: Path | None = None, timeout: float | None = None
    ) -> SiteResult:
        """Escribe `zensical.toml` (raíz del proyecto) + `<output_folder_name>/index.md` y, con `build=True`, ejecuta
        `zensical build` hacia `site_dir`.

        Con o sin `build`, saca del buscador las páginas que superarían el límite del índice de Zensical (ver la clase
        y `SiteResult.search_excluded`), para que un `build_site` posterior no falle por ellas.

        Si el proyecto tiene un `mkdocs.yml` de antes de 0.13.0, se borra: el contexto pasa a Zensical al reconstruirlo.

        Args:
            project: Proyecto (su `root_path` es la raíz de la configuración).
            context: Contexto ya reorganizado.
            build: Si se construye el sitio tras escribir la configuración.
            site_dir: Carpeta del sitio (por defecto `<root_path>/site`; relativa a `root_path` si no es absoluta).
                Tiene que colgar de `root_path` (lo exige Zensical) y no puede ser ni estar dentro de la carpeta
                reorganizada ni de otra carpeta reservada del proyecto: Zensical vacía `site_dir` al construir.
            timeout: Segundos máximos para `zensical build` (`None`: sin límite).

        Returns:
            `SiteResult` con las rutas escritas y si se construyó el sitio.

        Raises:
            InvalidPathError: `site_dir` no es válido, o la carpeta reorganizada es o pasa por un enlace simbólico
                (antes de escribir nada).
            SiteBuildError: Falta `zensical`, el build falla o se pasa de `timeout` (la configuración ya está escrita).
        """
        layout = ProjectLayout.for_project(project)
        target_site_dir = await asyncio.to_thread(_resolve_site_dir, layout, site_dir, context.output_folder_name)
        output_root = layout.output_root / validate_output_folder_name(context.output_folder_name)
        await asyncio.to_thread(Reorganizer.check_output_root, output_root)
        await asyncio.to_thread(output_root.mkdir, parents=True, exist_ok=True)
        index_path = output_root / _INDEX_MD_NAME
        await asyncio.to_thread(write_text_atomic, index_path, _render_index(context))
        pages = [_INDEX_MD_NAME] + [path for domain in context.domains for path in resolve_organized_paths(domain, project.root_path)]
        search_excluded = await asyncio.to_thread(_exclude_oversized_from_search, output_root, pages)

        relative_site_dir = target_site_dir.relative_to(os.path.abspath(layout.output_root)).as_posix()
        config = self._build_config(project, context, relative_site_dir)
        await asyncio.to_thread(write_text_atomic, layout.site_config_file, _CONFIG_HEADER + _render_toml(config))
        await asyncio.to_thread(layout.legacy_mkdocs_config_file.unlink, missing_ok=True)

        if build:
            await self.build_site(project, timeout=timeout)
        return SiteResult(
            config_path=layout.site_config_file, index_path=index_path, site_dir=target_site_dir, site_built=build, search_excluded=search_excluded
        )

    async def build_site(self, project: Project, *, timeout: float | None = None) -> None:
        """Ejecuta `zensical build` sobre el `zensical.toml` ya escrito por `generate` (usa su `site_dir`).

        Raises:
            SiteBuildError: Falta `zensical` (extra `site`), el build termina con error o se pasa de `timeout`.
        """
        config_path = ProjectLayout.for_project(project).site_config_file
        command = await asyncio.to_thread(self._zensical_command)
        if command is None:
            reason = "zensical no está instalado (extra 'doc_organize[site]')"
            raise SiteBuildError(f"{reason}: '{config_path}' escrito, sin sitio navegable.", cause=reason)
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [*command, "build", "-f", str(config_path)],
                cwd=project.root_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            reason = f"'zensical build' superó el tiempo máximo ({timeout} s)"
            raise SiteBuildError(f"{reason} para '{project.name}'.", cause=reason) from exc
        except OSError as exc:
            reason = f"No se pudo ejecutar 'zensical build': {exc}"
            raise SiteBuildError(f"No se pudo ejecutar 'zensical build' para '{project.name}': {exc}", cause=reason) from exc
        if result.returncode != 0:
            output = (result.stderr.strip() or result.stdout.strip())[-_STDERR_TAIL:]
            # La causa va al final (tras el traceback): la última línea, para que no se pierda si el mensaje se recorta.
            cause = next((line.strip() for line in reversed(output.splitlines()) if line.strip()), None)
            raise SiteBuildError(
                f"'zensical build' falló para '{project.name}' (código {result.returncode}): {cause or 'sin salida'}",
                cause=cause,
                output_tail=output or None,
            )

    @staticmethod
    def _zensical_command() -> list[str] | None:
        """`python -m zensical` del mismo entorno si está instalado ahí; si no, `zensical` del `PATH`."""
        if importlib.util.find_spec("zensical") is not None:
            return [sys.executable, "-m", "zensical"]
        executable = shutil.which("zensical")
        return [executable] if executable is not None else None

    async def delete_site(self, project: Project, *, site_dir: Path | None = None) -> None:
        """Borra la configuración (`zensical.toml` y, si queda, el `mkdocs.yml` anterior), el sitio y la caché de
        Zensical (`.cache/`) de `project.root_path`, si existen.

        Usado al eliminar el contexto de un proyecto para volver al estado anterior a la primera construcción.

        Args:
            site_dir: La misma carpeta que se pasó a `generate` (por defecto `<root_path>/site`).

        Raises:
            InvalidPathError: `site_dir` no es válido (mismas reglas que en `generate`).
        """
        layout = ProjectLayout.for_project(project)
        target_site_dir = await asyncio.to_thread(_resolve_site_dir, layout, site_dir, None)
        await asyncio.to_thread(layout.site_config_file.unlink, missing_ok=True)
        await asyncio.to_thread(layout.legacy_mkdocs_config_file.unlink, missing_ok=True)
        for directory in (target_site_dir, layout.site_cache_dir):
            await asyncio.to_thread(_remove_dir_or_link, directory)

    def _build_config(self, project: Project, context: Context, site_dir: str) -> dict[str, Any]:
        nav: list[Any] = [{"Inicio": _INDEX_MD_NAME}]
        for domain in context.domains:
            domain_nav = self._build_domain_nav(domain, context.taxonomy_manifest_used, project.root_path)
            if domain_nav:
                nav.append({_label(domain.name): domain_nav})
        return {
            "project": {
                "site_name": _label(f"{project.name} — Documentación organizada"),
                "docs_dir": context.output_folder_name,
                "site_dir": site_dir,
                "nav": nav,
                "theme": {"language": "es", "font": False},
            }
        }

    def _build_domain_nav(self, domain: Domain, taxonomy_manifest_used: bool, project_root: str) -> list[Any]:
        """Nav de un dominio: lista plana de documentos (modo sin manifiesto), o agrupada
        por `material_type` dentro del dominio cuando `taxonomy_manifest_used` — mismo
        criterio de profundidad `dominio > tipo de material > documentos` que la carpeta
        física (`Reorganizer`): las dos usan `resolve_organized_paths` (L-8d), que desambigua colisiones de `stem`."""
        paths = {id(document): path for document, path in zip(domain.documents, resolve_organized_paths(domain, project_root), strict=True)}
        if not taxonomy_manifest_used:
            return [{_label(document.title): paths[id(document)]} for document in domain.documents]

        by_material_type: dict[str, list[DomainDocument]] = {}
        for document in domain.documents:
            material_type = document.material_type or "sin-clasificar"
            by_material_type.setdefault(material_type, []).append(document)

        nav: list[Any] = []
        for material_type, docs in by_material_type.items():
            entries = [{_label(document.title): paths[id(document)]} for document in docs]
            # `material_type_name` (nombre legible del manifiesto) es el mismo para todos los
            # documentos de este grupo -- comparten `material_type`, luego la misma entrada del
            # catálogo `TaxonomyManifest.material_types`. `None` para el placeholder "sin-clasificar"
            # (sin entrada en el manifiesto) o en modo sin manifiesto: cae al fallback derivado del slug.
            label = docs[0].material_type_name or material_type.replace("-", " ").title()
            nav.append({_label(label): entries})
        return nav


def _resolve_site_dir(layout: ProjectLayout, site_dir: Path | None, output_folder_name: str | None) -> Path:
    """Ruta absoluta de `site_dir`, validada (ver `SiteGenerator.generate`)."""
    root = Path(os.path.abspath(layout.output_root))
    candidate = layout.site_dir if site_dir is None else Path(site_dir)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.abspath(candidate))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise InvalidPathError(f"site_dir '{candidate}' tiene que estar dentro de la raíz del proyecto '{root}' (lo exige Zensical).") from exc
    if not relative.parts:
        raise InvalidPathError("site_dir no puede ser la raíz del proyecto: Zensical vacía site_dir al construir.")
    first = _folder_key(relative.parts[0])
    forbidden = {_folder_key(name) for name in RESERVED_OUTPUT_FOLDER_NAMES if name != SITE_FOLDER_NAME}
    if output_folder_name is not None:
        forbidden.add(_folder_key(output_folder_name))
    if first in forbidden:
        raise InvalidPathError(f"site_dir '{candidate}' no puede ser ni estar dentro de '{relative.parts[0]}': Zensical vacía site_dir al construir.")
    try:
        ensure_no_symlinks(candidate)
    except OSError as exc:
        raise InvalidPathError(f"site_dir '{candidate}' no puede ser ni pasar por un enlace simbólico.") from exc
    return candidate


def _render_index(context: Context) -> str:
    """`index.md` del sitio. Los nombres de dominio se escapan: Zensical no filtra el HTML incrustado."""
    lines = [f"# {_escape_markdown(context.project_name)} — Documentación organizada", ""]
    if not context.domains:
        lines.append("*No aplica: todavía no hay dominios clasificados.*")
    else:
        lines.extend(f"- **{_escape_markdown(domain.name)}** ({len(domain.documents)} documento(s))" for domain in context.domains)
    return "\n".join(lines) + "\n"


def _escape_markdown(text: str) -> str:
    return _label(" ".join(text.split()))


#: `<` y `>` pasan a sus formas de ancho completo, no a `&lt;`/`&gt;`: el tema mete el título de la página en `<title>`
#: con `striptags`, que deshace las entidades, y un `&lt;/title&gt;&lt;script&gt;` volvería a ser HTML ejecutable.
_ANGLE_BRACKETS = str.maketrans({"<": "＜", ">": "＞"})


def _label(text: str) -> str:
    """Texto no confiable (etiqueta del `nav`, `site_name`, título de `index.md`) listo para Zensical, que lo inserta
    en el HTML sin escapar: sin `<`/`>` (ver `_ANGLE_BRACKETS`) y con `&` y comillas escapados."""
    return html.escape(text.translate(_ANGLE_BRACKETS), quote=True)


# --- Límite del índice de búsqueda de Zensical ------------------------------------------------------------------------
# Comprobado con zensical 0.1.1 (no está documentado): el índice guarda cada posición de token junto con el número de
# entrada en 30 bits, así que con N entradas en el sitio una sección admite 2**(30 - ceil(log2 N)) posiciones (sin
# límite práctico hasta 8 192 entradas, 65 536 de 8 193 a 16 384, 32 768 hasta 32 768...). Una entrada es una página
# más cada título (cualquier nivel, también setext) fuera de bloques de código; el `#` con el que empieza una página se
# funde con ella. Si una sección supera su máximo, `zensical build` falla entero. Se estima con el separador por
# defecto del buscador de Zensical (`plugins.search.separator`, que esta clase no cambia) y con margen en ambos valores.

_SEARCH_POSITION_BITS = 30
_SEARCH_ITEMS_MARGIN = 1.1
_SEARCH_TOKENS_MARGIN = 0.9
_SEARCH_SEPARATOR = re.compile(r'[\s\-_,:!=\[\]()\\"`/]+|\.(?!\d)')
_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+|$)")
_SETEXT_UNDERLINE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
_CODE_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_TAG = re.compile(r"<[^>]+>")
_FRONT_MATTER_KEY = re.compile(r"^[A-Za-z_][\w-]*[ \t]*:")
_SEARCH_EXCLUDE_LINES = ("search:", "  exclude: true")


def _exclude_oversized_from_search(output_root: Path, pages: list[str]) -> tuple[str, ...]:
    """Añade `search: exclude: true` a las `pages` (rutas relativas a `output_root`) con una sección que superaría el
    límite del índice de Zensical; devuelve las excluidas (también las que ya lo estaban por una pasada anterior)."""
    profiles: dict[str, tuple[int, int]] = {}
    for page in dict.fromkeys(pages):
        text = _read_page(output_root, page)
        if text is not None:
            profiles[page] = _search_profile(text)
    if not profiles:
        return ()
    items = math.ceil(sum(page_items for page_items, _ in profiles.values()) * _SEARCH_ITEMS_MARGIN)
    max_positions = 2 ** (_SEARCH_POSITION_BITS - max(items - 1, 1).bit_length())
    threshold = int(max_positions * _SEARCH_TOKENS_MARGIN)

    excluded: list[str] = []
    for page, (_, biggest) in profiles.items():
        if biggest > threshold and _mark_excluded_from_search(output_root, page):
            logger.info(f"'{page}' sale del buscador del sitio: una sección de ~{biggest} palabras supera el límite ({max_positions})")
            excluded.append(page)
    return tuple(excluded)


def _mark_excluded_from_search(output_root: Path, page: str) -> bool:
    """Pone `search: exclude: true` en la cabecera de `page`; `False` si no se pudo (se registra por qué)."""
    text = _read_page(output_root, page)
    if text is None:
        return False
    new_text = _with_search_exclusion(text)
    if new_text is None:
        logger.warning(f"'{page}' supera el límite del buscador de Zensical y su cabecera ya define 'search': no se toca")
        return False
    if new_text == text:
        return True
    path = output_root.joinpath(*PurePosixPath(page).parts)
    try:
        ensure_no_symlinks(path.parent)  # mismo criterio que `Reorganizer`: nunca escribir a través de un enlace
        write_text_atomic(path, new_text, newline="")
    except OSError as exc:
        logger.warning(f"No se pudo sacar '{page}' del buscador ({exc}): el build puede fallar por el límite del índice")
        return False
    return True


def _read_page(output_root: Path, page: str) -> str | None:
    """Texto de la página tal cual (saltos de línea incluidos), o `None` si falta, es un enlace o no es UTF-8."""
    path = output_root.joinpath(*PurePosixPath(page).parts)
    try:
        if path.is_symlink() or not path.is_file():
            return None
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(f"No se pudo leer '{page}' para estimar su tamaño en el buscador: {exc}")
        return None


def _split_front_matter(lines: list[str]) -> tuple[list[str] | None, list[str]]:
    """(líneas de la cabecera sin los `---`, resto), o `(None, lines)` si no empieza por una cabecera válida: un `---`
    con cierre (`---`/`...`) y una primera línea `clave:` (un `---` suelto al principio es una línea horizontal)."""
    if not lines or lines[0].strip() != "---":
        return None, lines
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            inner = lines[1:index]
            first = next((line for line in inner if line.strip()), None)
            if first is not None and _FRONT_MATTER_KEY.match(first):
                return inner, lines[index + 1 :]
            return None, lines
    return None, lines


def _search_profile(text: str) -> tuple[int, int]:
    """(entradas del índice que aporta la página, palabras de su sección más larga), estimadas como Zensical."""
    _, lines = _split_front_matter(text.lstrip("\ufeff").splitlines())
    # El texto del título no cuenta en su sección (Zensical lo indexa aparte).
    sections: list[list[str]] = [[]]
    headings = 0
    starts_with_h1 = False
    fence: str | None = None
    previous_is_paragraph = False
    for line in lines:
        fence, is_code = _code_fence_state(line, fence)
        heading = None if is_code else _heading(line, previous_is_paragraph)
        if heading is None:
            previous_is_paragraph = not is_code and bool(line.strip()) and not line.lstrip().startswith("|")
            sections[-1].append(line)
            continue
        level, setext = heading
        if setext:
            sections[-1].pop()  # la línea anterior era el título
        if headings == 0 and not any(text_line.strip() for text_line in sections[0]):
            starts_with_h1 = level == 1
        headings += 1
        sections.append([])
        previous_is_paragraph = False
    items = 1 + headings - (1 if starts_with_h1 else 0)
    return items, max(_count_search_tokens("\n".join(section)) for section in sections)


def _code_fence_state(line: str, fence: str | None) -> tuple[str | None, bool]:
    """(valla abierta tras `line`, si `line` es parte de un bloque de código)."""
    if fence is not None:
        return (None if line.strip().startswith(fence) else fence), True
    if match := _CODE_FENCE.match(line):
        return match.group(1)[0] * 3, True
    return None, False


def _heading(line: str, previous_is_paragraph: bool) -> tuple[int, bool] | None:
    """(nivel, si es setext) si `line` es un título; un subrayado setext solo lo es tras una línea de párrafo."""
    if match := _ATX_HEADING.match(line):
        return len(match.group(1)), False
    if previous_is_paragraph and _SETEXT_UNDERLINE.match(line):
        return (1 if line.strip().startswith("=") else 2), True
    return None


def _count_search_tokens(text: str) -> int:
    text = _MARKDOWN_IMAGE.sub(" ", text)
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _HTML_TAG.sub(" ", text).replace("|", " ")
    return sum(1 for token in _SEARCH_SEPARATOR.split(text) if token)


def _with_search_exclusion(text: str) -> str | None:
    """`text` con `search: exclude: true` en la cabecera (creándola si no hay), el mismo `text` si ya la tiene, o
    `None` si la cabecera ya define `search` de otra forma (no se toca)."""
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    body = text[len(bom) :]
    newline = "\r\n" if "\r\n" in body[: body.find("\n") + 1 or len(body)] else "\n"
    lines = body.splitlines()
    front_matter, _ = _split_front_matter(lines)
    block = newline.join(_SEARCH_EXCLUDE_LINES)
    if front_matter is None:
        return f"{bom}---{newline}{block}{newline}---{newline}{newline}{body}"
    for index, line in enumerate(front_matter):
        if _FRONT_MATTER_KEY.match(line) and line.split(":", 1)[0].strip() == "search":
            ours = line.rstrip() == _SEARCH_EXCLUDE_LINES[0] and front_matter[index + 1 : index + 2] == [_SEARCH_EXCLUDE_LINES[1]]
            return text if ours else None
    opening_end = body.find("\n") + 1
    return f"{bom}{body[:opening_end]}{block}{newline}{body[opening_end:]}"


# --- TOML -------------------------------------------------------------------------------------------------------------
# Escritor mínimo (la biblioteca estándar solo lee TOML): tablas, cadenas, booleanos y listas de tablas en línea, lo
# que usa `_build_config`. Los títulos del `nav` salen de los documentos: cada cadena se escapa entera.

_TOML_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _toml_string(value: str) -> str:
    out = []
    for char in value:
        code = ord(char)
        if char in _TOML_ESCAPES:
            out.append(_TOML_ESCAPES[char])
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04X}")
        elif 0xD800 <= code <= 0xDFFF:
            out.append("�")  # suplente suelto: TOML (y UTF-8) no lo admiten
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def _toml_value(value: Any, indent: int) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        pad = "  " * (indent + 1)
        items = "".join(f"{pad}{_toml_value(item, indent + 1)},\n" for item in value)
        return f"[\n{items}{'  ' * indent}]"
    if isinstance(value, dict):
        pairs = ", ".join(f"{_toml_string(key)} = {_toml_value(item, indent)}" for key, item in value.items())
        return f"{{ {pairs} }}"
    raise TypeError(f"Tipo no soportado en la configuración del sitio: {type(value).__name__}")


def _render_toml(config: dict[str, Any], prefix: str = "") -> str:
    scalars = {key: value for key, value in config.items() if not isinstance(value, dict)}
    tables = {key: value for key, value in config.items() if isinstance(value, dict)}
    lines = [f"[{prefix}]\n"] if prefix and scalars else []
    lines.extend(f"{key} = {_toml_value(value, 0)}\n" for key, value in scalars.items())
    for key, table in tables.items():
        if lines:
            lines.append("\n")
        lines.append(_render_toml(table, f"{prefix}.{key}" if prefix else key))
    return "".join(lines)


__all__ = ["SiteGenerator", "SiteResult"]
