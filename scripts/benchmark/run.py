"""Benchmark de la clasificación del contexto (F0 de `.ai/sessions/2026-11-27-precision-contexto/PLAN.md`, E3).

Herramienta de medición, **no** API: puede usar internos de la librería (las ablaciones parchean `score_catalog` solo
dentro de este proceso) y no se empaqueta. Aplica el protocolo de `docs/guides/medir_clasificacion.md`.

Subcomandos:

``run``
    Clasifica en seco (`dry_run_classify`, nada se guarda en el proyecto) los documentos de la referencia con cada
    configuración (`--config`, un `.toml` cada una), evalúa contra la referencia, compara cada configuración con la
    primera (`compare_classifications`, bootstrap pareado) y escribe `informe.md` y `run.json` en `--out`.

``blind-sheet``
    Hoja para etiquetar a ciegas una muestra de la referencia (sin lo que asignó doc_organize ni lo que propuso
    nadie), estratificada por el valor de la referencia.

``agreement``
    Acuerdo (kappa de Cohen por eje) entre la hoja a ciegas ya rellenada y la referencia.

La referencia y los informes contienen nombres de documentos reales: `--out` tiene que estar **fuera** del repositorio
(se rechaza si no) y la referencia no se sube nunca.

Uso (desde la raíz del repo, con el `.venv`):

    python scripts/benchmark/run.py run --project-root <raíz del proyecto> --gold <referencia.xlsx> \
        --config scripts/benchmark/configs/reglas_v1.toml --config scripts/benchmark/configs/ablacion_palabra_completa.toml \
        --out <carpeta fuera del repo> [--split all|holdout|calibrate] [--repeat N] [--seed S] \
        [--path-map /mnt/documentation=C:/Desarrollo/documentation]

    python scripts/benchmark/run.py blind-sheet --gold <referencia.xlsx> --size 50 --out <carpeta fuera del repo>
    python scripts/benchmark/run.py agreement --gold <referencia.xlsx> --blind <hoja_a_ciegas.xlsx> --out <carpeta>
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import sys
import time
import tomllib

from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from doc_organize import (
    UNCLASSIFIED_SLUG,
    ContextRegistry,
    GoldStandard,
    LlmClient,
    Project,
    __version__,
    compare_classifications,
    dry_run_classify,
    load_gold_xlsx,
    parse_taxonomy_template,
    settings_from_env,
)
from doc_organize.context import domain_classifier
from doc_organize.context.evaluation import NONE_LABEL, document_keys
from doc_organize.core.models import Context, ConversionResult

REPO_ROOT = Path(__file__).resolve().parents[2]
#: Umbral que ningún valor de reglas alcanza (notas 0-1): con `ai_scope="unclassified"` manda **todos** los documentos a
#: la IA en dominio y tipo, que en esos ejes no está limitada por el umbral (`context_builder._apply_manifest_ai`). Los
#: ejes que etiquetan quedan vacíos en ese modo (sí se filtran por umbral): medir solo dominio y tipo.
AI_ALL_THRESHOLD = 1.01
ABLATIONS = ("whole_word", "no_divide", "head_only", "tie_abstain")
#: Caracteres de título + comienzo que mira la ablación `head_only` (como `TAG_AXIS_TEXT_CHARS` en los ejes que etiquetan).
HEAD_CHARS = 6000
DEFAULT_COLUMNS = {"domains": "dominio_ok", "material_types": "tipo_ok"}


# --- entrada y salida ------------------------------------------------------------------------------------------------


def _safe_out(path: Path) -> Path:
    """La carpeta de salida, creada; aborta si está dentro del repositorio (C2: la referencia es privada)."""
    resolved = path.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        sys.exit(f"--out está dentro del repositorio ({resolved}): los informes llevan nombres de documentos reales. Usa una carpeta fuera.")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sheet_rows(path: Path, sheet: str = "Referencia") -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = workbook[sheet].iter_rows(values_only=True)
        header = [str(cell).strip() if cell is not None else "" for cell in next(rows, ())]
        return [dict(zip(header, row, strict=False)) for row in rows]
    finally:
        workbook.close()


def _key_of(row: Mapping[str, Any], column: str = "documento") -> str:
    return str(row.get(column) or "").strip().lstrip("'")


# --- configuraciones -------------------------------------------------------------------------------------------------


def _load_config(path: Path) -> dict[str, Any]:
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    config.setdefault("name", path.stem)
    ablations = config.get("ablation", [])
    config["ablation"] = [ablations] if isinstance(ablations, str) else list(ablations)
    unknown = [name for name in config["ablation"] if name not in ABLATIONS]
    if unknown:
        sys.exit(f"{path}: ablación desconocida {unknown}; válidas: {ABLATIONS}")
    if "template" not in config:
        sys.exit(f"{path}: falta `template` (ruta de la plantilla o manifiesto de taxonomía)")
    template = Path(config["template"])
    config["template"] = template if template.is_absolute() else (path.parent / template).resolve()
    return config


def _whole_word(keyword: str, haystack: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", haystack) is not None


@contextmanager
def _ablated(ablations: Sequence[str], no_divide_k: float) -> Iterator[None]:
    """Parchea `score_catalog`/`catalog_scores` de `domain_classifier` mientras dura el bloque (solo este proceso)."""
    if not ablations:
        yield
        return
    original_scores, original_best = domain_classifier.catalog_scores, domain_classifier.score_catalog
    fold = domain_classifier.fold_accents
    bonus = domain_classifier._PATH_SIGNAL_BONUS  # noqa: SLF001 - herramienta de medición

    def catalog_scores(
        catalog: list[str], haystack: str, folder_slug: str, extra_keywords: dict[str, list[str]] | None = None
    ) -> list[tuple[str, float]]:
        text = fold(haystack[:HEAD_CHARS] if "head_only" in ablations else haystack)
        folder = fold(folder_slug)
        found: Callable[[str, str], bool] = _whole_word if "whole_word" in ablations else (lambda keyword, hay: keyword in hay)
        scores = []
        for slug in catalog:
            keywords = slug.replace("-", " ").split() + [keyword for keyword in (extra_keywords or {}).get(slug, []) if keyword]
            keywords = [fold(keyword) for keyword in keywords]
            if not keywords:
                continue
            hits = sum(1 for keyword in keywords if found(keyword, text))
            score = min(1.0, hits / no_divide_k) if "no_divide" in ablations else hits / len(keywords)
            if folder and fold(slug) == folder:
                score = min(1.0, score + bonus)
            scores.append((slug, score))
        return scores

    def score_catalog(
        catalog: list[str], haystack: str, folder_slug: str, extra_keywords: dict[str, list[str]] | None = None
    ) -> tuple[str | None, float]:
        ranked = sorted(catalog_scores(catalog, haystack, folder_slug, extra_keywords), key=lambda item: -item[1])
        if not ranked or ranked[0][1] <= 0:
            return None, 0.0
        if "tie_abstain" in ablations and len(ranked) > 1 and ranked[1][1] == ranked[0][1]:
            return None, ranked[0][1]
        best = next(slug for slug, score in catalog_scores(catalog, haystack, folder_slug, extra_keywords) if score == ranked[0][1])
        return best, ranked[0][1]

    domain_classifier.catalog_scores, domain_classifier.score_catalog = catalog_scores, score_catalog  # type: ignore[assignment]
    try:
        yield
    finally:
        domain_classifier.catalog_scores, domain_classifier.score_catalog = original_scores, original_best  # type: ignore[assignment]


# --- partición -------------------------------------------------------------------------------------------------------


def _stratified_split(gold: GoldStandard, axis: str, holdout: float, folds: int, seed: int) -> dict[str, Any]:
    """Tramo bloqueado (~`holdout`, estratificado por el valor de `axis` en la referencia) y `folds` pliegues del resto."""
    rng = random.Random(seed)  # noqa: S311 - partición reproducible, no criptografía
    strata: dict[str, list[str]] = {}
    for label in sorted(gold.labels, key=lambda item: item.document):
        strata.setdefault(", ".join(sorted(label.axes.get(axis, []))) or NONE_LABEL, []).append(label.document)
    locked, rest = [], []
    for stratum in sorted(strata):
        keys = strata[stratum]
        rng.shuffle(keys)
        cut = round(len(keys) * holdout)
        locked += keys[:cut]
        rest += keys[cut:]
    rng.shuffle(rest)
    return {
        "seed": seed,
        "axis": axis,
        "holdout": sorted(locked),
        "calibrate": sorted(rest),
        "folds": {key: index % folds for index, key in enumerate(rest)},
    }


def _partition(gold: GoldStandard, out: Path, axis: str, seed: int) -> dict[str, Any]:
    """La partición guardada en `out/particion.json`, o una nueva si no existe (fija: se reutiliza siempre)."""
    path = out / "particion.json"
    if path.exists():
        saved: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return saved
    split = _stratified_split(gold, axis, holdout=1 / 3, folds=5, seed=seed)
    path.write_text(json.dumps(split, ensure_ascii=False, indent=2), encoding="utf-8")
    return split


def _subset(gold: GoldStandard, keys: set[str]) -> GoldStandard:
    return GoldStandard(labels=[label for label in gold.labels if label.document in keys])


# --- documentos y construcción en seco -------------------------------------------------------------------------------


def _documents(context: Context, path_map: tuple[str, str] | None) -> list[ConversionResult]:
    def local(path: str | None) -> str | None:
        if path and path_map and path.startswith(path_map[0]):
            return path_map[1] + path[len(path_map[0]) :]
        return path

    documents = [
        ConversionResult(
            source_path=document.source_path,
            markdown_path=local(document.markdown_path),
            json_path=local(document.json_path),
            source_sha256=document.source_sha256,
            success=True,
        )
        for domain in context.domains
        for document in domain.documents
    ]
    documents += [
        ConversionResult(
            source_path=detail.source_path,
            markdown_path=local(detail.markdown_path),
            json_path=local(detail.json_path),
            success=bool(detail.json_path),
        )
        for detail in context.unclassified_details
    ]
    return documents


async def _dry_run(
    project: Project, documents: list[ConversionResult], gold: GoldStandard, roots: Sequence[str] | None, config: Mapping[str, Any]
) -> tuple[Context, float]:
    manifest = parse_taxonomy_template(Path(config["template"]).read_text(encoding="utf-8"), source="plantilla")
    ai_all = bool(config.get("ai_all", False))
    options: dict[str, Any] = {
        "taxonomy_manifest": manifest,
        "threshold": AI_ALL_THRESHOLD if ai_all else float(config.get("threshold", 0.5)),
        "decisions": bool(config.get("decisions", False)),  # W5: lo decidido por personas siempre «acierta»
        "semantic": bool(config.get("semantic", False)),
        "ai_scope": "unclassified" if ai_all else config.get("ai_scope", "off"),
    }
    if "semantic_threshold" in config:
        options["semantic_threshold"] = float(config["semantic_threshold"])
    needs_llm = options["ai_scope"] != "off" or options["semantic"]
    start = time.perf_counter()
    with _ablated(config["ablation"], float(config.get("no_divide_k", 2.0))):
        if not needs_llm:
            result = await dry_run_classify(project, documents, gold=gold, roots=roots, **options)
        else:
            environ = dict(os.environ)
            if config.get("classify_model"):
                environ["DOC_ORGANIZE_LITELLM_MODEL_CLASSIFY"] = str(config["classify_model"])
            settings = settings_from_env(environ)
            if settings is None:
                sys.exit(f"{config['name']}: usa IA o semántica y no hay DOC_ORGANIZE_LITELLM_BASE_URL en el entorno")
            async with LlmClient(settings) as llm:
                result = await dry_run_classify(
                    project, documents, gold=gold, roots=roots, llm=llm, ai_cache=bool(config.get("ai_cache", False)), **options
                )
    seconds = time.perf_counter() - start
    if ai_all:
        classified = sum(len(domain.documents) for domain in result.context.domains)
        stats = result.context.ai_stats.classification
        if stats.stopped or stats.sent + stats.cached != classified:
            sys.exit(
                f"{config['name']}: «IA sobre toda la referencia» no llegó a todos ({stats.sent} enviados + {stats.cached} de caché de "
                f"{classified}; parada: {stats.stopped}). No se mide: revisa el proxy, ai_max_documents o el umbral."
            )
    return result.context, seconds


# --- vistas de la referencia (§9.3.1) --------------------------------------------------------------------------------


def _views(gold: GoldStandard, rows: list[dict[str, Any]], reviewed_column: str, reviewed_value: str) -> dict[str, GoldStandard]:
    views = {"toda la referencia": gold}
    reviewed = {_key_of(row) for row in rows if str(row.get(reviewed_column) or "").strip().casefold() == reviewed_value.casefold()}
    if reviewed:
        views["solo filas revisadas por personas"] = _subset(gold, reviewed)
    return views


def _reweighted_accuracy(
    context: Context,
    gold: GoldStandard,
    rows: list[dict[str, Any]],
    population: Counter[str],
    axis: str,
    stratum_column: str,
    roots: Sequence[str] | None,
) -> float | None:
    """Exactitud de `axis` reponderada por estratos: cada documento pesa `N_estrato / n_estrato` (corpus / muestra)."""
    from doc_organize.context.evaluation import _rows, _scored_predictions  # noqa: PLC2701 - herramienta de medición

    stratum_of = {_key_of(row): str(row.get(stratum_column) or "").strip() or UNCLASSIFIED_SLUG for row in rows}
    rows_by_key = _rows(_scored_predictions(context, roots), gold.by_document()).get(axis, {})
    sample = Counter(stratum_of.get(key, UNCLASSIFIED_SLUG) for key in rows_by_key)
    weighted = total = 0.0
    for key, row in rows_by_key.items():
        stratum = stratum_of.get(key, UNCLASSIFIED_SLUG)
        weight = population.get(stratum, 0) / sample[stratum] if sample[stratum] else 0.0
        weighted += weight * row.hit
        total += weight
    return round(weighted / total, 4) if total else None


def _missing_strata(rows: list[dict[str, Any]], population: Counter[str], stratum_column: str) -> list[str]:
    """Estratos de la muestra que no tienen documentos en el contexto guardado: la reponderación solo vale si el contexto
    es el mismo del que se sacó la muestra (en M0, el de la 1.x); si se reconstruyó, sus dominios ya no cuadran."""
    sampled = {str(row.get(stratum_column) or "").strip() or UNCLASSIFIED_SLUG for row in rows if _key_of(row)}
    return sorted(stratum for stratum in sampled if not population.get(stratum))


def _git_commit() -> str | None:
    """El commit del repositorio (los metadatos instalados pueden estar desfasados en una instalación editable)."""
    import subprocess

    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True, timeout=10)  # noqa: S607
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _population(context: Context) -> Counter[str]:
    """Documentos del contexto guardado por dominio asignado (los estratos de `prepare_reference.py` de M0)."""
    counts: Counter[str] = Counter({domain.slug: len(domain.documents) for domain in context.domains})
    counts[UNCLASSIFIED_SLUG] += len(context.unclassified_details)
    return counts


# --- run -------------------------------------------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> None:
    out = _safe_out(args.out)
    configs = [_load_config(path) for path in args.config]
    columns = dict(DEFAULT_COLUMNS)
    for item in args.column:
        axis, _, column = item.partition("=")
        columns[axis] = column
    gold_all = load_gold_xlsx(args.gold, columns=columns)
    rows = _sheet_rows(args.gold)
    split = _partition(gold_all, out, next(iter(columns)), args.seed)
    gold = gold_all if args.split == "all" else _subset(gold_all, set(split[args.split]))
    project = Project(name=args.project_root.name, root_path=str(args.project_root), created_at=datetime.now(UTC).isoformat())
    saved = await ContextRegistry().load_context(project)
    path_map = tuple(args.path_map.split("=", 1)) if args.path_map else None
    documents = _documents(saved, path_map)  # type: ignore[arg-type]
    roots = args.root or None
    keys = document_keys([document.source_path for document in documents], roots)
    labelled = {label.document for label in gold.labels}
    documents = [document for document in documents if keys[document.source_path] in labelled]
    population = _population(saved)

    record: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "doc_organize": __version__,
        "git_commit": _git_commit(),
        "gold_sha256": _sha256(args.gold.read_bytes()),
        "split": args.split,
        "seed": args.seed,
        "documents": len(documents),
        "labelled": len(gold.labels),
        "runs": [],
    }
    contexts: dict[str, list[Context]] = {}
    for config in configs:
        for repetition in range(args.repeat):
            print(f"[benchmark] {config['name']} ({repetition + 1}/{args.repeat}) sobre {len(documents)} documentos…", flush=True)
            context, seconds = await _dry_run(project, documents, gold, roots, config)
            contexts.setdefault(config["name"], []).append(context)
            stats = context.ai_stats
            record["runs"].append(
                {
                    "config": config["name"],
                    "repetition": repetition,
                    "seconds": round(seconds, 1),
                    "settings": {key: str(value) for key, value in config.items()},
                    "template_sha256": _sha256(Path(config["template"]).read_bytes()),
                    "profile_sha256": _profile_sha(args.project_root),
                    "classify_model": context.model_for_task("classify"),
                    "prompts": [item.model_dump() for item in context.ai_provenance],
                    "ai_classification": stats.classification.model_dump(),
                    "semantic_classification": stats.semantic_classification.model_dump(),
                }
            )
    report = _report(configs, contexts, gold, rows, population, columns, roots, args)
    (out / "informe.md").write_text(report, encoding="utf-8")
    (out / "run.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[benchmark] informe: {out / 'informe.md'}")


def _profile_sha(root: Path) -> str | None:
    from doc_organize import PROJECT_PROFILE_FILE

    path = root / PROJECT_PROFILE_FILE
    return _sha256(path.read_bytes()) if path.is_file() else None


def _report(
    configs: list[dict[str, Any]],
    contexts: dict[str, list[Context]],
    gold: GoldStandard,
    rows: list[dict[str, Any]],
    population: Counter[str],
    columns: Mapping[str, str],
    roots: Sequence[str] | None,
    args: argparse.Namespace,
) -> str:
    from doc_organize import evaluate_classification

    lines = [
        "# Benchmark de clasificación",
        "",
        f"doc_organize {__version__} · tramo `{args.split}` · {len(gold.labels)} documentos etiquetados · semilla {args.seed} · "
        f"{args.repeat} repetición(es)",
        "",
        "> Privado: contiene nombres de documentos reales. No subir al repositorio.",
    ]
    views = _views(gold, rows, args.reviewed_column, args.reviewed_value)
    for view, view_gold in views.items():
        lines += ["", f"## {view} ({len(view_gold.labels)})"]
        for config in configs:
            context = contexts[config["name"]][0]
            lines += [
                "",
                f"### {config['name']}",
                "",
                evaluate_classification(context, view_gold, roots=roots).to_markdown(detail=view == "toda la referencia"),
            ]
            if view == "toda la referencia":
                weighted = {axis: _reweighted_accuracy(context, view_gold, rows, population, axis, args.stratum_column, roots) for axis in columns}
                lines += ["", "Exactitud reponderada por estratos: " + " · ".join(f"{axis} {value}" for axis, value in weighted.items())]
                missing = _missing_strata(rows, population, args.stratum_column)
                if missing:
                    lines += [
                        "",
                        f"> **No fiable**: {len(missing)} estrato(s) de la muestra no están en el contexto guardado ({', '.join(missing[:10])}). "
                        "La reponderación solo vale con el contexto del que se sacó la muestra; si se reconstruyó, ignórala.",
                    ]
                lines += _small_support_warning(evaluate_classification(context, view_gold, roots=roots))
    if args.repeat > 1:
        lines += ["", "## Ruido entre repeticiones (exactitud)", "", "| Configuración | Eje | Mínima | Máxima | Rango |", "|---|---|---|---|---|"]
        for config in configs:
            per_axis: dict[str, list[float]] = {}
            for context in contexts[config["name"]]:
                for axis, metrics in evaluate_classification(context, gold, roots=roots).axes.items():
                    if metrics.accuracy is not None:
                        per_axis.setdefault(axis, []).append(metrics.accuracy)
            for axis, values in per_axis.items():
                lines.append(f"| {config['name']} | {axis} | {min(values)} | {max(values)} | {round(max(values) - min(values), 4)} |")
        lines += ["", "Si el rango es comparable a la diferencia entre configuraciones, no se decide (§9.3.7)."]
    baseline = configs[0]["name"]
    for config in configs[1:]:
        comparison = compare_classifications(
            contexts[baseline][0], contexts[config["name"]][0], gold, roots=roots, seed=args.seed, margin=args.margin
        )
        verdict = "pasa la puerta" if comparison.non_inferior and comparison.improved else "no pasa la puerta"
        lines += ["", f"## {config['name']} frente a {baseline} ({verdict})", "", comparison.to_markdown()]
        if comparison.unpaired:
            lines.append(f"\n{len(comparison.unpaired)} documentos sin parear.")
    models = {run.model_for_task("classify") for runs in contexts.values() for run in runs if run.model_for_task("classify")}
    if any(model and "claude" in model.casefold() for model in models):
        lines += ["", "> Aviso (§9.3.9): hay resultados con modelos Claude y la referencia la propuso en su mayoría Claude; léelos aparte."]
    return "\n".join(lines) + "\n"


def _small_support_warning(report: Any) -> list[str]:
    small = [
        f"{axis}/{metrics.value} ({metrics.support})"
        for axis, evaluation in report.axes.items()
        for metrics in evaluation.per_value
        if 0 < metrics.support < 5
    ]
    return ["", "Valores con menos de 5 documentos en la referencia (su F1 es inestable): " + ", ".join(small)] if small else []


# --- blind-sheet y agreement -----------------------------------------------------------------------------------------


def _blind_sheet(args: argparse.Namespace) -> None:
    from openpyxl import Workbook

    out = _safe_out(args.out)
    rows = [row for row in _sheet_rows(args.gold) if _key_of(row)]
    rng = random.Random(args.seed)  # noqa: S311 - muestra reproducible
    strata: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=_key_of):
        strata.setdefault(str(row.get(args.stratify_column) or NONE_LABEL).strip(), []).append(row)
    picked: list[dict[str, Any]] = []
    quota = max(1, round(args.size / max(1, len(strata))))
    for stratum in sorted(strata):  # primero el mismo número por estrato, para que los valores raros salgan
        rng.shuffle(strata[stratum])
        picked += strata[stratum][:quota]
    remaining = [row for stratum in sorted(strata) for row in strata[stratum][quota:]]
    rng.shuffle(remaining)
    picked = (picked + remaining)[: args.size]
    rng.shuffle(picked)  # sin orden por estrato: no dar pistas
    workbook = Workbook()
    sheet = workbook.create_sheet("A ciegas", 0)
    workbook.remove(workbook.worksheets[1])
    sheet.append(["id", "documento", "tipo_fichero", "dominio_ok", "tipo_ok", "notas"])
    for index, row in enumerate(picked, start=1):
        key = _key_of(row)
        sheet.append([index, "'" + key, Path(key).suffix.lstrip(".").lower(), None, None, None])
    path = out / "hoja_a_ciegas.xlsx"
    workbook.save(path)
    print(f"[benchmark] {len(picked)} documentos en {path}. Rellena dominio_ok y tipo_ok abriendo cada documento, sin mirar la referencia.")


def _cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    observed = sum(1 for a, b in pairs if a == b) / len(pairs)
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(left[label] * right[label] for label in set(left) | set(right)) / len(pairs) ** 2
    return round((observed - expected) / (1 - expected), 4) if expected < 1 else 1.0


def _agreement(args: argparse.Namespace) -> None:
    out = _safe_out(args.out)
    reference = load_gold_xlsx(args.gold, columns=DEFAULT_COLUMNS).by_document()
    blind = load_gold_xlsx(args.blind, columns=DEFAULT_COLUMNS, sheet="A ciegas").by_document()
    lines = ["# Acuerdo entre la hoja a ciegas y la referencia", "", "| Eje | Documentos | Acuerdo | Kappa de Cohen |", "|---|---|---|---|"]
    disagreements: list[str] = []
    for axis in DEFAULT_COLUMNS:
        pairs = []
        for key, label in blind.items():
            if axis in label.axes and key in reference and axis in reference[key].axes:
                pair = (", ".join(sorted(label.axes[axis])) or NONE_LABEL, ", ".join(sorted(reference[key].axes[axis])) or NONE_LABEL)
                pairs.append(pair)
                if pair[0] != pair[1]:
                    disagreements.append(f"| {axis} | {key} | {pair[0]} | {pair[1]} |")
        agreement = round(sum(1 for a, b in pairs if a == b) / len(pairs), 4) if pairs else None
        lines.append(f"| {axis} | {len(pairs)} | {agreement} | {_cohen_kappa(pairs)} |")
    lines += ["", "Kappa < 0,6: la referencia no es fiable para decidir; revisar las discrepancias antes de medir nada.", ""]
    if disagreements:
        lines += ["## Discrepancias", "", "| Eje | Documento | A ciegas | Referencia |", "|---|---|---|---|", *sorted(disagreements)]
    (out / "acuerdo.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[benchmark] acuerdo: {out / 'acuerdo.md'}")


# --- CLI -------------------------------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="medir y comparar configuraciones")
    run.add_argument("--project-root", type=Path, required=True, help="raíz del proyecto con el contexto guardado y sus conversiones")
    run.add_argument("--gold", type=Path, required=True, help="referencia .xlsx (hoja «Referencia»)")
    run.add_argument("--config", type=Path, action="append", required=True, help="configuración .toml; la primera es la de partida")
    run.add_argument("--out", type=Path, required=True, help="carpeta de salida, fuera del repositorio")
    run.add_argument(
        "--split", choices=("all", "holdout", "calibrate"), default="calibrate", help="tramo de la referencia (holdout solo en las puertas)"
    )
    run.add_argument("--repeat", type=int, default=1, help="repeticiones de cada configuración (ruido de la IA)")
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--margin", type=float, default=0.03, help="margen de no inferioridad (0,03 = 3 puntos)")
    run.add_argument("--root", action="append", default=[], help="raíz de escaneo para las claves (repetible); por defecto la carpeta común")
    run.add_argument("--path-map", default=None, help="prefijo_contenedor=prefijo_local para leer las conversiones")
    run.add_argument(
        "--column", action="append", default=[], help="eje=columna de la referencia (por defecto domains=dominio_ok, material_types=tipo_ok)"
    )
    run.add_argument("--reviewed-column", default="notas")
    run.add_argument("--reviewed-value", default="Revisado")
    run.add_argument("--stratum-column", default="dominio_doc_organize", help="columna con el estrato de la muestra (para reponderar)")

    blind = commands.add_parser("blind-sheet", help="hoja para etiquetar a ciegas una muestra de la referencia")
    blind.add_argument("--gold", type=Path, required=True)
    blind.add_argument("--size", type=int, default=50)
    blind.add_argument("--seed", type=int, default=0)
    blind.add_argument("--stratify-column", default="dominio_ok")
    blind.add_argument("--out", type=Path, required=True)

    agreement = commands.add_parser("agreement", help="kappa entre la hoja a ciegas rellenada y la referencia")
    agreement.add_argument("--gold", type=Path, required=True)
    agreement.add_argument("--blind", type=Path, required=True)
    agreement.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "run":
        if args.repeat < 1:
            parser.error("--repeat debe ser al menos 1")
        asyncio.run(_run(args))
    elif args.command == "blind-sheet":
        _blind_sheet(args)
    else:
        _agreement(args)


if __name__ == "__main__":
    main()
