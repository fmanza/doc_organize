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
from dataclasses import dataclass
from typing import Any

from doc_organize.ai.cache import AiResultCache
from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.evaluation import EvaluationReport, GoldStandard, common_root, document_keys, evaluate_classification
from doc_organize.core.models import Context, ConversionResult, Project


@dataclass(frozen=True)
class DryRunResult:
    """Resultado de `dry_run_classify`.

    Attributes:
        context (Context): El contexto construido (sin guardar); `context.ai_stats` trae llamadas, tokens y tiempos.
        evaluation (EvaluationReport | None): Su evaluación contra la referencia, si se dio.
        documents (int): Documentos clasificados (los de la referencia si `only_gold`).
    """

    context: Context
    evaluation: EvaluationReport | None
    documents: int


async def dry_run_classify(
    project: Project,
    documents: Sequence[ConversionResult],
    *,
    gold: GoldStandard | None = None,
    only_gold: bool = True,
    roots: Sequence[str] | None = None,
    builder: ContextBuilder | None = None,
    ai_cache: bool | AiResultCache = False,
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
    context = await (builder or ContextBuilder()).build(project, selected, ai_cache=ai_cache, scan_roots=roots, persist=False, **build_options)
    evaluation = evaluate_classification(context, gold, roots=roots) if gold is not None else None
    return DryRunResult(context=context, evaluation=evaluation, documents=len(selected))


__all__ = ["DryRunResult", "dry_run_classify"]
