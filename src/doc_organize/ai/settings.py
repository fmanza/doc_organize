"""
Configuración del cliente único de IA desde variables de entorno (2.0.0, G1; D15 y U17).

Variables de 2.0 (todas con el prefijo `DOC_ORGANIZE_LITELLM_`):

| Variable | Para qué |
|---|---|
| `BASE_URL` | URL del LiteLLM Proxy (la misma que ya usaba `LiteLLMUsageClient`) |
| `VIRTUAL_KEY` | Clave general |
| `MODEL_<TAREA>` | Modelo de cada tarea (`CLASSIFY`, `ENRICH`, `TAXONOMY_DESIGN`, `AGENT`, `EMBED`); si falta, el alias recomendado `doc-organize-<tarea>` |
| `VIRTUAL_KEY_<TAREA>` | Clave propia de una tarea (opcional, D12) |

Las variables de 1.x (`DOC_ORGANIZE_LITELLM_<CLIENTE>_BASE_URL`, `_VIRTUAL_KEY`, `_MODEL` de clasificación, clasificación
por manifiesto, enriquecimiento y borrador) **ya no se leen**: si alguna está definida, `settings_from_env` lanza
`AiConfigurationError` con la equivalencia, para que una actualización sin reconfigurar no deje la IA desactivada en
silencio.
"""

import os

from collections.abc import Mapping

from doc_organize.core.exceptions import AiConfigurationError
from doc_organize.core.models import AI_TASKS, AiSettings, TaskSettings

_PREFIX = "DOC_ORGANIZE_LITELLM_"
ENV_BASE_URL = f"{_PREFIX}BASE_URL"
ENV_VIRTUAL_KEY = f"{_PREFIX}VIRTUAL_KEY"

#: Cliente de 1.x → tarea de 2.0.
_LEGACY_CLIENTS = {
    "CLASSIFICATION": "CLASSIFY",
    "TAXONOMY_CLASSIFICATION": "CLASSIFY",
    "ENRICHMENT": "ENRICH",
    "TAXONOMY_MANIFEST_DRAFT": "TAXONOMY_DESIGN",
}


def legacy_variables(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Variables de entorno de 1.x definidas, con la de 2.0 que las sustituye (vacío si no hay ninguna).

    Example:
        >>> legacy_variables({"DOC_ORGANIZE_LITELLM_ENRICHMENT_MODEL": "qwen"})
        {'DOC_ORGANIZE_LITELLM_ENRICHMENT_MODEL': 'DOC_ORGANIZE_LITELLM_MODEL_ENRICH'}
    """
    environ = os.environ if environ is None else environ
    found = {}
    for client, task in _LEGACY_CLIENTS.items():
        for suffix, replacement in (("BASE_URL", ENV_BASE_URL), ("VIRTUAL_KEY", f"{_PREFIX}VIRTUAL_KEY_{task}"), ("MODEL", f"{_PREFIX}MODEL_{task}")):
            name = f"{_PREFIX}{client}_{suffix}"
            if environ.get(name):
                found[name] = replacement
    return found


def settings_from_env(environ: Mapping[str, str] | None = None) -> AiSettings | None:
    """`AiSettings` desde las variables de entorno de 2.0, o `None` si la IA no está configurada (sin `BASE_URL`).

    Raises:
        AiConfigurationError: Hay variables de 1.x definidas (el mensaje da la equivalente de cada una), o `BASE_URL` sin
            `VIRTUAL_KEY`.

    Example:
        >>> settings = settings_from_env({
        ...     "DOC_ORGANIZE_LITELLM_BASE_URL": "http://localhost:4000",
        ...     "DOC_ORGANIZE_LITELLM_VIRTUAL_KEY": "sk-general",
        ...     "DOC_ORGANIZE_LITELLM_MODEL_CLASSIFY": "qwen2.5",
        ... })
        >>> settings.model_for("classify"), settings.model_for("enrich")
        ('qwen2.5', 'doc-organize-enrich')
    """
    environ = os.environ if environ is None else environ
    legacy = legacy_variables(environ)
    if legacy:
        lines = "; ".join(f"{old} → {new}" for old, new in sorted(legacy.items()))
        raise AiConfigurationError(
            f"doc_organize 2.0 ya no lee las variables de entorno de 1.x y la IA no se configuraría. Cámbialas por las de 2.0: {lines} "
            "(ver docs/guides/migracion_2_0.md)."
        )
    base_url = environ.get(ENV_BASE_URL)
    if not base_url:
        return None
    virtual_key = environ.get(ENV_VIRTUAL_KEY)
    if not virtual_key:
        raise AiConfigurationError(f"{ENV_BASE_URL} está definida pero falta {ENV_VIRTUAL_KEY}.")
    tasks = {}
    for task in AI_TASKS:
        model = environ.get(f"{_PREFIX}MODEL_{task.upper()}")
        key = environ.get(f"{_PREFIX}VIRTUAL_KEY_{task.upper()}") or None
        if model or key:
            tasks[task] = TaskSettings(model=model or f"doc-organize-{task.replace('_', '-')}", virtual_key=key)
    return AiSettings(base_url=base_url, virtual_key=virtual_key, tasks=tasks)


__all__ = ["ENV_BASE_URL", "ENV_VIRTUAL_KEY", "legacy_variables", "settings_from_env"]
