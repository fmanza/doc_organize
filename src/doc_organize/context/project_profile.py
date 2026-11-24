"""
Perfil del proyecto (2.0.0, G2): secciones del cuerpo del manifiesto o la plantilla, más las del proyecto.

```markdown
## Contexto del proyecto
Documentación del SGSI y del sistema de calidad de una consultora.

## Reglas de desempate
- Una norma publicada (ISO, CCN, BOE) es referencial normativo aunque hable de procedimientos.

## Glosario
- SoA: declaración de aplicabilidad.

## Ejemplos
- «Política de seguridad de la información» → gobernanza-liderazgo, politica
```

Los títulos se reconocen sin distinguir mayúsculas ni acentos. El resto del cuerpo (tablas, diagramas, explicaciones)
no se envía al modelo. El proyecto puede añadir su propio perfil en `<raíz>/.doc_organize/profile.md` con las mismas
secciones: se añade detrás del de la plantilla (D11).
"""

import re

from pathlib import Path

from doc_organize.ai.profile_text import profile_prompt_text, render_profile_sections
from doc_organize.context.axis_rules import fold
from doc_organize.core.models import PROFILE_MAX_EXAMPLES, ProjectProfile

#: Fichero del perfil propio de un proyecto, relativo a su raíz.
PROJECT_PROFILE_FILE = Path(".doc_organize") / "profile.md"

_SECTIONS = {
    "contexto del proyecto": "context",
    "reglas de desempate": "tie_breakers",
    "glosario": "glossary",
    "ejemplos": "examples",
}
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$")


def parse_profile(body: str) -> ProjectProfile | None:
    """El perfil de las secciones de `body` (el cuerpo Markdown tras el front matter), o `None` si no tiene ninguna.

    Example:
        >>> profile = parse_profile("# Taxonomía\\n\\n## Contexto del proyecto\\nSGSI.\\n\\n## Ejemplos\\n- Política → gobernanza\\n- Acta → registro\\n")
        >>> profile.context, profile.examples
        ('SGSI.', ['Política → gobernanza', 'Acta → registro'])
    """
    found: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.replace("\r\n", "\n").split("\n"):
        heading = _HEADING.match(line)
        if heading:
            current = _SECTIONS.get(fold(heading.group(1)))
            if current is not None:
                found.setdefault(current, [])
            continue
        if current is not None:
            found[current].append(line)
    if not found:
        return None
    examples = []
    for line in found.get("examples", []):
        item = _LIST_ITEM.match(line)
        if item:
            examples.append(_clean(item.group(1)))
    return ProjectProfile(
        context=_text(found.get("context")),
        tie_breakers=_text(found.get("tie_breakers")),
        glossary=_text(found.get("glossary")),
        examples=[example for example in examples if example][:PROFILE_MAX_EXAMPLES],
    )


def load_project_profile(project_root: Path | str) -> ProjectProfile | None:
    """El perfil propio del proyecto (`<raíz>/.doc_organize/profile.md`), o `None` si no lo tiene o no se puede leer."""
    path = Path(project_root) / PROJECT_PROFILE_FILE
    try:
        if path.is_symlink() or not path.is_file():
            return None
        return parse_profile(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def compose_profile(template: ProjectProfile | None, project_root: Path | str | None) -> ProjectProfile | None:
    """El perfil que se usa: el de la plantilla o el manifiesto con el del proyecto añadido detrás (D11)."""
    project = load_project_profile(project_root) if project_root is not None else None
    if template is None:
        return project
    return template.merged(project)


def compose_profile_text(template: ProjectProfile | None, project_text: str | None) -> ProjectProfile | None:
    """Como `compose_profile`, con el perfil del proyecto dado como texto (el `profile.md` que se está editando, antes
    de guardarlo): para la vista previa de un editor.

    Example:
        >>> template = ProjectProfile(context="Sistema de gestión de calidad")
        >>> profile = compose_profile_text(template, "## Glosario\\n\\nSGC: sistema de gestión de calidad")
        >>> (profile.context, profile.glossary)
        ('Sistema de gestión de calidad', 'SGC: sistema de gestión de calidad')
    """
    project = parse_profile(project_text) if project_text else None
    if template is None:
        return project
    return template.merged(project)


def _text(lines: list[str] | None) -> str | None:
    if not lines:
        return None
    text = "\n".join(line.rstrip() for line in lines).strip()
    return text or None


def _clean(text: str) -> str:
    return " ".join(text.split())


__all__ = [
    "PROJECT_PROFILE_FILE",
    "compose_profile",
    "compose_profile_text",
    "load_project_profile",
    "parse_profile",
    "profile_prompt_text",
    "render_profile_sections",
]
