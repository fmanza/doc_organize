"""M0: clasificación **solo por reglas** de la versión instalada, en memoria y sin escribir nada, medida contra la
referencia (para no reconstruir el contexto real del proyecto).

Toma los documentos del contexto actual (sus `.json` de conversión), los vuelve a clasificar con el catálogo dado y el
umbral del contexto usando la clasificación por manifiesto de `ContextBuilder` (método interno: es una herramienta de
medición, no API) y compara con `dominio_ok`/`tipo_ok` como `measure_baseline.py`.

Uso:
    python measure_rules_only.py --project-root <raíz> --template <plantilla.md> --reference referencia.xlsx
        --label "1.7.0 reglas" [--path-map /mnt/documentation=C:/Desarrollo/documentation]
"""

from __future__ import annotations

import argparse
import asyncio
import json

from datetime import UTC, datetime
from pathlib import Path

from measure_baseline import _axis, _common_base, _relative
from openpyxl import load_workbook

from doc_organize import ContextBuilder, ContextRegistry, Project, __version__
from doc_organize.context.taxonomy_templates import parse_taxonomy_template
from doc_organize.core.models import ConversionResult


async def _classify(root: Path, template: Path, path_map: tuple[str, str] | None) -> dict[str, dict[str, str | None]]:
    project = Project(name=root.name, root_path=str(root), created_at=datetime.now(UTC).isoformat())
    context = await ContextRegistry().load_context(project)
    manifest = parse_taxonomy_template(template.read_text(encoding="utf-8"), source="plantilla")

    def local(path: str | None) -> str | None:
        if path and path_map and path.startswith(path_map[0]):
            return path_map[1] + path[len(path_map[0]) :]
        return path

    documents = [
        ConversionResult(
            source_path=doc.source_path,
            markdown_path=local(doc.markdown_path),
            json_path=local(doc.json_path),
            success=True,
        )
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
    base = _common_base([d.source_path for d in documents])
    classified, unclassified = await ContextBuilder()._classify_with_manifest(  # noqa: SLF001
        documents, manifest, context.ai_fallback_threshold
    )
    found: dict[str, dict[str, str | None]] = {}
    for slug, docs in classified.items():
        for doc in docs:
            found[_relative(doc.source_path, root, base)] = {
                "domain": None if slug == "sin-clasificar" else slug,
                "material": doc.material_type,
                "by": "rules",
            }
    for doc in unclassified:
        found[_relative(doc.source_path, root, base)] = {"domain": None, "material": None, "by": "unclassified"}
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--path-map", default=None, help="prefijo_contenedor=prefijo_local")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    path_map = tuple(args.path_map.split("=", 1)) if args.path_map else None

    predictions = asyncio.run(_classify(args.project_root, args.template, path_map))  # type: ignore[arg-type]
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
        "domain": _axis(domain_rows),
        "material_type": _axis(material_rows),
    }
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for axis in ("domain", "material_type"):
        data = result[axis]
        print(f"| {args.label} | {axis} | {data['labelled']} | {data['accuracy']} | {data['coverage']} |")
        print("   ", data["top_confusions"][:5])


if __name__ == "__main__":
    main()
