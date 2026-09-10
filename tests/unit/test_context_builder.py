"""Tests de ContextBuilder (orquesta DomainClassifier + ContextRegistry)."""

import json

from datetime import UTC, datetime
from pathlib import Path

import pytest

from doc_organize.context.context_builder import ContextBuilder
from doc_organize.core.exceptions import DomainClassificationError
from doc_organize.core.models import ConversionResult, DomainClassificationResult, Project, TaxonomyCatalogEntry, TaxonomyManifest


def _make_project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _make_document(tmp_path, folder: str, stem: str, title: str) -> ConversionResult:
    source_dir = tmp_path / folder
    source_dir.mkdir(exist_ok=True)
    json_path = tmp_path / f"{stem}.json"
    json_path.write_text(json.dumps({"title": title, "chunks": []}), encoding="utf-8")
    return ConversionResult(
        source_path=str(source_dir / f"{stem}.pdf"),
        markdown_path=str(tmp_path / f"{stem}.md"),
        json_path=str(json_path),
        success=True,
    )


@pytest.mark.asyncio
async def test_build_persists_discovered_domains(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "Ciberseguridad", "informe", "Informe")

    builder = ContextBuilder()
    context = await builder.build(project, [document])

    assert len(context.domains) == 1
    assert context.domains[0].slug == "ciberseguridad"
    assert context.unclassified_documents == []

    reloaded = await builder.registry.load_context(project)
    assert reloaded.domains[0].slug == "ciberseguridad"


@pytest.mark.asyncio
async def test_build_uses_default_output_folder_name_when_not_given(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "Ciberseguridad", "informe", "Informe")

    context = await ContextBuilder().build(project, [document])

    assert context.output_folder_name == "organizado"


@pytest.mark.asyncio
async def test_build_uses_given_output_folder_name(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "Ciberseguridad", "informe", "Informe")

    context = await ContextBuilder().build(project, [document], output_folder_name="docs_publicados")

    assert context.output_folder_name == "docs_publicados"


@pytest.mark.asyncio
async def test_build_tracks_unclassified_documents_outside_catalog(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina")

    builder = ContextBuilder()
    context = await builder.build(project, [document], candidate_domains=["calidad"])

    assert context.domains == []
    assert context.unclassified_documents == [document.source_path]


class _StubAIClient:
    """Doble de `DomainClassificationClient` para tests — mismo contrato (`async classify(...)`
    devolviendo `DomainClassificationResult`), sin `httpx` de por medio."""

    def __init__(self, domain: str | None, confidence: float = 0.8, error: bool = False) -> None:
        self.domain = domain
        self.confidence = confidence
        self.error = error
        self.calls: list[list[str]] = []

    async def classify(self, *, chunks_text: str, title: str | None, candidate_domains: list[str]) -> DomainClassificationResult:
        self.calls.append(candidate_domains)
        if self.error:
            raise DomainClassificationError("fallo simulado del proxy")
        return DomainClassificationResult(domain=self.domain, confidence=self.confidence, reasoning=None)


@pytest.mark.asyncio
async def test_ai_fallback_classifies_document_left_unclassified_by_rules(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina")

    ai_client = _StubAIClient(domain="calidad")
    builder = ContextBuilder()
    context = await builder.build(
        project,
        [document],
        candidate_domains=["calidad"],
        ai_classification_enabled=True,
        ai_classification_client=ai_client,
    )

    assert context.unclassified_documents == []
    assert context.domains[0].slug == "calidad"
    assert context.domains[0].documents[0].classified_by == "ai"
    assert ai_client.calls == [["calidad"]]  # catálogo predefinido, nunca inventado


@pytest.mark.asyncio
async def test_on_ai_progress_called_once_per_unclassified_document(tmp_path):
    project = _make_project(tmp_path)
    doc_a = _make_document(tmp_path, "varios", "a", "Receta A")
    doc_b = _make_document(tmp_path, "varios", "b", "Receta B")

    progress_calls: list[tuple[int, int, str]] = []

    async def on_progress(index: int, total: int, path: str) -> None:
        progress_calls.append((index, total, path))

    ai_client = _StubAIClient(domain="calidad")
    builder = ContextBuilder()
    await builder.build(
        project,
        [doc_a, doc_b],
        candidate_domains=["calidad"],
        ai_classification_enabled=True,
        ai_classification_client=ai_client,
        on_ai_progress=on_progress,
    )

    assert progress_calls == [(1, 2, doc_a.source_path), (2, 2, doc_b.source_path)]


@pytest.mark.asyncio
async def test_on_ai_progress_not_called_when_ai_disabled(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina")

    progress_calls: list[tuple[int, int, str]] = []

    async def on_progress(index: int, total: int, path: str) -> None:
        progress_calls.append((index, total, path))

    await ContextBuilder().build(project, [document], candidate_domains=["calidad"], on_ai_progress=on_progress)

    assert progress_calls == []


@pytest.mark.asyncio
async def test_ai_fallback_never_invents_domain_when_ai_finds_no_match(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina")

    ai_client = _StubAIClient(domain=None)
    builder = ContextBuilder()
    context = await builder.build(
        project, [document], candidate_domains=["calidad"], ai_classification_enabled=True, ai_classification_client=ai_client
    )

    assert context.domains == []
    assert context.unclassified_documents == [document.source_path]


@pytest.mark.asyncio
async def test_ai_fallback_client_error_leaves_document_unclassified_without_crashing(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina")

    ai_client = _StubAIClient(domain="calidad", error=True)
    builder = ContextBuilder()
    context = await builder.build(
        project, [document], candidate_domains=["calidad"], ai_classification_enabled=True, ai_classification_client=ai_client
    )

    assert context.unclassified_documents == [document.source_path]


@pytest.mark.asyncio
async def test_ai_fallback_disabled_by_default_even_with_client_provided(tmp_path):
    """`ai_classification_enabled=False` (default) — opt-in explícito, el cliente no se usa."""
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina")

    ai_client = _StubAIClient(domain="calidad")
    builder = ContextBuilder()
    context = await builder.build(project, [document], candidate_domains=["calidad"], ai_classification_client=ai_client)

    assert context.unclassified_documents == [document.source_path]
    assert ai_client.calls == []


@pytest.mark.asyncio
async def test_ai_fallback_skips_when_no_catalog_available_at_all(tmp_path):
    """Sin `candidate_domains` y sin ningún dominio descubierto por la Sub-fase A
    (aquí, porque el `.json` es ilegible y por tanto tampoco hay `chunks_text` que
    ofrecerle a la IA), no hay catálogo del que elegir — la Sub-fase B ni siquiera
    llama al cliente, nunca inventa un dominio de la nada. Nota: en modo
    descubrimiento, un documento con `.json` legible SIEMPRE lo clasifica la
    Sub-fase A (score fijo 1.0 por carpeta) — el único caso realista en el que la
    Sub-fase A "falla" en ese modo es un artefacto no legible, que tampoco puede
    resolver la Sub-fase B al depender de la misma fuente (`00_REQUEST.md` §2.4).
    """
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "roto", "Roto")
    Path(document.json_path).unlink()

    ai_client = _StubAIClient(domain="lo-que-sea")
    builder = ContextBuilder()
    context = await builder.build(project, [document], ai_classification_enabled=True, ai_classification_client=ai_client)

    assert context.domains == []
    assert context.unclassified_documents == [document.source_path]
    assert ai_client.calls == []


def _make_manifest(domain_slugs: list[str], material_slugs: list[str]) -> TaxonomyManifest:
    return TaxonomyManifest(
        domains=[TaxonomyCatalogEntry(slug=slug, name=slug.title()) for slug in domain_slugs],
        material_types=[TaxonomyCatalogEntry(slug=slug, name=slug.title()) for slug in material_slugs],
    )


@pytest.mark.asyncio
async def test_build_with_manifest_classifies_both_axes_by_rules(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "Ciberseguridad", "politica", "Política de seguridad normativa ISO 27001")
    manifest = _make_manifest(["ciberseguridad", "calidad"], ["normativa", "procedimiento"])

    context = await ContextBuilder().build(project, [document], taxonomy_manifest=manifest, threshold=0.1)

    assert context.taxonomy_manifest_used is True
    assert context.domains[0].slug == "ciberseguridad"
    assert context.domains[0].documents[0].material_type == "normativa"
    assert context.unclassified_documents == []


@pytest.mark.asyncio
async def test_build_with_manifest_places_document_under_placeholder_instead_of_excluding_it(tmp_path):
    """A diferencia del modo sin manifiesto (test_build_tracks_unclassified_documents_outside_catalog),
    con manifiesto activo un documento que no encaja en ningún dominio/tipo del catálogo
    SIGUE reorganizándose, bajo el slug placeholder 'sin-clasificar' en el eje que falló —
    nunca se excluye por completo mientras tenga los tres artefactos completos."""
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina con ingredientes y horno")
    manifest = _make_manifest(["ciberseguridad", "calidad"], ["normativa", "procedimiento"])

    context = await ContextBuilder().build(project, [document], taxonomy_manifest=manifest, threshold=0.5)

    assert context.unclassified_documents == []
    assert len(context.domains) == 1
    assert context.domains[0].slug == "sin-clasificar"
    assert context.domains[0].documents[0].material_type == "sin-clasificar"


@pytest.mark.asyncio
async def test_build_with_manifest_still_excludes_documents_with_incomplete_artifacts(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "roto", "Roto")
    Path(document.json_path).unlink()
    manifest = _make_manifest(["calidad"], ["normativa"])

    context = await ContextBuilder().build(project, [document], taxonomy_manifest=manifest)

    assert context.domains == []
    assert context.unclassified_documents == [document.source_path]


@pytest.mark.asyncio
async def test_build_with_manifest_excludes_failed_conversion_before_reading_json(tmp_path):
    """Mismo criterio que `test_incomplete_artifacts_go_to_unclassified_not_raised`
    (modo sin manifiesto) aplicado al camino de 2 ejes: un `ConversionResult` marcado
    `success=False` (o sin `markdown_path`/`json_path`) ni siquiera intenta leer el
    `.json` — va directo a `unclassified_documents`."""
    project = _make_project(tmp_path)
    document = ConversionResult(source_path=str(tmp_path / "roto.pdf"), markdown_path=None, json_path=None, success=False, error="conversión fallida")
    manifest = _make_manifest(["calidad"], ["normativa"])

    context = await ContextBuilder().build(project, [document], taxonomy_manifest=manifest)

    assert context.domains == []
    assert context.unclassified_documents == [document.source_path]


@pytest.mark.asyncio
async def test_build_without_manifest_keeps_material_type_unset(tmp_path):
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "Ciberseguridad", "informe", "Informe")

    context = await ContextBuilder().build(project, [document])

    assert context.taxonomy_manifest_used is False
    assert context.domains[0].documents[0].material_type is None


@pytest.mark.asyncio
async def test_build_with_manifest_uses_catalog_entry_keywords_for_scoring(tmp_path):
    """`TaxonomyCatalogEntry.keywords` debe sumar a la puntuación además del propio
    slug — sin esto, un documento que solo menciona las keywords declaradas (nunca la
    palabra exacta del slug) queda sin clasificar en ese eje (AUDIT_CODE). El texto no
    contiene "ciberseguridad" ni "normativa" (las palabras de los slugs) en absoluto —
    solo clasifica gracias a `keywords=["ens"]`/`["controles"]`.
    """
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "informe", "Informe sobre ENS y controles de acceso")
    manifest = TaxonomyManifest(
        domains=[TaxonomyCatalogEntry(slug="ciberseguridad", name="Ciberseguridad", keywords=["ENS"])],
        material_types=[TaxonomyCatalogEntry(slug="normativa", name="Normativa", keywords=["controles"])],
    )

    context = await ContextBuilder().build(project, [document], taxonomy_manifest=manifest, threshold=0.5)

    assert context.domains[0].slug == "ciberseguridad"
    assert context.domains[0].documents[0].material_type == "normativa"


@pytest.mark.asyncio
async def test_build_with_manifest_uses_catalog_entry_name_and_description_for_domain(tmp_path):
    """`TaxonomyCatalogEntry.name`/`.description` del manifiesto deben ganar sobre el
    fallback `slug.replace("-", " ").title()`/`None` — antes de este fix, `Domain.name`
    siempre se derivaba del slug e ignoraba el `name` (obligatorio en el manifiesto) y la
    `description` declarados (AUDIT_CODE, sesión de QA manual de la feature). El slug
    "rrhh" se elige a propósito porque `"rrhh".title()` == "Rrhh", claramente distinto del
    `name` declarado — así el test no puede pasar por coincidencia como con slugs tipo
    "calidad"/"Calidad".
    """
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "informe", "Gestion de personal y plantilla")
    manifest = TaxonomyManifest(
        domains=[TaxonomyCatalogEntry(slug="rrhh", name="Recursos Humanos", description="Gestión de personas", keywords=["personal", "plantilla"])],
        material_types=[TaxonomyCatalogEntry(slug="normativa", name="Normativa")],
    )

    context = await ContextBuilder().build(project, [document], taxonomy_manifest=manifest, threshold=0.5)

    assert context.domains[0].slug == "rrhh"
    assert context.domains[0].name == "Recursos Humanos"
    assert context.domains[0].description == "Gestión de personas"


@pytest.mark.asyncio
async def test_build_with_manifest_placeholder_domain_keeps_slug_derived_name(tmp_path):
    """El placeholder `sin-clasificar` no tiene entrada en el manifiesto -- debe seguir
    cayendo al fallback derivado del slug (`name="Sin Clasificar"`, `description=None`),
    no romperse por el lookup nuevo introducido para el resto de dominios."""
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina con ingredientes y horno")
    manifest = TaxonomyManifest(
        domains=[TaxonomyCatalogEntry(slug="ciberseguridad", name="Ciberseguridad")],
        material_types=[TaxonomyCatalogEntry(slug="normativa", name="Normativa")],
    )

    context = await ContextBuilder().build(project, [document], taxonomy_manifest=manifest, threshold=0.5)

    assert context.domains[0].slug == "sin-clasificar"
    assert context.domains[0].name == "Sin Clasificar"
    assert context.domains[0].description is None


@pytest.mark.asyncio
async def test_build_with_manifest_sets_material_type_name_from_catalog_entry(tmp_path):
    """Mismo hallazgo que el test de dominio, para el segundo eje: `DomainDocument.material_type_name`
    debe reflejar el `name` declarado para el tipo de material, no quedar `None` a la espera de que
    el llamador lo derive del slug."""
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "politica", "Politica de seguridad normativa ISO 27001")
    manifest = TaxonomyManifest(
        domains=[TaxonomyCatalogEntry(slug="ciberseguridad", name="Ciberseguridad")],
        material_types=[TaxonomyCatalogEntry(slug="normativa", name="Normativa Vigente")],
    )

    context = await ContextBuilder().build(project, [document], taxonomy_manifest=manifest, threshold=0.1)

    document_result = context.domains[0].documents[0]
    assert document_result.material_type == "normativa"
    assert document_result.material_type_name == "Normativa Vigente"


@pytest.mark.asyncio
async def test_build_with_manifest_placeholder_material_type_keeps_name_unset(tmp_path):
    """El placeholder `sin-clasificar` en el eje de tipo de material tampoco tiene entrada
    en el manifiesto -- `material_type_name` debe quedar `None` (el llamador, `MkDocsGenerator`,
    es quien decide el fallback visual), no reventar el lookup."""
    project = _make_project(tmp_path)
    document = _make_document(tmp_path, "varios", "receta", "Receta de cocina con ingredientes y horno")
    manifest = _make_manifest(["ciberseguridad", "calidad"], ["normativa", "procedimiento"])

    context = await ContextBuilder().build(project, [document], taxonomy_manifest=manifest, threshold=0.5)

    document_result = context.domains[0].documents[0]
    assert document_result.material_type == "sin-clasificar"
    assert document_result.material_type_name is None
