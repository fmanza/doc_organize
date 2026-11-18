"""
Orquestador de la construcción del contexto de organización documental de un proyecto.
"""

import asyncio

from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from doc_organize import __version__
from doc_organize.ai.cache import AiResultCache
from doc_organize.ai.excerpt import build_document_excerpt
from doc_organize.ai.llm_client import LlmClient, LlmResult, ResponseFormat
from doc_organize.ai.prompts import PromptRegistry
from doc_organize.ai.services import AxisChoice, AxisRequest, ClassificationAnswer, TaskRequest, classification_request, enrichment_request
from doc_organize.context.axis_rules import TAG_AXIS_TEXT_CHARS, AxisRuleScorer, FoldedText
from doc_organize.context.context_history import ContextHistoryPolicy, append_context_build, build_record
from doc_organize.context.context_registry import ContextRegistry
from doc_organize.context.conversion_document import ConversionDocument, read_conversion_document
from doc_organize.context.decisions import ClassificationDecisionStore, apply_decisions, not_applied_without_manifest
from doc_organize.context.document_properties import read_document_properties
from doc_organize.context.domain_classifier import DomainClassifier, MaterialTypeClassifier, read_conversion_json, resolve_title_and_type
from doc_organize.context.language_detection import detect_language
from doc_organize.context.project_profile import compose_profile, profile_prompt_text
from doc_organize.context.reorganizer import assign_organized_paths
from doc_organize.core.constants import UNCLASSIFIED_SLUG
from doc_organize.core.exceptions import AiAuthError, AiConnectionError, AiError, ContextError, ContextNotFoundError
from doc_organize.core.models import (
    CONTEXT_SCHEMA_VERSION,
    LEGACY_FOLDER_AXIS_KEY,
    AiClassificationStopReason,
    AiPhaseStats,
    AiScope,
    AiStats,
    AiTask,
    AxisClassifiedBy,
    AxisValue,
    ClassificationDecision,
    Context,
    ConversionResult,
    DocumentClassification,
    DocumentCredentialFindings,
    DocumentEnrichmentResult,
    Domain,
    DomainDocument,
    DomainStatus,
    Project,
    ProjectProfile,
    PromptProvenance,
    TaxonomyAxis,
    TaxonomyEntry,
    TaxonomyManifest,
    UnclassifiedDocument,
)
from doc_organize.core.progress import CancelToken, Phase, ProgressCallback, ProgressEvent, checkpoint
from doc_organize.projects.layout import ProjectLayout
from doc_organize.utils.logging import get_logger

_DEFAULT_THRESHOLD = 0.5
#: Medido en un NAS por SMB (G44, 2026-11-16): con 4 lecturas a la vez, 28 ms por documento frente a 88 ms de una en
#: una; con 8, apenas mejora y la lectura más lenta se duplica.
_DEFAULT_PROPERTIES_CONCURRENCY = 4

_UNCLASSIFIED_SLUG = UNCLASSIFIED_SLUG
"""Slug placeholder para un eje (dominio o tipo de material) que no alcanza `threshold`
cuando hay un manifiesto de taxonomía activo — el documento se reorganiza igual bajo este
slug en el eje afectado, en vez de excluirse por completo (`unclassified_documents` sigue
reservado a documentos con artefactos incompletos, ver `_classify_with_manifest`). Al
tratarse como un slug de dominio/tipo más, `Reorganizer`/`SiteGenerator` no necesitan
lógica especial: `"sin-clasificar".replace("-", " ").title()` ya da un nombre legible
("Sin Clasificar") igual que cualquier otro slug."""


@dataclass
class _AiRun:
    """Estado de una fase de IA en una construcción (L-3a…L-3c): recuentos, tokens, racha de errores y parada.

    Un documento cuenta como enviado al reservar su llamada (`may_send`; los reintentos del cliente no cuentan aparte),
    así que `sent == classified + failed + enviados sin asignación` siempre.
    """

    max_failures: int | None = None
    max_documents: int | None = None
    sent: int = 0
    classified: int = 0
    failed: int = 0
    consecutive_connection_failures: int = 0
    stopped: AiClassificationStopReason | None = None
    stop_logged: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    response_format: ResponseFormat | None = None
    #: Documentos resueltos con la caché de resultados (no cuentan en `sent` ni consumen presupuesto).
    cached: int = 0
    #: Recuento por documento y regla de lo redactado, compartido por todas las fases de IA de una construcción.
    credential_ledger: dict[str, Counter[str]] | None = None

    def redaction_note(self, source_path: str) -> Callable[[dict[str, int]], None]:
        """Callback para `LlmClient`: anota lo redactado en lo enviado de `source_path` (aunque la llamada falle)."""

        def note(counts: dict[str, int]) -> None:
            if self.credential_ledger is not None:
                self.credential_ledger.setdefault(source_path, Counter()).update(counts)

        return note

    def may_send(self) -> bool:
        """Reserva un envío si se puede; al agotar `max_documents` marca la parada `"budget"` y devuelve `False`."""
        if self.stopped is not None:
            return False
        if self.max_documents is not None and self.sent >= self.max_documents:
            self.stopped = "budget"
            return False
        self.sent += 1
        return True

    def release(self) -> None:
        """Devuelve un envío reservado que no llegó a hacerse (el `.json` no se pudo leer, 2.0.0)."""
        self.sent -= 1

    def record_response(self, result: LlmResult[Any]) -> None:
        """La llamada respondió: corta la racha de errores de conexión y suma sus tokens (el recuento de asignados se
        hace al aplicar el resultado)."""
        self.consecutive_connection_failures = 0
        self.prompt_tokens += result.usage.prompt_tokens or 0
        self.completion_tokens += result.usage.completion_tokens or 0
        self.response_format = result.response_format

    def record_failure(self, exc: AiError) -> None:
        """La llamada falló: `auth` para en el acto; `connection` para tras `max_failures` seguidos."""
        self.failed += 1
        if isinstance(exc, AiAuthError):
            self.stopped = "auth"
        elif isinstance(exc, AiConnectionError):
            self.consecutive_connection_failures += 1
            if self.max_failures is not None and self.consecutive_connection_failures >= self.max_failures:
                self.stopped = "connection"
        else:
            # El servidor respondió (5xx, respuesta mal formada...): no es un error de conexión.
            self.consecutive_connection_failures = 0

    def stats(self) -> AiPhaseStats:
        """Los recuentos de la fase, para `Context.ai_stats`."""
        return AiPhaseStats(
            sent=self.sent,
            assigned=self.classified,
            failed=self.failed,
            stopped=self.stopped,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            response_format=self.response_format,
            cached=self.cached,
        )


@dataclass
class _ReadFacts:
    """Lo que una construcción conserva de la lectura de un `.json` de conversión (2.0.0, B): no el texto."""

    title: str | None
    language: str | None
    #: Propuesta de las reglas por debajo del umbral (modo sin manifiesto), para el detalle de los sin clasificar.
    rules: tuple[str | None, float | None] = (None, None)


@dataclass
class _BuildReads:
    """Hechos de la lectura única de cada `.json` en una construcción, por `json_path` (2.0.0, B)."""

    facts: dict[str, _ReadFacts] = field(default_factory=dict)


def _provenance(llm: LlmClient | None, prompts: PromptRegistry, runs: Sequence[tuple[AiTask, _AiRun]]) -> list[PromptProvenance]:
    """Prompt y modelo de cada tarea que llegó a enviar algún documento o lo resolvió con la caché (2.0.0, G1)."""
    if llm is None:
        return []
    return [prompts.get(task).provenance(llm.model_for(task)) for task, run in runs if run.sent > 0 or run.cached > 0]


def _ai_value(choice: AxisChoice, axis: TaxonomyAxis, threshold: float, *, slugify: Callable[[str], str] = str) -> AxisValue:
    """Un valor elegido por la IA como `AxisValue`, con su cita. Si la cita no aparece en lo enviado, la confianza queda
    por debajo del umbral del eje (D10): el valor se conserva, pero para revisarlo."""
    names = {slugify(entry.slug): entry.name for entry in axis.entries}
    axis_threshold = axis.threshold if axis.threshold is not None else threshold
    confidence = choice.confidence if choice.evidence_verified is not False else min(choice.confidence, max(0.0, axis_threshold - 0.01))
    return AxisValue(
        slug=choice.slug,
        name=names.get(choice.slug, choice.slug),
        confidence=confidence,
        classified_by="ai",
        evidence=choice.evidence,
        evidence_verified=choice.evidence_verified,
    )


def _rules_value(slug: str, names: dict[str, str], confidence: float) -> list[AxisValue]:
    """Valor de un eje organizador asignado por las reglas; vacío si quedó en el marcador «sin clasificar»."""
    if slug == _UNCLASSIFIED_SLUG:
        return []
    return [AxisValue(slug=slug, name=names.get(slug, slug.replace("-", " ").title()), confidence=confidence, classified_by="rules")]


def _classify_single_axis(domains: list[Domain]) -> None:
    """Sin manifiesto hay un solo eje (`domains`): su valor es el dominio del documento, de quien lo clasificó."""
    for domain in domains:
        for document in domain.documents:
            classified_by: AxisClassifiedBy = "ai" if document.classified_by == "ai" else "rules"
            value = AxisValue(slug=domain.slug, name=domain.name, confidence=document.confidence, classified_by=classified_by)
            document.classification = DocumentClassification(axes={LEGACY_FOLDER_AXIS_KEY: [value]})


def _context_axes(manifest: TaxonomyManifest | None, domains: list[Domain]) -> list[TaxonomyAxis]:
    """Los ejes que se guardan en el contexto: los del manifiesto sin `keywords` ni `examples` (no hacen falta para
    leer el resultado y engordarían `context.json`); sin manifiesto, el eje `domains` con los dominios encontrados."""
    if manifest is not None:
        return [
            axis.model_copy(update={"entries": [entry.model_copy(update={"keywords": [], "examples": []}) for entry in axis.entries]})
            for axis in manifest.axes
        ]
    entries = [TaxonomyEntry(slug=domain.slug, name=domain.name, description=domain.description) for domain in domains]
    return [TaxonomyAxis(key=LEGACY_FOLDER_AXIS_KEY, name="Dominios", organizes="folder", entries=entries)] if entries else []


class ContextBuilder:
    """Clasifica los documentos convertidos de un proyecto y persiste el `Context` resultante.

    Dos sub-fases (ver `.ai/sessions/2026-09-08-organizacion-documental-contextos/00_REQUEST.md`):

    - **Sub-fase A** (siempre): `DomainClassifier`, reglas sobre `chunks`/`title`.
    - **Sub-fase B** (opt-in: `build(llm=..., ai_scope="unclassified")`): clasificación con IA, **solo** para
      los documentos que la Sub-fase A deja sin clasificar (en cualquiera de los dos ejes, en
      modo manifiesto), y **solo** eligiendo entre el catálogo ya confirmado por la Sub-fase A
      (el propio catálogo predefinido/manifiesto, o los dominios descubiertos) — nunca crea un
      dominio o tipo de material nuevo. En modo manifiesto, `classify_document`
      resuelve ambos ejes en una sola llamada combinada, pero solo se aplica al eje que seguía
      en el placeholder `sin-clasificar` — un eje que la Sub-fase A ya clasificó con confianza
      nunca se sobreescribe.

    La copia física a `<output_folder_name>/` y la generación del sitio son
    responsabilidad de `Reorganizer`/`SiteGenerator` — este builder no toca
    ficheros fuera de `context.json`/`domains/`.

    Attributes:
        registry (ContextRegistry): Persistencia del contexto construido.
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio, tempfile
        >>> from datetime import UTC, datetime
        >>> from doc_organize.core.models import ConversionResult, Project
        >>> async def main():
        ...     root = tempfile.mkdtemp()
        ...     project = Project(name="Demo", root_path=root, created_at=datetime.now(UTC).isoformat())
        ...     doc = ConversionResult(
        ...         source_path=f"{root}/Ciberseguridad/informe.pdf",
        ...         markdown_path=f"{root}/informe.md",
        ...         json_path=f"{root}/informe.json",
        ...         success=True,
        ...     )
        ...     with open(doc.json_path, "w", encoding="utf-8") as f:
        ...         f.write('{"title": "Informe", "chunks": []}')
        ...     builder = ContextBuilder()
        ...     context = await builder.build(project, [doc])
        ...     return context.domains[0].slug
        >>> asyncio.run(main())  # doctest: +SKIP
        'ciberseguridad'
    """

    def __init__(
        self,
        registry: ContextRegistry | None = None,
        *,
        history_policy: ContextHistoryPolicy | None = None,
        properties_concurrency: int = _DEFAULT_PROPERTIES_CONCURRENCY,
        ai_concurrency: int = 1,
    ) -> None:
        """
        Args:
            registry: Dónde se lee y guarda el contexto (`ContextRegistry()` por defecto).
            history_policy: Giro de `CONTEXT_HISTORY.jsonl` (1.6.0); `None` = `ContextHistoryPolicy()` (5 MB, 4 copias).
            properties_concurrency: Originales cuyas propiedades se leen a la vez (1.6.0). En una carpeta de red, 4
                lecturas a la vez cuestan un tercio que de una en una; `1` = una detrás de otra, como en 1.5.0.
            ai_concurrency: Llamadas a la IA a la vez en cada fase (clasificación y descripción, 2.0.0). `1` = una
                detrás de otra, como en 1.x. Los resultados se aplican en el orden de los documentos: el contexto es el
                mismo con 1 que con 4. `ai_max_documents` nunca se supera; tras alcanzar `ai_max_failures` no se envía
                nada más, pero las llamadas que ya estaban en vuelo pueden sumar hasta `ai_concurrency - 1` fallos. Ante
                respuestas 429, ver los reintentos del cliente.

        La redacción de credenciales de lo que sale hacia la IA la hace `LlmClient` (`AiSettings.redact_credentials`,
        2.0.0); hasta 1.7 era `ContextBuilder(ai_redact_credentials=)`.

        Raises:
            ValueError: Si `properties_concurrency` o `ai_concurrency` es menor que 1.
        """
        if properties_concurrency < 1:
            raise ValueError(f"properties_concurrency debe ser al menos 1, no {properties_concurrency}")
        if ai_concurrency < 1:
            raise ValueError(f"ai_concurrency debe ser al menos 1, no {ai_concurrency}")
        self.ai_concurrency = ai_concurrency
        self.registry = registry or ContextRegistry()
        self.history_policy = history_policy or ContextHistoryPolicy()
        self.properties_concurrency = properties_concurrency
        self.logger = get_logger(__name__)

    async def build(
        self,
        project: Project,
        documents: list[ConversionResult],
        *,
        candidate_domains: list[str] | None = None,
        threshold: float = _DEFAULT_THRESHOLD,
        taxonomy_manifest: TaxonomyManifest | None = None,
        taxonomy_template_name: str | None = None,
        output_folder_name: str = "organizado",
        llm: LlmClient | None = None,
        ai_scope: AiScope = "off",
        enrich: bool = False,
        prompts: PromptRegistry | None = None,
        ai_cache: bool | AiResultCache = True,
        profile: ProjectProfile | None = None,
        decisions: bool | Sequence[ClassificationDecision] = True,
        scan_roots: Sequence[str] | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
        ai_max_failures: int | None = None,
        ai_max_documents: int | None = None,
    ) -> Context:
        """Clasifica `documents` y persiste el contexto de `project`.

        Sin `taxonomy_manifest`: un eje (dominio), por reglas (`DomainClassifier`). Con `taxonomy_manifest`: todos sus
        ejes, por reglas (`_classify_with_manifest`). Con `llm` y `ai_scope="unclassified"`, la IA clasifica después lo
        que las reglas dejaron sin clasificar en un eje organizador (la Sub-fase B de 1.x), eligiendo solo entre el
        catálogo (nunca crea un valor) y sin sustituir nunca lo que decidieron las reglas.

        Args:
            project: Proyecto propietario del contexto.
            documents: Documentos ya convertidos (`converter/`) a clasificar. Con `ConversionResult.source_sha256`, el
                contexto podrá comprobar su frescura (`check_context_freshness`).
            candidate_domains: Catálogo de dominios permitidos, o `None` para descubrirlos de las carpetas. Ignorado si
                se da `taxonomy_manifest` (su catálogo manda).
            threshold: Confianza mínima de las reglas para dar por clasificado un eje.
            taxonomy_manifest: Manifiesto de taxonomía (`load_taxonomy_manifest` o una plantilla), o `None`.
            taxonomy_template_name: Plantilla de la que viene `taxonomy_manifest`, si es de una plantilla (informativo,
                `Context.taxonomy_template_name`).
            output_folder_name: Carpeta de salida reorganizada, relativa a `root_path`; solo tiene efecto en la primera
                construcción (el consumidor reutiliza la persistida).
            llm: Cliente de IA (`LlmClient`). Sin él no se llama a ninguna IA.
            ai_scope: Qué documentos clasifica la IA (se guarda en `Context.ai_stats.scope`): `"off"` (por defecto),
                ninguno; `"unclassified"`, los que las reglas dejaron sin clasificar en algún eje organizador;
                `"missing_axes"` (con manifiesto), además los que tienen vacío algún eje que solo etiqueta. La IA solo
                rellena ejes vacíos: nunca cambia lo que decidieron las reglas.
            enrich: Describir con IA (tarea `enrich`) los documentos clasificados que no declaran descripción o palabras
                clave; solo se rellena lo que falta (`DomainDocument.ai_filled`). El autor nunca sale de la IA.
            prompts: Prompts de cada tarea; por defecto, los del proyecto (`<raíz>/.doc_organize/prompts/`) o los
                empaquetados.
            ai_cache: Caché de resultados de IA (2.0.0): `True` (por defecto) usa la del proyecto
                (`<raíz>/.doc_organize/ai_cache/`), `False` no usa ninguna, o una `AiResultCache` concreta. Con ella,
                reconstruir sin cambios (mismo documento, prompt, modelo, catálogo y redacción) no llama al modelo: el
                resultado se vuelve a validar y cuenta en `AiPhaseStats.cached`, no en `sent`.
            profile: Perfil del proyecto que va en el prompt de clasificación (2.0.0, G2). `None` (por defecto): el de
                `taxonomy_manifest` con el de `<raíz>/.doc_organize/profile.md` añadido detrás (`compose_profile`).
            decisions: Decisiones de personas (2.0.0, F6): `True` (por defecto) aplica las del proyecto
                (`ClassificationDecisionStore`, `<raíz>/.doc_organize/decisions.json`), `False` ninguna, o una lista
                concreta. Se aplican tras las reglas y antes de la IA, solo con `taxonomy_manifest`; lo que no se pudo
                aplicar queda en `Context.stale_decisions`/`orphan_decisions`.
            scan_roots: Raíces de escaneo para las claves de los documentos en las decisiones (`document_key`); por
                defecto, la carpeta común de todos los originales.
            on_progress: Recibe un `ProgressEvent` (`operation="context_build"`, fase `classification` o `enrichment`)
                tras cada documento de una fase de IA (L-2). Un fallo del callback se registra y no para la construcción.
            cancel_token: Si se cancela, la construcción para entre documentos con `OperationCancelledError`, **sin**
                persistir un contexto a medias (L-2).
            ai_max_failures: Una fase de IA se detiene tras este número de errores de conexión **seguidos**
                (`AiPhaseStats.stopped = "connection"`, L-3a); un 401/403 la detiene siempre en el acto (`"auth"`).
            ai_max_documents: Tope de documentos enviados en cada fase de IA (L-3b); al alcanzarlo, `"budget"`.

            Al detenerse una fase, los documentos pendientes no se envían y la construcción termina con normalidad. Los
            recuentos y tokens quedan en `Context.ai_stats`, y el prompt y modelo de cada tarea en
            `Context.ai_provenance`.

        Returns:
            El `Context` construido y ya persistido vía `self.registry`.

        Raises:
            OperationCancelledError: Se canceló con `cancel_token`.
            ValueError: `ai_max_failures < 1`, `ai_max_documents < 0`, o `ai_scope`/`enrich` sin `llm`.
        """
        if ai_max_failures is not None and ai_max_failures < 1:
            raise ValueError("ai_max_failures debe ser >= 1 (o None)")
        if ai_max_documents is not None and ai_max_documents < 0:
            raise ValueError("ai_max_documents debe ser >= 0 (o None)")
        if (ai_scope != "off" or enrich) and llm is None:
            raise ValueError("ai_scope y enrich necesitan un cliente de IA (llm)")
        checkpoint(cancel_token)
        prompts = prompts if prompts is not None else PromptRegistry(project.root_path)
        cache = ai_cache if isinstance(ai_cache, AiResultCache) else (AiResultCache(project.root_path) if ai_cache and llm is not None else None)
        human_decisions = await self._load_decisions(project, decisions)
        if profile is None:
            profile = compose_profile(taxonomy_manifest.profile if taxonomy_manifest is not None else None, project.root_path)
        profile_text = profile_prompt_text(profile)
        credential_ledger: dict[str, Counter[str]] = {}
        ai_run = _AiRun(max_failures=ai_max_failures, max_documents=ai_max_documents, credential_ledger=credential_ledger)
        enrichment_run = _AiRun(max_failures=ai_max_failures, max_documents=ai_max_documents, credential_ledger=credential_ledger)

        def _report(phase: Phase, index: int, total: int, source_path: str) -> None:
            if on_progress is not None:
                try:
                    on_progress(ProgressEvent(operation="context_build", phase=phase, processed=index, total=total, current=source_path))
                except Exception as exc:  # noqa: BLE001 - un callback del consumidor nunca debe parar la operación
                    self.logger.warning(f"El callback de progreso falló: {type(exc).__name__}: {exc}")
            checkpoint(cancel_token)  # L-2: parada entre documentos de una fase de IA

        async def _ai_progress(index: int, total: int, source_path: str) -> None:
            _report("classification", index, total, source_path)

        async def _enrichment_progress(index: int, total: int, source_path: str) -> None:
            _report("enrichment", index, total, source_path)

        reads = _BuildReads()  # lectura única de cada `.json` para todo lo que no es IA (2.0.0, B)
        if taxonomy_manifest is not None:
            classified, unclassified = await self._classify_with_manifest(
                documents, taxonomy_manifest, threshold, reads=reads, cancel_token=cancel_token
            )
            decision_outcome = apply_decisions(
                human_decisions, classified, unclassified, taxonomy_manifest, slugify=DomainClassifier._slugify, roots=scan_roots
            )
            if llm is not None and ai_scope != "off":
                classified = await self._classify_with_manifest_ai(
                    llm,
                    prompts,
                    classified,
                    taxonomy_manifest,
                    on_progress=_ai_progress,
                    run=ai_run,
                    cache=cache,
                    scope=ai_scope,
                    threshold=threshold,
                    profile=profile_text,
                    locked=decision_outcome.locked,
                )
        else:
            decision_outcome = not_applied_without_manifest(human_decisions)
            classifier = DomainClassifier(candidate_domains=candidate_domains, threshold=threshold)
            classified, unclassified = await self._classify_by_rules(documents, classifier, reads, cancel_token)
            if llm is not None and ai_scope != "off" and unclassified:
                classified, unclassified = await self._classify_with_ai(
                    llm, prompts, classified, unclassified, classifier, on_progress=_ai_progress, run=ai_run, cache=cache, profile=profile_text
                )

        unclassified_details = self._describe_unclassified(unclassified, reads)
        await self._apply_document_properties(classified, unclassified_details, reads, cancel_token)
        if llm is not None and enrich:
            await self._enrich_with_ai(llm, prompts, classified, on_progress=_enrichment_progress, run=enrichment_run, cache=cache)

        has_predefined_catalog = bool(candidate_domains) or taxonomy_manifest is not None
        manifest_domains_by_slug = (
            {DomainClassifier._slugify(entry.slug): entry for entry in taxonomy_manifest.folder_axis.entries} if taxonomy_manifest is not None else {}
        )
        domains = [
            Domain(
                slug=slug,
                name=manifest_domains_by_slug[slug].name if slug in manifest_domains_by_slug else slug.replace("-", " ").title(),
                description=manifest_domains_by_slug[slug].description if slug in manifest_domains_by_slug else None,
                status=DomainStatus.CONFIRMED if has_predefined_catalog else DomainStatus.DRAFT,
                predefined=has_predefined_catalog,
                documents=domain_documents,
            )
            for slug, domain_documents in classified.items()
        ]
        if taxonomy_manifest is None:
            _classify_single_axis(domains)

        now = datetime.now(UTC).isoformat()
        context = Context(
            schema_version=CONTEXT_SCHEMA_VERSION,
            taxonomy_axes=_context_axes(taxonomy_manifest, domains),
            project_name=project.name,
            output_folder_name=output_folder_name,
            ai_fallback_threshold=threshold,
            built_with_version=__version__,
            domains=domains,
            decisions_applied=decision_outcome.applied,
            stale_decisions=decision_outcome.stale,
            orphan_decisions=decision_outcome.orphan,
            excluded_documents=decision_outcome.excluded,
            unclassified_documents=[document.source_path for document in unclassified],
            unclassified_details=unclassified_details,
            taxonomy_manifest_used=taxonomy_manifest is not None,
            taxonomy_template_name=taxonomy_template_name,
            ai_stats=AiStats(scope=ai_scope, enrich=enrich, classification=ai_run.stats(), enrichment=enrichment_run.stats()),
            ai_provenance=_provenance(llm, prompts, [("classify", ai_run), ("enrich", enrichment_run)]),
            ai_redact_credentials=llm.settings.redact_credentials if llm is not None else True,
            credential_findings=[
                DocumentCredentialFindings(source_path=source_path, rules=dict(sorted(counts.items())))
                for source_path, counts in sorted(credential_ledger.items())
            ],
            created_at=now,
            updated_at=now,
        )
        assign_organized_paths(context, project.root_path)  # L-8d: ruta final de cada documento, para el consumidor
        checkpoint(cancel_token)  # nunca se persiste un contexto a medias
        await self._save_and_record(project, context)
        self.logger.info(f"Contexto construido para '{project.name}': {len(domains)} dominio(s), {len(unclassified)} documento(s) sin clasificar")
        return context

    async def _read_conversions[T](
        self,
        documents: Sequence[ConversionResult],
        process: Callable[[ConversionResult, str, str | None], T],
        reads: _BuildReads | None,
        cancel_token: CancelToken | None,
    ) -> list[T | None]:
        """Lee el `.json` de conversión de cada documento **una sola vez** para todo lo que no es IA (2.0.0, B).

        Con hasta `properties_concurrency` lecturas a la vez (en una carpeta de red es lo que más cuesta). `process`
        (clasificar por reglas) corre en un hilo junto a la detección del idioma, y de cada documento solo se guarda el
        resultado, no el texto. Devuelve un resultado por documento, en el orden de `documents`: `None` si le falta algún
        artefacto o su `.json` no se puede leer. Los hechos de la lectura (título, idioma, propuesta de las reglas) quedan
        en `reads` para describir después los documentos sin volver a leerlos.
        """
        results: list[T | None] = [None] * len(documents)

        async def read(item: tuple[int, ConversionResult]) -> None:
            index, document = item
            if not document.success or not document.markdown_path or not document.json_path:
                return
            conversion = await read_conversion_json(document.json_path)
            if conversion is None:
                return
            chunks_text, title = conversion

            def work() -> tuple[T, str | None]:
                return process(document, chunks_text, title), detect_language(f"{title or ''}\n{chunks_text}")

            results[index], language = await asyncio.to_thread(work)
            if reads is not None:
                reads.facts[document.json_path] = _ReadFacts(title=title, language=language)

        await self._for_each_bounded(list(enumerate(documents)), read, cancel_token)
        return results

    async def _classify_by_rules(
        self, documents: list[ConversionResult], classifier: DomainClassifier, reads: _BuildReads, cancel_token: CancelToken | None
    ) -> tuple[dict[str, list[DomainDocument]], list[ConversionResult]]:
        """Sub-fase A sin manifiesto: lo mismo que `DomainClassifier.classify`, con la lectura única de `_read_conversions`.

        De los que quedan por debajo del umbral, la propuesta de las reglas queda en `reads` (la usa
        `_describe_unclassified`).
        """

        def score(document: ConversionResult, chunks_text: str, title: str | None) -> tuple[str | None, float, str | None]:
            slug, value = classifier.score_domain(document, chunks_text, title)
            return slug, value, title

        scores = await self._read_conversions(documents, score, reads, cancel_token)
        classified: dict[str, list[DomainDocument]] = {}
        unclassified: list[ConversionResult] = []
        for document, scored in zip(documents, scores, strict=True):
            if scored is None:
                unclassified.append(document)
                continue
            slug, value, title = scored
            if slug is None or value < classifier.threshold:
                unclassified.append(document)
                if document.json_path in reads.facts:
                    reads.facts[document.json_path].rules = (slug, value)
                continue
            resolved_title, document_type = resolve_title_and_type(document, title)
            classified.setdefault(slug, []).append(
                DomainDocument(
                    source_path=document.source_path,
                    markdown_path=document.markdown_path,
                    json_path=document.json_path,  # type: ignore[arg-type]  # leído: no es None
                    images_dir=document.images_dir,
                    source_sha256=document.source_sha256,
                    title=resolved_title,
                    document_type=document_type,
                    confidence=value,
                    classified_by="rules",
                    rules_domain=slug,
                    rules_confidence=value,
                )
            )
        return classified, unclassified

    async def _classify_with_manifest(
        self,
        documents: list[ConversionResult],
        manifest: TaxonomyManifest,
        threshold: float,
        *,
        reads: _BuildReads | None = None,
        cancel_token: CancelToken | None = None,
    ) -> tuple[dict[str, list[DomainDocument]], list[ConversionResult]]:
        """Clasifica `documents` en todos los ejes de `manifest`, solo por reglas (Sub-fase A).

        A diferencia del modo de un eje (`DomainClassifier.classify()`), un documento con
        los tres artefactos completos SIEMPRE se reorganiza aquí: si un eje organizador no alcanza
        `threshold`, se le asigna el slug placeholder `_UNCLASSIFIED_SLUG` en ese eje en vez
        de excluir el documento por completo — decisión de negocio explícita de esta
        sesión (manifiesto de taxonomía). Solo un documento con algún artefacto incompleto
        (falta original/`.md`/`.json`) queda en `unclassified_documents`, igual criterio que
        el modo de un eje. La Sub-fase B, si está activa, se aplica después vía
        `_classify_with_manifest_ai` sobre el resultado de este método. Cada `.json` se lee una vez
        (`_read_conversions`); el idioma queda ya en cada `DomainDocument`.
        """
        domain_slugs = [entry.slug for entry in manifest.folder_axis.entries]
        material_slugs = [entry.slug for entry in manifest.subfolder_axis.entries]
        domain_classifier = DomainClassifier(candidate_domains=domain_slugs, threshold=threshold)
        material_classifier = MaterialTypeClassifier(material_slugs, threshold=threshold)

        # `entry.slug` saneado (no el original tal cual) porque es la clave por la que
        # `score_catalog()` busca en `extra_keywords` — debe coincidir con los slugs ya
        # saneados en `domain_classifier.candidate_domains`/`material_classifier.material_types`
        # (AUDIT_CODE: antes de esto, `TaxonomyEntry.keywords` se leía del manifiesto
        # pero no se usaba nunca en la puntuación).
        domain_keywords = {DomainClassifier._slugify(entry.slug): entry.keywords for entry in manifest.folder_axis.entries if entry.keywords}
        material_keywords = {DomainClassifier._slugify(entry.slug): entry.keywords for entry in manifest.subfolder_axis.entries if entry.keywords}

        # Mismo saneado que `domain_keywords`/`material_keywords`, para el mismo motivo:
        # `TaxonomyEntry.name` (nombre legible declarado en el manifiesto) se leía
        # pero nunca se propagaba a `DomainDocument.material_type_name` — `SiteGenerator`
        # acababa derivando la etiqueta del nav del slug (`"normativa" -> "Normativa"`) en vez
        # de usar el nombre declarado (AUDIT_CODE, mismo hallazgo que `Domain.name`/`.description`
        # en `build()`).
        material_names = {DomainClassifier._slugify(entry.slug): entry.name for entry in manifest.subfolder_axis.entries}
        domain_names = {DomainClassifier._slugify(entry.slug): entry.name for entry in manifest.folder_axis.entries}
        # 2.0.0 (A2): los ejes que solo etiquetan, con su propio puntuador por palabra completa; los organizadores
        # siguen con `score_catalog` (mismo resultado que 1.x).
        tag_scorers = [AxisRuleScorer(axis, threshold) for axis in manifest.tag_axes]

        def classify(document: ConversionResult, chunks_text: str, title: str | None) -> tuple[str, DomainDocument]:
            rules_domain, domain_score = domain_classifier.score_domain(document, chunks_text, title, extra_keywords=domain_keywords)
            domain_slug = rules_domain if rules_domain is not None and domain_score >= threshold else _UNCLASSIFIED_SLUG

            material_slug, material_score = material_classifier.classify_text(title=title, chunks_text=chunks_text, extra_keywords=material_keywords)
            if material_slug is None:
                material_slug = _UNCLASSIFIED_SLUG

            axes = {
                manifest.folder_axis.key: _rules_value(domain_slug, domain_names, domain_score),
                manifest.subfolder_axis.key: _rules_value(material_slug, material_names, material_score),
            }
            if tag_scorers:
                folded = FoldedText.of(title, chunks_text[:TAG_AXIS_TEXT_CHARS])
                axes.update({scorer.axis.key: scorer.classify(folded) for scorer in tag_scorers})

            resolved_title, document_type = resolve_title_and_type(document, title)
            return domain_slug, DomainDocument(
                source_path=document.source_path,
                markdown_path=document.markdown_path,  # type: ignore[arg-type]  # leído: no es None
                json_path=document.json_path,  # type: ignore[arg-type]
                images_dir=document.images_dir,
                source_sha256=document.source_sha256,
                title=resolved_title,
                document_type=document_type,
                material_type=material_slug,
                material_type_name=material_names.get(material_slug),
                confidence=domain_score,
                classified_by="rules",
                rules_domain=rules_domain,
                rules_confidence=domain_score,
                material_type_confidence=material_score,
                classification=DocumentClassification(axes=axes),
            )

        reads = reads if reads is not None else _BuildReads()
        results = await self._read_conversions(documents, classify, reads, cancel_token)
        classified: dict[str, list[DomainDocument]] = {}
        unclassified: list[ConversionResult] = []
        for document, result in zip(documents, results, strict=True):
            if result is None:
                unclassified.append(document)
                continue
            domain_slug, domain_document = result
            domain_document.language = reads.facts[domain_document.json_path].language
            classified.setdefault(domain_slug, []).append(domain_document)
        return classified, unclassified

    async def _run_ai_phase[T, R](
        self,
        items: Sequence[T],
        call: Callable[[T], Awaitable[R | None]],
        run: _AiRun,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None,
        path_of: Callable[[T], str],
        *,
        stage: str = "Sub-fase B detenida",
        outcome: str = "quedan sin clasificar",
    ) -> list[R | None]:
        """Una fase de IA con hasta `ai_concurrency` llamadas a la vez (2.0.0, B).

        `call` hace la llamada de un elemento y devuelve lo que haya que aplicar; el llamador lo aplica **después**, en
        el orden de `items`, para que el resultado no dependa del orden de llegada (`context.json` idéntico con 1 y con
        4). Tras parar la fase (`run.stopped`) no se despacha nada más; las llamadas en vuelo terminan y su resultado se
        conserva, así que con `ai_concurrency > 1` puede haber hasta `ai_concurrency - 1` fallos más que
        `ai_max_failures`. El progreso cuenta los terminados (monótono). Con `ai_concurrency=1`, mismas llamadas y en
        el mismo orden que 1.x.
        """
        results: list[R | None] = [None] * len(items)
        finished = 0

        async def attempt(item: tuple[int, T]) -> None:
            nonlocal finished
            index, value = item
            if run.stopped is None:
                results[index] = await call(value)
            finished += 1
            self._log_stop(run, len(items) - finished, stage=stage, outcome=outcome)
            if on_progress is not None:
                await on_progress(finished, len(items), path_of(value))

        await self._for_each_bounded(list(enumerate(items)), attempt, None, limit=self.ai_concurrency)
        return results

    async def _classify_with_manifest_ai(
        self,
        llm: LlmClient,
        prompts: PromptRegistry,
        classified: dict[str, list[DomainDocument]],
        manifest: TaxonomyManifest,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
        run: _AiRun | None = None,
        cache: AiResultCache | None = None,
        *,
        scope: AiScope = "unclassified",
        threshold: float = _DEFAULT_THRESHOLD,
        profile: str = "",
        locked: dict[int, set[str]] | None = None,
    ) -> dict[str, list[DomainDocument]]:
        """Clasificación con IA en modo manifiesto (2.0.0, G1.4).

        - `scope="unclassified"`: documentos que las reglas dejaron con el placeholder `_UNCLASSIFIED_SLUG` en el eje de
          dominio y/o en el de tipo de material (la Sub-fase B de 1.x).
        - `scope="missing_axes"`: además, los que tienen **vacío** algún eje que solo etiqueta (también los de
          `rules: false`).

        Una llamada por documento con los ejes que le faltan (los dos organizadores si falta alguno, para conservar la
        propuesta de la IA en `ai_domain`). Solo se aplica a lo que estaba vacío: nunca sustituye lo que decidieron las
        reglas (E1-E5). En los ejes que etiquetan, los valores de la IA pasan por el umbral del eje (E4). Una cita que no
        aparece en lo enviado deja la confianza por debajo del umbral (D10); el valor se conserva para revisarlo.

        `DomainDocument.classified_by` pasa a `"ai"` si la IA cambió al menos un eje. Las llamadas pueden ir varias a la
        vez (`ai_concurrency`); los resultados se aplican en el orden de los documentos.
        """
        folder, subfolder = manifest.folder_axis, manifest.subfolder_axis
        requests_by_key = {axis.key: AxisRequest.from_axis(axis, DomainClassifier._slugify if axis.organizes else str) for axis in manifest.axes}
        terms_by_key = {axis.key: [term for entry in axis.entries for term in (entry.name, *entry.keywords)] for axis in manifest.axes}

        def missing(domain_slug: str, document: DomainDocument) -> list[str]:
            keys = []
            if domain_slug == _UNCLASSIFIED_SLUG or document.material_type == _UNCLASSIFIED_SLUG:
                keys += [folder.key, subfolder.key]
            if scope == "missing_axes":
                keys += [axis.key for axis in manifest.tag_axes if not document.classification.axes.get(axis.key)]
            decided = (locked or {}).get(id(document), set())  # lo que decidió una persona no se pregunta (F6)
            return [key for key in keys if key not in decided]

        pending = [
            (domain_slug, document, keys)
            for domain_slug, documents in classified.items()
            for document in documents
            if (keys := missing(domain_slug, document))
        ]
        if not pending:
            return classified

        ai_run = run if run is not None else _AiRun()

        def request_for(keys: list[str]) -> Callable[[ConversionDocument, str], TaskRequest[ClassificationAnswer]]:
            def request(conversion: ConversionDocument, source_path: str) -> TaskRequest[ClassificationAnswer]:
                excerpt = build_document_excerpt(
                    conversion,
                    folder=str(Path(source_path).parent),
                    metadata={"Tipo de fichero": Path(source_path).suffix.lstrip(".").lower() or None},
                    catalog_terms=[term for key in keys for term in terms_by_key[key]],
                )
                return classification_request(
                    prompts, axes=[requests_by_key[key] for key in keys], title=conversion.title, content=excerpt, profile=profile
                )

            return request

        hits = await self._cache_hits(llm, cache, [(document.json_path, document.source_path, request_for(keys)) for _, document, keys in pending])

        async def call(item: tuple[tuple[str, DomainDocument, list[str]], bool]) -> ClassificationAnswer | None:
            (_, document, keys), cached = item
            asked = await self._ask_ai(llm, ai_run, cache, document, request_for(keys), cached=cached, failure="Falló la clasificación por IA de")
            return asked[0] if asked is not None else None

        results = await self._run_ai_phase(list(zip(pending, hits, strict=True)), call, ai_run, on_progress, lambda item: item[0][1].source_path)
        for (old_domain_slug, document, _keys), answer in zip(pending, results, strict=True):
            if answer is not None:
                self._apply_manifest_ai(document, old_domain_slug, answer, classified, manifest, ai_run, threshold)

        # Poda buckets que quedaron vacíos (p.ej. todo "sin-clasificar" se resolvió a otros
        # dominios) — sin esto, `build()` crearía un `Domain` fantasma sin documentos.
        return {slug: documents for slug, documents in classified.items() if documents}

    async def _load_decisions(self, project: Project, decisions: bool | Sequence[ClassificationDecision]) -> list[ClassificationDecision]:
        """Las decisiones de esta construcción: las del proyecto (`True`), ninguna (`False`) o las dadas. Un fichero de
        decisiones ilegible se registra y no para la construcción (como si no hubiera decisiones)."""
        if decisions is False:
            return []
        if decisions is True:
            try:
                return await ClassificationDecisionStore(project.root_path).load()
            except (OSError, ValueError) as exc:
                self.logger.warning(f"No se pudieron leer las decisiones del proyecto: {type(exc).__name__}: {exc}")
                return []
        return list(decisions)

    async def _cache_hits[T](
        self,
        llm: LlmClient,
        cache: AiResultCache | None,
        items: Sequence[tuple[str | None, str, Callable[[ConversionDocument, str], TaskRequest[T]]]],
    ) -> list[bool]:
        """Qué documentos tienen ya su respuesta en la caché (2.0.0, G1), sin enviar nada. `items`: por documento, su
        `.json`, su original y cómo se arma su petición.

        Se mira **antes** de la fase de IA para que los aciertos no consuman presupuesto y el reparto del presupuesto entre
        los demás siga en el orden de los documentos.
        """
        hits = [False] * len(items)
        if cache is None:
            return hits

        async def check(item: tuple[int, tuple[str | None, str, Callable[[ConversionDocument, str], TaskRequest[T]]]]) -> None:
            index, (json_path, source_path, make_request) = item
            conversion = await read_conversion_document(json_path) if json_path else None
            if conversion is not None:
                hits[index] = cache.has(make_request(conversion, source_path).cache_key(llm))

        await self._for_each_bounded(list(enumerate(items)), check, None)
        return hits

    async def _ask_ai[T](
        self,
        llm: LlmClient,
        run: _AiRun,
        cache: AiResultCache | None,
        document: ConversionResult | DomainDocument,
        make_request: Callable[[ConversionDocument, str], TaskRequest[T]],
        *,
        cached: bool,
        failure: str,
    ) -> tuple[T, ConversionDocument] | None:
        """Una petición de una fase de IA para `document`: la respuesta validada y el `.json` leído; `None` si no hubo
        presupuesto, el `.json` no se pudo leer o la llamada falló (anotado en `run`).

        Un documento ya en caché (`cached`) no reserva presupuesto ni llama al modelo; los demás reservan antes de leer
        (`_reserve_and_read`) y su respuesta se guarda en la caché.
        """
        conversion = await read_conversion_document(document.json_path) if cached and document.json_path else None
        if not cached:
            conversion = await self._reserve_and_read(document.json_path, run)
        if conversion is None:
            return None
        try:
            result = await make_request(conversion, document.source_path).send(llm, on_redacted=run.redaction_note(document.source_path), cache=cache)
        except AiError as exc:
            if cached:
                run.sent += 1  # la entrada desapareció entre la comprobación y la llamada: fue una llamada de verdad
            run.record_failure(exc)
            self.logger.warning(f"{failure} '{document.source_path}': {exc}")
            return None
        if result.cached:
            run.cached += 1
            if not cached:
                run.release()  # reservado, pero lo resolvió la caché (la escribió otra llamada en vuelo)
        else:
            if cached:
                run.sent += 1  # la entrada desapareció entre la comprobación y la llamada
            run.record_response(result)
        return result.value, conversion

    async def _reserve_and_read(self, json_path: str | None, run: _AiRun) -> ConversionDocument | None:
        """El `.json` de un documento para enviarlo a la IA, si hay presupuesto; `None` si no.

        El envío se reserva **antes** de leer (`may_send`), para que con varias llamadas a la vez el presupuesto se
        reparta en el orden de los documentos y no en el de las lecturas; si el `.json` no se puede leer, se devuelve.
        """
        if not json_path or not run.may_send():
            return None
        conversion = await read_conversion_document(json_path)
        if conversion is None:
            run.release()
        return conversion

    def _apply_manifest_ai(
        self,
        document: DomainDocument,
        old_domain_slug: str,
        answer: ClassificationAnswer,
        classified: dict[str, list[DomainDocument]],
        manifest: TaxonomyManifest,
        run: _AiRun,
        threshold: float = _DEFAULT_THRESHOLD,
    ) -> None:
        """Aplica la respuesta de la IA a `document` y a `classified`, solo en los ejes que estaban vacíos: mueve el
        documento de bucket si el eje de dominio cambió, o lo muta in-place si cambió otro. Lo que cambia queda en
        `document.classification` con `classified_by="ai"` y su cita."""
        folder, subfolder = manifest.folder_axis, manifest.subfolder_axis
        axes = document.classification.axes
        changed = False
        domain = answer.axes.get(folder.key)
        if domain is not None:
            document.ai_domain = domain.slug
            document.ai_confidence = domain.confidence
            document.ai_reasoning = answer.reasoning
            if old_domain_slug == _UNCLASSIFIED_SLUG and domain.choices:
                value = _ai_value(domain.choices[0], folder, threshold, slugify=DomainClassifier._slugify)
                classified[old_domain_slug] = [candidate for candidate in classified[old_domain_slug] if candidate is not document]
                document.confidence = value.confidence
                classified.setdefault(value.slug, []).append(document)
                axes[folder.key] = [value]
                changed = True
        material = answer.axes.get(subfolder.key)
        if material is not None and document.material_type == _UNCLASSIFIED_SLUG and material.choices:
            value = _ai_value(material.choices[0], subfolder, threshold, slugify=DomainClassifier._slugify)
            document.material_type = value.slug
            document.material_type_name = value.name if value.name != value.slug else None
            document.material_type_confidence = value.confidence
            axes[subfolder.key] = [value]
            changed = True
        for axis in manifest.tag_axes:
            tag = answer.axes.get(axis.key)
            if tag is None or axes.get(axis.key):
                continue  # no se pidió, o ya tiene valores: nunca se sustituyen
            axis_threshold = axis.threshold if axis.threshold is not None else threshold
            values = [_ai_value(choice, axis, threshold) for choice in tag.choices if choice.confidence >= axis_threshold]
            if values:
                axes[axis.key] = values
                changed = True
        if changed:
            document.classified_by = "ai"
            run.classified += 1

    async def _classify_with_ai(
        self,
        llm: LlmClient,
        prompts: PromptRegistry,
        classified: dict[str, list[DomainDocument]],
        unclassified: list[ConversionResult],
        rules: DomainClassifier,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
        run: _AiRun | None = None,
        cache: AiResultCache | None = None,
        *,
        profile: str = "",
    ) -> tuple[dict[str, list[DomainDocument]], list[ConversionResult]]:
        """Clasificación con IA sin manifiesto (`ai_scope="unclassified"`): lo que las reglas dejaron sin clasificar,
        eligiendo solo entre el catálogo ya confirmado (el predefinido, o los dominios que las reglas descubrieron),
        nunca uno nuevo.

        `rules` es el clasificador de las reglas: da el catálogo y la propuesta que dejaron por debajo del umbral
        (`DomainDocument.rules_domain`/`rules_confidence`). Las llamadas pueden ir varias a la vez (`ai_concurrency`);
        los resultados se aplican en el orden de los documentos.
        """
        catalog = rules.candidate_domains if rules.candidate_domains else list(classified.keys())
        if not catalog:
            return classified, unclassified

        ai_run = run if run is not None else _AiRun()

        def request(conversion: ConversionDocument, source_path: str) -> TaskRequest[ClassificationAnswer]:
            excerpt = build_document_excerpt(conversion, folder=str(Path(source_path).parent), catalog_terms=catalog)
            return classification_request(
                prompts, axes=[AxisRequest.from_slugs(LEGACY_FOLDER_AXIS_KEY, catalog)], title=conversion.title, content=excerpt, profile=profile
            )

        hits = await self._cache_hits(
            llm,
            cache,
            [
                (document.json_path if document.success and document.markdown_path else None, document.source_path, request)
                for document in unclassified
            ],
        )

        async def call(item: tuple[ConversionResult, bool]) -> tuple[str, DomainDocument] | None:
            document, cached = item
            return await self._try_classify_document_with_ai(llm, request, document, rules, ai_run, cache, cached=cached)

        results = await self._run_ai_phase(list(zip(unclassified, hits, strict=True)), call, ai_run, on_progress, lambda item: item[0].source_path)
        still_unclassified: list[ConversionResult] = []
        for document, assigned in zip(unclassified, results, strict=True):
            if assigned is None:
                still_unclassified.append(document)
            else:
                slug, domain_document = assigned
                classified.setdefault(slug, []).append(domain_document)
        return classified, still_unclassified

    async def _try_classify_document_with_ai(
        self,
        llm: LlmClient,
        request: Callable[[ConversionDocument, str], TaskRequest[ClassificationAnswer]],
        document: ConversionResult,
        rules: DomainClassifier,
        run: _AiRun,
        cache: AiResultCache | None,
        *,
        cached: bool,
    ) -> tuple[str, DomainDocument] | None:
        if not document.success or not document.markdown_path or not document.json_path:
            return None
        asked = await self._ask_ai(llm, run, cache, document, request, cached=cached, failure="Falló la clasificación por IA de")
        if asked is None:
            return None
        value, conversion = asked
        chunks_text, title = conversion.text, conversion.title
        answer = value.axes[LEGACY_FOLDER_AXIS_KEY]
        if answer.slug is None:
            return None
        run.classified += 1
        resolved_title, document_type = resolve_title_and_type(document, title)
        rules_domain, rules_confidence = rules.score_domain(document, chunks_text, title)
        return answer.slug, DomainDocument(
            source_path=document.source_path,
            markdown_path=document.markdown_path,
            json_path=document.json_path,
            images_dir=document.images_dir,
            source_sha256=document.source_sha256,
            title=resolved_title,
            document_type=document_type,
            confidence=answer.confidence,
            classified_by="ai",
            rules_domain=rules_domain,
            rules_confidence=rules_confidence,
            ai_domain=answer.slug,
            ai_confidence=answer.confidence,
            ai_reasoning=value.reasoning,
        )

    async def _save_and_record(self, project: Project, context: Context) -> None:
        """Persiste `context` y añade la construcción al histórico (`ProjectLayout.context_history`, 1.5.0).

        El contexto anterior se lee antes de sobrescribirlo, para registrar qué documentos cambiaron y para conservar
        su `created_at` (1.6.0): reconstruir actualiza `updated_at`, no la fecha de creación. Si no se puede leer
        (dañado), se compara con nada, `created_at` queda en la hora de esta construcción y la construcción no falla;
        si el histórico no se puede escribir, se avisa y el contexto ya guardado se mantiene.
        """
        try:
            previous: Context | None = await self.registry.load_context(project)
        except ContextNotFoundError:
            previous = None
        except ContextError as exc:
            self.logger.warning(f"No se pudo leer el contexto anterior de '{project.name}' para el histórico: {exc}")
            previous = None

        if previous is not None:
            context.created_at = previous.created_at
        await self.registry.save_context(project, context)
        try:
            await append_context_build(ProjectLayout.for_project(project).context_history, build_record(previous, context), self.history_policy)
        except OSError as exc:
            self.logger.warning(f"No se pudo añadir la construcción al histórico del contexto de '{project.name}': {exc}")

    def _describe_unclassified(self, unclassified: list[ConversionResult], reads: _BuildReads) -> list[UnclassifiedDocument]:
        """Motivo, título, propuesta de las reglas e idioma de cada documento sin clasificar (1.6.0, G42), en el orden de
        `unclassified`. Autor, descripción y palabras clave los rellena después `_apply_document_properties`.

        Sin `.md`/`.json` o con un `.json` ilegible, `"incomplete_artifacts"`; si no, `"below_threshold"`, con lo que
        propusieron las reglas (vacío en modo manifiesto, donde solo quedan sin clasificar los incompletos). Todo sale
        de la lectura de la Sub-fase A (`reads`): no se vuelve a leer ningún `.json` (2.0.0, B).
        """
        details: list[UnclassifiedDocument] = []
        for document in unclassified:
            facts = reads.facts.get(document.json_path) if document.success and document.markdown_path and document.json_path else None
            if facts is None:
                title, document_type = resolve_title_and_type(document, None)
                details.append(
                    UnclassifiedDocument(
                        source_path=document.source_path,
                        title=title or None,
                        document_type=document_type,
                        markdown_path=document.markdown_path,
                        json_path=document.json_path,
                        reason="incomplete_artifacts",
                        source_sha256=document.source_sha256,
                    )
                )
                continue
            title, document_type = resolve_title_and_type(document, facts.title)
            rules_domain, rules_confidence = facts.rules
            details.append(
                UnclassifiedDocument(
                    source_path=document.source_path,
                    title=title or None,
                    document_type=document_type,
                    markdown_path=document.markdown_path,
                    json_path=document.json_path,
                    reason="below_threshold",
                    source_sha256=document.source_sha256,
                    rules_domain=rules_domain,
                    rules_confidence=rules_confidence if rules_domain is not None else None,
                    language=facts.language,
                )
            )
        return details

    async def _apply_document_properties(
        self,
        classified: dict[str, list[DomainDocument]],
        unclassified: list[UnclassifiedDocument],
        reads: _BuildReads,
        cancel_token: CancelToken | None,
    ) -> None:
        """Rellena `author`, `description` y `keywords` con lo que declara cada documento original, y `language` con
        el idioma detectado en su texto convertido al clasificarlo (1.5.0; desde 2.0.0 sin volver a leer el `.json`).
        Los originales de los sin clasificar se leen en la misma pasada (1.6.0); su idioma ya lo puso
        `_describe_unclassified`.

        Un original ilegible o borrado deja los campos vacíos (`read_document_properties` no lanza). Los originales se
        leen de `properties_concurrency` en `properties_concurrency` (1.6.0).
        """
        documents = [document for domain_documents in classified.values() for document in domain_documents]
        await self._read_properties([*documents, *unclassified], cancel_token)
        for document in documents:
            facts = reads.facts.get(document.json_path)
            if facts is not None:
                document.language = facts.language

    async def _read_properties(self, documents: Sequence[DomainDocument | UnclassifiedDocument], cancel_token: CancelToken | None) -> None:
        """Autor, descripción y palabras clave de cada original, con hasta `properties_concurrency` lecturas a la vez.

        Si se cancela, se propaga la misma excepción que en 1.5.0 (ver `_for_each_bounded`).
        """

        async def read(document: DomainDocument | UnclassifiedDocument) -> None:
            properties = await asyncio.to_thread(read_document_properties, document.source_path)
            document.author = properties.author
            document.description = properties.description
            document.keywords = list(properties.keywords)

        await self._for_each_bounded(documents, read, cancel_token)

    async def _for_each_bounded[T](
        self, items: Sequence[T], action: Callable[[T], Awaitable[None]], cancel_token: CancelToken | None, *, limit: int | None = None
    ) -> None:
        """`action` sobre cada elemento de `items`, con hasta `limit` a la vez (`properties_concurrency` por defecto).

        Cada tarea toma el siguiente elemento pendiente, en orden, y comprueba la cancelación antes de empezarlo. Si una
        falla, las demás se detienen y se propaga la primera excepción tal cual (no un `ExceptionGroup`, para que la
        cancelación siga siendo `OperationCancelledError`); las demás distintas, si las hay, se registran como aviso.
        """
        pending = iter(items)

        async def worker() -> None:
            for item in pending:  # iterador compartido: el bucle de eventos no cambia de tarea dentro de next()
                checkpoint(cancel_token)
                await action(item)

        try:
            async with asyncio.TaskGroup() as group:
                for _ in range(min(limit or self.properties_concurrency, len(items))):
                    group.create_task(worker())
        except BaseExceptionGroup as errors:
            first, *others = errors.exceptions
            for other in others:
                if type(other) is not type(first):
                    self.logger.warning(f"Otro error a la vez que {type(first).__name__}: {type(other).__name__}: {other}")
            raise first from None

    async def _enrich_with_ai(
        self,
        llm: LlmClient,
        prompts: PromptRegistry,
        classified: dict[str, list[DomainDocument]],
        on_progress: Callable[[int, int, str], Awaitable[None]],
        run: _AiRun,
        cache: AiResultCache | None = None,
    ) -> None:
        """Pide a la IA la descripción y las palabras clave de los documentos que no las declaran (tarea `enrich`).

        Solo rellena lo que falta; lo declarado por el documento nunca se sustituye. Mismas paradas que la
        clasificación (`_AiRun`), con su propio recuento: `run.classified` cuenta los documentos en los que se rellenó
        algo. Con `ai_concurrency`, varias llamadas a la vez (cada una solo toca su documento); con `cache`, lo ya
        descrito con la misma petición no vuelve al modelo.
        """
        pending = [document for documents in classified.values() for document in documents if document.description is None or not document.keywords]

        def request(conversion: ConversionDocument, _source_path: str) -> TaskRequest[DocumentEnrichmentResult]:
            return enrichment_request(prompts, title=conversion.title, content=conversion.text)

        hits = await self._cache_hits(llm, cache, [(document.json_path, document.source_path, request) for document in pending])

        async def call(item: tuple[DomainDocument, bool]) -> None:
            document, cached = item
            asked = await self._ask_ai(llm, run, cache, document, request, cached=cached, failure="Falló la descripción con IA de")
            if asked is None:
                return
            value = asked[0]
            if document.description is None and value.description is not None:
                document.description = value.description
                document.ai_filled.append("description")
            if not document.keywords and value.keywords:
                document.keywords = value.keywords
                document.ai_filled.append("keywords")
            if document.ai_filled:
                run.classified += 1

        await self._run_ai_phase(
            list(zip(pending, hits, strict=True)),
            call,
            run,
            on_progress,
            lambda item: item[0].source_path,
            stage="Descripción con IA detenida",
            outcome="quedan solo con lo que declaran",
        )

    def _log_stop(self, run: _AiRun, remaining: int, *, stage: str = "Sub-fase B detenida", outcome: str = "quedan sin clasificar") -> None:
        """Avisa una sola vez, justo tras el documento que la provocó, de que una fase de IA se detuvo."""
        if run.stopped is None or run.stop_logged:
            return
        run.stop_logged = True
        if run.stopped == "budget":
            remaining += 1  # el documento que topó con el presupuesto tampoco se envió
        self.logger.warning(f"{stage} ({run.stopped}) tras {run.sent} documento(s) enviado(s): {remaining} documento(s) pendiente(s) {outcome}")


__all__ = ["ContextBuilder"]
