"""M0: mide la clasificación de un contexto contra la referencia etiquetada a mano (plan único 2.0.0, M0 / G3.1).

Compara el contexto **actual** del proyecto (el de la última construcción: se puede reconstruir con otra
configuración, p. ej. solo reglas o con IA, y volver a medir) con las columnas `dominio_ok` y `tipo_ok` de la hoja de
`prepare_reference.py`. Las filas sin etiqueta se ignoran.

Métricas por eje (dominio, tipo de material):
- exactitud sobre las filas etiquetadas (un documento sin clasificar cuenta como fallo si la etiqueta no es «ninguno»);
- cobertura (filas con algún valor asignado);
- exactitud por `classified_by` (reglas / ia / sin clasificar);
- confusiones más frecuentes (etiqueta → asignado).

Escribe un JSON con todo y un resumen en Markdown para pegar en `BASELINE.md`. Sin red.

Uso:
    python measure_baseline.py --project-root <raíz> --reference referencia.xlsx --label "1.7.0 solo reglas"
        [--json resultado.json]

Convención de etiquetas: `dominio_ok` / `tipo_ok` con el slug correcto, o `ninguno` si ningún valor del catálogo
encaja (entonces «sin clasificar» es lo correcto).
"""

from __future__ import annotations

import argparse
import asyncio
import json

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from openpyxl import load_workbook

from doc_organize import ContextRegistry, Project

NONE_LABEL = "ninguno"


def _relative(path: str, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(path).name


async def _predictions(root: Path) -> dict[str, dict[str, str | None]]:
    project = Project(name=root.name, root_path=str(root), created_at=datetime.now(UTC).isoformat())
    context = await ContextRegistry().load_context(project)
    found: dict[str, dict[str, str | None]] = {}
    for domain in context.domains:
        for doc in domain.documents:
            found[_relative(doc.source_path, root)] = {
                "domain": domain.slug,
                "material": doc.material_type,
                "by": doc.classified_by,
            }
    for doc in context.unclassified_details:
        found[_relative(doc.source_path, root)] = {"domain": None, "material": None, "by": "unclassified"}
    return found


def _axis(rows: list[tuple[str, str | None, str]]) -> dict[str, object]:
    """`rows`: (etiqueta, asignado, quién) de las filas etiquetadas en un eje."""
    hits = [label == (assigned or NONE_LABEL) for label, assigned, _ in rows]
    by_who: dict[str, list[bool]] = {}
    for (label, assigned, who), hit in zip(rows, hits, strict=True):
        by_who.setdefault(who, []).append(hit)
    confusions = Counter(
        (label, assigned or NONE_LABEL) for (label, assigned, _), hit in zip(rows, hits, strict=True) if not hit
    )
    return {
        "labelled": len(rows),
        "accuracy": round(sum(hits) / len(rows), 4) if rows else None,
        "coverage": round(sum(1 for _, assigned, _ in rows if assigned) / len(rows), 4) if rows else None,
        "accuracy_by_classified_by": {who: round(sum(v) / len(v), 4) for who, v in sorted(by_who.items())},
        "top_confusions": [{"label": lab, "assigned": a, "count": c} for (lab, a), c in confusions.most_common(10)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--label", required=True, help="Qué configuración se mide (aparece en el informe)")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    predictions = asyncio.run(_predictions(args.project_root))
    sheet = load_workbook(args.reference, read_only=True)["Referencia"]
    header = [cell for cell in next(sheet.iter_rows(max_row=1, values_only=True))]
    domain_rows: list[tuple[str, str | None, str]] = []
    material_rows: list[tuple[str, str | None, str]] = []
    missing = 0
    for values in sheet.iter_rows(min_row=2, values_only=True):
        row = dict(zip(header, values, strict=False))
        key = str(row["documento"] or "").lstrip("'")
        pred = predictions.get(key)
        if pred is None:
            missing += 1
            continue
        who = str(pred["by"] or "unclassified")
        if row.get("dominio_ok"):
            domain_rows.append((str(row["dominio_ok"]).strip(), pred["domain"], who))
        if row.get("tipo_ok"):
            material_rows.append((str(row["tipo_ok"]).strip(), pred["material"], who))

    result = {
        "label": args.label,
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "reference_rows_not_in_context": missing,
        "domain": _axis(domain_rows),
        "material_type": _axis(material_rows),
    }
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"| {args.label} | eje | etiquetadas | exactitud | cobertura | por quién |")
    print("|---|---|---|---|---|---|")
    for axis in ("domain", "material_type"):
        data = result[axis]
        print(
            f"| {args.label} | {axis} | {data['labelled']} | {data['accuracy']} | {data['coverage']} | "
            f"{data['accuracy_by_classified_by']} |"
        )
    if missing:
        print(
            f"\nAviso: {missing} filas de la referencia no están en el contexto actual (¿otro corpus o reconstruido?)."
        )


if __name__ == "__main__":
    main()
