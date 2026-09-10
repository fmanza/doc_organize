"""
Cliente de clasificación combinada dominio + tipo de material por IA vía LiteLLM Proxy
(Sub-fase B para manifiesto de taxonomía, `TaxonomyManifest`).

Fallback opcional de `MaterialTypeClassifier`/`DomainClassifier.score_domain()` (Sub-fase A,
reglas) en modo manifiesto: solo se invoca desde `ContextBuilder` para documentos a los que
las reglas dejan el placeholder `sin-clasificar` en el eje de dominio y/o en el de tipo de
material, y resuelve AMBOS ejes en una sola llamada combinada — decisión explícita de la sesión
que añadió este cliente, en vez de dos llamadas independientes (una por eje). Solo elige entre
los catálogos ya confirmados por el manifiesto — nunca inventa un dominio o tipo de material
nuevo. Config propia (`LiteLLMTaxonomyClassificationConfig`), no comparte credenciales con
`LiteLLMClassificationConfig` (ISP, mismo criterio documentado en `domain_classification_client.py`):
la clasificación combinada de 2 ejes es una carga de trabajo distinta de la de 1 eje, aunque en
despliegue ambas apunten al mismo LiteLLM Proxy.
"""

import json
import os

from types import TracebackType
from typing import Any, Self

import httpx

from doc_organize.core.exceptions import TaxonomyClassificationAuthError, TaxonomyClassificationConnectionError, TaxonomyClassificationError
from doc_organize.core.models import LiteLLMTaxonomyClassificationConfig, TaxonomyClassificationResult
from doc_organize.utils.logging import get_logger

_ENV_VAR_BASE_URL = "DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_BASE_URL"
_ENV_VAR_VIRTUAL_KEY = "DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY"
_ENV_VAR_MODEL = "DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_MODEL"

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "Clasificas un documento en dos ejes independientes, cada uno con su propia lista cerrada: "
    "dominio y tipo de material de origen. Responde EXCLUSIVAMENTE con un JSON de la forma "
    '{"domain": <uno de los dominios candidatos, o null si ninguno encaja>, "domain_confidence": '
    '<0.0-1.0>, "material_type": <uno de los tipos de material candidatos, o null si ninguno '
    'encaja>, "material_type_confidence": <0.0-1.0>, "reasoning": <una frase breve>}. Nunca '
    "inventes un valor fuera de la lista dada para cada eje."
)
_MAX_CONTENT_CHARS = 4000


def litellm_taxonomy_classification_config_from_env() -> LiteLLMTaxonomyClassificationConfig:
    """Construye `LiteLLMTaxonomyClassificationConfig` desde variables de entorno.

    Lee `DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_BASE_URL`/`_VIRTUAL_KEY` (obligatorias)
    y `DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_MODEL` (opcional, usa el valor por defecto
    de `LiteLLMTaxonomyClassificationConfig.model` si no se define). Mismo criterio que
    `litellm_classification_config_from_env()`: resolución explícita, nunca implícita dentro
    del cliente.

    Returns:
        Config lista para `TaxonomyClassificationClient`.

    Raises:
        ValueError: Si falta `_BASE_URL` o `_VIRTUAL_KEY`.

    Example:
        >>> config = litellm_taxonomy_classification_config_from_env()  # doctest: +SKIP
    """
    base_url = os.environ.get(_ENV_VAR_BASE_URL)
    virtual_key = os.environ.get(_ENV_VAR_VIRTUAL_KEY)
    if not base_url or not virtual_key:
        raise ValueError(f"Definir {_ENV_VAR_BASE_URL} y {_ENV_VAR_VIRTUAL_KEY} para usar litellm_taxonomy_classification_config_from_env().")
    model = os.environ.get(_ENV_VAR_MODEL)
    return LiteLLMTaxonomyClassificationConfig(base_url=base_url, virtual_key=virtual_key, **({"model": model} if model else {}))


class TaxonomyClassificationClient:
    """Clasifica un documento en dominio + tipo de material (2 ejes) en una sola llamada, vía LiteLLM Proxy.

    Habla el mismo endpoint `chat/completions` OpenAI-compatible que `DomainClassificationClient`,
    pidiendo salida JSON (`response_format: json_object`) con los dos ejes a la vez. Cada valor
    devuelto se valida siempre contra su propio catálogo candidato antes de devolverlo — si el
    modelo sugiere algo fuera de esa lista (o no responde JSON válido) en cualquiera de los dos
    ejes, ese eje se trata como "no encaja en ninguno" (`None`), nunca se propaga tal cual.

    Attributes:
        config (LiteLLMTaxonomyClassificationConfig): Configuración de acceso al proxy.
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> from doc_organize.core.models import LiteLLMTaxonomyClassificationConfig
        >>> config = LiteLLMTaxonomyClassificationConfig(base_url="https://litellm.example.com", virtual_key="sk-...")
        >>> async def demo() -> None:  # doctest: +SKIP
        ...     async with TaxonomyClassificationClient(config) as client:
        ...         result = await client.classify(
        ...             chunks_text="Procedimiento de gestión de incidentes ISO 27001...",
        ...             title="Procedimiento de incidentes",
        ...             candidate_domains=["ciberseguridad", "calidad"],
        ...             candidate_material_types=["normativa", "procedimiento"],
        ...         )
    """

    def __init__(self, config: LiteLLMTaxonomyClassificationConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Inicializa el cliente.

        Args:
            config: Configuración de acceso al LiteLLM Proxy para clasificación por manifiesto.
            transport: Transporte `httpx` alternativo (inyección para tests con
                `httpx.MockTransport`, sin llamadas de red reales). `None` usa
                el transporte HTTP real por defecto.
        """
        self.config = config
        self.logger = logger
        self._client = httpx.AsyncClient(base_url=config.base_url, timeout=config.timeout_s, transport=transport)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    async def classify(
        self, *, chunks_text: str, title: str | None, candidate_domains: list[str], candidate_material_types: list[str]
    ) -> TaxonomyClassificationResult:
        """Clasifica un documento (`chunks_text`/`title`) entre `candidate_domains` y `candidate_material_types` a la vez.

        Args:
            chunks_text: Contenido del documento (de `chunks` del `.json` de
                conversión, ver `domain_classifier.read_conversion_json`).
            title: Título del documento, si se conoce.
            candidate_domains: Catálogo cerrado de slugs de dominio entre los que elegir.
            candidate_material_types: Catálogo cerrado de slugs de tipo de material entre los que elegir.
                Ambos catálogos vacíos a la vez devuelve el resultado vacío sin llamar al proxy.

        Returns:
            `TaxonomyClassificationResult` cuyo `domain` es siempre uno de `candidate_domains` o
            `None`, y cuyo `material_type` es siempre uno de `candidate_material_types` o `None` —
            nunca un valor fuera de su catálogo respectivo, aunque el modelo lo sugiera (validado
            aquí, no solo por prompt).

        Raises:
            TaxonomyClassificationAuthError: Virtual key inválida o sin permiso (401/403).
            TaxonomyClassificationConnectionError: Error de red o timeout.
            TaxonomyClassificationError: Cualquier otro error del proxy.
        """
        if not candidate_domains and not candidate_material_types:
            return TaxonomyClassificationResult(reasoning="Sin catálogos de dominio ni tipo de material candidatos.")

        user_prompt = (
            f"Dominios candidatos: {', '.join(candidate_domains) or '(ninguno)'}\n"
            f"Tipos de material candidatos: {', '.join(candidate_material_types) or '(ninguno)'}\n"
            f"Título: {title or '(sin título)'}\n"
            f"Contenido: {chunks_text[:_MAX_CONTENT_CHARS]}"
        )
        try:
            response = await self._client.post(
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
            )
        except httpx.TimeoutException as exc:
            raise TaxonomyClassificationConnectionError(f"Timeout consultando el LiteLLM Proxy en {self.config.base_url}") from exc
        except httpx.HTTPError as exc:
            raise TaxonomyClassificationConnectionError(f"Error de red consultando el LiteLLM Proxy en {self.config.base_url}") from exc

        if response.status_code in (401, 403):
            raise TaxonomyClassificationAuthError(
                f"LiteLLM Proxy rechazó la virtual key de clasificación por manifiesto (HTTP {response.status_code})"
            )
        if response.is_error:
            raise TaxonomyClassificationError(f"LiteLLM Proxy devolvió HTTP {response.status_code} clasificando un documento por manifiesto")

        return self._parse_result(response.json(), candidate_domains, candidate_material_types)

    def _parse_result(
        self, payload: dict[str, Any], candidate_domains: list[str], candidate_material_types: list[str]
    ) -> TaxonomyClassificationResult:
        try:
            content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise TaxonomyClassificationError("La respuesta del LiteLLM Proxy no es el JSON de clasificación esperado") from exc

        if not isinstance(parsed, dict):
            # Mismo caso límite que `DomainClassificationClient._parse_result`: `json.loads`
            # acepta "null"/"42"/"[...]" sin error pero sin `.get()` — sin esta comprobación,
            # `parsed.get(...)` de abajo lanzaba un `AttributeError` sin capturar.
            raise TaxonomyClassificationError(
                f"La respuesta del LiteLLM Proxy no es un objeto JSON de clasificación (se recibió {type(parsed).__name__})"
            )

        domain = parsed.get("domain")
        if domain not in candidate_domains:
            # El modelo sugirió un valor fuera del catálogo de dominios (o ninguno) — nunca se
            # inventa uno nuevo, se trata como "no encaja" (regla de negocio).
            domain = None
        material_type = parsed.get("material_type")
        if material_type not in candidate_material_types:
            material_type = None

        reasoning = parsed.get("reasoning")
        return TaxonomyClassificationResult(
            domain=domain,
            domain_confidence=self._clamp_confidence(parsed.get("domain_confidence", 0.0)),
            material_type=material_type,
            material_type_confidence=self._clamp_confidence(parsed.get("material_type_confidence", 0.0)),
            reasoning=reasoning if isinstance(reasoning, str) else None,
        )

    @staticmethod
    def _clamp_confidence(raw: Any) -> float:
        try:
            confidence = float(raw)
        except (TypeError, ValueError):
            confidence = 0.0
        return max(0.0, min(1.0, confidence))  # el modelo puede devolver cualquier número, no solo 0-1


__all__ = ["TaxonomyClassificationClient", "litellm_taxonomy_classification_config_from_env"]
