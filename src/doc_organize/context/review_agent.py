"""
Revisor y auditor de la clasificación (2.0.0, G6): `ReviewAgent` y `audit_taxonomy`.

`ReviewAgent` recorre la cola de revisión (`review_queue`, F6) y, para cada documento, **propone** una decisión
(`ReviewProposal`: confirmar, cambiar un eje, excluir o confirmar la versión vigente) con su justificación y una cita del
documento. **Nunca la aplica** (D14): una persona la acepta convirtiéndola en `ClassificationDecision`
(`ReviewProposal.to_decision`) y guardándola con `ClassificationDecisionStore`.

`audit_taxonomy` es el auditor, sin IA: estadísticas de cómo ha quedado clasificado un contexto (valores por eje, quién
clasificó, confianza baja, citas sin verificar, entradas sin documentos o que se lo llevan casi todo, desacuerdos entre
reglas e IA) y propuestas de qué revisar en el catálogo.

Seguridad (B12): las herramientas del revisor solo leen el contexto y los textos ya convertidos; las propuestas viven en
memoria y se validan contra el catálogo antes de aceptarlas. Topes y cancelación del `AgentRunner`.

Example:
    ```python
    review = await ReviewAgent(llm).propose(context, corpus=corpus, max_items=20)
    for proposal in review.proposals:
        print(proposal.document_key, proposal.action, proposal.axes, proposal.rationale)
    decision = review.proposals[0].to_decision(author="ana")  # solo si una persona la acepta
    await ClassificationDecisionStore(project.root_path).add(decision)

    audit = audit_taxonomy(context)
    print(audit.to_markdown())
    ```
"""

from __future__ import annotations

import uuid

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from doc_organize.ai.agents import AgentLimits, AgentRun, AgentRunner, AgentTool, StepCallback
from doc_organize.ai.llm_client import LlmClient
from doc_organize.ai.prompts import PromptRegistry
from doc_organize.context.domain_classifier import read_conversion_json
from doc_organize.context.evaluation import document_keys
from doc_organize.context.review_queue import ReviewItem, review_queue
from doc_organize.context.taxonomy_check import RulesCorpus
from doc_organize.core.models import ClassificationDecision, Context, DomainDocument, TaxonomyAxis
from doc_organize.core.progress import CancelToken

#: Topes por defecto del revisor: unos pocos pasos por documento.
DEFAULT_REVIEW_LIMITS = AgentLimits(
    max_steps=40, max_tokens=400_000, max_tool_calls=80, max_tool_result_chars=10_000, answer_retries=2, keep_tool_results=4
)
#: Documentos de la cola que se le dan al revisor por defecto.
DEFAULT_REVIEW_ITEMS = 20
#: Caracteres del texto que ve el revisor de cada documento.
REVIEW_TEXT_CHARS = 3000
#: Una entrada «se lo lleva casi todo» si recibe esta fracción de los documentos (en un eje de varias entradas).
DOMINANT_SHARE = 0.5

ProposalAction = Literal["confirm", "set_axis", "exclude", "set_current_version"]


class ReviewProposal(BaseModel):
    """Una decisión que propone el revisor (no aplicada).

    Attributes:
        document_key (str): Documento (clave de las decisiones).
        action (ProposalAction): `confirm`, `set_axis`, `exclude` o `set_current_version`.
        axes (dict[str, list[str]]): Valores por eje (como en `ClassificationDecision`).
        rationale (str): Por qué, según el revisor.
        evidence (str | None): Cita del documento que lo apoya.
        source_sha256 (str | None): Huella del original revisado (la decisión solo valdrá para esa versión).
        id (str): Identificador estable de la propuesta (para guardarla fuera de la librería, aceptarla o descartarla).
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    document_key: str
    action: ProposalAction
    axes: dict[str, list[str]] = Field(default_factory=dict)
    rationale: str = ""
    evidence: str | None = None
    source_sha256: str | None = None

    def to_decision(self, *, author: str | None = None) -> ClassificationDecision:
        """La decisión que resulta de aceptar la propuesta (sin guardar: `ClassificationDecisionStore.add`)."""
        reason = f"Propuesta del revisor: {self.rationale}" if self.rationale else "Propuesta del revisor"
        return ClassificationDecision(
            document_key=self.document_key, source_sha256=self.source_sha256, action=self.action, axes=self.axes, author=author, reason=reason[:1000]
        )


@dataclass
class ReviewResult:
    """Resultado de `ReviewAgent.propose`.

    Attributes:
        proposals (list[ReviewProposal]): Las propuestas (una por documento y acción; la última gana).
        items (list[ReviewItem]): Los elementos de la cola que se le dieron al revisor.
        summary (str | None): Resumen del revisor (si terminó).
        run (AgentRun): La ejecución (pasos, tokens, motivo de parada). Las propuestas valen aunque no terminara.
    """

    proposals: list[ReviewProposal]
    items: list[ReviewItem]
    summary: str | None
    run: AgentRun


class ReviewAgent:
    """Agente que propone decisiones para la cola de revisión (nunca las aplica, D14).

    Args:
        llm: Cliente de IA (tarea `agent`).
        prompts: Prompts (por defecto, los empaquetados); el del revisor es `review_agent`.
        limits: Topes (`DEFAULT_REVIEW_LIMITS`).
    """

    def __init__(self, llm: LlmClient, *, prompts: PromptRegistry | None = None, limits: AgentLimits | None = None) -> None:
        self.llm = llm
        self.prompts = prompts or PromptRegistry()
        self.limits = limits or DEFAULT_REVIEW_LIMITS

    async def propose(
        self,
        context: Context,
        *,
        corpus: RulesCorpus | None = None,
        items: Sequence[ReviewItem] | None = None,
        max_items: int = DEFAULT_REVIEW_ITEMS,
        roots: Sequence[str] | None = None,
        instructions: str = "",
        cancel_token: CancelToken | None = None,
        on_step: StepCallback | None = None,
    ) -> ReviewResult:
        """Propone decisiones para los primeros `max_items` documentos de la cola.

        Args:
            context: El contexto construido (con manifiesto: `taxonomy_axes`).
            corpus: Textos ya leídos (`RulesCorpus.load`); sin él, se lee el `.json` de cada documento cuando se pide.
            items: La cola (por defecto, `review_queue(context)`).
            max_items: Documentos distintos de la cola que se revisan.
            roots: Raíces de escaneo para las claves.
            instructions: Indicaciones de la persona.
            cancel_token: Para cancelar desde fuera.
            on_step: Progreso por paso (`AgentRunner.run`).

        Raises:
            ValueError: El contexto no tiene ejes de taxonomía (sin manifiesto no hay catálogo que proponer).
        """
        if not context.taxonomy_axes:
            raise ValueError("El revisor necesita un contexto construido con manifiesto de taxonomía")
        queue = list(items) if items is not None else review_queue(context, roots=roots)
        selected_keys = list(dict.fromkeys(item.document_key for item in queue))[:max_items]
        selected = [item for item in queue if item.document_key in set(selected_keys)]
        tools = _ReviewTools(context, selected, corpus, roots)
        runner = AgentRunner(self.llm, tools.all(), limits=self.limits, answer_schema=_SUMMARY_SCHEMA, parse_answer=_summary)
        messages = self.prompts.get("agent", "review_agent").render(
            documents=len(selected_keys), catalog=_catalog_text(context.taxonomy_axes), instructions=_instructions(instructions)
        )
        run = await runner.run(messages, cancel_token=cancel_token, on_step=on_step)
        return ReviewResult(proposals=list(tools.proposals.values()), items=selected, summary=run.answer if run.finished else None, run=run)


_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string", "description": "Qué propusiste y qué dejaste sin proponer (2-5 frases)"}},
    "required": ["summary"],
}
_PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "document_key": {"type": "string"},
        "action": {"type": "string", "enum": ["confirm", "set_axis", "exclude", "set_current_version"]},
        "axes": {
            "type": "object",
            "description": "Eje → lista de slugs del catálogo (set_axis: un solo eje; confirm: los ejes que confirmas; vacío en exclude)",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        },
        "rationale": {"type": "string"},
        "evidence": {"type": "string", "description": "Cita literal del documento que lo apoya"},
    },
    "required": ["document_key", "action", "rationale"],
}


def _summary(data: dict[str, Any]) -> str:
    summary = data.get("summary")
    return summary.strip() if isinstance(summary, str) else ""


@dataclass
class _ReviewTools:
    """Herramientas del revisor (solo lectura; las propuestas viven en memoria)."""

    context: Context
    items: list[ReviewItem]
    corpus: RulesCorpus | None
    roots: Sequence[str] | None
    proposals: dict[tuple[str, str], ReviewProposal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        documents = [document for domain in self.context.domains for document in domain.documents]
        keys = document_keys([document.source_path for document in documents], self.roots)
        self.documents = {keys[document.source_path]: document for document in documents}
        self.axes = {axis.key: axis for axis in self.context.taxonomy_axes}
        self.texts = {item.key: item for item in self.corpus.documents} if self.corpus is not None else {}
        self.queue_keys = {item.document_key for item in self.items}

    def all(self) -> list[AgentTool]:
        return [
            AgentTool(
                "list_queue",
                "Los documentos de la cola de revisión que te tocan, con el motivo de cada uno.",
                {"type": "object", "properties": {}},
                self.list_queue,
            ),
            AgentTool(
                "get_document",
                f"Un documento por su clave: su clasificación actual (valor, quién, confianza, cita) y el comienzo del texto "
                f"(hasta {REVIEW_TEXT_CHARS} caracteres).",
                {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
                self.get_document,
            ),
            AgentTool(
                "propose_decision",
                "Registra tu propuesta para un documento de la cola (no se aplica: la revisará una persona). Sustituye la "
                "anterior del mismo documento y eje.",
                _PROPOSAL_SCHEMA,
                self.propose_decision,
                idempotent=False,
            ),
        ]

    def list_queue(self, arguments: dict[str, Any]) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in self.items:
            grouped.setdefault(item.document_key, []).append(
                {
                    key: value
                    for key, value in item.model_dump(include={"reason", "axis", "value", "confidence", "detail"}).items()
                    if value is not None
                }
            )
        proposed = {key for key, _ in self.proposals}
        return {"documents": [{"key": key, "reasons": reasons, "proposed": key in proposed} for key, reasons in grouped.items()]}

    async def get_document(self, arguments: dict[str, Any]) -> dict[str, Any]:
        key = str(arguments["key"])
        document = self.documents.get(key)
        if document is None:
            raise KeyError(f"no hay ningún documento clasificado con la clave '{key}' (usa las de list_queue)")
        return {
            "key": key,
            "title": document.title,
            "axes": {
                axis: [value.model_dump(include={"slug", "confidence", "classified_by", "evidence", "evidence_verified"}) for value in values]
                for axis, values in document.classification.axes.items()
            },
            **({"version": document.version, "is_current": document.is_current} if document.version else {}),
            "text": await self._text(key, document),
        }

    def propose_decision(self, arguments: dict[str, Any]) -> dict[str, Any]:
        key = str(arguments.get("document_key") or "")
        if key not in self.queue_keys:
            raise ValueError(f"'{key}' no está en tu parte de la cola (usa las claves de list_queue)")
        axes = arguments.get("axes") or {}
        if not isinstance(axes, dict):
            raise TypeError("'axes' debe ser un objeto eje → lista de slugs")
        axes = {str(axis): [str(value) for value in (values if isinstance(values, list) else [values])] for axis, values in axes.items()}
        for axis_key, values in axes.items():
            self._check_values(axis_key, values)
        document = self.documents.get(key)
        try:
            proposal = ReviewProposal(
                document_key=key,
                action=arguments.get("action"),  # type: ignore[arg-type]  # lo valida el modelo
                axes=axes,
                rationale=str(arguments.get("rationale") or "")[:1000],
                evidence=str(arguments["evidence"])[:500] if arguments.get("evidence") else None,
                source_sha256=document.source_sha256 if document is not None else None,
            )
            proposal.to_decision()  # mismas reglas que una decisión de verdad
        except ValidationError as exc:
            raise ValueError("; ".join(error["msg"] for error in exc.errors()[:5])) from exc
        slot = next(iter(axes), "") if proposal.action == "set_axis" else ""
        self.proposals[(key, slot)] = proposal
        return {"recorded": True, "document_key": key, "action": proposal.action, "proposals": len(self.proposals)}

    def _check_values(self, axis_key: str, values: list[str]) -> None:
        axis = self.axes.get(axis_key)
        if axis is None:
            raise ValueError(f"el eje '{axis_key}' no existe; los ejes son {sorted(self.axes)}")
        unknown = [value for value in values if value not in {entry.slug for entry in axis.entries}]
        if unknown:
            raise ValueError(f"{unknown} no están en el catálogo de '{axis_key}': {[entry.slug for entry in axis.entries]}")
        if (axis.organizes is not None or not axis.multiple) and len(values) != 1:
            raise ValueError(f"el eje '{axis_key}' lleva exactamente un valor")

    async def _text(self, key: str, document: DomainDocument) -> str:
        if key in self.texts:
            return self.texts[key].chunks_text[:REVIEW_TEXT_CHARS]
        read = await read_conversion_json(document.json_path)
        return read[0][:REVIEW_TEXT_CHARS] if read is not None else "(no se pudo leer el texto)"


def _catalog_text(axes: Sequence[TaxonomyAxis]) -> str:
    lines = []
    for axis in axes:
        kind = "organiza carpetas" if axis.organizes else ("varios valores" if axis.multiple else "un valor")
        lines.append(f"Eje {axis.key} ({axis.name}; {kind}):")
        lines.extend(f"- {entry.slug}: {entry.name}" + (f". {entry.description}" if entry.description else "") for entry in axis.entries)
    return "\n".join(lines)


def _instructions(text: str) -> str:
    text = " ".join(text.split())
    return f"Indicaciones de la persona que revisará tus propuestas: {text[:1000]}" if text else ""


# --- Auditor -----------------------------------------------------------------------------------------------------------

AuditFindingKind = Literal["empty_entry", "dominant_entry", "rules_ai_confusion", "low_confidence", "unverified_evidence", "unclassified"]


class AuditFinding(BaseModel):
    """Una propuesta del auditor.

    Attributes:
        kind (AuditFindingKind): Qué encontró.
        axis (str | None): Eje.
        values (list[str]): Valores implicados.
        count (int): Documentos afectados.
        message (str): Qué revisar.
    """

    kind: AuditFindingKind
    axis: str | None = None
    values: list[str] = Field(default_factory=list)
    count: int = 0
    message: str


class AxisAudit(BaseModel):
    """Estadísticas de un eje en un contexto."""

    axis: str
    documents: int = 0
    with_value: int = 0
    value_counts: dict[str, int] = Field(default_factory=dict)
    classified_by: dict[str, int] = Field(default_factory=dict)
    low_confidence: int = 0
    unverified_evidence: int = 0


class TaxonomyAudit(BaseModel):
    """Resultado de `audit_taxonomy`: estadísticas por eje y propuestas, de más a menos documentos afectados."""

    documents: int = 0
    unclassified: int = 0
    axes: list[AxisAudit] = Field(default_factory=list)
    findings: list[AuditFinding] = Field(default_factory=list)

    def to_markdown(self) -> str:
        """Informe legible: una tabla por eje y la lista de propuestas.

        Example:
            >>> audit = TaxonomyAudit(documents=2, axes=[AxisAudit(axis="domains", documents=2, with_value=1)],
            ...     findings=[AuditFinding(kind="empty_entry", axis="domains", values=["rgpd"], message="Sin documentos")])
            >>> print(audit.to_markdown().splitlines()[2])
            | domains | 2 | 50,0 % | 0 | 0 |
        """
        lines = ["| Eje | Documentos | Con valor | Confianza baja | Citas sin verificar |", "|---|---|---|---|---|"]
        for axis in self.axes:
            share = f"{(axis.with_value / axis.documents if axis.documents else 0) * 100:.1f} %".replace(".", ",")
            lines.append(f"| {axis.axis} | {axis.documents} | {share} | {axis.low_confidence} | {axis.unverified_evidence} |")
        if self.findings:
            lines += ["", "Propuestas:", ""]
            lines += [f"- [{finding.kind}] {finding.message}" for finding in self.findings]
        return "\n".join(lines)


def audit_taxonomy(context: Context, *, min_confusions: int = 3) -> TaxonomyAudit:
    """Estadísticas y propuestas sobre cómo ha quedado clasificado `context` (sin IA ni escritura).

    Args:
        context: Contexto construido con manifiesto.
        min_confusions: Documentos como mínimo para proponer revisar un par reglas → IA.

    Propone revisar: entradas sin documentos (`empty_entry`), entradas que se llevan la mitad o más de un eje
    (`dominant_entry`), pares de dominios en los que la IA corrige a menudo a las reglas (`rules_ai_confusion`: sus
    descripciones o palabras clave se confunden), y ejes con muchos valores de confianza baja o citas sin verificar.
    """
    documents = [document for domain in context.domains for document in domain.documents]
    threshold = context.ai_fallback_threshold
    audit = TaxonomyAudit(documents=len(documents), unclassified=len(context.unclassified_details))
    for axis in context.taxonomy_axes:
        stats = AxisAudit(axis=axis.key, documents=len(documents))
        counts: Counter[str] = Counter()
        by: Counter[str] = Counter()
        limit = axis.threshold if axis.threshold is not None else threshold
        for document in documents:
            values = document.classification.axes.get(axis.key, [])
            stats.with_value += bool(values)
            counts.update(value.slug for value in values)
            by.update(value.classified_by for value in values)
            stats.low_confidence += sum(1 for value in values if value.classified_by != "human" and value.confidence < limit)
            stats.unverified_evidence += sum(1 for value in values if value.evidence_verified is False)
        stats.value_counts = {entry.slug: counts.get(entry.slug, 0) for entry in axis.entries}
        stats.classified_by = dict(sorted(by.items()))
        audit.axes.append(stats)
        audit.findings += _axis_findings(axis, stats)
    audit.findings += _confusions(context, documents, min_confusions)
    if audit.unclassified:
        audit.findings.append(
            AuditFinding(
                kind="unclassified",
                count=audit.unclassified,
                message=f"{audit.unclassified} documentos sin clasificar (sin conversión o sin dominio)",
            )
        )
    audit.findings.sort(key=lambda finding: finding.count, reverse=True)
    return audit


def _axis_findings(axis: TaxonomyAxis, stats: AxisAudit) -> list[AuditFinding]:
    findings = []
    empty = [slug for slug, count in stats.value_counts.items() if not count]
    if empty and stats.documents:
        findings.append(
            AuditFinding(
                kind="empty_entry",
                axis=axis.key,
                values=empty,
                message=f"Eje {axis.key}: sin documentos en {', '.join(empty)}. ¿Sobran, o les faltan palabras clave que usen los documentos?",
            )
        )
    if len(axis.entries) > 1 and stats.documents:
        for slug, count in stats.value_counts.items():
            if count / stats.documents >= DOMINANT_SHARE:
                findings.append(
                    AuditFinding(
                        kind="dominant_entry",
                        axis=axis.key,
                        values=[slug],
                        count=count,
                        message=f"Eje {axis.key}: «{slug}» tiene {count} de {stats.documents} documentos. ¿Es demasiado general, o conviene dividirlo?",
                    )
                )
    for kind, count, text in (
        ("low_confidence", stats.low_confidence, "valores con confianza por debajo del umbral"),
        ("unverified_evidence", stats.unverified_evidence, "citas de la IA que no aparecen en el documento"),
    ):
        if count:
            findings.append(AuditFinding(kind=kind, axis=axis.key, count=count, message=f"Eje {axis.key}: {count} {text} (ver la cola de revisión)"))  # type: ignore[arg-type]
    return findings


def _confusions(context: Context, documents: list[DomainDocument], minimum: int) -> list[AuditFinding]:
    folder = next((axis for axis in context.taxonomy_axes if axis.organizes == "folder"), None)
    pairs: Counter[tuple[str, str]] = Counter(
        (document.rules_domain, document.ai_domain)
        for document in documents
        if document.rules_domain and document.ai_domain and document.rules_domain != document.ai_domain
    )
    return [
        AuditFinding(
            kind="rules_ai_confusion",
            axis=folder.key if folder else None,
            values=[rules, ai],
            count=count,
            message=f"La IA corrigió {count} veces «{rules}» (reglas) por «{ai}»: revisa sus descripciones y palabras clave para separarlos",
        )
        for (rules, ai), count in pairs.most_common()
        if count >= minimum
    ]


__all__ = [
    "DEFAULT_REVIEW_LIMITS",
    "AuditFinding",
    "AxisAudit",
    "ReviewAgent",
    "ReviewProposal",
    "ReviewResult",
    "TaxonomyAudit",
    "audit_taxonomy",
]
