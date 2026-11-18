"""
Prompts del cliente único de IA (2.0.0, G1): uno por tarea, empaquetados y sustituibles por proyecto.

Cada prompt es un `.md` con front matter (`id`, `version`) y dos secciones, `## system` y `## user`, con marcadores
`$nombre` (`string.Template`). El orden de las secciones da un **prefijo estable** (instrucciones, catálogo y perfil en
`system`; ejemplos y documento en `user`) que el proveedor puede cachear entre documentos.

Un proyecto puede sustituir el de una tarea con `<raíz>/.doc_organize/prompts/<tarea>.md`. La procedencia (id, versión,
origen y SHA-256 del texto) queda en `Context.ai_provenance`, para saber con qué prompt se clasificó cada contexto.
"""

import hashlib
import re

from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Literal

import yaml

from doc_organize.core.exceptions import AiConfigurationError
from doc_organize.core.models import AI_TASKS, AiTask, PromptProvenance

_BUILTIN_DIR = Path(__file__).parent
#: Carpeta de los prompts de un proyecto, relativa a su raíz.
PROJECT_PROMPTS_DIR = Path(".doc_organize") / "prompts"
_SECTION = re.compile(r"^## (system|user)\s*$", re.MULTILINE)

PromptSource = Literal["builtin", "project"]


@dataclass(frozen=True)
class PromptTemplate:
    """Un prompt de una tarea, listo para rellenar.

    Attributes:
        task (AiTask): Tarea.
        prompt_id (str): `id` del front matter.
        version (str): `version` del front matter.
        source (str): `builtin` (empaquetado) o `project` (del proyecto).
        sha256 (str): Huella del texto completo del fichero.
        system (Template): Sección `## system`.
        user (Template): Sección `## user`.
    """

    task: AiTask
    prompt_id: str
    version: str
    source: PromptSource
    sha256: str
    system: Template
    user: Template

    def render(self, **values: object) -> list[dict[str, str]]:
        """Mensajes `system` y `user` con los marcadores sustituidos.

        Los valores se insertan tal cual: un `$` dentro del texto de un documento no se interpreta.

        Raises:
            AiConfigurationError: El prompt usa un marcador que no se ha dado (p. ej. un prompt de proyecto mal escrito).
        """
        texts = {key: str(value) for key, value in values.items()}
        try:
            return [
                {"role": "system", "content": self.system.substitute(texts).strip()},
                {"role": "user", "content": self.user.substitute(texts).strip()},
            ]
        except (KeyError, ValueError) as exc:
            raise AiConfigurationError(f"El prompt '{self.prompt_id}' ({self.source}) usa un marcador que no existe: {exc}") from exc

    def provenance(self, model: str) -> PromptProvenance:
        """Procedencia para `Context.ai_provenance`."""
        return PromptProvenance(task=self.task, prompt_id=self.prompt_id, version=self.version, source=self.source, sha256=self.sha256, model=model)


class PromptRegistry:
    """Los prompts de cada tarea: el del proyecto si existe, si no el empaquetado.

    Args:
        project_root: Raíz del proyecto, para buscar `<raíz>/.doc_organize/prompts/<tarea>.md`; `None` = solo los
            empaquetados.

    Example:
        >>> registry = PromptRegistry()
        >>> template = registry.get("classify")
        >>> (template.prompt_id, template.source)
        ('classify', 'builtin')
        >>> template.render(catalog="Eje domains: calidad", title="T", content="texto")[1]["content"]
        'Título: T\\nContenido: texto'
    """

    def __init__(self, project_root: Path | str | None = None) -> None:
        self.project_dir = Path(project_root) / PROJECT_PROMPTS_DIR if project_root is not None else None
        self._cache: dict[AiTask, PromptTemplate] = {}

    def get(self, task: AiTask) -> PromptTemplate:
        """El prompt de `task`.

        Raises:
            AiConfigurationError: La tarea no existe, no tiene prompt o el fichero no tiene el formato esperado.
        """
        if task not in AI_TASKS:
            raise AiConfigurationError(f"Tarea de IA desconocida: '{task}'")
        if task not in self._cache:
            self._cache[task] = self._load(task)
        return self._cache[task]

    def _load(self, task: AiTask) -> PromptTemplate:
        if self.project_dir is not None:
            candidate = self.project_dir / f"{task}.md"
            if candidate.is_file() and not candidate.is_symlink():
                return _parse(task, candidate.read_text(encoding="utf-8"), "project")
        builtin = _BUILTIN_DIR / f"{task}.md"
        if not builtin.is_file():
            raise AiConfigurationError(f"La tarea '{task}' no tiene prompt")
        return _parse(task, builtin.read_text(encoding="utf-8"), "builtin")


def _parse(task: AiTask, text: str, source: PromptSource) -> PromptTemplate:
    normalized = text.replace("\r\n", "\n")
    parts = normalized.split("---\n", 2)
    if len(parts) != 3 or parts[0].strip():
        raise AiConfigurationError(f"El prompt de '{task}' ({source}) debe empezar con un front matter entre '---'")
    meta = yaml.safe_load(parts[1]) or {}
    if not isinstance(meta, dict) or not meta.get("id") or meta.get("version") is None:
        raise AiConfigurationError(f"El front matter del prompt de '{task}' ({source}) necesita 'id' y 'version'")
    body = parts[2]
    sections = _SECTION.split(body)
    found = dict(zip(sections[1::2], sections[2::2], strict=True))
    if set(found) != {"system", "user"}:
        raise AiConfigurationError(f"El prompt de '{task}' ({source}) necesita las secciones '## system' y '## user'")
    return PromptTemplate(
        task=task,
        prompt_id=str(meta["id"]),
        version=str(meta["version"]),
        source=source,
        sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        system=Template(found["system"]),
        user=Template(found["user"]),
    )


__all__ = ["PROJECT_PROMPTS_DIR", "PromptRegistry", "PromptTemplate"]
