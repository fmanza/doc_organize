"""
Orquestador de la construcción del contexto de organización documental de un proyecto.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from doc_organize.ai import DomainClassificationClient, TaxonomyClassificationClient
from doc_organize.context.context_registry import ContextRegistry
from doc_organize.context.domain_classifier import DomainClassifier, MaterialTypeClassifier, read_conversion_json, resolve_title_and_type
from doc_organize.core.exceptions import DomainClassificationError, TaxonomyClassificationError
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
    - **Sub-fase B** (opt-in vía `ai_classification_enabled` + `ai_classification_client`, o
      `+ taxonomy_classification_client` en modo manifiesto): fallback por IA, **solo** para
      los documentos que la Sub-fase A deja sin clasificar (en cualquiera de los dos ejes, en
      modo manifiesto), y **solo** eligiendo entre el catálogo ya confirmado por la Sub-fase A
      (el propio catálogo predefinido/manifiesto, o los dominios descubiertos) — nunca crea un
      dominio o tipo de material nuevo. En modo manifiesto, `TaxonomyClassificationClient`
      resuelve ambos ejes en una sola llamada combinada, pero solo se aplica al eje que seguía
      en el placeholder `sin-clasificar` — un eje que la Sub-fase A ya clasificó con confianza
      nunca se sobreescribe.

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
        taxonomy_classification_client: TaxonomyClassificationClient | None = None,
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
            taxonomy_classification_client: Cliente ya configurado para la Sub-fase B en modo
                manifiesto (2 ejes, una sola llamada combinada). Sin efecto si `taxonomy_manifest`
                es `None`, o si `ai_classification_enabled=False`.

        Returns:
            El `Context` construido y ya persistido vía `self.registry`.
        """
        if taxonomy_manifest is not None:
            classified, unclassified = await self._classify_with_manifest(documents, taxonomy_manifest, threshold)
            if ai_classification_enabled and taxonomy_classification_client is not None:
                classified = await self._classify_with_manifest_ai(
                    taxonomy_classification_client, classified, taxonomy_manifest, on_progress=on_ai_progress
                )
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
        el modo de un eje. Solo reglas (Sub-fase A) — la Sub-fase B combinada de 2 ejes, si
        está activa, se aplica después vía `_classify_with_manifest_ai` sobre el resultado
        de este método.
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

    async def _classify_with_manifest_ai(
        self,
        client: TaxonomyClassificationClient,
        classified: dict[str, list[DomainDocument]],
        manifest: TaxonomyManifest,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
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
        """
        domain_slugs = list(dict.fromkeys(slug for slug in (DomainClassifier._slugify(entry.slug) for entry in manifest.domains) if slug))
        material_slugs = list(dict.fromkeys(slug for slug in (DomainClassifier._slugify(entry.slug) for entry in manifest.material_types) if slug))
        material_names = {DomainClassifier._slugify(entry.slug): entry.name for entry in manifest.material_types}

        pending = [
            (domain_slug, document)
            for domain_slug, documents in classified.items()
            for document in documents
            if domain_slug == _UNCLASSIFIED_SLUG or document.material_type == _UNCLASSIFIED_SLUG
        ]
        if not pending:
            return classified

        total = len(pending)
        for index, (old_domain_slug, document) in enumerate(pending, start=1):
            await self._try_classify_document_with_manifest_ai(
                client, document, old_domain_slug, classified, domain_slugs, material_slugs, material_names
            )
            if on_progress is not None:
                await on_progress(index, total, document.source_path)

        # Poda buckets que quedaron vacíos (p.ej. todo "sin-clasificar" se resolvió a otros
        # dominios) — sin esto, `build()` crearía un `Domain` fantasma sin documentos.
        return {slug: documents for slug, documents in classified.items() if documents}

    async def _try_classify_document_with_manifest_ai(
        self,
        client: TaxonomyClassificationClient,
        document: DomainDocument,
        old_domain_slug: str,
        classified: dict[str, list[DomainDocument]],
        domain_slugs: list[str],
        material_slugs: list[str],
        material_names: dict[str, str],
    ) -> None:
        """Resuelve un único `document` vía `client.classify()` y aplica el resultado a
        `classified` in-place — mueve el documento de bucket si el eje de dominio cambió,
        o lo muta in-place si solo cambió el eje de tipo de material (mismo objeto en la
        misma lista, sin necesidad de mover nada).
        """
        chunks_result = await read_conversion_json(document.json_path)
        if chunks_result is None:
            return
        chunks_text, title = chunks_result

        try:
            result = await client.classify(
                chunks_text=chunks_text, title=title, candidate_domains=domain_slugs, candidate_material_types=material_slugs
            )
        except TaxonomyClassificationError as exc:
            self.logger.warning(f"Fallo la clasificación por IA (manifiesto) de '{document.source_path}': {exc} — sigue sin clasificar")
            return

        changed = False
        if old_domain_slug == _UNCLASSIFIED_SLUG and result.domain is not None:
            classified[old_domain_slug] = [candidate for candidate in classified[old_domain_slug] if candidate is not document]
            document.confidence = result.domain_confidence
            classified.setdefault(result.domain, []).append(document)
            changed = True
        if document.material_type == _UNCLASSIFIED_SLUG and result.material_type is not None:
            document.material_type = result.material_type
            document.material_type_name = material_names.get(result.material_type)
            changed = True
        if changed:
            document.classified_by = "ai"

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
