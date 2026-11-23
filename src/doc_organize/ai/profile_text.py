"""Texto del perfil del proyecto (2.0.0, G2): sus secciones en Markdown y tal como van en el prompt.

Vive en `ai/` porque lo usan los servicios de IA (`render_prompt_preview`); `context/project_profile.py`, que lee y
compone el perfil, lo reexporta.
"""

from doc_organize.core.models import PROFILE_MAX_CHARS, ProjectProfile

_TITLES = {"context": "Contexto del proyecto", "tie_breakers": "Reglas de desempate", "glossary": "Glosario", "examples": "Ejemplos"}


def render_profile_sections(profile: ProjectProfile) -> str:
    """Las secciones de `profile` en Markdown (lo que `parse_profile` vuelve a leer igual)."""
    blocks = []
    for field, title in _TITLES.items():
        if field == "examples":
            if profile.examples:
                blocks.append(f"## {title}\n\n" + "\n".join(f"- {example}" for example in profile.examples))
        else:
            value = getattr(profile, field)
            if value:
                blocks.append(f"## {title}\n\n{value}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def profile_prompt_text(profile: ProjectProfile | None) -> str:
    """El perfil tal como va en el prompt: secciones con su título, sin caracteres de control y con el tope de
    `PROFILE_MAX_CHARS` (S3)."""
    if profile is None or profile.is_empty:
        return ""
    text = render_profile_sections(profile)
    cleaned = "".join(char if char.isprintable() or char == "\n" else " " for char in text)
    return cleaned[:PROFILE_MAX_CHARS].strip()


__all__ = ["profile_prompt_text", "render_profile_sections"]
