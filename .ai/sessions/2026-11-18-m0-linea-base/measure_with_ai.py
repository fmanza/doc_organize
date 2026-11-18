"""M0: clasificación **reglas + IA (Sub-fase B)** de la versión instalada, en memoria y sin escribir nada en el proyecto,
con tokens y tiempos por documento enviado, medida contra la referencia.

Igual que `measure_rules_only.py` (mismos documentos, catálogo y umbral), y después la Sub-fase B en modo manifiesto de
`ContextBuilder` (métodos internos: es una herramienta de medición, no API) con `TaxonomyClassificationClient` real. Un
transporte `httpx` envuelve al del cliente y anota de cada llamada la duración y el `usage` de la respuesta; el texto
sale redactado (`ai_redact_credentials=True`, como en 1.7.0). La clave se lee de una variable de entorno y nunca se
imprime.

Antes de medir se hace una llamada de calentamiento con texto sintético (el modelo local tarda en cargar), que se anota
aparte.

Uso:
    python measure_with_ai.py --project-root <raíz> --template <plantilla.md> --reference referencia.xlsx \
        --base-url http://localhost:4000 --model <alias> --key-env LiteLLM --label "1.7.1 reglas+IA" \
        [--path-map /mnt/documentation=C:/Desarrollo/documentation] [--json salida.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time

from datetime import UTC, datetime
from pathlib import Path

import httpx

from measure_baseline import _axis, _common_base, _relative
from openpyxl import load_workbook

from doc_organize import ContextBuilder, ContextRegistry, Project, __version__
from doc_organize.ai import TaxonomyClassificationClient
from doc_organize.context.taxonomy_templates import parse_taxonomy_template
from doc_organize.core.models import ConversionResult, LiteLLMTaxonomyClassificationConfig


class _MeteredTransport(httpx.AsyncBaseTransport):
    """Delega en el transporte real y anota duración y `usage` de cada `chat/completions`."""

    def __init__(self) -> None:
        self._inner = httpx.AsyncHTTPTransport()
        self.calls: list[dict[str, float | int | None]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        start = time.perf_counter()
        response = await self._inner.handle_async_request(request)
        await response.aread()
        usage: dict = {}
        try:
            usage = response.json().get("usage") or {}
        except ValueError:
            pass
        self.calls.append(
            {
                "seconds": time.perf_counter() - start,
                "status": response.status_code,
                "prompt": usage.get("prompt_tokens"),
                "completion": usage.get("completion_tokens"),
            }
        )
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


def _documents(context, path_map: tuple[str, str] | None) -> list[ConversionResult]:
    def local(path: str | None) -> str | None:
        if path and path_map and path.startswith(path_map[0]):
            return path_map[1] + path[len(path_map[0]) :]
        return path

    return [
        ConversionResult(source_path=doc.source_path, markdown_path=local(doc.markdown_path), json_path=local(doc.json_path), success=True)
        for domain in context.domains
        for doc in domain.documents
    ] + [
        ConversionResult(
            source_path=doc.source_path,
            markdown_path=local(doc.markdown_path),
            json_path=local(doc.json_path),
            success=bool(doc.json_path),
        )
        for doc in context.unclassified_details
    ]


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"total": 0, "mean": None, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)
    return {
        "total": round(sum(values), 2),
        "mean": round(statistics.fmean(values), 2),
        "p50": round(statistics.median(values), 2),
        "p95": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 2),
        "max": round(ordered[-1], 2),
    }


async def _run(args: argparse.Namespace, key: str) -> tuple[dict[str, dict[str, str | None]], dict]:
    path_map = tuple(args.path_map.split("=", 1)) if args.path_map else None
    root: Path = args.project_root
    project = Project(name=root.name, root_path=str(root), created_at=datetime.now(UTC).isoformat())
    context = await ContextRegistry().load_context(project)
    manifest = parse_taxonomy_template(args.template.read_text(encoding="utf-8"), source="plantilla")
    documents = _documents(context, path_map)  # type: ignore[arg-type]
    base = _common_base([d.source_path for d in documents])
    builder = ContextBuilder()

    start = time.perf_counter()
    classified, unclassified = await builder._classify_with_manifest(documents, manifest, context.ai_fallback_threshold)
    rules_seconds = time.perf_counter() - start

    transport = _MeteredTransport()
    config = LiteLLMTaxonomyClassificationConfig(base_url=args.base_url, virtual_key=key, model=args.model, timeout_s=args.timeout, retries=1)
    async with TaxonomyClassificationClient(config, transport=transport) as client:
        warm_start = time.perf_counter()
        try:
            await client.classify(
                chunks_text="Texto sintético de calentamiento.",
                title="Calentamiento",
                candidate_domains=["uno", "dos"],
                candidate_material_types=["a", "b"],
            )
        except Exception as exc:  # noqa: BLE001 - solo calienta el modelo
            print(f"Calentamiento: {type(exc).__name__}")
        warm_seconds = time.perf_counter() - warm_start
        transport.calls.clear()

        run = builder._new_ai_run(None, None, {})
        done = 0

        async def progress(index: int, total: int, _path: str) -> None:
            nonlocal done
            done = index
            if index % 10 == 0 or index == total:
                print(f"  IA {index}/{total}", flush=True)

        start = time.perf_counter()
        classified = await builder._classify_with_manifest_ai(client, classified, manifest, on_progress=progress, run=run)
        ai_seconds = time.perf_counter() - start

    found: dict[str, dict[str, str | None]] = {}
    for slug, docs in classified.items():
        for doc in docs:
            found[_relative(doc.source_path, root, base)] = {
                "domain": None if slug == "sin-clasificar" else slug,
                "material": doc.material_type,  # como measure_rules_only.py
                "by": doc.classified_by,
            }
    for doc in unclassified:
        found[_relative(doc.source_path, root, base)] = {"domain": None, "material": None, "by": "unclassified"}

    calls = transport.calls
    prompt = [int(c["prompt"]) for c in calls if c["prompt"] is not None]
    completion = [int(c["completion"]) for c in calls if c["completion"] is not None]
    cost = {
        "documents": len(documents),
        "rules_seconds": round(rules_seconds, 2),
        "warmup_seconds": round(warm_seconds, 2),
        "ai_sent": run.sent,
        "ai_assigned": run.classified,
        "ai_failed": run.failed,
        "ai_stopped": run.stopped,
        "http_calls": len(calls),
        "http_errors": sum(1 for c in calls if int(c["status"] or 0) >= 400),
        "ai_seconds": round(ai_seconds, 2),
        "seconds_per_call": _summary([float(c["seconds"] or 0) for c in calls]),
        "prompt_tokens": _summary([float(v) for v in prompt]),
        "completion_tokens": _summary([float(v) for v in completion]),
        "redacted_documents": len(run.credential_ledger or {}),
    }
    return found, cost


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--key-env", default="DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--label", required=True)
    parser.add_argument("--path-map", default=None, help="prefijo_contenedor=prefijo_local")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    key = os.environ.get(args.key_env)
    if not key:
        raise SystemExit(f"Define la variable {args.key_env} con la virtual key (no se imprime).")

    predictions, cost = asyncio.run(_run(args, key))
    sheet = load_workbook(args.reference, read_only=True)["Referencia"]
    header = list(next(sheet.iter_rows(max_row=1, values_only=True)))
    domain_rows, material_rows = [], []
    for values in sheet.iter_rows(min_row=2, values_only=True):
        row = dict(zip(header, values, strict=False))
        pred = predictions.get(str(row["documento"] or "").lstrip("'"))
        if pred is None:
            continue
        if row.get("dominio_ok"):
            domain_rows.append((str(row["dominio_ok"]).strip(), pred["domain"], str(pred["by"])))
        if row.get("tipo_ok"):
            material_rows.append((str(row["tipo_ok"]).strip(), pred["material"], str(pred["by"])))
    result = {
        "label": args.label,
        "doc_organize": __version__,
        "model": args.model,
        "cost": cost,
        "domain": _axis(domain_rows),
        "material_type": _axis(material_rows),
    }
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(cost, ensure_ascii=False, indent=2))
    for axis in ("domain", "material_type"):
        data = result[axis]
        print(f"| {args.label} | {axis} | {data['labelled']} | {data['accuracy']} | {data['coverage']} | {data['accuracy_by_classified_by']} |")
        print("   ", data["top_confusions"][:5])


if __name__ == "__main__":
    main()
