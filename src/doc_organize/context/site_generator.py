"""
Sitio de contexto de un proyecto con Zensical (L-8, G10; sustituye a MkDocs desde 0.13.0).
"""

import asyncio
import html
import importlib.util
import os
import shutil
import subprocess
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from doc_organize.context.reorganizer import Reorganizer, _remove_dir_or_link, resolve_document_slug_parts
from doc_organize.core.constants import SITE_FOLDER_NAME
from doc_organize.core.exceptions import InvalidPathError, SiteBuildError
from doc_organize.core.models import Context, Domain, DomainDocument, Project
from doc_organize.projects.layout import RESERVED_OUTPUT_FOLDER_NAMES, ProjectLayout, _folder_key
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
    """

    config_path: Path
    index_path: Path
    site_dir: Path
    site_built: bool


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
        output_root = layout.output_root / context.output_folder_name
        await asyncio.to_thread(Reorganizer.check_output_root, output_root)
        await asyncio.to_thread(output_root.mkdir, parents=True, exist_ok=True)
        index_path = output_root / _INDEX_MD_NAME
        await asyncio.to_thread(_write_text_atomic, index_path, _render_index(context))

        relative_site_dir = target_site_dir.relative_to(os.path.abspath(layout.output_root)).as_posix()
        config = self._build_config(project, context, relative_site_dir)
        await asyncio.to_thread(_write_text_atomic, layout.site_config_file, _CONFIG_HEADER + _render_toml(config))
        await asyncio.to_thread(layout.legacy_mkdocs_config_file.unlink, missing_ok=True)

        if build:
            await self.build_site(project, timeout=timeout)
        return SiteResult(config_path=layout.site_config_file, index_path=index_path, site_dir=target_site_dir, site_built=build)

    async def build_site(self, project: Project, *, timeout: float | None = None) -> None:
        """Ejecuta `zensical build` sobre el `zensical.toml` ya escrito por `generate` (usa su `site_dir`).

        Raises:
            SiteBuildError: Falta `zensical` (extra `site`), el build termina con error o se pasa de `timeout`.
        """
        config_path = ProjectLayout.for_project(project).site_config_file
        command = await asyncio.to_thread(self._zensical_command)
        if command is None:
            raise SiteBuildError(f"zensical no está instalado (extra 'doc_organize[site]'): '{config_path}' escrito, sin sitio navegable.")
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
            raise SiteBuildError(f"'zensical build' superó el tiempo máximo ({timeout} s) para '{project.name}'.") from exc
        except OSError as exc:
            raise SiteBuildError(f"No se pudo ejecutar 'zensical build' para '{project.name}': {exc}") from exc
        if result.returncode != 0:
            output = (result.stderr.strip() or result.stdout.strip())[-_STDERR_TAIL:]
            raise SiteBuildError(f"'zensical build' falló para '{project.name}' (código {result.returncode}): {output}")

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
            domain_nav = self._build_domain_nav(domain, context.taxonomy_manifest_used)
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

    def _build_domain_nav(self, domain: Domain, taxonomy_manifest_used: bool) -> list[Any]:
        """Nav de un dominio: lista plana de documentos (modo sin manifiesto), o agrupada
        por `material_type` dentro del dominio cuando `taxonomy_manifest_used` — mismo
        criterio de profundidad `dominio > tipo de material > documentos` que la carpeta
        física (`Reorganizer`, vía `resolve_document_slug_parts`)."""
        if not taxonomy_manifest_used:
            return [{_label(document.title): self._relative_doc_path(domain, document)} for document in domain.documents]

        by_material_type: dict[str, list[DomainDocument]] = {}
        for document in domain.documents:
            material_type = document.material_type or "sin-clasificar"
            by_material_type.setdefault(material_type, []).append(document)

        nav: list[Any] = []
        for material_type, docs in by_material_type.items():
            entries = [{_label(document.title): self._relative_doc_path(domain, document)} for document in docs]
            # `material_type_name` (nombre legible del manifiesto) es el mismo para todos los
            # documentos de este grupo -- comparten `material_type`, luego la misma entrada del
            # catálogo `TaxonomyManifest.material_types`. `None` para el placeholder "sin-clasificar"
            # (sin entrada en el manifiesto) o en modo sin manifiesto: cae al fallback derivado del slug.
            label = docs[0].material_type_name or material_type.replace("-", " ").title()
            nav.append({_label(label): entries})
        return nav

    @staticmethod
    def _relative_doc_path(domain: Domain, document: DomainDocument) -> str:
        # Con "/" literales, nunca `Path` (en Windows uniría con "\\", rompiendo
        # el `nav`) — misma fórmula que usa `Reorganizer` para el destino real
        # en disco, via `resolve_document_slug_parts` compartida.
        document_type, stem = resolve_document_slug_parts(document)
        return f"{domain.slug}/{document_type}/{stem}/{stem}.md"


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


def _write_text_atomic(path: Path, content: str) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


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
