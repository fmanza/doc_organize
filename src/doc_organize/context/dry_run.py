"""
Clasificación de prueba (2.0.0, G3): construir un contexto **sin guardarlo** para comparar reglas, prompts, perfiles o
modelos antes de adoptarlos, y medirlo contra una referencia si se da.

`dry_run_classify` llama a `ContextBuilder.build(..., persist=False)`: no escribe `context.json` ni el histórico y, por
defecto, no usa la caché de IA (para que dos modelos o dos prompts se comparen con llamadas de verdad). Con una
referencia, solo clasifica los documentos que están en ella, para gastar el presupuesto de IA en lo que se mide.

Example:
    ```python
    base = await dry_run_classify(project, documents, gold=gold, taxonomy_manifest=manifest, llm=llm, ai_scope="unclassified")
    nuevo = await dry_run_classify(project, documents, gold=gold, taxonomy_manifest=manifest, llm=llm, ai_scope="unclassified",
                                   prompts=PromptRegistry(carpeta_con_el_prompt_nuevo))
    print(base.evaluation.to_markdown(), nuevo.evaluation.to_markdown())
    ```
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from doc_organize.ai.cache import AiResultCache
from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.evaluation import EvaluationReport, GoldStandard, _predictions, common_root, document_keys, evaluate_classification
from doc_organize.core.models import Context, ConversionResult, Project


@dataclass(frozen=True)
class DocumentChange:
    """Un documento cuyo valor en un eje cambia entre el contexto de partida y la prueba.

    Attributes:
        document_key (str): Clave del documento.
        axis (str): Eje.
        before (list[str]): Valores en el contexto de partida (vacío si no tenía o el documento no estaba).
        after (list[str]): Valores en la prueba.
        before_by (str | None): Quién los asignó en el de partida (`rules`, `semantic`, `ai`, `human`), o `None`.
        after_by (str | None): Quién en la prueba, o `None`.
    """

    document_key: str
    axis: str
    before: list[str]
    after: list[str]
    before_by: str | None = None
    after_by: str | None = None


@dataclass(frozen=True)
class DryRunResult:
    """Resultado de `dry_run_classify`.

    Attributes:
        context (Context): El contexto construido (sin guardar); `context.ai_stats` trae llamadas, tokens y tiempos.
        evaluation (EvaluationReport | None): Su evaluación contra la referencia, si se dio.
        documents (int): Documentos clasificados (los de la referencia si `only_gold`).
        changes (list[DocumentChange]): Con `baseline`, los documentos (de los clasificados en la prueba) cuyo valor
            cambia en algún eje, ordenados por documento y eje; vacío sin `baseline`.
    """

    context: Context
    evaluation: EvaluationReport | None
    documents: int
    changes: list[DocumentChange] = field(default_factory=list)


async def dry_run_classify(
    project: Project,
    documents: Sequence[ConversionResult],
    *,
    gold: GoldStandard | None = None,
    only_gold: bool = True,
    roots: Sequence[str] | None = None,
    builder: ContextBuilder | None = None,
    ai_cache: bool | AiResultCache = False,
    baseline: Context | None = None,
    **build_options: Any,
) -> DryRunResult:
    """Clasifica `documents` como lo haría `ContextBuilder.build`, sin guardar nada, y evalúa contra `gold`.

    Args:
        project: Proyecto (su raíz da los prompts, el perfil y las decisiones, que solo se leen).
        documents: Documentos convertidos.
        gold: Referencia (`load_gold_xlsx`, `gold_from_decisions`); sin ella no hay evaluación.
        only_gold: Con `gold`, clasificar solo los documentos que están en ella (por defecto).
        roots: Raíces de escaneo para las claves (por defecto, la carpeta común de todos los originales); también se
            pasan a `build(scan_roots=)`.
        builder: El `ContextBuilder` (por defecto, uno nuevo).
        ai_cache: Como en `build`; por defecto `False`, para comparar con llamadas de verdad.
        baseline: El contexto de partida (el guardado, `ContextRegistry.load_context`); con él, `DryRunResult.changes`
            dice qué documentos cambian de valor y en qué eje.
        **build_options: El resto de opciones de `ContextBuilder.build` (`taxonomy_manifest`, `llm`, `ai_scope`,
            `prompts`, `profile`, `ai_max_documents`...). `persist` no se admite: nunca se guarda.

    Raises:
        TypeError: Se pasó `persist`.
    """
    if "persist" in build_options:
        raise TypeError("dry_run_classify nunca guarda el contexto: no admite persist")
    selected = list(documents)
    if roots is None:  # la raíz común de **todos**: tras filtrar podría ser otra y cambiarían las claves
        root = common_root(document.source_path for document in selected)
        roots = [root] if root else []
    if gold is not None and only_gold:
        keys = document_keys([document.source_path for document in selected], roots)
        wanted = set(gold.by_document())
        selected = [document for document in selected if keys[document.source_path] in wanted]
    if gold is not None:  # la referencia nunca sirve de ejemplo a la IA: vería la respuesta (B16)
        build_options["example_exclusions"] = [*build_options.get("example_exclusions", ()), *gold.by_document()]
    context = await (builder or ContextBuilder()).build(project, selected, ai_cache=ai_cache, scan_roots=roots, persist=False, **build_options)
    evaluation = evaluate_classification(context, gold, roots=roots) if gold is not None else None
    changes = _changes(baseline, context, roots) if baseline is not None else []
    return DryRunResult(context=context, evaluation=evaluation, documents=len(selected), changes=changes)


def _changes(baseline: Context, trial: Context, roots: Sequence[str] | None) -> list[DocumentChange]:
    """Los valores que cambian, por documento y eje, entre `baseline` y `trial` (solo los documentos de `trial`)."""
    before, after = _predictions(baseline, roots), _predictions(trial, roots)
    changes = []
    for key in sorted(after):
        old_axes, new_axes = before.get(key, {}), after[key]
        for axis in sorted(set(old_axes) | set(new_axes)):
            old_values, old_by = old_axes.get(axis, ([], None))
            new_values, new_by = new_axes.get(axis, ([], None))
            if sorted(old_values) != sorted(new_values):
                changes.append(
                    DocumentChange(
                        document_key=key,
                        axis=axis,
                        before=list(old_values),
                        after=list(new_values),
                        before_by=old_by if old_values else None,
                        after_by=new_by if new_values else None,
                    )
                )
    return changes


__all__ = ["DocumentChange", "DryRunResult", "dry_run_classify"]
