"""
Biblioteca de plantillas de manifiesto de taxonomía reutilizables entre proyectos.

El formato de fichero (parsear/renderizar) y las plantillas empaquetadas viven en
`doc_organize.context.taxonomy_templates` (L-8c), sin carpeta de usuario; este registro
añade la biblioteca de usuario en disco encima.
"""

import asyncio
import os

from pathlib import Path

from doc_organize.context.taxonomy_templates import (
    TEMPLATE_FILE_EXTENSION,
    list_builtin_templates,
    list_template_names,
    load_builtin_template,
    parse_taxonomy_template,
    render_taxonomy_template,
    template_file,
)
from doc_organize.core.exceptions import TaxonomyTemplateError
from doc_organize.core.models import TaxonomyManifest, TaxonomyTemplateSummary
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)


def default_templates_dir() -> Path:
    """Carpeta de plantillas de usuario por defecto: `~/.doc_organize/taxonomy_templates/`.

    Fuera de cualquier `project.root_path` (cada proyecto puede vivir en una ubicación
    distinta elegida por el usuario) — mismo criterio que `ProjectRegistry`/`AuthStore`
    (`~/.doc_organize/projects.json`, `~/.doc_organize/auth.db`): una única biblioteca
    compartida por toda la instalación de doc_organize, no por proyecto ni por tenant.
    Se calcula al crear un registro sin carpeta, no al importar el módulo (L-8c).
    """
    return Path.home() / ".doc_organize" / "taxonomy_templates"


class TaxonomyTemplateRegistry:
    """Biblioteca de plantillas de manifiesto de taxonomía, compartida entre proyectos.

    Cada plantilla es un fichero `<nombre>.md` con el mismo formato que el
    `taxonomy_manifest.md` de un proyecto (front matter YAML + prosa libre, ver
    `doc_organize.context.taxonomy_manifest`): permite reutilizar un mismo catálogo de
    dominios/tipos de material (p. ej. "sgi-iso27001", "calidad") en varios proyectos
    sin copiar y pegar el fichero.

    Busca primero en `templates_dir` (por defecto `~/.doc_organize/taxonomy_templates/`,
    fuera de cualquier `project.root_path` — gestionado por el usuario) y, si no
    encuentra el nombre ahí, en las plantillas de ejemplo empaquetadas con
    `doc_organize` (de solo lectura, `load_builtin_template`). Una plantilla de usuario
    con el mismo nombre que una empaquetada tiene prioridad — nunca al revés.

    Un proyecto que quiere usar una plantilla la referencia por nombre en la
    petición de construcción de contexto (`BuildContextRequest.taxonomy_template_name`,
    ver `web/routes/context.py`); si el proyecto además tiene su propio
    `taxonomy_manifest.md`, ese fichero local siempre gana — es el "override" sin
    tocar la plantilla compartida, sin necesidad de ningún mecanismo nuevo.

    Attributes:
        templates_dir (Path): Carpeta de plantillas de usuario.

    Example:
        >>> import asyncio, tempfile
        >>> from pathlib import Path
        >>> async def main():
        ...     templates_dir = Path(tempfile.mkdtemp())
        ...     (templates_dir / "calidad.md").write_text(
        ...         "---\\ndomains:\\n  - slug: calidad\\n    name: Calidad\\n"
        ...         "material_types:\\n  - slug: procedimiento\\n    name: Procedimiento\\n---\\n",
        ...         encoding="utf-8",
        ...     )
        ...     registry = TaxonomyTemplateRegistry(templates_dir)
        ...     manifest = await registry.load_template("calidad")
        ...     return manifest.domains[0].slug
        >>> asyncio.run(main())
        'calidad'
    """

    def __init__(self, templates_dir: str | Path | None = None) -> None:
        self.templates_dir = Path(templates_dir) if templates_dir is not None else default_templates_dir()

    async def list_templates(self) -> list[TaxonomyTemplateSummary]:
        """Lista las plantillas disponibles (usuario + empaquetadas), sin duplicar nombres.

        Una plantilla de usuario oculta a la empaquetada del mismo nombre — mismo
        criterio de precedencia que `load_template()`. Un fichero de plantilla con
        front matter inválido se omite del listado (con aviso en el log) en vez de
        romper el listado completo: es una vista de solo lectura para poblar un
        selector, no una validación exhaustiva.

        Returns:
            Resúmenes ordenados por `name`, para un listado determinista.
        """
        summaries = {summary.name: summary for summary in await asyncio.to_thread(list_builtin_templates)}
        for name in await asyncio.to_thread(list_template_names, self.templates_dir):
            try:
                manifest = await self._load_from_dir(self.templates_dir, name)
            except TaxonomyTemplateError:
                continue
            summaries[name] = TaxonomyTemplateSummary(name=name, title=manifest.title, description=manifest.description)
        return [summaries[name] for name in sorted(summaries)]

    async def load_template(self, name: str) -> TaxonomyManifest:
        """Carga la plantilla `name`: primero de `templates_dir` (usuario), si no de
        las plantillas empaquetadas.

        Args:
            name: Nombre de la plantilla (slug del fichero, sin extensión).

        Returns:
            El `TaxonomyManifest` ya validado.

        Raises:
            TaxonomyTemplateError: `name` no es un slug válido; no existe ninguna
                plantilla con ese nombre en ninguna de las dos ubicaciones; o SÍ existe
                una plantilla de usuario con ese nombre pero su front matter es
                inválido — en ese caso el error se propaga tal cual, sin caer en
                silencio a la empaquetada (que enmascararía un fichero de usuario roto
                detrás de un mensaje de "no existe" que no ayuda a arreglarlo).
        """
        user_template_path = template_file(self.templates_dir, name)
        if await asyncio.to_thread(user_template_path.is_file):
            return await self._load_from_dir(self.templates_dir, name)
        manifest = await asyncio.to_thread(load_builtin_template, name)
        logger.info(f"Plantilla de taxonomía '{name}' cargada de la biblioteca empaquetada (sin override de usuario en '{self.templates_dir}')")
        return manifest

    async def _load_from_dir(self, directory: Path, name: str) -> TaxonomyManifest:
        template_path = template_file(directory, name)
        if not await asyncio.to_thread(template_path.is_file):
            raise TaxonomyTemplateError(f"No existe ninguna plantilla de taxonomía llamada '{name}' en '{directory}'.")
        raw = await asyncio.to_thread(template_path.read_text, encoding="utf-8")
        return parse_taxonomy_template(raw, source=str(template_path))

    async def save_template(self, name: str, manifest: TaxonomyManifest) -> None:
        """Crea o sobrescribe la plantilla `name` en `templates_dir` (biblioteca de usuario).

        Nunca escribe en las plantillas empaquetadas (de solo lectura) -- una plantilla
        guardada aquí ya tiene precedencia sobre una empaquetada del mismo nombre
        (`load_template()`), así que "editar" una empaquetada equivale a crear un
        override de usuario con su mismo nombre, nunca a tocar el fichero empaquetado.

        Args:
            name: Slug de la plantilla (sin extensión).
            manifest: Catálogo a guardar (`render_taxonomy_template`) -- `title`/`description`
                (si se rellenan) se usan para el listado (`list_templates()`);
                `domains`/`material_types` son el catálogo cerrado en sí.

        Raises:
            TaxonomyTemplateError: `name` no es un slug válido.
        """
        template_path = template_file(self.templates_dir, name)
        content = render_taxonomy_template(manifest)

        await asyncio.to_thread(self.templates_dir.mkdir, parents=True, exist_ok=True)
        tmp_path = template_path.with_suffix(".tmp")
        await asyncio.to_thread(tmp_path.write_text, content, encoding="utf-8")
        await asyncio.to_thread(os.replace, tmp_path, template_path)
        logger.info(f"Plantilla de taxonomía '{name}' guardada en '{template_path}'")

    async def delete_template(self, name: str) -> None:
        """Borra la plantilla de usuario `name` de `templates_dir`.

        Nunca borra una plantilla empaquetada -- si `name` solo existe ahí, no hay nada
        que hacer en `templates_dir` y se levanta el mismo error que "no existe" (desde
        fuera, una empaquetada sin override de usuario no es borrable, igual que no lo
        es editable sin crear un override).

        Raises:
            TaxonomyTemplateError: `name` no es un slug válido, o no existe ninguna
                plantilla de usuario llamada `name` en `templates_dir`.
        """
        template_path = template_file(self.templates_dir, name)
        if not await asyncio.to_thread(template_path.is_file):
            raise TaxonomyTemplateError(f"No existe ninguna plantilla de usuario llamada '{name}' en '{self.templates_dir}' que se pueda eliminar.")
        await asyncio.to_thread(template_path.unlink)
        logger.info(f"Plantilla de taxonomía '{name}' eliminada de '{template_path}'")


__all__ = ["TEMPLATE_FILE_EXTENSION", "TaxonomyTemplateRegistry", "default_templates_dir"]
