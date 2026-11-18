"""Redacción de credenciales (1.7.0): reglas, marcadores que no son secretos, idempotencia y su aplicación en todo lo
que sale hacia la IA (`ContextBuilder`, `TaxonomyManifestDraftClient`) y en el sitio (`SiteGenerator`).

Valores sintéticos evidentes: nunca un secreto real.
"""

import json

from datetime import UTC, datetime

import pytest

from doc_organize import redact_credentials, scan_credentials
from doc_organize.ai import PromptRegistry, SampledDocument, draft_taxonomy
from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.site_generator import SiteGenerator
from doc_organize.core.models import AiSettings, Context, ConversionResult, Project
from doc_organize.security import CREDENTIAL_RULES, REDACTED, CredentialFinding
from tests.unit.fake_llm import FakeLlmClient, enrichment, fake_client
from tests.unit.test_site_generator import _PAGE, _site_with_page

FAKE = "Abc123FakeSecretValue9"


# --- reglas -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        (f"client_secret={FAKE}&scope=openid", "client_secret"),
        (f"&amp;client\\_secret= **{FAKE}** &amp;redirect", "client_secret"),  # Markdown de docling
        (f"password={FAKE}", "password"),
        (f"**Contraseña:** {FAKE}", "password"),
        (f"Clave: {FAKE}", "password"),
        (f"https://host/api?user=demo&pass={FAKE}", "password"),
        (f"usuario (demo) y token({FAKE}-0000-1111)", "token"),
        (f"api_key: {FAKE}XYZ", "token"),
        (f"https://demo:{FAKE}@host.example/path", "url_basic_auth"),
    ],
)
def test_detects_and_redacts_the_value_only(text: str, rule: str) -> None:
    result = redact_credentials(text)
    assert [finding.rule for finding in result.findings] == [rule]
    assert FAKE not in result.text
    assert result.text.startswith(text.split(FAKE)[0] + REDACTED)  # la clave se conserva


@pytest.mark.parametrize(
    ("value", "rule"),
    [
        ("AKIAABCDEFGHIJKLMNOP", "aws_access_key"),
        ("ghp_" + "a1" * 18, "github_token"),
        ("sk-proj-" + "A1b2" * 6, "api_key_sk"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkZW1vMTIzNDUifQ.c2lnbmF0dXJlMTIzNDU2", "jwt"),
    ],
)
def test_known_token_formats_are_redacted_whole(value: str, rule: str) -> None:
    result = redact_credentials(f"usar {value} aquí")
    assert [finding.rule for finding in result.findings] == [rule]
    assert result.text == f"usar {REDACTED} aquí"


def test_private_key_block_is_redacted_whole() -> None:
    key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEfake\nlinea2\n-----END RSA PRIVATE KEY-----"
    result = redact_credentials(f"antes\n{key}\ndespués")
    assert result.findings == (CredentialFinding(line=2, rule="private_key"),)
    assert result.text == f"antes\n{REDACTED}\ndespués"


@pytest.mark.parametrize(
    "text",
    [
        "| p2 | String | -- | Password de la llamada a la integración |",
        "**Contraseña:** xxxxxx",
        "password=<oculto>",
        "client_secret: proporcionado por SSO",
        "Contraseña: obligatoria",
        "Token url: [https://idp.example/oauth2/v1/token](https://idp.example/oauth2/v1/token)",
        "password=${DB_PASSWORD}",
        f"client_secret={REDACTED}",
        "El token de acceso caduca a la hora.",
        "La clave del éxito es la constancia.",
    ],
)
def test_placeholders_and_prose_are_left_alone(text: str) -> None:
    assert scan_credentials(text) == []
    assert redact_credentials(text).text == text


def test_redaction_is_idempotent_and_never_exposes_the_value() -> None:
    once = redact_credentials(f"client_secret={FAKE}")
    twice = redact_credentials(once.text)
    assert (twice.text, twice.findings) == (once.text, ())
    assert FAKE not in repr(once.findings)
    assert {finding.rule for finding in once.findings} <= set(CREDENTIAL_RULES)


def test_line_numbers_refer_to_the_original_text() -> None:
    text = "uno\n-----BEGIN PRIVATE KEY-----\na\n-----END PRIVATE KEY-----\n" + f"password={FAKE}\n"
    assert scan_credentials(text) == [CredentialFinding(2, "private_key"), CredentialFinding(5, "password")]


def test_the_marker_is_visible_in_markdown() -> None:
    """Sin `<`/`>`: Python-Markdown tomaría `<REDACTADO>` por una etiqueta HTML y no se vería en el sitio."""
    assert "<" not in REDACTED
    assert ">" not in REDACTED


# --- ContextBuilder: lo que sale hacia la IA ----------------------------------------------------------------------------


def _project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _document(tmp_path, folder: str, stem: str, text: str, title: str) -> ConversionResult:
    source = tmp_path / folder / f"{stem}.pdf"
    source.parent.mkdir(exist_ok=True)
    json_path = tmp_path / f"{stem}.json"
    json_path.write_text(json.dumps({"title": title, "chunks": [{"text": text}]}), encoding="utf-8")
    markdown_path = tmp_path / f"{stem}.md"
    markdown_path.write_text(f"# {stem}", encoding="utf-8")
    return ConversionResult(source_path=str(source), markdown_path=str(markdown_path), json_path=str(json_path), success=True)


def _client(*, redact: bool = True) -> FakeLlmClient:
    """IA que clasifica en `calidad` y describe; guarda lo que recibe (`sent_texts`)."""
    settings = AiSettings(base_url="https://proxy.test", virtual_key="sk-test", rate_limit_retries=0, redact_credentials=redact)
    return fake_client(settings=settings, classify=lambda request: {request.axes[0]: ("calidad", 0.9)}, enrich=enrichment("Resumen", ["ia"]))


async def _build(tmp_path, documents, client: FakeLlmClient) -> Context:
    return await ContextBuilder().build(
        _project(tmp_path), documents, candidate_domains=["calidad"], llm=client, ai_scope="unclassified", enrich=True
    )


@pytest.mark.asyncio
async def test_text_sent_to_the_ai_is_redacted_and_summarised_without_values(tmp_path) -> None:
    documents = [_document(tmp_path, "varios", "acta", f"Acceso al servidor: password={FAKE}", f"token: {FAKE}XYZ")]
    client = _client()

    context = await _build(tmp_path, documents, client)

    assert client.sent_texts, "el documento sin clasificar va a la IA"
    assert all(FAKE not in text for text in client.sent_texts)
    assert any(REDACTED in text for text in client.sent_texts)
    assert context.ai_redact_credentials is True
    [finding] = context.credential_findings
    assert finding.source_path == documents[0].source_path
    assert finding.rules == {"password": 2, "token": 2}  # clasificación + enriquecimiento
    # Solo cambia lo que sale: el contexto guarda el título del documento tal cual (el sitio lo redacta al publicar).
    assert FAKE not in finding.model_dump_json()


@pytest.mark.asyncio
async def test_redaction_can_be_turned_off(tmp_path) -> None:
    documents = [_document(tmp_path, "varios", "acta", f"password={FAKE}", "Acta")]
    client = _client(redact=False)

    context = await _build(tmp_path, documents, client)

    assert any(FAKE in text for text in client.sent_texts)
    assert context.ai_redact_credentials is False
    assert context.credential_findings == []


@pytest.mark.asyncio
async def test_without_ai_nothing_is_reported(tmp_path) -> None:
    documents = [_document(tmp_path, "calidad", "acta", f"password={FAKE}", "Acta")]

    context = await ContextBuilder().build(_project(tmp_path), documents, candidate_domains=["calidad"])

    assert context.credential_findings == []


def test_a_context_from_before_1_6_1_still_loads() -> None:
    now = datetime.now(UTC).isoformat()
    context = Context.model_validate({"project_name": "Demo", "created_at": now, "updated_at": now})
    assert (context.ai_redact_credentials, context.credential_findings) == (False, [])


# --- Borrador de taxonomía (draft_taxonomy) --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("redact", [True, False])
async def test_the_manifest_draft_sample_is_redacted(redact: bool) -> None:
    settings = AiSettings(base_url="https://proxy.test", virtual_key="k", rate_limit_retries=0, redact_credentials=redact)
    draft = {"domains": [{"slug": "ti", "name": "TI"}], "material_types": [{"slug": "acta", "name": "Acta"}], "reasoning": "x"}
    client = fake_client(settings=settings, taxonomy_design=lambda _request: draft)
    sample = [SampledDocument(folder="TI", title=f"token: {FAKE}XYZ", chunks_text=f"password={FAKE}")]

    async with client:
        await draft_taxonomy(client, PromptRegistry(), sample)

    assert (FAKE in client.sent_texts[0]) is not redact


# --- SiteGenerator ----------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_site_pages_are_redacted_before_publishing(tmp_path) -> None:
    project, context, page = _site_with_page(tmp_path, f"# Acceso\n\npassword={FAKE}\n")

    result = await SiteGenerator().generate(project, context, build=False)

    assert result.credentials_redacted == (_PAGE,)
    assert page.read_text(encoding="utf-8") == f"# Acceso\n\npassword={REDACTED}\n"
    again = await SiteGenerator().generate(project, context, build=False)
    assert again.credentials_redacted == ()  # idempotente


@pytest.mark.asyncio
async def test_document_titles_in_the_site_nav_are_redacted(tmp_path) -> None:
    project, context, _ = _site_with_page(tmp_path, "# Acta\n")
    context.domains[0].documents[0].title = f"Acta token: {FAKE}XYZ"

    await SiteGenerator().generate(project, context, build=False)

    config = (tmp_path / "zensical.toml").read_text(encoding="utf-8")
    assert FAKE not in config
    assert REDACTED in config


@pytest.mark.asyncio
async def test_site_redaction_can_be_turned_off(tmp_path) -> None:
    project, context, page = _site_with_page(tmp_path, f"password={FAKE}\n")

    result = await SiteGenerator().generate(project, context, build=False, redact_credentials=False)

    assert result.credentials_redacted == ()
    assert FAKE in page.read_text(encoding="utf-8")
