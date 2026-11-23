"""
Servicios por tarea sobre el cliente único de IA (2.0.0, G1 y G2): clasificar ejes, describir un documento y proponer
una taxonomía. Sustituyen a los métodos de los cuatro clientes de 1.x.

Cada servicio arma los mensajes con el prompt de su tarea (`PromptRegistry`), define el esquema de la respuesta (que
`LlmClient` envía como `json_schema` estricto) y la valida. La clasificación (M5) envía el catálogo con nombres y
descripciones, el perfil del proyecto y el extracto del documento, y pide una cita por valor.
"""

import re

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from doc_organize.ai.cache import AiResultCache
from doc_organize.ai.excerpt import MAX_EXCERPT_CHARS
from doc_organize.ai.llm_client import LlmClient, LlmResult
from doc_organize.ai.profile_text import profile_prompt_text
from doc_organize.ai.prompts import PromptRegistry
from doc_organize.core.models import (
    AiTask,
    DocumentEnrichmentResult,
    ProjectProfile,
    TaxonomyAxis,
    TaxonomyEntry,
    TaxonomyManifest,
    TaxonomyManifestDraftResult,
)
from doc_organize.utils.folding import FoldedText, fold
from doc_organize.utils.text_clean import clean_text

#: Caracteres del documento que se envían para describirlo (`enrich`, como en 1.x): su extracto, más corto que el de
#: clasificar (`MAX_EXCERPT_CHARS`).
MAX_CONTENT_CHARS = 4000
#: Caracteres de cada documento de la muestra al proponer una taxonomía (como en 1.x).
MAX_SAMPLE_CHARS_PER_DOCUMENT = 600
MAX_KEYWORDS = 8
_KEYWORD_MAX_CHARS = 60
_DESCRIPTION_MAX_CHARS = 500


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


@dataclass(frozen=True)
class AxisOption:
    """Un valor posible de un eje, como se le presenta al modelo: slug, nombre y qué cubre."""

    slug: str
    name: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class AxisRequest:
    """Un eje que se pide clasificar (2.0.0, G2): su clave, nombre, descripción, si admite varios valores y sus valores.

    El modelo recibe nombres y descripciones (no solo slugs, se revierte S3 con las mitigaciones de G2.2), pero solo
    puede responder slugs de `options` (`enum` del esquema).
    """

    key: str
    options: Sequence[AxisOption]
    name: str | None = None
    description: str | None = None
    multiple: bool = False

    @property
    def slugs(self) -> list[str]:
        return [option.slug for option in self.options]

    @classmethod
    def from_slugs(cls, key: str, slugs: Sequence[str]) -> "AxisRequest":
        """Un eje del que solo se conocen los slugs (sin manifiesto: los dominios)."""
        return cls(key=key, options=[AxisOption(slug) for slug in slugs])

    @classmethod
    def from_axis(cls, axis: TaxonomyAxis, slugify: Callable[[str], str] = str) -> "AxisRequest":
        """Un eje del manifiesto; `slugify` sanea los slugs como lo hace quien aplica la respuesta."""
        options = {}
        for entry in axis.entries:
            slug = slugify(entry.slug)
            if slug and slug not in options:
                options[slug] = AxisOption(slug=slug, name=entry.name, description=entry.description)
        return cls(key=axis.key, options=list(options.values()), name=axis.name, description=axis.description, multiple=axis.multiple)


@dataclass(frozen=True)
class AxisChoice:
    """Un valor que eligió el modelo para un eje, con su confianza y la cita que lo justifica.

    Attributes:
        slug (str): Valor del catálogo del eje.
        confidence (float): Confianza 0-1 que dio el modelo.
        evidence (str | None): Cita literal que dio el modelo, o `None`.
        evidence_verified (bool | None): Si la cita aparece en lo enviado (sin distinguir mayúsculas, acentos ni
            espacios); `None` sin cita.
    """

    slug: str
    confidence: float
    evidence: str | None = None
    evidence_verified: bool | None = None


@dataclass(frozen=True)
class AxisAnswer:
    """Lo que respondió el modelo para un eje: como mucho un valor (o 5 si el eje es múltiple), del catálogo."""

    choices: tuple[AxisChoice, ...] = ()

    @property
    def slug(self) -> str | None:
        """El primer valor, o `None` (para los ejes de un valor)."""
        return self.choices[0].slug if self.choices else None

    @property
    def confidence(self) -> float:
        """La confianza del primer valor, o 0."""
        return self.choices[0].confidence if self.choices else 0.0


@dataclass(frozen=True)
class ClassificationAnswer:
    """Respuesta validada de `classify_document`: una entrada por eje pedido y la justificación."""

    axes: dict[str, AxisAnswer]
    reasoning: str | None


#: Delimitadores del documento en el mensaje: lo de dentro es material, no instrucciones (G2.2).
DOCUMENT_START = "<<<DOCUMENTO"
DOCUMENT_END = "DOCUMENTO>>>"
#: Valores como mucho por eje de varios valores (como las reglas, A2).
MAX_VALUES_PER_AXIS = 5
_MAX_EVIDENCE_CHARS = 300
_ELLIPSIS = re.compile(r"\[\.\.\.\]|\.\.\.+|…")


def render_catalog(axes: Sequence[AxisRequest]) -> str:
    """El catálogo como lo lee el modelo: por eje, su nombre, si admite varios valores, qué clasifica y sus valores con
    nombre y descripción (una línea cada uno, sin caracteres de control).

    Example:
        >>> print(render_catalog([AxisRequest("domains", [AxisOption("calidad", "Calidad", "Sistema de gestión de calidad")], name="Dominios")]))
        Eje domains: Dominios (un valor)
        - calidad: Calidad. Sistema de gestión de calidad
    """
    blocks = []
    for axis in axes:
        cardinality = f"varios valores, hasta {MAX_VALUES_PER_AXIS}" if axis.multiple else "un valor"
        lines = [f"Eje {axis.key}: {_line(axis.name) or axis.key} ({cardinality})"]
        if axis.description:
            lines.append(f"  {_line(axis.description)}")
        for option in axis.options:
            details = ". ".join(part for part in (_line(option.name), _line(option.description)) if part)
            lines.append(f"- {option.slug}" + (f": {details}" if details else ""))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def classification_request(
    prompts: PromptRegistry,
    *,
    axes: Sequence[AxisRequest],
    title: str | None,
    content: str,
    profile: str = "",
    examples: Sequence[str] = (),
) -> TaskRequest[ClassificationAnswer]:
    """La petición de `classify_document`, sin enviarla.

    Args:
        prompts: Prompts de cada tarea.
        axes: Ejes que se piden (solo los que faltan).
        title: Título del documento.
        content: Lo que se envía del documento: el extracto (`build_document_excerpt`), hasta `MAX_EXCERPT_CHARS`.
        profile: Perfil del proyecto ya preparado (`profile_prompt_text`).
        examples: Documentos parecidos ya clasificados, una línea cada uno (2.0.0, G4); van en el mensaje `user`, antes
            del documento, para que el prefijo `system` siga siendo el mismo en todo el proyecto.

    Raises:
        ValueError: `axes` está vacío.
    """
    if not axes:
        raise ValueError("No se puede clasificar sin ningún eje")
    document = _material(content, MAX_EXCERPT_CHARS)
    messages = prompts.get("classify").render(
        catalog=render_catalog(axes),
        profile=_profile_block(profile),
        document=f"{DOCUMENT_START}\n{document}\n{DOCUMENT_END}",
        examples=_examples_block(examples),
        title=title or "(sin título)",
        content=document,
    )
    choice_properties: dict[str, Any] = {"confidence": {"type": "number"}, "evidence": {"type": ["string", "null"]}}

    def choice_schema(slugs: list[str]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"value": {"type": "string", "enum": slugs}, **choice_properties},
            "required": ["value", "confidence", "evidence"],
            "additionalProperties": False,
        }

    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            **{
                axis.key: {
                    "type": "object",
                    "properties": {
                        "values": {
                            "type": "array",
                            "items": choice_schema(axis.slugs),
                        }
                    },
                    "required": ["values"],
                    "additionalProperties": False,
                }
                for axis in axes
            },
            "reasoning": {"type": ["string", "null"]},
        },
        "required": [*(axis.key for axis in axes), "reasoning"],
        "additionalProperties": False,
    }
    sent = FoldedText.of(document)

    def parse(data: Any) -> ClassificationAnswer:
        if not isinstance(data, dict):
            raise TypeError("se esperaba un objeto")
        answers = {}
        for axis in axes:
            entry = data.get(axis.key)
            values = entry.get("values") if isinstance(entry, dict) else None
            if not isinstance(values, list):
                raise TypeError(f"falta el eje {axis.key}")
            answers[axis.key] = AxisAnswer(choices=_choices(axis, values, sent))
        reasoning = data.get("reasoning")
        return ClassificationAnswer(axes=answers, reasoning=clean_text(reasoning) if isinstance(reasoning, str) else None)

    return TaskRequest("classify", messages, schema, parse, "clasificacion")


def _choices(axis: AxisRequest, values: list[Any], sent: FoldedText) -> tuple[AxisChoice, ...]:
    """Los valores válidos de un eje: del catálogo, sin repetir, como mucho 1 (o 5 si es múltiple), con la cita
    comprobada contra lo enviado."""
    allowed = set(axis.slugs)
    choices: list[AxisChoice] = []
    for item in values:
        if not isinstance(item, dict) or item.get("value") not in allowed or any(choice.slug == item["value"] for choice in choices):
            continue
        evidence = item.get("evidence")
        cleaned = clean_text(evidence) if isinstance(evidence, str) else None
        text = cleaned[:_MAX_EVIDENCE_CHARS] if cleaned else None
        verified = None if text is None else _evidence_found(text, sent)
        choices.append(AxisChoice(slug=item["value"], confidence=_confidence(item.get("confidence")), evidence=text, evidence_verified=verified))
    return tuple(choices[: MAX_VALUES_PER_AXIS if axis.multiple else 1])


def _evidence_found(evidence: str, sent: FoldedText) -> bool:
    """Si la cita aparece en lo enviado (sin distinguir mayúsculas, acentos ni espacios). Una cita con puntos
    suspensivos vale si cada trozo aparece; las comillas que la rodeen no cuentan.

    Example:
        >>> sent = FoldedText.of("La política de seguridad se revisa anualmente por la dirección.")
        >>> _evidence_found("«política de seguridad … por la dirección»", sent), _evidence_found("política de calidad", sent)
        (True, False)
    """
    pieces = [fold(piece) for piece in _ELLIPSIS.split(evidence.strip().strip("\"'«»“”‘’"))]
    pieces = [piece for piece in pieces if piece]
    return bool(pieces) and all(sent.contains(piece) for piece in pieces)


async def classify_document(
    llm: LlmClient,
    prompts: PromptRegistry,
    *,
    axes: Sequence[AxisRequest],
    title: str | None,
    content: str,
    profile: str = "",
    on_redacted: Redacted | None = None,
    cache: AiResultCache | None = None,
) -> LlmResult[ClassificationAnswer]:
    """Clasifica un documento en `axes` con una sola llamada (tarea `classify`).

    El modelo recibe el catálogo con nombres y descripciones, el perfil del proyecto y el documento (el extracto) entre
    delimitadores. Responde, por eje, una lista de valores del catálogo (`enum` del esquema), cada uno con su confianza
    y una cita literal; la cita se comprueba contra lo enviado (`AxisChoice.evidence_verified`). Un valor fuera del
    catálogo se descarta aunque el modelo no admita el esquema estricto. Con `cache`, una petición idéntica a una ya hecha
    no llama al modelo.

    Raises:
        ValueError: `axes` está vacío.
        AiError: Ver `LlmClient.complete_json`.
    """
    request = classification_request(prompts, axes=axes, title=title, content=content, profile=profile)
    return await request.send(llm, on_redacted=on_redacted, cache=cache)


def render_prompt_preview(
    manifest: TaxonomyManifest,
    *,
    prompts: PromptRegistry | None = None,
    profile: ProjectProfile | None = None,
    title: str = "Título del documento",
    excerpt: str = "(aquí va el extracto de cada documento)",
) -> list[dict[str, str]]:
    """Los mensajes que recibiría el modelo al clasificar con `manifest`, **sin llamar a nadie** (2.0.0, G2): para
    revisar el catálogo y el perfil antes de gastar una sola llamada.

    Args:
        manifest: Manifiesto o plantilla (todos sus ejes; en una construcción solo se piden los que faltan).
        prompts: Prompts (por defecto, los empaquetados).
        profile: Perfil (por defecto, `manifest.profile`).
        title: Título de ejemplo.
        excerpt: Extracto de ejemplo.

    Example:
        >>> from doc_organize.core.models import TaxonomyAxis, TaxonomyEntry
        >>> manifest = TaxonomyManifest(axes=[
        ...     TaxonomyAxis(key="domains", name="Dominios", organizes="folder", entries=[TaxonomyEntry(slug="calidad", name="Calidad")]),
        ...     TaxonomyAxis(key="material_types", name="Tipos", organizes="subfolder", entries=[TaxonomyEntry(slug="politica", name="Política")]),
        ... ])
        >>> messages = render_prompt_preview(manifest)
        >>> "- calidad: Calidad" in messages[0]["content"], messages[1]["content"].startswith(DOCUMENT_START)
        (True, True)
    """
    request = classification_request(
        prompts or PromptRegistry(),
        axes=[AxisRequest.from_axis(axis) for axis in manifest.axes],
        title=title,
        content=excerpt,
        profile=profile_prompt_text(profile if profile is not None else manifest.profile),
    )
    return request.messages


def _material(content: str, max_chars: int) -> str:
    """Lo que se envía del documento: hasta `max_chars`, sin los delimitadores (no puede cerrar su bloque, G2.2)."""
    return content[:max_chars].replace(DOCUMENT_END, "DOCUMENTO").replace(DOCUMENT_START, "DOCUMENTO")


def _examples_block(examples: Sequence[str]) -> str:
    lines = [_line(example) for example in examples]
    lines = [line for line in lines if line]
    return "Documentos parecidos ya clasificados (orientativo):\n" + "\n".join(f"- {line}" for line in lines) if lines else ""


def _profile_block(profile: str) -> str:
    return f"Perfil del proyecto:\n{profile}" if profile else ""


def _line(text: str | None) -> str:
    """Una línea sin caracteres de control (los nombres y descripciones del catálogo van al prompt, S3)."""
    if not text:
        return ""
    return " ".join("".join(char if char.isprintable() else " " for char in text).split())


def enrichment_request(prompts: PromptRegistry, *, title: str | None, content: str, profile: str = "") -> TaskRequest[DocumentEnrichmentResult]:
    """La petición de `enrich_document`, sin enviarla.

    Args:
        prompts: Prompts de cada tarea.
        title: Título del documento.
        content: Lo que se envía del documento: su extracto (`build_document_excerpt`), hasta `MAX_CONTENT_CHARS`.
        profile: Perfil del proyecto ya preparado (`profile_prompt_text`): el glosario ayuda a describir.
    """
    document = _material(content, MAX_CONTENT_CHARS)
    messages = prompts.get("enrich").render(
        max_keywords=MAX_KEYWORDS,
        profile=_profile_block(profile),
        document=f"{DOCUMENT_START}\n{document}\n{DOCUMENT_END}",
        title=title or "(sin título)",
        content=document,
    )
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
    profile: str = "",
    on_redacted: Redacted | None = None,
    cache: AiResultCache | None = None,
) -> LlmResult[DocumentEnrichmentResult]:
    """Descripción y palabras clave de un documento (tarea `enrich`) a partir de su extracto, con el perfil del
    proyecto; con `cache`, como `classify_document`.

    Raises:
        AiError: Ver `LlmClient.complete_json`.
    """
    request = enrichment_request(prompts, title=title, content=content, profile=profile)
    return await request.send(llm, on_redacted=on_redacted, cache=cache)


async def draft_taxonomy(llm: LlmClient, prompts: PromptRegistry, documents: Sequence[SampledDocument]) -> LlmResult[TaxonomyManifestDraftResult]:
    """Propone un borrador de taxonomía (dominios y tipos de material) a partir de una muestra (tarea `taxonomy_design`).

    Cada entrada lleva su descripción (qué cubre, que es lo que lee el modelo al clasificar) y el borrador trae un
    perfil inicial del proyecto (contexto, reglas de desempate y glosario, `TaxonomyManifestDraftResult.profile`).
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
            "profile": {
                "type": "object",
                "properties": {field: {"type": ["string", "null"]} for field in _DRAFT_PROFILE_FIELDS},
                "required": list(_DRAFT_PROFILE_FIELDS),
                "additionalProperties": False,
            },
            "reasoning": {"type": ["string", "null"]},
        },
        "required": ["domains", "material_types", "profile", "reasoning"],
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
            domains=domains,
            material_types=material_types,
            profile=_draft_profile(data.get("profile")),
            reasoning=reasoning if isinstance(reasoning, str) else None,
        )

    return await llm.complete_json("taxonomy_design", messages, schema=schema, parse=parse, schema_name="borrador_taxonomia")


#: Secciones del perfil que propone el borrador (los ejemplos los pone quien conoce los documentos).
_DRAFT_PROFILE_FIELDS = ("context", "tie_breakers", "glossary")
_DRAFT_PROFILE_FIELD_CHARS = 1500


def _draft_profile(raw: Any) -> ProjectProfile | None:
    """El perfil inicial del borrador, con cada sección limpia y acotada; `None` si no trae nada."""
    if not isinstance(raw, dict):
        return None
    fields = {}
    for field in _DRAFT_PROFILE_FIELDS:
        value = raw.get(field)
        text = "\n".join(_line(line) for line in value.splitlines()).strip() if isinstance(value, str) else ""
        fields[field] = text[:_DRAFT_PROFILE_FIELD_CHARS] or None
    profile = ProjectProfile(**fields)
    return None if profile.is_empty else profile


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
    "DOCUMENT_END",
    "DOCUMENT_START",
    "MAX_CONTENT_CHARS",
    "MAX_VALUES_PER_AXIS",
    "AxisAnswer",
    "AxisChoice",
    "AxisOption",
    "AxisRequest",
    "ClassificationAnswer",
    "SampledDocument",
    "TaskRequest",
    "classification_request",
    "classify_document",
    "draft_taxonomy",
    "enrich_document",
    "enrichment_request",
    "render_catalog",
    "render_prompt_preview",
]
