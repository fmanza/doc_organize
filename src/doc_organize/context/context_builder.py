"""
Orquestador de la construcción del contexto de organización documental de un proyecto.
"""

from datetime import UTC, datetime

from doc_organize.ai import DomainClassificationClient
from doc_organize.context.context_registry import ContextRegistry
from doc_organize.context.domain_classifier import DomainClassifier, read_conversion_json, resolve_title_and_type
from doc_organize.core.exceptions import DomainClassificationError
from doc_organize.core.models import Context, ConversionResult, Domain, DomainDocument, DomainStatus, Project
from doc_organize.utils.logging import get_logger

_DEFAULT_THRESHOLD = 0.5


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
    ) -> Context:
        """Clasifica `documents` (Sub-fase A + B opcional) y persiste el contexto de `project`.

        Args:
            project: Proyecto propietario del contexto.
            documents: Documentos ya convertidos (`converter/`) a clasificar.
            candidate_domains: Catálogo de dominios permitidos, o `None` para descubrirlos
                del contenido escaneado (ver `DomainClassifier`).
            threshold: Score mínimo de la Sub-fase A antes de considerar un documento
                candidato a la Sub-fase B (o "sin clasificar" si la B está desactivada).
            ai_classification_enabled: Activa la Sub-fase B — opt-in explícito, se
                persiste en `Context.ai_classification_enabled`.
            ai_classification_client: Cliente ya configurado para la Sub-fase B. Si
                `ai_classification_enabled=True` pero no se pasa cliente, la Sub-fase B
                simplemente no se ejecuta (los documentos quedan sin clasificar).

        Returns:
            El `Context` construido y ya persistido vía `self.registry`.
        """
        classifier = DomainClassifier(candidate_domains=candidate_domains, threshold=threshold)
        classified, unclassified = await classifier.classify(documents)

        if ai_classification_enabled and ai_classification_client is not None and unclassified:
            classified, unclassified = await self._classify_with_ai(
                ai_classification_client, classified, unclassified, classifier.candidate_domains
            )

        domains = [
            Domain(
                slug=slug,
                name=slug.replace("-", " ").title(),
                status=DomainStatus.CONFIRMED if candidate_domains else DomainStatus.DRAFT,
                predefined=bool(candidate_domains),
                documents=domain_documents,
            )
            for slug, domain_documents in classified.items()
        ]

        now = datetime.now(UTC).isoformat()
        context = Context(
            project_name=project.name,
            tenant_id=project.tenant_id,
            ai_classification_enabled=ai_classification_enabled,
            ai_fallback_threshold=threshold,
            domains=domains,
            unclassified_documents=[document.source_path for document in unclassified],
            created_at=now,
            updated_at=now,
        )
        await self.registry.save_context(project, context)
        self.logger.info(f"Contexto construido para '{project.name}': {len(domains)} dominio(s), {len(unclassified)} documento(s) sin clasificar")
        return context

    async def _classify_with_ai(
        self,
        client: DomainClassificationClient,
        classified: dict[str, list[DomainDocument]],
        unclassified: list[ConversionResult],
        candidate_domains: list[str] | None,
    ) -> tuple[dict[str, list[DomainDocument]], list[ConversionResult]]:
        """Sub-fase B: intenta clasificar por IA lo que la Sub-fase A dejó sin
        clasificar, eligiendo solo entre el catálogo ya confirmado (el predefinido,
        o los dominios que la Sub-fase A ya descubrió) — nunca crea uno nuevo.
        """
        catalog = candidate_domains if candidate_domains else list(classified.keys())
        if not catalog:
            return classified, unclassified

        still_unclassified: list[ConversionResult] = []
        for document in unclassified:
            assigned = await self._try_classify_document_with_ai(client, document, catalog)
            if assigned is None:
                still_unclassified.append(document)
                continue
            slug, domain_document = assigned
            classified.setdefault(slug, []).append(domain_document)
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
            title=resolved_title,
            document_type=document_type,
            confidence=result.confidence,
            classified_by="ai",
        )


__all__ = ["ContextBuilder"]
