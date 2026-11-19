"""
Agente diseñador de la taxonomía (2.0.0, G5): `TaxonomyDesignAgent`.

Mejora un manifiesto (o diseña uno desde cero) mirando los documentos del proyecto y **probando** cada cambio con las
reglas (`check_taxonomy_rules`), hasta proponer el que más documentos cubre con menos conflictos. A diferencia de
`draft_taxonomy`, que propone un borrador en una sola llamada a partir de una muestra, el agente comprueba sus cambios
contra todos los documentos.

El agente trabaja sobre un **borrador** que empieza siendo el manifiesto de partida: cada `edit_draft` aplica cambios
pequeños (añadir, cambiar o quitar entradas y palabras clave) y devuelve el informe por reglas; `undo_edit` deshace el
último. Así un modelo local no tiene que escribir el manifiesto entero, y la propuesta es siempre un manifiesto válido
y ya comprobado.

Seguridad (B12, D14):

- Todas sus herramientas son de **solo lectura y locales**: leen los textos ya convertidos (en memoria, una sola vez)
  y calculan; el borrador vive en memoria. La comprobación es por reglas, sin IA dentro de la herramienta.
- **Propone, no aplica**: la propuesta (`TaxonomyDesignProposal`) no se guarda; una persona la revisa y, si quiere, la
  guarda con `save_taxonomy_manifest`.
- Topes de pasos, tokens y herramientas y cancelación (`AgentRunner`).

Example:
    ```python
    agent = TaxonomyDesignAgent(llm)
    proposal = await agent.propose(documents, base=manifest)
    if proposal.manifest is not None:
        print(proposal.base_report.to_markdown(), proposal.report.to_markdown(), proposal.improves)
        print(proposal.markdown())  # para revisarlo y guardarlo
    ```
"""

from __future__ import annotations

import re

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from doc_organize.ai.agents import AgentLimits, AgentRun, AgentRunner, AgentTool
from doc_organize.ai.llm_client import LlmClient
from doc_organize.ai.prompts import PromptRegistry
from doc_organize.context.domain_classifier import _DEFAULT_THRESHOLD
from doc_organize.context.taxonomy_check import AxisRulesReport, CorpusDocument, RulesCorpus, TaxonomyRulesReport, check_taxonomy_rules
from doc_organize.context.taxonomy_templates import render_taxonomy_template
from doc_organize.core.models import ConversionResult, TaxonomyAxis, TaxonomyEntry, TaxonomyManifest
from doc_organize.core.progress import CancelToken
from doc_organize.utils.folding import FoldedText, fold

#: Topes por defecto del diseñador: cada comprobación es barata, pero un modelo local tarda en cada paso; solo los tres
#: últimos resultados van enteros (el informe del borrador ya resume lo anterior).
DEFAULT_DESIGN_LIMITS = AgentLimits(max_steps=24, max_tokens=200_000, max_tool_calls=40, answer_retries=2, keep_tool_results=3)
#: Documentos por página en `search_documents` y caracteres como mucho de `read_document`.
SEARCH_PAGE = 20
READ_MAX_CHARS = 2000
#: Carpetas que muestra `overview` (las de más documentos).
OVERVIEW_FOLDERS = 40
#: Cambios como mucho en un `edit_draft`.
MAX_CHANGES_PER_EDIT = 30

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_KEYWORDS = {"type": "array", "items": {"type": "string"}}
_ENTRY = {
    "type": "object",
    "properties": {"slug": {"type": "string"}, "name": {"type": "string"}, "description": {"type": ["string", "null"]}, "keywords": _KEYWORDS},
    "required": ["slug", "name"],
}
_AXIS = {
    "type": "object",
    "properties": {
        "key": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": ["string", "null"]},
        "organizes": {"type": ["string", "null"], "enum": ["folder", "subfolder", None]},
        "multiple": {"type": "boolean"},
        "entries": {"type": "array", "items": _ENTRY},
    },
    "required": ["key", "name", "entries"],
}
MANIFEST_SCHEMA = {"type": "object", "properties": {"axes": {"type": "array", "items": _AXIS}}, "required": ["axes"]}
CHANGE_SCHEMA = {
    "type": "object",
    "properties": {
        "axis": {"type": "string", "description": "Clave del eje"},
        "action": {"type": "string", "enum": ["add", "update", "remove"]},
        "slug": {"type": "string", "description": "Entrada que se añade, cambia o quita"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "keywords": {**_KEYWORDS, "description": "Sustituye todas las palabras clave"},
        "add_keywords": {**_KEYWORDS, "description": "Añade palabras clave"},
        "remove_keywords": {**_KEYWORDS, "description": "Quita palabras clave"},
    },
    "required": ["axis", "action", "slug"],
}
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"rationale": {"type": "string", "description": "Qué cambiaste en el borrador y por qué (2-6 frases)"}},
    "required": ["rationale"],
}


@dataclass
class TaxonomyDesignProposal:
    """Lo que propone `TaxonomyDesignAgent.propose` (nunca se guarda solo).

    Attributes:
        manifest (TaxonomyManifest | None): El manifiesto propuesto (el borrador al terminar); `None` si el agente no
            terminó (ver `run.stop_reason`) o no hizo ningún borrador.
        rationale (str | None): Qué cambió y por qué, según el agente.
        report (TaxonomyRulesReport | None): Cómo lo clasifican las reglas.
        base_report (TaxonomyRulesReport | None): Cómo clasifican las reglas el de partida (si lo hay).
        run (AgentRun): La ejecución del agente (pasos, herramientas, tokens, motivo de parada).
        draft (TaxonomyManifest | None): El último borrador válido, también si el agente no terminó (para no perder lo
            avanzado; no es una propuesta: el agente no la dio por buena).
        edits (int): Ediciones del borrador que quedaron (tras deshacer).
    """

    manifest: TaxonomyManifest | None
    rationale: str | None
    report: TaxonomyRulesReport | None
    base_report: TaxonomyRulesReport | None
    run: AgentRun
    draft: TaxonomyManifest | None = None
    edits: int = 0

    @property
    def improves(self) -> bool | None:
        """Si la propuesta mejora el de partida por reglas (`TaxonomyRulesReport.improves_on`); `None` sin uno de los
        dos."""
        if self.report is None or self.base_report is None:
            return None
        return self.report.improves_on(self.base_report)

    def markdown(self, body: str = "") -> str | None:
        """La propuesta como manifiesto (front matter + `body`), lista para revisar y guardar."""
        return render_taxonomy_template(self.manifest, body) if self.manifest is not None else None


class TaxonomyDesignAgent:
    """Agente que propone un manifiesto de taxonomía comprobado con las reglas.

    Args:
        llm: Cliente de IA (tarea `agent`).
        prompts: Prompts (por defecto, los empaquetados); el del agente es `taxonomy_agent`.
        limits: Topes (`DEFAULT_DESIGN_LIMITS`).
        threshold: Umbral de las reglas (el de `ContextBuilder.build`).
    """

    def __init__(
        self, llm: LlmClient, *, prompts: PromptRegistry | None = None, limits: AgentLimits | None = None, threshold: float = _DEFAULT_THRESHOLD
    ) -> None:
        self.llm = llm
        self.prompts = prompts or PromptRegistry()
        self.limits = limits or DEFAULT_DESIGN_LIMITS
        self.threshold = threshold

    async def propose(
        self,
        documents: Sequence[ConversionResult] | RulesCorpus,
        *,
        base: TaxonomyManifest | None = None,
        instructions: str = "",
        roots: Sequence[str] | None = None,
        cancel_token: CancelToken | None = None,
    ) -> TaxonomyDesignProposal:
        """Propone un manifiesto para `documents`, mejorando `base` si se da.

        Args:
            documents: Documentos convertidos (o un `RulesCorpus` ya leído).
            base: Manifiesto de partida (el del proyecto o una plantilla): es el primer borrador, y la propuesta
                conserva sus ejes, título, descripción y perfil.
            instructions: Indicaciones de la persona para el agente (p. ej. «separa calidad de medio ambiente»).
            roots: Raíces de escaneo para las claves de los documentos.
            cancel_token: Para cancelar desde fuera.

        Raises:
            ValueError: No hay ningún documento legible.
            AiAuthError, AiConnectionError, AiError: Fallos del proxy.
        """
        corpus = documents if isinstance(documents, RulesCorpus) else await RulesCorpus.load(documents, roots=roots)
        if not corpus.documents:
            raise ValueError("No hay ningún documento legible para diseñar la taxonomía")
        base_report = check_taxonomy_rules(base, corpus, threshold=self.threshold) if base is not None else None
        tools = _Tools(corpus, base, base_report, self.threshold)
        runner = AgentRunner(self.llm, tools.all(), limits=self.limits, answer_schema=ANSWER_SCHEMA, parse_answer=tools.parse_answer)
        messages = self.prompts.get("agent", "taxonomy_agent").render(
            threshold=f"{self.threshold:.2f}".replace(".", ","),
            documents=len(corpus.documents),
            start="Partes del manifiesto de partida: es tu primer borrador." if base is not None else _NO_BASE,
            instructions=_instructions(instructions),
        )
        run = await runner.run(messages, cancel_token=cancel_token)
        edits = len(tools.history)
        if not run.finished:
            return TaxonomyDesignProposal(
                manifest=None, rationale=None, report=None, base_report=base_report, run=run, draft=tools.draft, edits=edits
            )
        manifest, rationale = run.answer
        return TaxonomyDesignProposal(
            manifest=manifest,
            rationale=rationale,
            report=check_taxonomy_rules(manifest, corpus, threshold=self.threshold),
            base_report=base_report,
            run=run,
            draft=manifest,
            edits=edits,
        )


_NO_BASE = "No hay manifiesto de partida: crea el primer borrador con `set_draft` (un eje `domains` y uno `material_types`)."


@dataclass
class _Tools:
    """Las herramientas del diseñador sobre un corpus ya leído (solo lectura; el borrador vive en memoria)."""

    corpus: RulesCorpus
    base: TaxonomyManifest | None
    base_report: TaxonomyRulesReport | None
    threshold: float
    history: list[TaxonomyManifest | None] = field(default_factory=list)
    draft: TaxonomyManifest | None = None

    def __post_init__(self) -> None:
        self.draft = self.base
        self.by_key = {item.key: item for item in self.corpus.documents}
        self._folded: dict[str, FoldedText] = {}

    def all(self) -> list[AgentTool]:
        empty = {"type": "object", "properties": {}}
        return [
            AgentTool("overview", "Resumen: documentos por carpeta, el borrador actual y su informe por reglas.", empty, self.overview),
            AgentTool(
                "search_documents",
                "Documentos cuyo título o texto contiene `query` (palabra o frase, sin distinguir mayúsculas ni acentos), "
                "opcionalmente de una carpeta; sin `query`, los de la carpeta. Devuelve el total y una página.",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}, "folder": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}},
                },
                self.search_documents,
            ),
            AgentTool(
                "read_document",
                f"El comienzo del texto de un documento (hasta {READ_MAX_CHARS} caracteres), por su clave.",
                {"type": "object", "properties": {"key": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["key"]},
                self.read_document,
            ),
            AgentTool(
                "edit_draft",
                "Aplica cambios al borrador (añadir, cambiar o quitar entradas y palabras clave) y devuelve su informe por "
                "reglas comparado con el de partida. Si un cambio no es válido, no se aplica ninguno.",
                {"type": "object", "properties": {"changes": {"type": "array", "items": CHANGE_SCHEMA}}, "required": ["changes"]},
                self.edit_draft,
                idempotent=False,
            ),
            AgentTool("undo_edit", "Deshace la última edición del borrador y devuelve su informe.", empty, self.undo_edit, idempotent=False),
            AgentTool(
                "set_draft",
                "Sustituye el borrador por un manifiesto completo (para empezar sin manifiesto de partida) y devuelve su informe.",
                {"type": "object", "properties": {"manifest": MANIFEST_SCHEMA}, "required": ["manifest"]},
                self.set_draft,
                idempotent=False,
            ),
        ]

    # --- Herramientas --------------------------------------------------------------------------------------------------

    def overview(self, arguments: dict[str, Any]) -> dict[str, Any]:
        folders = Counter(_top_folder(item) for item in self.corpus.documents)
        return {
            "documents": len(self.corpus.documents),
            "folders": [{"folder": folder or "(raíz)", "documents": count} for folder, count in folders.most_common(OVERVIEW_FOLDERS)],
            "draft": _manifest_json(self.draft) if self.draft is not None else None,
            "report": self._report(self.draft) if self.draft is not None else None,
        }

    def search_documents(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = fold(str(arguments.get("query") or ""))
        folder = str(arguments.get("folder") or "").strip("/")
        offset = max(0, int(arguments.get("offset") or 0))
        found = [
            item
            for item in self.corpus.documents
            if (not folder or item.folder == folder or item.folder.startswith(folder + "/")) and (not query or self._text(item).contains(query))
        ]
        page = found[offset : offset + SEARCH_PAGE]
        return {"total": len(found), "offset": offset, "documents": [{"key": item.key, "title": item.display_title} for item in page]}

    def read_document(self, arguments: dict[str, Any]) -> dict[str, Any]:
        key = str(arguments["key"])
        item = self.by_key.get(key)
        if item is None:
            raise KeyError(f"no hay ningún documento con la clave '{key}' (usa las de search_documents)")
        limit = min(READ_MAX_CHARS, max(100, int(arguments.get("max_chars") or READ_MAX_CHARS)))
        return {"key": item.key, "folder": item.folder, "title": item.display_title, "text": item.chunks_text[:limit]}

    def edit_draft(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.draft is None:
            raise ValueError("todavía no hay borrador: créalo con set_draft")
        changes = arguments.get("changes")
        if not isinstance(changes, list) or not changes:
            raise TypeError("'changes' debe ser una lista de cambios")
        if len(changes) > MAX_CHANGES_PER_EDIT:
            raise ValueError(f"como mucho {MAX_CHANGES_PER_EDIT} cambios por edición")
        previous, draft = self.draft, self.draft
        for index, change in enumerate(changes, start=1):
            try:
                draft = _apply_change(draft, change)
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"cambio {index}: {exc}; no se aplicó ningún cambio") from exc
        self._push(draft)
        result = self._report(draft)
        before = check_taxonomy_rules(previous, self.corpus, threshold=self.threshold)
        result["before_this_edit"] = {axis.axis: _axis_summary(axis) for axis in before.axes}
        return result

    def undo_edit(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.history:
            raise ValueError("no hay ninguna edición que deshacer")
        self.draft = self.history.pop()
        return self._report(self.draft) if self.draft is not None else {"draft": None}

    def set_draft(self, arguments: dict[str, Any]) -> dict[str, Any]:
        manifest = self.validate(arguments.get("manifest"))
        self._push(manifest)
        return self._report(manifest)

    # --- Borrador y validación -----------------------------------------------------------------------------------------

    def _push(self, draft: TaxonomyManifest) -> None:
        self.history.append(self.draft)  # `None` antes del primer `set_draft`
        self.draft = draft

    def validate(self, raw: Any) -> TaxonomyManifest:
        """Un manifiesto completo validado, con lo que no toca el agente (título, perfil) del de partida.

        Raises:
            TypeError: No es un objeto con `axes`.
            ValueError: No es un manifiesto válido o cambia los ejes del de partida.
        """
        if not isinstance(raw, dict) or not isinstance(raw.get("axes"), list):
            raise TypeError("el manifiesto debe ser un objeto con 'axes' (lista de ejes)")
        manifest = _validated({"schema": 2, "axes": raw["axes"]})
        if self.base is None:
            return manifest
        expected = {axis.key: (axis.organizes, axis.multiple) for axis in self.base.axes}
        found = {axis.key: (axis.organizes, axis.multiple) for axis in manifest.axes}
        if found != expected:
            raise ValueError(f"conserva los ejes del manifiesto de partida (clave → organizes, multiple): {expected}")
        return manifest.model_copy(update={"title": self.base.title, "description": self.base.description, "profile": self.base.profile})

    def parse_answer(self, data: dict[str, Any]) -> tuple[TaxonomyManifest, str]:
        if self.draft is None:
            raise ValueError("no hay borrador: créalo con set_draft antes de terminar")
        rationale = data.get("rationale")
        return self.draft, rationale.strip() if isinstance(rationale, str) else ""

    def _report(self, manifest: TaxonomyManifest) -> dict[str, Any]:
        report = check_taxonomy_rules(manifest, self.corpus, threshold=self.threshold)
        result = _report_json(report, self.corpus)
        if self.base_report is not None:
            result["improves_on_base"] = report.improves_on(self.base_report)
            result["base"] = {axis.axis: _axis_summary(axis) for axis in self.base_report.axes}
        result["edits"] = len(self.history)
        return result

    def _text(self, item: CorpusDocument) -> FoldedText:
        if item.key not in self._folded:
            self._folded[item.key] = FoldedText.of(item.title, item.chunks_text)
        return self._folded[item.key]


def _apply_change(manifest: TaxonomyManifest, change: Any) -> TaxonomyManifest:
    """`manifest` con un cambio aplicado (no modifica `manifest`)."""
    if not isinstance(change, dict):
        raise TypeError("cada cambio debe ser un objeto")
    axis = manifest.axis(str(change.get("axis")))
    if axis is None:
        raise ValueError(f"el eje '{change.get('axis')}' no existe; los ejes son {[axis.key for axis in manifest.axes]}")
    action = change.get("action")
    if action not in _ACTIONS:
        raise ValueError(f"acción '{action}' no válida (add, update o remove)")
    entries = _ACTIONS[action](list(axis.entries), str(change.get("slug") or ""), change, axis.key)
    axes = [_validated_axis(axis.model_copy(update={"entries": entries})) if item.key == axis.key else item for item in manifest.axes]
    return manifest.model_copy(update={"axes": axes})


def _position(entries: list[TaxonomyEntry], slug: str, axis: str) -> int:
    position = next((index for index, entry in enumerate(entries) if entry.slug == slug), None)
    if position is None:
        raise ValueError(f"'{slug}' no existe en '{axis}'; sus entradas son {[entry.slug for entry in entries]}")
    return position


def _add(entries: list[TaxonomyEntry], slug: str, change: dict[str, Any], axis: str) -> list[TaxonomyEntry]:
    if any(entry.slug == slug for entry in entries):
        raise ValueError(f"'{slug}' ya existe en '{axis}' (usa update)")
    if not _SLUG.match(slug):
        raise ValueError(f"slug '{slug}' no válido: kebab-case, sin acentos ni espacios")
    return [*entries, _entry(TaxonomyEntry(slug=slug, name=str(change.get("name") or slug)), change)]


def _update(entries: list[TaxonomyEntry], slug: str, change: dict[str, Any], axis: str) -> list[TaxonomyEntry]:
    position = _position(entries, slug, axis)
    entries[position] = _entry(entries[position], change)
    return entries


def _remove(entries: list[TaxonomyEntry], slug: str, change: dict[str, Any], axis: str) -> list[TaxonomyEntry]:
    entries.pop(_position(entries, slug, axis))
    return entries


_ACTIONS = {"add": _add, "update": _update, "remove": _remove}


def _entry(entry: TaxonomyEntry, change: dict[str, Any]) -> TaxonomyEntry:
    keywords = list(entry.keywords)
    if "keywords" in change:
        keywords = _strings(change["keywords"])
    keywords += [keyword for keyword in _strings(change.get("add_keywords")) if fold(keyword) not in {fold(k) for k in keywords}]
    removed = {fold(keyword) for keyword in _strings(change.get("remove_keywords"))}
    update: dict[str, Any] = {"keywords": [keyword for keyword in keywords if fold(keyword) not in removed]}
    if change.get("name"):
        update["name"] = str(change["name"])
    if change.get("description"):
        update["description"] = str(change["description"])
    return TaxonomyEntry.model_validate({**entry.model_dump(), **update})


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("las palabras clave van en una lista")
    return [str(item).strip() for item in value if str(item).strip()]


def _validated_axis(axis: TaxonomyAxis) -> TaxonomyAxis:
    try:
        return TaxonomyAxis.model_validate(axis.model_dump())
    except ValidationError as exc:
        raise ValueError(_errors(exc)) from exc


def _validated(raw: dict[str, Any]) -> TaxonomyManifest:
    try:
        return TaxonomyManifest.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"manifiesto no válido: {_errors(exc)}") from exc


def _errors(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()[:8])


def _top_folder(item: CorpusDocument) -> str:
    """La carpeta del documento hasta dos niveles."""
    return "/".join(item.folder.split("/")[:2]) if item.folder else ""


def _manifest_json(manifest: TaxonomyManifest) -> dict[str, Any]:
    return {
        "axes": [
            {
                **axis.model_dump(include={"key", "name", "organizes", "multiple"}, exclude_none=True),
                "entries": [entry.model_dump(include={"slug", "name", "keywords"}) for entry in axis.entries],
            }
            for axis in manifest.axes
        ]
    }


def _axis_summary(axis: AxisRulesReport) -> dict[str, Any]:
    return {"coverage": round(axis.coverage, 3), "covered": axis.covered, "documents": axis.documents, "conflicts": axis.conflicts}


def _report_json(report: TaxonomyRulesReport, corpus: RulesCorpus) -> dict[str, Any]:
    titles = {item.key: item.display_title for item in corpus.documents}
    axes = {}
    for axis in report.axes:
        axes[axis.axis] = {
            **_axis_summary(axis),
            "entry_counts": axis.entry_counts,
            "empty_entries": axis.empty_entries,
            "shared_terms": dict(list(axis.shared_terms.items())[:10]),
            "unused_keywords": axis.unused_keywords,
            "uncovered_examples": [{"key": key, "title": titles.get(key, key)} for key in axis.uncovered_examples],
            "conflict_examples": [{"key": key, "title": titles.get(key, key), "tied": tied} for key, tied in axis.conflict_examples.items()],
        }
    return {"axes": axes}


def _instructions(text: str) -> str:
    text = " ".join(text.split())
    return f"Indicaciones de la persona que lo revisará: {text[:1000]}" if text else ""


__all__ = ["DEFAULT_DESIGN_LIMITS", "TaxonomyDesignAgent", "TaxonomyDesignProposal"]
