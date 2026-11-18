"""
Orquestador de la construcción del contexto de organización documental de un proyecto.
"""

import asyncio

from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from doc_organize import __version__
from doc_organize.ai import DocumentEnrichmentClient, DomainClassificationClient, TaxonomyClassificationClient
from doc_organize.context.axis_rules import TAG_AXIS_TEXT_CHARS, AxisRuleScorer, FoldedText
from doc_organize.context.context_history import ContextHistoryPolicy, append_context_build, build_record
from doc_organize.context.context_registry import ContextRegistry
from doc_organize.context.document_properties import read_document_properties
from doc_organize.context.domain_classifier import DomainClassifier, MaterialTypeClassifier, read_conversion_json, resolve_title_and_type
from doc_organize.context.language_detection import detect_language
from doc_organize.context.reorganizer import assign_organized_paths
from doc_organize.core.constants import UNCLASSIFIED_SLUG
from doc_organize.core.exceptions import (
    ContextError,
    ContextNotFoundError,
    DocumentEnrichmentAuthError,
    DocumentEnrichmentConnectionError,
    DocumentEnrichmentError,
    DomainClassificationAuthError,
    DomainClassificationConnectionError,
    DomainClassificationError,
    TaxonomyClassificationAuthError,
    TaxonomyClassificationConnectionError,
    TaxonomyClassificationError,
)
from doc_organize.core.models import (
    CONTEXT_SCHEMA_VERSION,
    LEGACY_FOLDER_AXIS_KEY,
    AiClassificationStopReason,
    AxisClassifiedBy,
    AxisValue,
    Context,
    ConversionResult,
    DocumentClassification,
    DocumentCredentialFindings,
    Domain,
    DomainDocument,
    DomainStatus,
    Project,
    TaxonomyAxis,
    TaxonomyClassificationResult,
    TaxonomyEntry,
    TaxonomyManifest,
    UnclassifiedDocument,
)
from doc_organize.core.progress import CancelToken, Phase, ProgressCallback, ProgressEvent, checkpoint
from doc_organize.projects.layout import ProjectLayout
from doc_organize.security.credentials import redact_credentials
from doc_organize.utils.logging import get_logger
from doc_organize.utils.text_clean import clean_text

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
    """Estado de la Sub-fase B en una construcción (L-3a…L-3c): recuentos, racha de errores de conexión y parada.

    Compartido por los dos modos (`_classify_with_ai` y `_classify_with_manifest_ai`). Un documento cuenta como
    enviado al llamar a `client.classify()` una vez (los reintentos de transporte del cliente no cuentan aparte), así
    que `sent == classified + failed + enviados sin asignación` siempre.
    """

    max_failures: int | None = None
    max_documents: int | None = None
    sent: int = 0
    classified: int = 0
    failed: int = 0
    consecutive_connection_failures: int = 0
    stopped: AiClassificationStopReason | None = None
    stop_logged: bool = False
    #: Redactar credenciales del título y el texto antes de enviarlos (1.7.0, `ContextBuilder(ai_redact_credentials=)`).
    redact: bool = True
    #: Recuento por documento y regla de lo redactado, compartido por todas las fases de IA de una construcción.
    credential_ledger: dict[str, Counter[str]] | None = None

    def outgoing(self, source_path: str, chunks_text: str, title: str | None) -> tuple[str, str | None]:
        """Título y texto tal como salen hacia la IA: redactados si `redact`, y lo redactado anotado en el registro.

        Solo para enviar: las reglas, el idioma y lo que se guarda siguen usando el texto original.
        """
        if not self.redact:
            return chunks_text, title
        body = redact_credentials(chunks_text)
        head = redact_credentials(title) if title else None
        found = [*body.findings, *(head.findings if head is not None else ())]
        if found and self.credential_ledger is not None:
            self.credential_ledger.setdefault(source_path, Counter()).update(finding.rule for finding in found)
        return body.text, head.text if head is not None else title

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

    def record_response(self) -> None:
        """La llamada respondió: corta la racha de errores de conexión (el recuento se hace al aplicar el resultado)."""
        self.consecutive_connection_failures = 0

    def record_result(self, *, assigned: bool) -> None:
        """La llamada respondió: corta la racha de errores de conexión y cuenta si asignó algún eje."""
        self.record_response()
        if assigned:
            self.classified += 1

    def record_failure(self, exc: Exception, auth_error_cls: type[Exception], connection_error_cls: type[Exception]) -> None:
        """La llamada falló: `auth` para en el acto; `connection` para tras `max_failures` seguidos."""
        self.failed += 1
        if isinstance(exc, auth_error_cls):
            self.stopped = "auth"
        elif isinstance(exc, connection_error_cls):
            self.consecutive_connection_failures += 1
            if self.max_failures is not None and self.consecutive_connection_failures >= self.max_failures:
                self.stopped = "connection"
        else:
            # El servidor respondió (5xx, respuesta mal formada...): no es un error de conexión.
            self.consecutive_connection_failures = 0


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


def _model_used(client: DomainClassificationClient | TaxonomyClassificationClient | DocumentEnrichmentClient | None, run: _AiRun) -> str | None:
    """Alias de modelo del cliente si esa fase de IA llegó a enviar algún documento; si no, `None` (1.5.0)."""
    if client is None or run.sent == 0:
        return None
    return client.config.model


def _classification_model(
    manifest: TaxonomyManifest | None,
    domain_client: DomainClassificationClient | None,
    taxonomy_client: TaxonomyClassificationClient | None,
    run: _AiRun,
) -> str | None:
    """Modelo de la Sub-fase B: el cliente de 2 ejes en modo manifiesto, el de 1 eje si no (1.5.0)."""
    return _model_used(taxonomy_client if manifest is not None else domain_client, run)


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
    - **Sub-fase B** (opt-in vía `ai_classification_enabled` + `ai_classification_client`, o
      `+ taxonomy_classification_client` en modo manifiesto): fallback por IA, **solo** para
      los documentos que la Sub-fase A deja sin clasificar (en cualquiera de los dos ejes, en
      modo manifiesto), y **solo** eligiendo entre el catálogo ya confirmado por la Sub-fase A
      (el propio catálogo predefinido/manifiesto, o los dominios descubiertos) — nunca crea un
      dominio o tipo de material nuevo. En modo manifiesto, `TaxonomyClassificationClient`
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
        ai_redact_credentials: bool = True,
        ai_concurrency: int = 1,
    ) -> None:
        """
        Args:
            registry: Dónde se lee y guarda el contexto (`ContextRegistry()` por defecto).
            history_policy: Giro de `CONTEXT_HISTORY.jsonl` (1.6.0); `None` = `ContextHistoryPolicy()` (5 MB, 4 copias).
            properties_concurrency: Originales cuyas propiedades se leen a la vez (1.6.0). En una carpeta de red, 4
                lecturas a la vez cuestan un tercio que de una en una; `1` = una detrás de otra, como en 1.5.0.
            ai_redact_credentials: Redacta las credenciales (`doc_organize.security.redact_credentials`) del título y el texto
                de cada documento antes de enviarlo a la IA, en la Sub-fase B y el enriquecimiento (1.7.0). Por
                defecto **activado**: cambia lo que sale hacia la IA, no lo que se clasifica con reglas ni lo que se
                guarda. Lo redactado se resume, sin valores, en `Context.credential_findings`.

            ai_concurrency: Llamadas a la IA a la vez en cada fase (Sub-fase B y enriquecimiento, 2.0.0). `1` = una
                detrás de otra, como en 1.x. Los resultados se aplican en el orden de los documentos: el contexto es el
                mismo con 1 que con 4. `ai_max_documents` nunca se supera; tras alcanzar `ai_max_failures` no se envía
                nada más, pero las llamadas que ya estaban en vuelo pueden sumar hasta `ai_concurrency - 1` fallos. Ante
                respuestas 429, ver los reintentos del cliente.

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
        self.ai_redact_credentials = ai_redact_credentials
        self.logger = get_logger(__name__)

    async def build(
        self,
        project: Project,
        documents: list[ConversionResult],
        candidate_domains: list[str] | None = None,
        threshold: float = _DEFAULT_THRESHOLD,
        ai_classification_enabled: bool = False,
        ai_classification_client: DomainClassificationClient | None = None,
        output_folder_name: str = "organizado",
        on_ai_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
        taxonomy_manifest: TaxonomyManifest | None = None,
        taxonomy_classification_client: TaxonomyClassificationClient | None = None,
        taxonomy_template_name: str | None = None,
        *,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
        ai_max_failures: int | None = None,
        ai_max_documents: int | None = None,
        ai_enrichment_enabled: bool = False,
        ai_enrichment_client: DocumentEnrichmentClient | None = None,
    ) -> Context:
        """Clasifica `documents` y persiste el contexto de `project`.

        Sin `taxonomy_manifest` (default): comportamiento sin cambios — Sub-fase A
        (`DomainClassifier`, un eje) + Sub-fase B opcional (IA, fallback vía
        `ai_classification_client`). Con `taxonomy_manifest`: clasificación de 2 ejes
        (dominio + tipo de material de origen) vía `_classify_with_manifest` (reglas) +
        Sub-fase B opcional vía `taxonomy_classification_client` (`_classify_with_manifest_ai`,
        una sola llamada combinada para ambos ejes) — `ai_classification_client` (de un eje)
        se ignora en modo manifiesto, que usa `taxonomy_classification_client` en su lugar.

        Args:
            project: Proyecto propietario del contexto.
            documents: Documentos ya convertidos (`converter/`) a clasificar.
            candidate_domains: Catálogo de dominios permitidos, o `None` para descubrirlos
                del contenido escaneado (ver `DomainClassifier`). Ignorado si se da
                `taxonomy_manifest` (su catálogo de dominios manda).
            threshold: Score mínimo de la Sub-fase A antes de considerar un documento
                candidato a la Sub-fase B (o "sin clasificar"/placeholder según el modo).
            ai_classification_enabled: Activa la Sub-fase B — opt-in explícito, se
                persiste en `Context.ai_classification_enabled`. En modo manifiesto activa
                `_classify_with_manifest_ai` en vez de `_classify_with_ai` (ver arriba).
            ai_classification_client: Cliente ya configurado para la Sub-fase B de un eje. Si
                `ai_classification_enabled=True` pero no se pasa cliente, la Sub-fase B
                simplemente no se ejecuta (los documentos quedan sin clasificar). Ignorado si
                hay `taxonomy_manifest`.
            output_folder_name: Nombre de la carpeta de salida reorganizada, relativa
                a `root_path` — solo tiene efecto en la primera construcción de un
                proyecto; el consumidor reutiliza el valor ya persistido en
                reconstrucciones posteriores (el campo queda fijo tras la primera vez).
            on_ai_progress: Si se da, se invoca `await on_ai_progress(index, total, source_path)`
                tras cada documento intentado en la Sub-fase B (clasificado o no),
                `index` empezando en 1 — pensado para que el consumidor
                retransmita el progreso en tiempo real (semáforo). `None` (default)
                no tiene efecto ninguno: los llamadores existentes no cambian de
                comportamiento.
            taxonomy_manifest: Manifiesto de taxonomía del proyecto (ver
                `doc_organize.context.taxonomy_manifest.load_taxonomy_manifest`), o `None`
                (default) para el modo de un eje sin cambios.
            taxonomy_classification_client: Cliente ya configurado para la Sub-fase B en modo
                manifiesto (2 ejes, una sola llamada combinada). Sin efecto si `taxonomy_manifest`
                es `None`, o si `ai_classification_enabled=False`.
            taxonomy_template_name: Nombre de la plantilla de `TaxonomyTemplateRegistry` de la que
                proviene `taxonomy_manifest`, o `None` si viene de un `taxonomy_manifest.md` local o
                si no hay manifiesto — puramente informativo, se persiste en
                `Context.taxonomy_template_name` para que la UI pueda mostrar/preseleccionar qué
                plantilla se usó; no afecta a la clasificación (ya resuelta en `taxonomy_manifest`).

            on_progress: Recibe un `ProgressEvent` (`operation="context_build"`, fase `classification`) tras cada
                documento de la Sub-fase B (L-2). Un fallo del callback se registra y no para la construcción.
            cancel_token: Si se cancela, la construcción para **entre documentos** de la Sub-fase B (o antes de
                empezar) con `OperationCancelledError`, **sin** persistir un contexto a medias (L-2).
            ai_max_failures: Si se da, la Sub-fase B se detiene tras este número de errores de conexión **seguidos**
                (`Context.ai_classification_stopped = "connection"`, L-3a). `None` (por defecto): nunca para por eso.
                Un error de autenticación (401/403) la detiene siempre en el acto (`"auth"`), con o sin este
                parámetro: no se hace ni una petición más.
            ai_max_documents: Tope de documentos enviados a la IA en esta construcción (L-3b). Al alcanzarlo con
                documentos aún pendientes, la Sub-fase B se detiene (`"budget"`). `None` (por defecto): sin tope.

            Al detenerse la Sub-fase B, los documentos pendientes no se leen ni se envían: quedan sin clasificar (o en
            el placeholder `sin-clasificar`, en modo manifiesto), siguen emitiendo su evento de progreso (y el
            `cancel_token` se sigue comprobando entre ellos), y la construcción termina y persiste el contexto con
            normalidad. Los recuentos quedan en `Context.ai_documents_sent/_classified/_failed` (L-3c).

            ai_enrichment_enabled: Activa el enriquecimiento por IA (1.5.0) — opt-in explícito, se persiste en
                `Context.ai_enrichment_enabled`. Sin él, `author`, `description` y `keywords` de cada `DomainDocument`
                salen solo de las propiedades que declara el propio documento (PDF y Office), que se leen siempre.
            ai_enrichment_client: Cliente ya configurado. Con `ai_enrichment_enabled=True`, se llama una vez por
                documento clasificado que no declara descripción o palabras clave, y solo se rellena lo que falta
                (`DomainDocument.ai_filled`); el autor nunca sale de la IA. Usa los mismos `ai_max_failures` y
                `ai_max_documents` que la Sub-fase B, pero con su propio recuento: cada fase puede enviar hasta
                `ai_max_documents`. Al detenerse, el resto queda solo con lo declarado (`Context.ai_enrichment_*`).

        Returns:
            El `Context` construido y ya persistido vía `self.registry`.

        Raises:
            OperationCancelledError: Se canceló con `cancel_token`.
            ValueError: `ai_max_failures < 1` o `ai_max_documents < 0`.
        """
        if ai_max_failures is not None and ai_max_failures < 1:
            raise ValueError("ai_max_failures debe ser >= 1 (o None)")
        if ai_max_documents is not None and ai_max_documents < 0:
            raise ValueError("ai_max_documents debe ser >= 0 (o None)")
        checkpoint(cancel_token)
        credential_ledger: dict[str, Counter[str]] = {}
        ai_run = self._new_ai_run(ai_max_failures, ai_max_documents, credential_ledger)

        def _report(phase: Phase, index: int, total: int, source_path: str) -> None:
            if on_progress is not None:
                try:
                    on_progress(ProgressEvent(operation="context_build", phase=phase, processed=index, total=total, current=source_path))
                except Exception as exc:  # noqa: BLE001 - un callback del consumidor nunca debe parar la operación
                    self.logger.warning(f"El callback de progreso falló: {type(exc).__name__}: {exc}")
            checkpoint(cancel_token)  # L-2: parada entre documentos de la Sub-fase B o del enriquecimiento

        async def _ai_progress(index: int, total: int, source_path: str) -> None:
            if on_ai_progress is not None:
                await on_ai_progress(index, total, source_path)
            _report("classification", index, total, source_path)

        async def _enrichment_progress(index: int, total: int, source_path: str) -> None:
            _report("enrichment", index, total, source_path)

        reads = _BuildReads()  # lectura única de cada `.json` para todo lo que no es IA (2.0.0, B)
        if taxonomy_manifest is not None:
            classified, unclassified = await self._classify_with_manifest(
                documents, taxonomy_manifest, threshold, reads=reads, cancel_token=cancel_token
            )
            if ai_classification_enabled and taxonomy_classification_client is not None:
                classified = await self._classify_with_manifest_ai(
                    taxonomy_classification_client, classified, taxonomy_manifest, on_progress=_ai_progress, run=ai_run
                )
        else:
            classifier = DomainClassifier(candidate_domains=candidate_domains, threshold=threshold)
            classified, unclassified = await self._classify_by_rules(documents, classifier, reads, cancel_token)

            if ai_classification_enabled and ai_classification_client is not None and unclassified:
                classified, unclassified = await self._classify_with_ai(
                    ai_classification_client,
                    classified,
                    unclassified,
                    classifier,
                    on_progress=_ai_progress,
                    run=ai_run,
                )

        unclassified_details = self._describe_unclassified(unclassified, reads)
        enrichment_run = self._new_ai_run(ai_max_failures, ai_max_documents, credential_ledger)
        await self._describe_documents(
            classified, unclassified_details, reads, ai_enrichment_enabled, ai_enrichment_client, enrichment_run, _enrichment_progress, cancel_token
        )

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
            ai_classification_enabled=ai_classification_enabled,
            ai_fallback_threshold=threshold,
            ai_classification_model=_classification_model(taxonomy_manifest, ai_classification_client, taxonomy_classification_client, ai_run),
            ai_enrichment_model=_model_used(ai_enrichment_client, enrichment_run),
            built_with_version=__version__,
            domains=domains,
            unclassified_documents=[document.source_path for document in unclassified],
            unclassified_details=unclassified_details,
            taxonomy_manifest_used=taxonomy_manifest is not None,
            taxonomy_template_name=taxonomy_template_name,
            ai_classification_stopped=ai_run.stopped,
            ai_documents_sent=ai_run.sent,
            ai_documents_classified=ai_run.classified,
            ai_documents_failed=ai_run.failed,
            ai_enrichment_enabled=ai_enrichment_enabled,
            ai_enrichment_stopped=enrichment_run.stopped,
            ai_enrichment_sent=enrichment_run.sent,
            ai_enrichment_applied=enrichment_run.classified,
            ai_enrichment_failed=enrichment_run.failed,
            ai_redact_credentials=self.ai_redact_credentials,
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

    def _new_ai_run(self, max_failures: int | None, max_documents: int | None, ledger: dict[str, Counter[str]]) -> _AiRun:
        return _AiRun(max_failures=max_failures, max_documents=max_documents, redact=self.ai_redact_credentials, credential_ledger=ledger)

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
        client: TaxonomyClassificationClient,
        classified: dict[str, list[DomainDocument]],
        manifest: TaxonomyManifest,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
        run: _AiRun | None = None,
    ) -> dict[str, list[DomainDocument]]:
        """Sub-fase B en modo manifiesto: para cada documento que `_classify_with_manifest` dejó
        con el placeholder `_UNCLASSIFIED_SLUG` en el eje de dominio y/o en el de tipo de
        material, intenta resolver AMBOS ejes en una sola llamada combinada a `client.classify()`
        — decisión de esta sesión, en vez de una llamada por eje. Solo se aplica la sugerencia de
        la IA al eje que seguía en el placeholder; un eje que la Sub-fase A ya clasificó con
        confianza nunca se sobreescribe, aunque la IA sugiera algo distinto para ese eje en la
        misma respuesta.

        `DomainDocument.classified_by` pasa a `"ai"` si la IA cambió efectivamente al menos un eje
        (de placeholder a un valor real); se queda en `"rules"` si no cambió nada, aunque se haya
        intentado — un único campo string sigue bastando (mismo criterio que en modo de un eje).
        Las llamadas pueden ir varias a la vez (`ai_concurrency`); los resultados se aplican en el
        orden de los documentos.
        """
        domain_slugs = list(dict.fromkeys(slug for slug in (DomainClassifier._slugify(entry.slug) for entry in manifest.folder_axis.entries) if slug))
        material_slugs = list(
            dict.fromkeys(slug for slug in (DomainClassifier._slugify(entry.slug) for entry in manifest.subfolder_axis.entries) if slug)
        )

        pending = [
            (domain_slug, document)
            for domain_slug, documents in classified.items()
            for document in documents
            if domain_slug == _UNCLASSIFIED_SLUG or document.material_type == _UNCLASSIFIED_SLUG
        ]
        if not pending:
            return classified

        ai_run = run if run is not None else _AiRun()

        async def call(item: tuple[str, DomainDocument]) -> TaxonomyClassificationResult | None:
            document = item[1]
            texts = await self._outgoing_texts(document.source_path, document.json_path, ai_run)
            if texts is None:
                return None
            try:
                result = await client.classify(
                    chunks_text=texts[0], title=texts[1], candidate_domains=domain_slugs, candidate_material_types=material_slugs
                )
            except TaxonomyClassificationError as exc:
                ai_run.record_failure(exc, TaxonomyClassificationAuthError, TaxonomyClassificationConnectionError)
                self.logger.warning(f"Fallo la clasificación por IA (manifiesto) de '{document.source_path}': {exc} — sigue sin clasificar")
                return None
            ai_run.record_response()
            return result

        results = await self._run_ai_phase(pending, call, ai_run, on_progress, lambda item: item[1].source_path)
        for (old_domain_slug, document), result in zip(pending, results, strict=True):
            if result is not None:
                self._apply_manifest_ai(document, old_domain_slug, result, classified, manifest, ai_run)

        # Poda buckets que quedaron vacíos (p.ej. todo "sin-clasificar" se resolvió a otros
        # dominios) — sin esto, `build()` crearía un `Domain` fantasma sin documentos.
        return {slug: documents for slug, documents in classified.items() if documents}

    async def _outgoing_texts(self, source_path: str, json_path: str | None, run: _AiRun) -> tuple[str, str | None] | None:
        """Texto y título de un documento tal como salen hacia la IA, si hay presupuesto; `None` si no.

        El envío se reserva **antes** de leer (`may_send`), para que con varias llamadas a la vez el presupuesto se
        reparta en el orden de los documentos y no en el de las lecturas; si el `.json` no se puede leer, se devuelve.
        """
        if not json_path or not run.may_send():
            return None
        conversion = await read_conversion_json(json_path)
        if conversion is None:
            run.release()
            return None
        return run.outgoing(source_path, *conversion)

    def _apply_manifest_ai(
        self,
        document: DomainDocument,
        old_domain_slug: str,
        result: TaxonomyClassificationResult,
        classified: dict[str, list[DomainDocument]],
        manifest: TaxonomyManifest,
        run: _AiRun,
    ) -> None:
        """Aplica la respuesta de la IA a `document` y a `classified`: mueve el documento de bucket si el eje de
        dominio cambió, o lo muta in-place si solo cambió el de tipo de material. El eje que cambia queda en
        `document.classification` con `classified_by="ai"` (2.0.0)."""
        domain_names = {DomainClassifier._slugify(entry.slug): entry.name for entry in manifest.folder_axis.entries}
        material_names = {DomainClassifier._slugify(entry.slug): entry.name for entry in manifest.subfolder_axis.entries}
        document.ai_domain = result.domain
        document.ai_confidence = result.domain_confidence
        document.ai_reasoning = clean_text(result.reasoning)
        changed = False
        axes = document.classification.axes
        if old_domain_slug == _UNCLASSIFIED_SLUG and result.domain is not None:
            classified[old_domain_slug] = [candidate for candidate in classified[old_domain_slug] if candidate is not document]
            document.confidence = result.domain_confidence
            classified.setdefault(result.domain, []).append(document)
            axes[manifest.folder_axis.key] = [
                AxisValue(
                    slug=result.domain, name=domain_names.get(result.domain, result.domain), confidence=result.domain_confidence, classified_by="ai"
                )
            ]
            changed = True
        if document.material_type == _UNCLASSIFIED_SLUG and result.material_type is not None:
            document.material_type = result.material_type
            document.material_type_name = material_names.get(result.material_type)
            document.material_type_confidence = result.material_type_confidence
            axes[manifest.subfolder_axis.key] = [
                AxisValue(
                    slug=result.material_type,
                    name=material_names.get(result.material_type, result.material_type),
                    confidence=result.material_type_confidence,
                    classified_by="ai",
                )
            ]
            changed = True
        if changed:
            document.classified_by = "ai"
            run.classified += 1

    async def _classify_with_ai(
        self,
        client: DomainClassificationClient,
        classified: dict[str, list[DomainDocument]],
        unclassified: list[ConversionResult],
        rules: DomainClassifier,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
        run: _AiRun | None = None,
    ) -> tuple[dict[str, list[DomainDocument]], list[ConversionResult]]:
        """Sub-fase B: intenta clasificar por IA lo que la Sub-fase A dejó sin
        clasificar, eligiendo solo entre el catálogo ya confirmado (el predefinido,
        o los dominios que la Sub-fase A ya descubrió) — nunca crea uno nuevo.

        `rules` es el clasificador de la Sub-fase A: da el catálogo y la propuesta que las reglas dejaron por debajo
        del umbral (`DomainDocument.rules_domain`/`rules_confidence`). Las llamadas pueden ir varias a la vez
        (`ai_concurrency`); los resultados se aplican en el orden de los documentos.
        """
        catalog = rules.candidate_domains if rules.candidate_domains else list(classified.keys())
        if not catalog:
            return classified, unclassified

        ai_run = run if run is not None else _AiRun()

        async def call(document: ConversionResult) -> tuple[str, DomainDocument] | None:
            return await self._try_classify_document_with_ai(client, document, catalog, rules, ai_run)

        results = await self._run_ai_phase(unclassified, call, ai_run, on_progress, lambda document: document.source_path)
        still_unclassified: list[ConversionResult] = []
        for document, assigned in zip(unclassified, results, strict=True):
            if assigned is None:
                still_unclassified.append(document)
            else:
                slug, domain_document = assigned
                classified.setdefault(slug, []).append(domain_document)
        return classified, still_unclassified

    async def _try_classify_document_with_ai(
        self, client: DomainClassificationClient, document: ConversionResult, catalog: list[str], rules: DomainClassifier, run: _AiRun
    ) -> tuple[str, DomainDocument] | None:
        if not document.success or not document.markdown_path or not document.json_path:
            return None
        if not run.may_send():
            return None
        conversion = await read_conversion_json(document.json_path)
        if conversion is None:
            run.release()
            return None
        chunks_text, title = conversion

        sent_text, sent_title = run.outgoing(document.source_path, chunks_text, title)
        try:
            result = await client.classify(chunks_text=sent_text, title=sent_title, candidate_domains=catalog)
        except DomainClassificationError as exc:
            run.record_failure(exc, DomainClassificationAuthError, DomainClassificationConnectionError)
            self.logger.warning(f"Fallo la clasificación por IA de '{document.source_path}': {exc} — queda sin clasificar")
            return None

        run.record_result(assigned=result.domain is not None)
        if result.domain is None:
            return None

        resolved_title, document_type = resolve_title_and_type(document, title)
        rules_domain, rules_confidence = rules.score_domain(document, chunks_text, title)
        return result.domain, DomainDocument(
            source_path=document.source_path,
            markdown_path=document.markdown_path,
            json_path=document.json_path,
            images_dir=document.images_dir,
            source_sha256=document.source_sha256,
            title=resolved_title,
            document_type=document_type,
            confidence=result.confidence,
            classified_by="ai",
            rules_domain=rules_domain,
            rules_confidence=rules_confidence,
            ai_domain=result.domain,
            ai_confidence=result.confidence,
            ai_reasoning=clean_text(result.reasoning),
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

    async def _describe_documents(
        self,
        classified: dict[str, list[DomainDocument]],
        unclassified: list[UnclassifiedDocument],
        reads: _BuildReads,
        enrichment_enabled: bool,
        enrichment_client: DocumentEnrichmentClient | None,
        run: _AiRun,
        on_progress: Callable[[int, int, str], Awaitable[None]],
        cancel_token: CancelToken | None,
    ) -> None:
        """Autor, descripción, palabras clave e idioma de cada documento clasificado; con el enriquecimiento activo y
        cliente, la IA rellena después la descripción y las palabras clave que falten (1.5.0). De los sin clasificar,
        solo lo que declara el original (1.6.0): la IA no los enriquece."""
        await self._apply_document_properties(classified, unclassified, reads, cancel_token)
        if enrichment_enabled and enrichment_client is not None:
            await self._enrich_with_ai(enrichment_client, classified, on_progress=on_progress, run=run)

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
        client: DocumentEnrichmentClient,
        classified: dict[str, list[DomainDocument]],
        on_progress: Callable[[int, int, str], Awaitable[None]],
        run: _AiRun,
    ) -> None:
        """Pide a la IA la descripción y las palabras clave de los documentos que no las declaran (1.5.0).

        Solo rellena lo que falta; lo declarado por el documento nunca se sustituye. Mismas paradas que la
        Sub-fase B (`_AiRun`), con su propio recuento: `run.classified` cuenta los documentos en los que se rellenó
        algo. Con `ai_concurrency`, varias llamadas a la vez (cada una solo toca su documento).
        """
        pending = [document for documents in classified.values() for document in documents if document.description is None or not document.keywords]

        async def call(document: DomainDocument) -> None:
            await self._try_enrich_document(client, document, run)

        await self._run_ai_phase(
            pending,
            call,
            run,
            on_progress,
            lambda document: document.source_path,
            stage="Enriquecimiento por IA detenido",
            outcome="quedan solo con lo que declaran",
        )

    async def _try_enrich_document(self, client: DocumentEnrichmentClient, document: DomainDocument, run: _AiRun) -> None:
        texts = await self._outgoing_texts(document.source_path, document.json_path, run)
        if texts is None:
            return
        try:
            result = await client.enrich(chunks_text=texts[0], title=texts[1])
        except DocumentEnrichmentError as exc:
            run.record_failure(exc, DocumentEnrichmentAuthError, DocumentEnrichmentConnectionError)
            self.logger.warning(f"Fallo el enriquecimiento por IA de '{document.source_path}': {exc} — queda con lo que declara")
            return

        if document.description is None and result.description is not None:
            document.description = result.description
            document.ai_filled.append("description")
        if not document.keywords and result.keywords:
            document.keywords = result.keywords
            document.ai_filled.append("keywords")
        run.record_result(assigned=bool(document.ai_filled))

    def _log_stop(self, run: _AiRun, remaining: int, *, stage: str = "Sub-fase B detenida", outcome: str = "quedan sin clasificar") -> None:
        """Avisa una sola vez, justo tras el documento que la provocó, de que una fase de IA se detuvo."""
        if run.stopped is None or run.stop_logged:
            return
        run.stop_logged = True
        if run.stopped == "budget":
            remaining += 1  # el documento que topó con el presupuesto tampoco se envió
        self.logger.warning(f"{stage} ({run.stopped}) tras {run.sent} documento(s) enviado(s): {remaining} documento(s) pendiente(s) {outcome}")


__all__ = ["ContextBuilder"]
