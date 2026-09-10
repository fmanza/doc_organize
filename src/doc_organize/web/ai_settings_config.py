"""
Especificación de las 5 familias de configuración de IA gestionables desde el panel
`/admin/configuracion-ia`, y resolución de sus valores con precedencia
`InstanceSecretsStore` (panel) > `DOC_ORGANIZE_*` del entorno.

No es un router (ver `web/routes/ai_settings.py` para los endpoints) -- mismo
patrón que `web/scan_errors_data.py`: lógica de soporte reutilizable entre una
ruta HTML (`context.py::context_page`, estado del toggle "IA") y una API
(`ai_settings.py`, panel de administración), sin repetir la lista de familias/
campos en los dos sitios.
"""

import os

from dataclasses import dataclass

from doc_organize.auth import InstanceSecretsStore


@dataclass(frozen=True)
class AiSettingsField:
    """Un campo de una familia de configuración de IA (p.ej. `base_url` de clasificación).

    `env_var_name` es también la clave (en minúsculas) bajo la que
    `InstanceSecretsStore` guarda un override -- trazabilidad directa con
    `.env.example` y las funciones `*_config_from_env()`, sin vocabulario nuevo.
    """

    name: str
    env_var_name: str
    is_secret: bool
    required: bool


@dataclass(frozen=True)
class AiSettingsFamily:
    """Una de las 5 familias de configuración de IA, con sus campos en orden de formulario."""

    key: str
    label: str
    fields: tuple[AiSettingsField, ...]


#: Orden fijo (no alfabético): agrupa primero las 3 familias de clasificación/borrador
#: (Sub-fase B, todas del mismo LiteLLM Proxy) y después las 2 de monitorización de
#: uso/coste -- mismo agrupamiento que ya usa la auditoría de parametrización.
AI_SETTINGS_FAMILIES: tuple[AiSettingsFamily, ...] = (
    AiSettingsFamily(
        key="litellm_classification",
        label="Clasificación de dominios por IA (1 eje)",
        fields=(
            AiSettingsField("base_url", "DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL", is_secret=False, required=True),
            AiSettingsField("virtual_key", "DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY", is_secret=True, required=True),
            AiSettingsField("model", "DOC_ORGANIZE_LITELLM_CLASSIFICATION_MODEL", is_secret=False, required=False),
        ),
    ),
    AiSettingsFamily(
        key="litellm_taxonomy_classification",
        label="Clasificación por manifiesto de taxonomía (2 ejes)",
        fields=(
            AiSettingsField("base_url", "DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_BASE_URL", is_secret=False, required=True),
            AiSettingsField("virtual_key", "DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY", is_secret=True, required=True),
            AiSettingsField("model", "DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_MODEL", is_secret=False, required=False),
        ),
    ),
    AiSettingsFamily(
        key="litellm_taxonomy_manifest_draft",
        label="Borrador de manifiesto de taxonomía por IA",
        fields=(
            AiSettingsField("base_url", "DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_BASE_URL", is_secret=False, required=True),
            AiSettingsField("virtual_key", "DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_VIRTUAL_KEY", is_secret=True, required=True),
            AiSettingsField("model", "DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_MODEL", is_secret=False, required=False),
        ),
    ),
    AiSettingsFamily(
        key="litellm_usage",
        label="Monitorización de uso/coste (LiteLLM Proxy)",
        fields=(
            AiSettingsField("base_url", "DOC_ORGANIZE_LITELLM_BASE_URL", is_secret=False, required=True),
            AiSettingsField("virtual_key", "DOC_ORGANIZE_LITELLM_VIRTUAL_KEY", is_secret=True, required=True),
        ),
    ),
    AiSettingsFamily(
        key="github_copilot_usage",
        label="Monitorización de uso (GitHub Copilot Pro)",
        fields=(
            AiSettingsField("username", "DOC_ORGANIZE_GITHUB_USERNAME", is_secret=False, required=True),
            AiSettingsField("pat", "DOC_ORGANIZE_GITHUB_PAT", is_secret=True, required=True),
        ),
    ),
)

_FAMILIES_BY_KEY = {family.key: family for family in AI_SETTINGS_FAMILIES}


def get_family(key: str) -> AiSettingsFamily | None:
    """La familia `key`, o `None` si no es una de las 5 reconocidas."""
    return _FAMILIES_BY_KEY.get(key)


async def resolve_field_value(field: AiSettingsField, store: InstanceSecretsStore) -> str | None:
    """Valor de `field` con precedencia `store` > `DOC_ORGANIZE_*` del entorno.

    Nunca falla por falta de cifrado configurado si `field` no tiene ninguna fila
    guardada (`store.get()` devuelve `None` sin tocar `secrets_cipher` en ese caso) --
    solo se necesita `DOC_ORGANIZE_SECRETS_KEY` para leer un valor SÍ guardado.

    Comprobación por verdad, no `is not None`: `update_ai_settings_family()` nunca
    persiste una cadena vacía como override (la trata como borrado), pero esta
    función se mantiene igual de estricta aquí para no depender de esa garantía
    externa -- un valor vacío nunca debe contar como "guardado" (AUDIT_CODE, sesión
    2026-09-11: antes esta función sí devolvía `""` tal cual, mientras que
    `is_family_configured()`/`*_config_from_store_or_env()` ya la trataban como
    ausente, una inconsistencia entre lo que mostraba el panel y lo que de verdad
    se usaba al construir el contexto).
    """
    stored = await store.get(field.env_var_name.lower())
    return stored if stored else os.environ.get(field.env_var_name)


async def is_family_configured(family: AiSettingsFamily, store: InstanceSecretsStore) -> bool:
    """`True` si todos los campos obligatorios de `family` resuelven a un valor (store o entorno)."""
    for field in family.fields:
        if field.required and not await resolve_field_value(field, store):
            return False
    return True


__all__ = [
    "AI_SETTINGS_FAMILIES",
    "AiSettingsField",
    "AiSettingsFamily",
    "get_family",
    "is_family_configured",
    "resolve_field_value",
]
