"""
`llms.txt` del contexto (2.0.0, F7): el índice que lee un chat o un agente de IA, en el paquete para IA
(`write_ai_context_bundle`) y en la raíz del sitio (`SiteGenerator.generate(llms_txt=True)`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from doc_organize.context.evaluation import document_keys
from doc_organize.context.reorganizer import resolve_organized_paths
from doc_organize.core.models import Context, Domain, DomainDocument
from doc_organize.security.credentials import redact_credentials


@dataclass(frozen=True)
class LlmsEntry:
    """Un documento del contexto con su ruta en la carpeta reorganizada y la de su original."""

    domain: Domain
    document: DomainDocument
    organized: str  # ruta del `.md` en la carpeta reorganizada (dominio/tipo/carpeta/doc.md)
    key: str  # ruta del original relativa a la raíz de escaneo


def render_llms_txt(
    project_name: str, context: Context, link: Callable[[str], str], *, project_root: str = ".", redact: bool = True, current_only: bool = True
) -> str:
    """El `llms.txt` del contexto: una sección por dominio y una línea por documento.

    Args:
        project_name: Nombre del proyecto (título).
        context: El contexto.
        link: Ruta del `.md` en la carpeta reorganizada → enlace en el destino (el paquete o el sitio).
        project_root: Raíz del proyecto (desambigua dos documentos con el mismo nombre, como `resolve_organized_paths`).
        redact: Títulos y descripciones sin credenciales.
        current_only: Sin las versiones antiguas.

    Example:
        >>> from doc_organize.core.models import Domain, DomainDocument
        >>> document = DomainDocument(source_path="/d/Manual.pdf", markdown_path="/c/Manual.md", json_path="/c/Manual.json",
        ...     title="Manual de calidad", document_type="pdf", confidence=1.0, description="Cómo se gestiona la calidad")
        >>> context = Context(project_name="p", created_at="2026-01-01", updated_at="2026-01-01",
        ...     domains=[Domain(slug="calidad", name="Calidad", documents=[document])])
        >>> print(render_llms_txt("Demo", context, lambda path: path), end="")
        # Demo
        <BLANKLINE>
        > Documentación organizada del proyecto Demo: 1 documento en 1 dominio.
        <BLANKLINE>
        ## Calidad
        <BLANKLINE>
        - [Manual de calidad](calidad/pdf/Manual/Manual.md): Cómo se gestiona la calidad
    """
    entries = llms_entries(context, project_root, current_only=current_only)[0]
    domains = list(dict.fromkeys(entry.domain.slug for entry in entries))
    count = len(entries)
    lines = [
        f"# {one_line(project_name, redact)}",
        "",
        (
            f"> Documentación organizada del proyecto {one_line(project_name, redact)}: {count} documento{'s' if count != 1 else ''} "
            f"en {len(domains)} dominio{'s' if len(domains) != 1 else ''}."
        ),
    ]
    for slug in domains:
        domain_entries = [entry for entry in entries if entry.domain.slug == slug]
        lines += ["", f"## {one_line(domain_entries[0].domain.name, redact)}", ""]
        for entry in domain_entries:
            summary = entry.document.description or entry.document.material_type_name or ""
            line = f"- [{_link_text(one_line(entry.document.title, redact))}]({link(entry.organized)})"
            lines.append(f"{line}: {one_line(summary, redact)}" if summary else line)
    return "\n".join(lines) + "\n"


def llms_entries(context: Context, project_root: str, *, current_only: bool, roots: Sequence[str] | None = None) -> tuple[list[LlmsEntry], int]:
    superseded = set(context.superseded_documents)
    pairs = [
        (domain, document, organized)
        for domain in context.domains
        for document, organized in zip(domain.documents, resolve_organized_paths(domain, project_root), strict=True)
    ]
    keys = document_keys([document.source_path for _, document, _ in pairs], roots)
    entries, skipped = [], 0
    for domain, document, organized in pairs:
        if current_only and (document.source_path in superseded or document.is_current is False):
            skipped += 1
            continue
        entries.append(LlmsEntry(domain=domain, document=document, organized=organized, key=keys[document.source_path]))
    return entries, skipped


def one_line(text: str | None, redact: bool) -> str:
    value = " ".join((text or "").split())
    return redact_credentials(value).text if redact else value


def _link_text(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


__all__ = ["LlmsEntry", "llms_entries", "one_line", "render_llms_txt"]
