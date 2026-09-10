"""
Biblioteca de plantillas de manifiesto de taxonomía reutilizables entre proyectos.
"""

import asyncio
import re

from pathlib import Path

import yaml

from pydantic import ValidationError

from doc_organize.core.exceptions import TaxonomyTemplateError
from doc_organize.core.models import TaxonomyManifest, TaxonomyTemplateSummary
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

TEMPLATE_FILE_EXTENSION = ".md"
_FRONT_MATTER_DELIMITER = "---"

#: Fuera de cualquier `project.root_path` (cada proyecto puede vivir en una ubicación
#: distinta elegida por el usuario) — mismo criterio que `ProjectRegistry`/`AuthStore`
#: (`~/.doc_organize/projects.json`, `~/.doc_organize/auth.db`): una única biblioteca
#: compartida por toda la instalación de doc_organize, no por proyecto ni por tenant.
_DEFAULT_TEMPLATES_DIR = Path.home() / ".doc_organize" / "taxonomy_templates"

#: Plantillas de ejemplo distribuidas con el propio paquete (ver `MANIFEST.in`) — de
#: solo lectura, nunca escritas por la aplicación. Una plantilla de usuario con el
#: mismo nombre en `_DEFAULT_TEMPLATES_DIR` tiene prioridad (ver `TaxonomyTemplateRegistry.load_template`).
_BUILTIN_TEMPLATES_DIR = Path(__file__).parent / "taxonomy_templates_builtin"

#: Un nombre de plantilla llega desde un payload de API y se usa para construir una
#: ruta de fichero (`<templates_dir>/<name>.md`) — se valida contra este patrón ANTES
#: de tocar el filesystem, para que `../otra-cosa` o rutas absolutas nunca lleguen a
#: `Path.__truediv__` (path traversal fuera de las dos carpetas de plantillas).
_TEMPLATE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


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
    `doc_organize` (de solo lectura). Una plantilla de usuario con el mismo nombre
    que una empaquetada tiene prioridad — nunca al revés.

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

    def __init__(self, templates_dir: str | Path = _DEFAULT_TEMPLATES_DIR) -> None:
        self.templates_dir = Path(templates_dir)

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
        summaries: dict[str, TaxonomyTemplateSummary] = {}
        for directory in (_BUILTIN_TEMPLATES_DIR, self.templates_dir):
            for name in await asyncio.to_thread(self._list_template_names, directory):
                try:
                    manifest = await self._load_from_dir(directory, name)
                except TaxonomyTemplateError:
                    continue
                summaries[name] = TaxonomyTemplateSummary(name=name, title=manifest.title, description=manifest.description)
        return [summaries[name] for name in sorted(summaries)]

    @staticmethod
    def _list_template_names(directory: Path) -> list[str]:
        if not directory.is_dir():
            return []
        # Mismo patrón que `load_template()`: un fichero cuyo nombre NO es un slug
        # válido (mayúsculas, espacios...) se omite del listado en vez de mostrarse
        # y luego rechazarse al intentar cargarlo por ese mismo nombre (AUDIT_CODE).
        return [path.stem for path in directory.glob(f"*{TEMPLATE_FILE_EXTENSION}") if path.is_file() and _TEMPLATE_NAME_PATTERN.match(path.stem)]

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
        if not _TEMPLATE_NAME_PATTERN.match(name):
            raise TaxonomyTemplateError(f"'{name}' no es un nombre de plantilla válido — solo minúsculas, dígitos y guiones (p. ej. 'sgi-iso27001').")
        user_template_path = self.templates_dir / f"{name}{TEMPLATE_FILE_EXTENSION}"
        if await asyncio.to_thread(user_template_path.is_file):
            return await self._load_from_dir(self.templates_dir, name)
        manifest = await self._load_from_dir(_BUILTIN_TEMPLATES_DIR, name)
        logger.info(f"Plantilla de taxonomía '{name}' cargada de la biblioteca empaquetada (sin override de usuario en '{self.templates_dir}')")
        return manifest

    async def _load_from_dir(self, directory: Path, name: str) -> TaxonomyManifest:
        template_path = directory / f"{name}{TEMPLATE_FILE_EXTENSION}"
        if not await asyncio.to_thread(template_path.is_file):
            raise TaxonomyTemplateError(f"No existe ninguna plantilla de taxonomía llamada '{name}' en '{directory}'.")
        raw = await asyncio.to_thread(template_path.read_text, encoding="utf-8")
        front_matter = _extract_front_matter(raw, template_path)
        return _parse_front_matter(front_matter, template_path)


# Duplicado intencional de `_extract_front_matter`/`_parse_front_matter`
# (`taxonomy_manifest.py`, privadas a su módulo) — política "prohibido refactorizar"
# de `/new-feature`, mismo criterio que `ConfirmedActionRequest`/`_acquire_operation_lock`
# en `web/routes/context.py`.
def _extract_front_matter(raw: str, template_path: Path) -> str:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != _FRONT_MATTER_DELIMITER:
        raise TaxonomyTemplateError(f"'{template_path}' debe empezar con el delimitador de front matter YAML ('---').")
    try:
        closing_index = lines.index(_FRONT_MATTER_DELIMITER, 1)
    except ValueError as exc:
        raise TaxonomyTemplateError(f"'{template_path}' no cierra el front matter YAML (falta un segundo '---').") from exc
    return "\n".join(lines[1:closing_index])


def _parse_front_matter(front_matter: str, template_path: Path) -> TaxonomyManifest:
    try:
        payload = yaml.safe_load(front_matter)
    except yaml.YAMLError as exc:
        raise TaxonomyTemplateError(f"El front matter YAML de '{template_path}' no es válido: {exc}") from exc
    if not isinstance(payload, dict):
        raise TaxonomyTemplateError(f"El front matter de '{template_path}' debe ser un mapeo YAML con 'domains'/'material_types'.")
    try:
        return TaxonomyManifest.model_validate(payload)
    except ValidationError as exc:
        raise TaxonomyTemplateError(f"El front matter de '{template_path}' no cumple el schema de taxonomía: {exc}") from exc


__all__ = ["TaxonomyTemplateRegistry"]
