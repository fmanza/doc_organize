"""
Panel de configuración de IA: ver/editar desde la web las 5 familias de credenciales
que hoy solo eran configurables editando `.env` a mano (auditoría de parametrización,
2026-09-10) -- complementa esa vía, con precedencia `InstanceSecretsStore` > entorno
(ver `web/ai_settings_config.py`).
"""

import os

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from doc_organize.auth import InstanceSecretsStore, is_secrets_encryption_configured
from doc_organize.core.exceptions import SecretsCipherError
from doc_organize.web.ai_settings_config import AI_SETTINGS_FAMILIES, AiSettingsFamily, AiSettingsField, get_family, is_family_configured
from doc_organize.web.dependencies import get_instance_secrets_store, require_admin
from doc_organize.web.templating import create_templates

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = create_templates(_TEMPLATES_DIR)

router = APIRouter(tags=["ai-settings"], dependencies=[Depends(require_admin)])

#: Nº de caracteres finales de un secreto ya guardado que se muestran en `masked_hint`
#: (p.ej. "sk-...ab12") -- suficiente para que un admin reconozca CUÁL credencial es
#: sin poder reconstruirla, ni de lejos, a partir del hint.
_MASKED_HINT_SUFFIX_LENGTH = 4


class AiSettingsFieldResponse(BaseModel):
    name: str
    env_var_name: str
    is_secret: bool
    required: bool
    configured_via: str  # "store" | "env" | "none"
    value: str | None = None
    masked_hint: str | None = None


class AiSettingsFamilyResponse(BaseModel):
    key: str
    label: str
    configured: bool
    fields: list[AiSettingsFieldResponse]


class AiSettingsResponse(BaseModel):
    encryption_configured: bool
    families: list[AiSettingsFamilyResponse]


class UpdateAiSettingsRequest(BaseModel):
    fields: dict[str, str | None] = Field(
        default_factory=dict,
        description="Nombre de campo -> valor nuevo. Un campo AUSENTE del dict no se toca; "
        "un valor `null` explícito, o una cadena vacía, borra el override guardado (vuelve a "
        "depender del entorno) -- una cadena vacía nunca queda guardada como override.",
    )


async def _field_response(field: AiSettingsField, store: InstanceSecretsStore) -> AiSettingsFieldResponse:
    # Comprobación por verdad (no `is not None`): un valor vacío nunca debe leerse como
    # "guardado" -- `update_ai_settings_family` ya no persiste cadenas vacías (las trata
    # como borrado), pero esta comprobación se mantiene igual de estricta aquí por si acaso,
    # para que este endpoint nunca pueda divergir de `is_family_configured()`/
    # `*_config_from_store_or_env()` (que sí usan verdad), aunque llegase a existir una fila
    # vacía por cualquier otra vía (AUDIT_CODE, sesión 2026-09-11).
    stored = await store.get(field.env_var_name.lower())
    env_value = os.environ.get(field.env_var_name)
    if stored:
        configured_via = "store"
        resolved: str | None = stored
    elif env_value:
        configured_via = "env"
        resolved = env_value
    else:
        configured_via = "none"
        resolved = None

    if field.is_secret:
        # Un secreto de 4 caracteres o menos nunca muestra sufijo real (revelaría el
        # valor completo bajo la apariencia de un hint "enmascarado") -- se marca con
        # "***" en vez de con `None`, para no confundir "hay algo guardado, es
        # demasiado corto para insinuar" con "no hay nada guardado" (AUDIT_CODE,
        # sesión 2026-09-11).
        if not resolved:
            masked_hint = None
        elif len(resolved) > _MASKED_HINT_SUFFIX_LENGTH:
            masked_hint = f"...{resolved[-_MASKED_HINT_SUFFIX_LENGTH:]}"
        else:
            masked_hint = "***"
        return AiSettingsFieldResponse(
            name=field.name,
            env_var_name=field.env_var_name,
            is_secret=True,
            required=field.required,
            configured_via=configured_via,
            value=None,
            masked_hint=masked_hint,
        )
    return AiSettingsFieldResponse(
        name=field.name,
        env_var_name=field.env_var_name,
        is_secret=False,
        required=field.required,
        configured_via=configured_via,
        value=resolved,
        masked_hint=None,
    )


async def _family_response(family: AiSettingsFamily, store: InstanceSecretsStore) -> AiSettingsFamilyResponse:
    fields = [await _field_response(field, store) for field in family.fields]
    configured = await is_family_configured(family, store)
    return AiSettingsFamilyResponse(key=family.key, label=family.label, configured=configured, fields=fields)


@router.get("/api/admin/ai-settings", response_model=AiSettingsResponse)
async def get_ai_settings(request: Request) -> AiSettingsResponse:
    """Estado + valores no-secretos de las 5 familias de configuración de IA.

    Un campo secreto (`is_secret=True`) nunca devuelve `value` -- solo `masked_hint`
    (últimos 4 caracteres) si hay uno guardado en el store o en el entorno. Nunca
    intenta descifrar nada solo para listar el estado (`InstanceSecretsStore.get()`
    ya descifra internamente lo que haga falta; si `DOC_ORGANIZE_SECRETS_KEY` no
    está definida y SÍ hay un secreto guardado cifrado, esta llamada se propaga como
    500 -- caso que no debería darse en la práctica: sin esa clave no se puede haber
    guardado nada cifrado en primer lugar, ver `InstanceSecretsStore.set()`).
    """
    async with get_instance_secrets_store(request) as store:
        families = [await _family_response(family, store) for family in AI_SETTINGS_FAMILIES]
    return AiSettingsResponse(encryption_configured=is_secrets_encryption_configured(), families=families)


@router.put("/api/admin/ai-settings/{family_key}", response_model=AiSettingsFamilyResponse)
async def update_ai_settings_family(family_key: str, payload: UpdateAiSettingsRequest, request: Request) -> AiSettingsFamilyResponse:
    """Guarda (o borra) uno o más campos de la familia `family_key`.

    Raises:
        HTTPException: 404 si `family_key` no es una de las 5 familias reconocidas;
            400 si algún nombre de campo no pertenece a esa familia, o si se intenta
            guardar (no borrar) un campo secreto sin `DOC_ORGANIZE_SECRETS_KEY` definida.
    """
    family = get_family(family_key)
    if family is None:
        raise HTTPException(status_code=404, detail=f"Familia de configuración de IA desconocida: '{family_key}'.")
    fields_by_name = {field.name: field for field in family.fields}

    async with get_instance_secrets_store(request) as store:
        for field_name, value in payload.fields.items():
            field = fields_by_name.get(field_name)
            if field is None:
                raise HTTPException(status_code=400, detail=f"'{field_name}' no es un campo de la familia '{family_key}'.")
            store_key = field.env_var_name.lower()
            if not value:
                # `None` explícito, o una cadena vacía (campo borrado en el formulario y
                # guardado tal cual): ambos se tratan como "borrar el override" -- nunca se
                # persiste una cadena vacía, para que `store.get()` no pueda devolver un
                # valor "guardado" que en la práctica equivale a no tener nada configurado
                # (AUDIT_CODE, sesión 2026-09-11: antes una cadena vacía SÍ quedaba guardada,
                # y `_config_from_store_or_env()`/`is_family_configured()` la trataban como
                # no configurada mientras que el panel la mostraba como "guardado").
                await store.delete(store_key)
                continue
            try:
                await store.set(store_key, value, is_secret=field.is_secret, updated_by_user_id=getattr(request.state, "user_id", None))
            except SecretsCipherError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return await _family_response(family, store)


@router.get("/admin/configuracion-ia", response_class=HTMLResponse)
async def ai_settings_page(request: Request) -> HTMLResponse:
    async with get_instance_secrets_store(request) as store:
        families = [await _family_response(family, store) for family in AI_SETTINGS_FAMILIES]
    return _templates.TemplateResponse(
        request,
        "ai_settings.html.j2",
        # `model_dump()` (dicts planos, no los propios modelos Pydantic): la plantilla
        # los reincrusta en un <script> vía `| tojson` para que el JS conozca
        # `env_var_name`/`is_secret` de cada campo sin otra petición -- `tojson` solo
        # sabe serializar tipos JSON nativos.
        {"families": [family.model_dump() for family in families], "encryption_configured": is_secrets_encryption_configured()},
    )


__all__ = ["router"]
