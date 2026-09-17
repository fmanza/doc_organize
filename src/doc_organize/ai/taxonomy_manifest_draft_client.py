"""
Cliente de propuesta de manifiesto de taxonomía por IA vía LiteLLM Proxy.

A diferencia de `DomainClassificationClient`/`TaxonomyClassificationClient` (Sub-fase B: eligen
DENTRO de un catálogo ya cerrado, nunca inventan), este cliente hace lo contrario a propósito:
propone el catálogo mismo (dominios + tipos de material) a partir de una muestra de documentos
ya convertidos de un proyecto. Es un endpoint nuevo y distinto de la Sub-fase B — nunca se aplica
directamente, el usuario revisa/edita el borrador antes de guardarlo como `taxonomy_manifest.md`
(ver `web/routes/context.py::draft_taxonomy_manifest`). Config propia
(`LiteLLMTaxonomyManifestDraftConfig`), no comparte credenciales con los otros dos clientes de IA
(ISP, mismo criterio documentado en `domain_classification_client.py`).
"""

import json
import os

from dataclasses import dataclass
from typing import Any

import httpx

from pydantic import ValidationError

from doc_organize.ai._http_client_base import AiHttpClientBase
from doc_organize.auth import InstanceSecretsStore
from doc_organize.core.exceptions import TaxonomyManifestDraftAuthError, TaxonomyManifestDraftConnectionError, TaxonomyManifestDraftError
from doc_organize.core.models import LiteLLMTaxonomyManifestDraftConfig, TaxonomyCatalogEntry, TaxonomyManifestDraftResult
from doc_organize.utils.logging import get_logger

_ENV_VAR_BASE_URL = "DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_BASE_URL"
_ENV_VAR_VIRTUAL_KEY = "DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_VIRTUAL_KEY"
_ENV_VAR_MODEL = "DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_MODEL"

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "Analizas una muestra de documentos ya escaneados de un proyecto y propones un BORRADOR de "
    'catálogo de taxonomía documental en dos ejes independientes: "domains" (áreas temáticas o '
    'normativas del contenido) y "material_types" (tipos de material de origen, p. ej. '
    "procedimiento, normativa, registro, evidencia, informe). Es una propuesta que el usuario "
    "revisará y editará antes de usarla -- nunca un catálogo cerrado definitivo por sí sola.\n\n"
    "Responde EXCLUSIVAMENTE con un JSON de la forma "
    '{"domains": [{"slug": <kebab-case>, "name": <nombre legible>, "description": <1 frase>, '
    '"keywords": [<3-6 palabras clave adicionales, distintas de las del slug>]}], '
    '"material_types": [{...mismo formato...}], "reasoning": <1-2 frases explicando el criterio '
    "usado>}.\n\n"
    "Reglas:\n"
    "- Basa cada entrada en patrones que de verdad aparecen en la muestra (títulos, carpetas, "
    "contenido) -- no generes categorías genéricas sin relación con los documentos dados.\n"
    '- Entre 2 y 8 entradas en "domains", entre 2 y 6 en "material_types" -- agrupa, no crees una '
    "entrada por documento.\n"
    '- "slug" en kebab-case, sin espacios ni acentos, sin repetir dentro del mismo eje.\n'
    "- Si la muestra no da para distinguir un eje con confianza, propón menos entradas en vez de "
    "inventar sin evidencia."
)
_MAX_CONTENT_CHARS_PER_DOCUMENT = 600


@dataclass(frozen=True)
class SampledDocument:
    """Un documento de la muestra enviada a la IA: carpeta contenedora + título + contenido.

    Construido por `context.taxonomy_manifest_sampler.select_document_sample()` a partir de
    `ConversionResult` + `read_conversion_json()` — este cliente solo conoce esta forma reducida,
    no `ConversionResult` (que arrastra rutas de fichero irrelevantes para el prompt).
    """

    folder: str
    title: str | None
    chunks_text: str


def litellm_taxonomy_manifest_draft_config_from_env() -> LiteLLMTaxonomyManifestDraftConfig:
    """Construye `LiteLLMTaxonomyManifestDraftConfig` desde variables de entorno.

    Lee `DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_BASE_URL`/`_VIRTUAL_KEY` (obligatorias) y
    `DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_MODEL` (opcional, usa el valor por defecto de
    `LiteLLMTaxonomyManifestDraftConfig.model` si no se define). Mismo criterio que
    `litellm_taxonomy_classification_config_from_env()`: resolución explícita, nunca implícita
    dentro del cliente.

    Returns:
        Config lista para `TaxonomyManifestDraftClient`.

    Raises:
        ValueError: Si falta `_BASE_URL` o `_VIRTUAL_KEY`.

    Example:
        >>> config = litellm_taxonomy_manifest_draft_config_from_env()  # doctest: +SKIP
    """
    base_url = os.environ.get(_ENV_VAR_BASE_URL)
    virtual_key = os.environ.get(_ENV_VAR_VIRTUAL_KEY)
    if not base_url or not virtual_key:
        raise ValueError(f"Definir {_ENV_VAR_BASE_URL} y {_ENV_VAR_VIRTUAL_KEY} para usar litellm_taxonomy_manifest_draft_config_from_env().")
    model = os.environ.get(_ENV_VAR_MODEL)
    return LiteLLMTaxonomyManifestDraftConfig(base_url=base_url, virtual_key=virtual_key, **({"model": model} if model else {}))


async def litellm_taxonomy_manifest_draft_config_from_store_or_env(store: InstanceSecretsStore) -> LiteLLMTaxonomyManifestDraftConfig:
    """Construye `LiteLLMTaxonomyManifestDraftConfig` con precedencia `store` (panel de
    configuración IA) > `DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_*` del entorno.

    Mismo criterio que `domain_classification_client.litellm_classification_config_from_store_or_env()`.

    Returns:
        Config lista para `TaxonomyManifestDraftClient`.

    Raises:
        ValueError: Si, tras aplicar la precedencia, falta `base_url` o `virtual_key`.
    """
    base_url = await store.get(_ENV_VAR_BASE_URL.lower()) or os.environ.get(_ENV_VAR_BASE_URL)
    virtual_key = await store.get(_ENV_VAR_VIRTUAL_KEY.lower()) or os.environ.get(_ENV_VAR_VIRTUAL_KEY)
    if not base_url or not virtual_key:
        raise ValueError(f"Definir {_ENV_VAR_BASE_URL} y {_ENV_VAR_VIRTUAL_KEY} (panel de configuración IA o entorno) para proponer un manifiesto.")
    model = await store.get(_ENV_VAR_MODEL.lower()) or os.environ.get(_ENV_VAR_MODEL)
    return LiteLLMTaxonomyManifestDraftConfig(base_url=base_url, virtual_key=virtual_key, **({"model": model} if model else {}))


class TaxonomyManifestDraftClient(AiHttpClientBase):
    """Propone un borrador de manifiesto de taxonomía (dominios + tipos de material) a partir de
    una muestra de documentos, vía LiteLLM Proxy.

    Habla el mismo endpoint `chat/completions` OpenAI-compatible que los clientes de clasificación,
    pidiendo salida JSON (`response_format: json_object`) con AMBOS ejes a la vez, en una sola
    llamada para toda la muestra (no una llamada por documento). El resultado siempre se valida
    contra el schema de `TaxonomyCatalogEntry` antes de devolverlo — un JSON malformado, un
    catálogo vacío en algún eje, o una respuesta que no es JSON válido se traducen en
    `TaxonomyManifestDraftError`, nunca en un borrador a medias silencioso.

    Attributes:
        config (LiteLLMTaxonomyManifestDraftConfig): Configuración de acceso al proxy.
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> from doc_organize.core.models import LiteLLMTaxonomyManifestDraftConfig
        >>> config = LiteLLMTaxonomyManifestDraftConfig(base_url="https://litellm.example.com", virtual_key="sk-...")
        >>> async def demo() -> None:  # doctest: +SKIP
        ...     async with TaxonomyManifestDraftClient(config) as client:
        ...         result = await client.propose_manifest(
        ...             documents=[SampledDocument(folder="Ciberseguridad", title="Política de seguridad", chunks_text="ISO 27001...")]
        ...         )
    """

    def __init__(self, config: LiteLLMTaxonomyManifestDraftConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Inicializa el cliente.

        Args:
            config: Configuración de acceso al LiteLLM Proxy para propuesta de manifiestos.
            transport: Transporte `httpx` alternativo (inyección para tests con
                `httpx.MockTransport`, sin llamadas de red reales). `None` usa el transporte HTTP
                real por defecto.
        """
        self.config = config
        super().__init__(
            base_url=config.base_url,
            timeout_s=config.timeout_s,
            logger=logger,
            auth_error_cls=TaxonomyManifestDraftAuthError,
            connection_error_cls=TaxonomyManifestDraftConnectionError,
            generic_error_cls=TaxonomyManifestDraftError,
            transport=transport,
        )

    async def propose_manifest(self, *, documents: list[SampledDocument]) -> TaxonomyManifestDraftResult:
        """Propone un borrador de taxonomía (dominios + tipos de material) a partir de `documents`.

        Args:
            documents: Muestra ya seleccionada (`context.taxonomy_manifest_sampler.select_document_sample()`).
                Nunca vacía — a diferencia de `DomainClassificationClient.classify()` (que acepta
                un catálogo candidato vacío y devuelve `domain=None` sin llamar al proxy), aquí no
                tiene sentido pedir un borrador sin ninguna muestra.

        Returns:
            `TaxonomyManifestDraftResult` con al menos un dominio y un tipo de material — nunca un
            borrador con algún eje vacío (se traduce en `TaxonomyManifestDraftError` en su lugar).

        Raises:
            ValueError: `documents` está vacío.
            TaxonomyManifestDraftAuthError: Virtual key inválida o sin permiso (401/403).
            TaxonomyManifestDraftConnectionError: Error de red o timeout.
            TaxonomyManifestDraftError: Cualquier otro error del proxy, o una respuesta que no
                cumple el schema de catálogo de taxonomía esperado.
        """
        if not documents:
            raise ValueError("No se puede proponer un borrador de manifiesto sin ningún documento de muestra.")

        user_prompt = self._build_user_prompt(documents)
        response = await self._request(
            "POST",
            "/chat/completions",
            json={
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,
            },
            headers={"Authorization": f"Bearer {self.config.virtual_key}"},
            timeout_message=f"Timeout consultando el LiteLLM Proxy en {self.config.base_url}",
            connection_message=f"Error de red consultando el LiteLLM Proxy en {self.config.base_url}",
            auth_message="LiteLLM Proxy rechazó la virtual key de propuesta de manifiesto (HTTP {status_code})",
            error_message="LiteLLM Proxy devolvió HTTP {status_code} proponiendo un manifiesto de taxonomía",
        )

        return self._parse_result(response.json())

    @staticmethod
    def _build_user_prompt(documents: list[SampledDocument]) -> str:
        lines = [f"Muestra de {len(documents)} documentos ya convertidos del proyecto:", ""]
        for index, document in enumerate(documents, start=1):
            excerpt = document.chunks_text[:_MAX_CONTENT_CHARS_PER_DOCUMENT]
            lines.append(f"{index}. Carpeta: {document.folder or '(raíz)'} | Título: {document.title or '(sin título)'} | Contenido: {excerpt}")
        lines.append("")
        lines.append("Propón el borrador de taxonomía (dominios + tipos de material) que mejor organice estos documentos.")
        return "\n".join(lines)

    def _parse_result(self, payload: dict[str, Any]) -> TaxonomyManifestDraftResult:
        try:
            content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise TaxonomyManifestDraftError("La respuesta del LiteLLM Proxy no es el JSON de propuesta de manifiesto esperado") from exc

        if not isinstance(parsed, dict):
            # Mismo caso límite que `DomainClassificationClient._parse_result`: `json.loads`
            # acepta "null"/"42"/"[...]" sin error pero sin `.get()`.
            raise TaxonomyManifestDraftError(
                f"La respuesta del LiteLLM Proxy no es un objeto JSON de propuesta de manifiesto (se recibió {type(parsed).__name__})"
            )

        try:
            domains = [TaxonomyCatalogEntry.model_validate(entry) for entry in parsed.get("domains") or []]
            material_types = [TaxonomyCatalogEntry.model_validate(entry) for entry in parsed.get("material_types") or []]
        except ValidationError as exc:
            raise TaxonomyManifestDraftError(f"La respuesta del LiteLLM Proxy no cumple el schema de catálogo de taxonomía: {exc}") from exc

        domains = _dedupe_by_slug(domains)
        material_types = _dedupe_by_slug(material_types)
        if not domains or not material_types:
            raise TaxonomyManifestDraftError(
                "La IA no propuso ningún dominio, o ningún tipo de material -- muestra insuficiente para generar un borrador."
            )

        reasoning = parsed.get("reasoning")
        return TaxonomyManifestDraftResult(
            domains=domains, material_types=material_types, reasoning=reasoning if isinstance(reasoning, str) else None
        )


def _dedupe_by_slug(entries: list[TaxonomyCatalogEntry]) -> list[TaxonomyCatalogEntry]:
    """Descarta entradas repetidas por `slug` (primera gana), conservando el orden.

    El modelo puede alucinar el mismo slug dos veces (con distinto `name`/`description`) pese a
    la instrucción del prompt de no repetir — nunca se deja llegar eso a `TaxonomyManifest`, que
    no valida unicidad de slug por sí mismo.
    """
    seen: set[str] = set()
    deduped: list[TaxonomyCatalogEntry] = []
    for entry in entries:
        if entry.slug not in seen:
            seen.add(entry.slug)
            deduped.append(entry)
    return deduped


__all__ = [
    "SampledDocument",
    "TaxonomyManifestDraftClient",
    "litellm_taxonomy_manifest_draft_config_from_env",
    "litellm_taxonomy_manifest_draft_config_from_store_or_env",
]
