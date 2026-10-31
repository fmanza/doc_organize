"""
Cliente de clasificación de dominios por IA vía LiteLLM Proxy (Sub-fase B, fase 2 IA).

Fallback opcional de `DomainClassifier` (Sub-fase A, reglas): solo se invoca desde
`ContextBuilder` para documentos que las reglas dejan sin clasificar, y solo elige
entre el catálogo de dominios ya confirmado por la Sub-fase A — nunca inventa uno
nuevo (ver `.ai/sessions/2026-09-08-organizacion-documental-contextos/00_REQUEST.md`
§2.5). Config propia (`LiteLLMClassificationConfig`), no comparte credenciales con
`LiteLLMUsageConfig` (ISP) aunque en despliegue apunte al mismo LiteLLM Proxy —
mismo criterio que recomienda LiteLLM: una virtual key por carga de trabajo, para
poder atribuir presupuesto/rate-limit por separado.
"""

import json
import os

from typing import Any

import httpx

from doc_organize.ai._http_client_base import AiHttpClientBase
from doc_organize.auth import InstanceSecretsStore
from doc_organize.core.exceptions import DomainClassificationAuthError, DomainClassificationConnectionError, DomainClassificationError
from doc_organize.core.models import DomainClassificationResult, LiteLLMClassificationConfig
from doc_organize.utils.logging import get_logger

_ENV_VAR_BASE_URL = "DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL"
_ENV_VAR_VIRTUAL_KEY = "DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY"
_ENV_VAR_MODEL = "DOC_ORGANIZE_LITELLM_CLASSIFICATION_MODEL"

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "Clasificas un documento en uno de los dominios de una lista cerrada. Responde "
    'EXCLUSIVAMENTE con un JSON de la forma {"domain": <uno de los dominios de la '
    'lista, o null si ninguno encaja>, "confidence": <0.0-1.0>, "reasoning": <una '
    "frase breve>}. Nunca inventes un dominio fuera de la lista dada."
)
_MAX_CONTENT_CHARS = 4000


def litellm_classification_config_from_env() -> LiteLLMClassificationConfig:
    """Construye `LiteLLMClassificationConfig` desde variables de entorno.

    Lee `DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL`/`_VIRTUAL_KEY` (obligatorias)
    y `DOC_ORGANIZE_LITELLM_CLASSIFICATION_MODEL` (opcional, usa el valor por
    defecto de `LiteLLMClassificationConfig.model` si no se define). Mismo
    criterio que `litellm_usage_config_from_env()`: resolución explícita, nunca
    implícita dentro del cliente.

    Returns:
        Config lista para `DomainClassificationClient`.

    Raises:
        ValueError: Si falta `_BASE_URL` o `_VIRTUAL_KEY`.

    Example:
        >>> config = litellm_classification_config_from_env()  # doctest: +SKIP
    """
    base_url = os.environ.get(_ENV_VAR_BASE_URL)
    virtual_key = os.environ.get(_ENV_VAR_VIRTUAL_KEY)
    if not base_url or not virtual_key:
        raise ValueError(f"Definir {_ENV_VAR_BASE_URL} y {_ENV_VAR_VIRTUAL_KEY} para usar litellm_classification_config_from_env().")
    model = os.environ.get(_ENV_VAR_MODEL)
    return LiteLLMClassificationConfig(base_url=base_url, virtual_key=virtual_key, **({"model": model} if model else {}))


async def litellm_classification_config_from_store_or_env(store: InstanceSecretsStore) -> LiteLLMClassificationConfig:
    """Construye `LiteLLMClassificationConfig` con precedencia `store` (panel de
    configuración IA) > `DOC_ORGANIZE_LITELLM_CLASSIFICATION_*` del entorno.

    Complementa a `litellm_classification_config_from_env()` (sin modificarla, ni
    cambiar su comportamiento para quien ya la usa) — pensada para las rutas web,
    que sí tienen un `InstanceSecretsStore` disponible (ver
    `web/dependencies.py::get_instance_secrets_store`). Nunca rompe un despliegue
    que solo usa `.env`: si no hay ninguna fila guardada para una clave, cae al
    valor del entorno exactamente igual que la versión `_from_env`.

    Returns:
        Config lista para `DomainClassificationClient`.

    Raises:
        ValueError: Si, tras aplicar la precedencia, falta `base_url` o `virtual_key`.

    Example:
        >>> config = await litellm_classification_config_from_store_or_env(store)  # doctest: +SKIP
    """
    base_url = await store.get(_ENV_VAR_BASE_URL.lower()) or os.environ.get(_ENV_VAR_BASE_URL)
    virtual_key = await store.get(_ENV_VAR_VIRTUAL_KEY.lower()) or os.environ.get(_ENV_VAR_VIRTUAL_KEY)
    if not base_url or not virtual_key:
        raise ValueError(f"Definir {_ENV_VAR_BASE_URL} y {_ENV_VAR_VIRTUAL_KEY} (panel de configuración IA o entorno) para clasificar por IA.")
    model = await store.get(_ENV_VAR_MODEL.lower()) or os.environ.get(_ENV_VAR_MODEL)
    return LiteLLMClassificationConfig(base_url=base_url, virtual_key=virtual_key, **({"model": model} if model else {}))


class DomainClassificationClient(AiHttpClientBase):
    """Clasifica un documento entre un catálogo cerrado de dominios, vía LiteLLM Proxy.

    Habla el endpoint `chat/completions` OpenAI-compatible que expone LiteLLM
    Proxy, pidiendo salida JSON (`response_format: json_object`). El dominio
    devuelto siempre se valida contra `candidate_domains` antes de devolverlo —
    si el modelo sugiere algo fuera de esa lista (o no responde JSON válido), se
    trata como "no encaja en ninguno" (`domain=None`), nunca se propaga tal cual.

    Attributes:
        config (LiteLLMClassificationConfig): Configuración de acceso al proxy.
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> from doc_organize.core.models import LiteLLMClassificationConfig
        >>> config = LiteLLMClassificationConfig(base_url="https://litellm.example.com", virtual_key="sk-...")
        >>> async def demo() -> None:  # doctest: +SKIP
        ...     async with DomainClassificationClient(config) as client:
        ...         result = await client.classify(
        ...             chunks_text="Política de gestión de calidad ISO 9001...",
        ...             title="Política de calidad",
        ...             candidate_domains=["calidad", "ciberseguridad"],
        ...         )
    """

    def __init__(self, config: LiteLLMClassificationConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Inicializa el cliente.

        Args:
            config: Configuración de acceso al LiteLLM Proxy para clasificación.
            transport: Transporte `httpx` alternativo (inyección para tests con
                `httpx.MockTransport`, sin llamadas de red reales). `None` usa
                el transporte HTTP real por defecto.
        """
        self.config = config
        super().__init__(
            base_url=config.base_url,
            timeout_s=config.timeout_s,
            logger=logger,
            auth_error_cls=DomainClassificationAuthError,
            connection_error_cls=DomainClassificationConnectionError,
            generic_error_cls=DomainClassificationError,
            transport=transport,
        )

    async def classify(self, *, chunks_text: str, title: str | None, candidate_domains: list[str]) -> DomainClassificationResult:
        """Clasifica un documento (`chunks_text`/`title`) entre `candidate_domains`.

        Args:
            chunks_text: Contenido del documento (de `chunks` del `.json` de
                conversión, ver `domain_classifier.read_conversion_json`).
            title: Título del documento, si se conoce.
            candidate_domains: Catálogo cerrado de slugs entre los que elegir.
                Lista vacía devuelve `domain=None` sin llamar al proxy.

        Returns:
            `DomainClassificationResult` cuyo `domain` es siempre uno de
            `candidate_domains` o `None` — nunca un valor fuera de esa lista,
            aunque el modelo lo sugiera (validado aquí, no solo por prompt).

        Raises:
            DomainClassificationAuthError: Virtual key inválida o sin permiso (401/403).
            DomainClassificationConnectionError: Error de red o timeout.
            DomainClassificationError: Cualquier otro error del proxy.
        """
        if not candidate_domains:
            return DomainClassificationResult(domain=None, confidence=0.0, reasoning="Sin catálogo de dominios candidatos.")

        user_prompt = (
            f"Dominios candidatos: {', '.join(candidate_domains)}\nTítulo: {title or '(sin título)'}\nContenido: {chunks_text[:_MAX_CONTENT_CHARS]}"
        )
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
            auth_message="LiteLLM Proxy rechazó la virtual key de clasificación (HTTP {status_code})",
            error_message="LiteLLM Proxy devolvió HTTP {status_code} clasificando un documento",
        )

        return self._parse_result(response.json(), candidate_domains)

    def _parse_result(self, payload: dict[str, Any], candidate_domains: list[str]) -> DomainClassificationResult:
        try:
            content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise DomainClassificationError("La respuesta del LiteLLM Proxy no es el JSON de clasificación esperado") from exc

        if not isinstance(parsed, dict):
            # `json.loads` acepta cualquier valor JSON válido, no solo objetos —
            # "null"/"42"/"[...]" parsean sin error pero no tienen `.get()`.
            # Sin esta comprobación, `parsed.get(...)` de abajo lanzaba un
            # `AttributeError` sin capturar que tumbaba toda la petición en vez
            # de tratar solo este documento como sin clasificar (AUDIT_CODE,
            # sesión 2026-09-09).
            raise DomainClassificationError(
                f"La respuesta del LiteLLM Proxy no es un objeto JSON de clasificación (se recibió {type(parsed).__name__})"
            )

        domain = parsed.get("domain")
        if domain not in candidate_domains:
            # El modelo sugirió un dominio fuera del catálogo (o ninguno) — nunca
            # se inventa uno nuevo, se trata como "no encaja" (regla de negocio).
            domain = None
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))  # el modelo puede devolver cualquier número, no solo 0-1
        reasoning = parsed.get("reasoning")
        return DomainClassificationResult(domain=domain, confidence=confidence, reasoning=reasoning if isinstance(reasoning, str) else None)


__all__ = ["DomainClassificationClient", "litellm_classification_config_from_env", "litellm_classification_config_from_store_or_env"]
