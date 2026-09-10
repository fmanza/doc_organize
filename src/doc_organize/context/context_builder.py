"""
Orquestador de la construcción del contexto de organización documental de un proyecto.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from doc_organize.ai import DomainClassificationClient
from doc_organize.context.context_registry import ContextRegistry
from doc_organize.context.domain_classifier import DomainClassifier, MaterialTypeClassifier, read_conversion_json, resolve_title_and_type
from doc_organize.core.exceptions import DomainClassificationError
from doc_organize.core.models import Context, ConversionResult, Domain, DomainDocument, DomainStatus, Project, TaxonomyManifest
from doc_organize.utils.logging import get_logger

_DEFAULT_THRESHOLD = 0.5

_UNCLASSIFIED_SLUG = "sin-clasificar"
"""Slug placeholder para un eje (dominio o tipo de material) que no alcanza `threshold`
cuando hay un manifiesto de taxonomía activo — el documento se reorganiza igual bajo este
slug en el eje afectado, en vez de excluirse por completo (`unclassified_documents` sigue
reservado a documentos con artefactos incompletos, ver `_classify_with_manifest`). Al
tratarse como un slug de dominio/tipo más, `Reorganizer`/`MkDocsGenerator` no necesitan
lógica especial: `"sin-clasificar".replace("-", " ").title()` ya da un nombre legible
("Sin Clasificar") igual que cualquier otro slug."""


class ContextBuilder:
    """Clasifica los documentos convertidos de un proyecto y persiste el `Context` resultante.

    Dos sub-fases (ver `.ai/sessions/2026-09-08-organizacion-documental-contextos/00_REQUEST.md`):

    - **Sub-fase A** (siempre): `DomainClassifier`, reglas sobre `chunks`/`title`.
    - **Sub-fase B** (opt-in vía `ai_classification_enabled` + `ai_classification_client`):
      fallback por IA, **solo** para los documentos que la Sub-fase A deja sin
      clasificar, y **solo** eligiendo entre el catálogo ya confirmado por la
      Sub-fase A (el propio catálogo predefinido, o los dominios descubiertos) —
      nunca crea un dominio nuevo.

    La copia física a `<output_folder_name>/` y la generación del sitio MkDocs son
    responsabilidad de `Reorganizer`/`MkDocsGenerator` — este builder no toca
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

    def __init__(self, registry: ContextRegistry | None = None) -> None:
        self.registry = registry or ContextRegistry()
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
    ) -> Context:
        """Clasifica `documents` y persiste el contexto de `project`.

        Sin `taxonomy_manifest` (default): comportamiento sin cambios — Sub-fase A
        (`DomainClassifier`, un eje) + Sub-fase B opcional (IA, fallback). Con
        `taxonomy_manifest`: clasificación de 2 ejes (dominio + tipo de material de
        origen) vía `_classify_with_manifest`, solo por reglas en este ciclo — la
        Sub-fase B combinada de 2 ejes queda fuera de alcance (ver PLAN de la sesión de
        manifiesto de taxonomía); `ai_classification_enabled`/`ai_classification_client`
        se ignoran cuando hay manifiesto.

        Args:
            project: Proyecto propietario del contexto.
            documents: Documentos ya convertidos (`converter/`) a clasificar.
            candidate_domains: Catálogo de dominios permitidos, o `None` para descubrirlos
                del contenido escaneado (ver `DomainClassifier`). Ignorado si se da
                `taxonomy_manifest` (su catálogo de dominios manda).
            threshold: Score mínimo de la Sub-fase A antes de considerar un documento
                candidato a la Sub-fase B (o "sin clasificar"/placeholder según el modo).
            ai_classification_enabled: Activa la Sub-fase B — opt-in explícito, se
                persiste en `Context.ai_classification_enabled`. Sin efecto si hay
                `taxonomy_manifest` (ver arriba).
            ai_classification_client: Cliente ya configurado para la Sub-fase B. Si
                `ai_classification_enabled=True` pero no se pasa cliente, la Sub-fase B
                simplemente no se ejecuta (los documentos quedan sin clasificar).
            output_folder_name: Nombre de la carpeta de salida reorganizada, relativa
                a `root_path` — solo tiene efecto en la primera construcción de un
                proyecto; `web/routes/context.py` reutiliza el valor ya persistido en
                reconstrucciones posteriores (el campo queda fijo tras la primera vez).
            on_ai_progress: Si se da, se invoca `await on_ai_progress(index, total, source_path)`
                tras cada documento intentado en la Sub-fase B (clasificado o no),
                `index` empezando en 1 — usado por `web/routes/context.py::context_build_websocket`
                para retransmitir progreso en tiempo real (semáforo). `None` (default)
                no tiene efecto ninguno: los llamadores existentes no cambian de
                comportamiento.
            taxonomy_manifest: Manifiesto de taxonomía del proyecto (ver
                `doc_organize.context.taxonomy_manifest.load_taxonomy_manifest`), o `None`
                (default) para el modo de un eje sin cambios.

        Returns:
            El `Context` construido y ya persistido vía `self.registry`.
        """
        if taxonomy_manifest is not None:
            classified, unclassified = await self._classify_with_manifest(documents, taxonomy_manifest, threshold)
        else:
            classifier = DomainClassifier(candidate_domains=candidate_domains, threshold=threshold)
            classified, unclassified = await classifier.classify(documents)

            if ai_classification_enabled and ai_classification_client is not None and unclassified:
                classified, unclassified = await self._classify_with_ai(
                    ai_classification_client, classified, unclassified, classifier.candidate_domains, on_progress=on_ai_progress
                )

        has_predefined_catalog = bool(candidate_domains) or taxonomy_manifest is not None
        manifest_domains_by_slug = (
            {DomainClassifier._slugify(entry.slug): entry for entry in taxonomy_manifest.domains} if taxonomy_manifest is not None else {}
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

        now = datetime.now(UTC).isoformat()
        context = Context(
            project_name=project.name,
            tenant_id=project.tenant_id,
            output_folder_name=output_folder_name,
            ai_classification_enabled=ai_classification_enabled,
            ai_fallback_threshold=threshold,
            domains=domains,
            unclassified_documents=[document.source_path for document in unclassified],
            taxonomy_manifest_used=taxonomy_manifest is not None,
            created_at=now,
            updated_at=now,
        )
        await self.registry.save_context(project, context)
        self.logger.info(f"Contexto construido para '{project.name}': {len(domains)} dominio(s), {len(unclassified)} documento(s) sin clasificar")
        return context

    async def _classify_with_manifest(
        self, documents: list[ConversionResult], manifest: TaxonomyManifest, threshold: float
    ) -> tuple[dict[str, list[DomainDocument]], list[ConversionResult]]:
        """Clasifica `documents` en 2 ejes (dominio + tipo de material) usando `manifest`.

        A diferencia del modo de un eje (`DomainClassifier.classify()`), un documento con
        los tres artefactos completos SIEMPRE se reorganiza aquí: si un eje no alcanza
        `threshold`, se le asigna el slug placeholder `_UNCLASSIFIED_SLUG` en ese eje en vez
        de excluir el documento por completo — decisión de negocio explícita de esta
        sesión (manifiesto de taxonomía). Solo un documento con algún artefacto incompleto
        (falta original/`.md`/`.json`) queda en `unclassified_documents`, igual criterio que
        el modo de un eje. Solo reglas (Sub-fase A): la Sub-fase B combinada de 2 ejes queda
        fuera de alcance de este ciclo.
        """
        domain_slugs = [entry.slug for entry in manifest.domains]
        material_slugs = [entry.slug for entry in manifest.material_types]
        domain_classifier = DomainClassifier(candidate_domains=domain_slugs, threshold=threshold)
        material_classifier = MaterialTypeClassifier(material_slugs, threshold=threshold)

        # `entry.slug` saneado (no el original tal cual) porque es la clave por la que
        # `score_catalog()` busca en `extra_keywords` — debe coincidir con los slugs ya
        # saneados en `domain_classifier.candidate_domains`/`material_classifier.material_types`
        # (AUDIT_CODE: antes de esto, `TaxonomyCatalogEntry.keywords` se leía del manifiesto
        # pero no se usaba nunca en la puntuación).
        domain_keywords = {DomainClassifier._slugify(entry.slug): entry.keywords for entry in manifest.domains if entry.keywords}
        material_keywords = {DomainClassifier._slugify(entry.slug): entry.keywords for entry in manifest.material_types if entry.keywords}

        # Mismo saneado que `domain_keywords`/`material_keywords`, para el mismo motivo:
        # `TaxonomyCatalogEntry.name` (nombre legible declarado en el manifiesto) se leía
        # pero nunca se propagaba a `DomainDocument.material_type_name` — `MkDocsGenerator`
        # acababa derivando la etiqueta del nav del slug (`"normativa" -> "Normativa"`) en vez
        # de usar el nombre declarado (AUDIT_CODE, mismo hallazgo que `Domain.name`/`.description`
        # en `build()`).
        material_names = {DomainClassifier._slugify(entry.slug): entry.name for entry in manifest.material_types}

        classified: dict[str, list[DomainDocument]] = {}
        unclassified: list[ConversionResult] = []

        for document in documents:
            if not document.success or not document.markdown_path or not document.json_path:
                unclassified.append(document)
                continue
            chunks_result = await read_conversion_json(document.json_path)
            if chunks_result is None:
                unclassified.append(document)
                continue
            chunks_text, title = chunks_result

            domain_slug, domain_score = domain_classifier.score_domain(document, chunks_text, title, extra_keywords=domain_keywords)
            if domain_slug is None or domain_score < threshold:
                domain_slug = _UNCLASSIFIED_SLUG

            material_slug, _material_score = material_classifier.classify_text(title=title, chunks_text=chunks_text, extra_keywords=material_keywords)
            if material_slug is None:
                material_slug = _UNCLASSIFIED_SLUG

            resolved_title, document_type = resolve_title_and_type(document, title)
            classified.setdefault(domain_slug, []).append(
                DomainDocument(
                    source_path=document.source_path,
                    markdown_path=document.markdown_path,
                    json_path=document.json_path,
                    images_dir=document.images_dir,
                    title=resolved_title,
                    document_type=document_type,
                    material_type=material_slug,
                    material_type_name=material_names.get(material_slug),
                    confidence=domain_score,
                    classified_by="rules",
                )
            )

        return classified, unclassified

    async def _classify_with_ai(
        self,
        client: DomainClassificationClient,
        classified: dict[str, list[DomainDocument]],
        unclassified: list[ConversionResult],
        candidate_domains: list[str] | None,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> tuple[dict[str, list[DomainDocument]], list[ConversionResult]]:
        """Sub-fase B: intenta clasificar por IA lo que la Sub-fase A dejó sin
        clasificar, eligiendo solo entre el catálogo ya confirmado (el predefinido,
        o los dominios que la Sub-fase A ya descubrió) — nunca crea uno nuevo.
        """
        catalog = candidate_domains if candidate_domains else list(classified.keys())
        if not catalog:
            return classified, unclassified

        total = len(unclassified)
        still_unclassified: list[ConversionResult] = []
        for index, document in enumerate(unclassified, start=1):
            assigned = await self._try_classify_document_with_ai(client, document, catalog)
            if assigned is None:
                still_unclassified.append(document)
            else:
                slug, domain_document = assigned
                classified.setdefault(slug, []).append(domain_document)
            if on_progress is not None:
                await on_progress(index, total, document.source_path)
        return classified, still_unclassified

    async def _try_classify_document_with_ai(
        self, client: DomainClassificationClient, document: ConversionResult, catalog: list[str]
    ) -> tuple[str, DomainDocument] | None:
        if not document.success or not document.markdown_path or not document.json_path:
            return None
        chunks_result = await read_conversion_json(document.json_path)
        if chunks_result is None:
            return None
        chunks_text, title = chunks_result

        try:
            result = await client.classify(chunks_text=chunks_text, title=title, candidate_domains=catalog)
        except DomainClassificationError as exc:
            self.logger.warning(f"Fallo la clasificación por IA de '{document.source_path}': {exc} — queda sin clasificar")
            return None

        if result.domain is None:
            return None

        resolved_title, document_type = resolve_title_and_type(document, title)
        return result.domain, DomainDocument(
            source_path=document.source_path,
            markdown_path=document.markdown_path,
            json_path=document.json_path,
            images_dir=document.images_dir,
            title=resolved_title,
            document_type=document_type,
            confidence=result.confidence,
            classified_by="ai",
        )


__all__ = ["ContextBuilder"]
