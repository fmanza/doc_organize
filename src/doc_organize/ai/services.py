"""
Servicios por tarea sobre el cliente único de IA (2.0.0, G1): clasificar ejes, describir un documento y proponer una
taxonomía. Sustituyen a los métodos de los cuatro clientes de 1.x.

Cada servicio arma los mensajes con el prompt de su tarea (`PromptRegistry`), define el esquema de la respuesta (que
`LlmClient` envía como `json_schema` estricto) y la valida. El contenido de lo que se envía es, en este paso, el mismo que
en 1.x (slugs del catálogo y los primeros 4000 caracteres del documento); cambia en M5 (descripciones, perfil y extracto).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from doc_organize.ai.cache import AiResultCache
from doc_organize.ai.llm_client import LlmClient, LlmResult
from doc_organize.ai.prompts import PromptRegistry
from doc_organize.core.models import AiTask, DocumentEnrichmentResult, TaxonomyEntry, TaxonomyManifestDraftResult
from doc_organize.utils.text_clean import clean_text

#: Caracteres del documento que se envían para clasificar y describir (como en 1.x).
MAX_CONTENT_CHARS = 4000
#: Caracteres de cada documento de la muestra al proponer una taxonomía (como en 1.x).
MAX_SAMPLE_CHARS_PER_DOCUMENT = 600
MAX_KEYWORDS = 8
_KEYWORD_MAX_CHARS = 60
_DESCRIPTION_MAX_CHARS = 500


@dataclass(frozen=True)
class AxisRequest:
    """Un eje que se pide clasificar: su clave y sus valores posibles (slugs)."""

    key: str
    slugs: Sequence[str]


@dataclass(frozen=True)
class AxisAnswer:
    """Lo que respondió el modelo para un eje: un valor del catálogo o `None`, y su confianza (0-1)."""

    slug: str | None
    confidence: float


@dataclass(frozen=True)
class ClassificationAnswer:
    """Respuesta validada de `classify_document`: una entrada por eje pedido y la justificación."""

    axes: dict[str, AxisAnswer]
    reasoning: str | None


@dataclass(frozen=True)
class SampledDocument:
    """Un documento de la muestra para proponer una taxonomía: carpeta, título y contenido.

    Lo construye `context.taxonomy_manifest_sampler.select_document_sample()`.
    """

    folder: str
    title: str | None
    chunks_text: str


Redacted = Callable[[dict[str, int]], None]


@dataclass(frozen=True)
class TaskRequest[T]:
    """Una petición lista para `LlmClient`: tarea, mensajes, esquema y validación. Permite saber su clave de caché
    (`LlmClient.cache_key_for`) antes de decidir si se envía."""

    task: AiTask
    messages: list[dict[str, str]]
    schema: dict[str, Any]
    parse: Callable[[Any], T]
    schema_name: str

    def cache_key(self, llm: LlmClient) -> str:
        """Clave de caché de esta petición con la configuración de `llm`."""
        return llm.cache_key_for(self.task, self.messages, self.schema)

    async def send(self, llm: LlmClient, *, on_redacted: Redacted | None = None, cache: AiResultCache | None = None) -> LlmResult[T]:
        """La envía (o la sirve de `cache`)."""
        return await llm.complete_json(
            self.task, self.messages, schema=self.schema, parse=self.parse, schema_name=self.schema_name, on_redacted=on_redacted, cache=cache
        )


def classification_request(
    prompts: PromptRegistry, *, axes: Sequence[AxisRequest], title: str | None, content: str
) -> TaskRequest[ClassificationAnswer]:
    """La petición de `classify_document`, sin enviarla.

    Raises:
        ValueError: `axes` está vacío.
    """
    if not axes:
        raise ValueError("No se puede clasificar sin ningún eje")
    catalog = "\n".join(f"- {axis.key}: {', '.join(axis.slugs) or '(ninguno)'}" for axis in axes)
    messages = prompts.get("classify").render(
        catalog=f"Ejes y sus valores:\n{catalog}", title=title or "(sin título)", content=content[:MAX_CONTENT_CHARS]
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            **{
                axis.key: {
                    "type": "object",
                    "properties": {"value": {"type": ["string", "null"], "enum": [*axis.slugs, None]}, "confidence": {"type": "number"}},
                    "required": ["value", "confidence"],
                    "additionalProperties": False,
                }
                for axis in axes
            },
            "reasoning": {"type": ["string", "null"]},
        },
        "required": [*(axis.key for axis in axes), "reasoning"],
        "additionalProperties": False,
    }

    def parse(data: Any) -> ClassificationAnswer:
        if not isinstance(data, dict):
            raise TypeError("se esperaba un objeto")
        answers = {}
        for axis in axes:
            entry = data.get(axis.key)
            if not isinstance(entry, dict):
                raise TypeError(f"falta el eje {axis.key}")
            value = entry.get("value")
            answers[axis.key] = AxisAnswer(slug=value if value in axis.slugs else None, confidence=_confidence(entry.get("confidence")))
        reasoning = data.get("reasoning")
        return ClassificationAnswer(axes=answers, reasoning=clean_text(reasoning) if isinstance(reasoning, str) else None)

    return TaskRequest("classify", messages, schema, parse, "clasificacion")


async def classify_document(
    llm: LlmClient,
    prompts: PromptRegistry,
    *,
    axes: Sequence[AxisRequest],
    title: str | None,
    content: str,
    on_redacted: Redacted | None = None,
    cache: AiResultCache | None = None,
) -> LlmResult[ClassificationAnswer]:
    """Clasifica un documento en `axes` con una sola llamada (tarea `classify`).

    El esquema tiene, por eje, `value` con un `enum` de sus slugs (o `null`) y `confidence`. Un valor fuera del catálogo
    no pasa la validación aunque el modelo no admita el esquema estricto. Con `cache`, una petición idéntica a una ya
    hecha no llama al modelo.

    Raises:
        ValueError: `axes` está vacío.
        AiError: Ver `LlmClient.complete_json`.
    """
    request = classification_request(prompts, axes=axes, title=title, content=content)
    return await request.send(llm, on_redacted=on_redacted, cache=cache)


def enrichment_request(prompts: PromptRegistry, *, title: str | None, content: str) -> TaskRequest[DocumentEnrichmentResult]:
    """La petición de `enrich_document`, sin enviarla."""
    messages = prompts.get("enrich").render(max_keywords=MAX_KEYWORDS, title=title or "(sin título)", content=content[:MAX_CONTENT_CHARS])
    schema = {
        "type": "object",
        "properties": {"description": {"type": ["string", "null"]}, "keywords": {"type": "array", "items": {"type": "string"}}},
        "required": ["description", "keywords"],
        "additionalProperties": False,
    }

    def parse(data: Any) -> DocumentEnrichmentResult:
        if not isinstance(data, dict):
            raise TypeError("se esperaba un objeto")
        description = data.get("description")
        keywords = data.get("keywords") or []
        if not isinstance(keywords, list):
            raise TypeError("keywords no es una lista")
        cleaned = [text[:_KEYWORD_MAX_CHARS] for text in (clean_text(str(keyword)) for keyword in keywords) if text]
        text = clean_text(description) if isinstance(description, str) else None
        return DocumentEnrichmentResult(
            description=text[:_DESCRIPTION_MAX_CHARS] if text else None, keywords=list(dict.fromkeys(cleaned))[:MAX_KEYWORDS]
        )

    return TaskRequest("enrich", messages, schema, parse, "descripcion")


async def enrich_document(
    llm: LlmClient,
    prompts: PromptRegistry,
    *,
    title: str | None,
    content: str,
    on_redacted: Redacted | None = None,
    cache: AiResultCache | None = None,
) -> LlmResult[DocumentEnrichmentResult]:
    """Descripción y palabras clave de un documento (tarea `enrich`); con `cache`, como `classify_document`.

    Raises:
        AiError: Ver `LlmClient.complete_json`.
    """
    return await enrichment_request(prompts, title=title, content=content).send(llm, on_redacted=on_redacted, cache=cache)


async def draft_taxonomy(llm: LlmClient, prompts: PromptRegistry, documents: Sequence[SampledDocument]) -> LlmResult[TaxonomyManifestDraftResult]:
    """Propone un borrador de taxonomía (dominios y tipos de material) a partir de una muestra (tarea `taxonomy_design`).

    Nunca se aplica solo: el usuario lo revisa (`TaxonomyManifestDraftResult.to_manifest()` y
    `render_taxonomy_manifest_markdown`).

    Raises:
        ValueError: `documents` está vacío.
        AiResponseError: La respuesta no trae ningún dominio o ningún tipo de material válido.
        AiError: Ver `LlmClient.complete_json`.
    """
    if not documents:
        raise ValueError("No se puede proponer un borrador de taxonomía sin ningún documento de muestra")
    lines = [
        f"{index}. Carpeta: {document.folder or '(raíz)'} | Título: {document.title or '(sin título)'} | "
        f"Contenido: {document.chunks_text[:MAX_SAMPLE_CHARS_PER_DOCUMENT]}"
        for index, document in enumerate(documents, start=1)
    ]
    messages = prompts.get("taxonomy_design").render(sample_size=len(documents), documents="\n".join(lines))
    entry_schema = {
        "type": "object",
        "properties": {
            "slug": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": ["string", "null"]},
            "keywords": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["slug", "name", "description", "keywords"],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {
            "domains": {"type": "array", "items": entry_schema},
            "material_types": {"type": "array", "items": entry_schema},
            "reasoning": {"type": ["string", "null"]},
        },
        "required": ["domains", "material_types", "reasoning"],
        "additionalProperties": False,
    }

    def parse(data: Any) -> TaxonomyManifestDraftResult:
        if not isinstance(data, dict):
            raise TypeError("se esperaba un objeto")
        try:
            domains = _dedupe([TaxonomyEntry.model_validate(entry) for entry in data.get("domains") or []])
            material_types = _dedupe([TaxonomyEntry.model_validate(entry) for entry in data.get("material_types") or []])
        except ValidationError as exc:
            raise ValueError(f"entrada no válida: {exc.error_count()} error(es)") from exc
        if not domains or not material_types:
            raise ValueError("la IA no propuso ningún dominio o ningún tipo de material (muestra insuficiente)")
        reasoning = data.get("reasoning")
        return TaxonomyManifestDraftResult(
            domains=domains, material_types=material_types, reasoning=reasoning if isinstance(reasoning, str) else None
        )

    return await llm.complete_json("taxonomy_design", messages, schema=schema, parse=parse, schema_name="borrador_taxonomia")


def _confidence(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def _dedupe(entries: list[TaxonomyEntry]) -> list[TaxonomyEntry]:
    """Quita entradas con un `slug` repetido (gana la primera): el modelo puede repetirlo pese al prompt."""
    seen: set[str] = set()
    unique = []
    for entry in entries:
        if entry.slug not in seen:
            seen.add(entry.slug)
            unique.append(entry)
    return unique


__all__ = [
    "MAX_CONTENT_CHARS",
    "AxisAnswer",
    "AxisRequest",
    "ClassificationAnswer",
    "SampledDocument",
    "TaskRequest",
    "classification_request",
    "classify_document",
    "draft_taxonomy",
    "enrich_document",
    "enrichment_request",
]
