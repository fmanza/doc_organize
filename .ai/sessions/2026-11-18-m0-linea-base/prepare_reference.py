"""M0: prepara la hoja de referencia que se etiqueta a mano (plan único 2.0.0, hito M0, U6).

Lee el contexto ya construido de un proyecto (`context.json`, `domains/`, `unclassified.json`), elige una muestra
estratificada (por dominio y sin clasificar, con semilla fija) y escribe un Excel con:

- hoja **Referencia**: una fila por documento con lo que dijo doc_organize (dominio, tipo de material, quién lo
  clasificó, confianza) y columnas **vacías** para la etiqueta correcta (`dominio_ok`, `tipo_ok`, `marcos_ok`, `notas`),
  con listas desplegables del catálogo;
- hoja **Catálogo**: slugs y nombres de dominios y tipos de material (del manifiesto si se da, si no del contexto).

La persona que etiqueta rellena solo las columnas `*_ok` (y `notas`). Las rutas son relativas a la raíz del proyecto
cuando se puede: el fichero no lleva rutas del servidor. **No** se envía nada a ningún servicio.

Uso:
    python prepare_reference.py --project-root <raíz del proyecto> --out referencia.xlsx [--size 150] [--seed 7]
        [--manifest <taxonomy_manifest.md o plantilla>]
"""

from __future__ import annotations

import argparse
import asyncio
import random

from datetime import UTC, datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.worksheet.datavalidation import DataValidation

from doc_organize import ContextRegistry, Project
from doc_organize.context.taxonomy_templates import parse_taxonomy_template

COLUMNS = (
    "id",
    "documento",
    "titulo",
    "tipo_fichero",
    "dominio_doc_organize",
    "tipo_material_doc_organize",
    "clasificado_por",
    "confianza",
    "dominio_ok",
    "tipo_ok",
    "marcos_ok",
    "notas",
)


def _relative(path: str, root: Path, base: str | None = None) -> str:
    """Ruta para la hoja: relativa a la raíz del proyecto si cuelga de ella; si no, relativa a `base` (el prefijo
    común de los originales, p. ej. `/mnt/documentation/entrada_vd`), nunca la ruta absoluta del servidor."""
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        pass
    posix = path.replace("\\", "/")
    if base and posix.startswith(base.rstrip("/") + "/"):
        return posix[len(base.rstrip("/")) + 1 :]
    return Path(path).name


def _common_base(paths: list[str]) -> str | None:
    posix = [p.replace("\\", "/") for p in paths]
    if len(posix) < 2:
        return None
    prefix = posix[0].rsplit("/", 1)[0]
    for other in posix[1:]:
        while prefix and not other.startswith(prefix + "/"):
            prefix = prefix.rsplit("/", 1)[0] if "/" in prefix else ""
    return prefix or None


def _excel_safe(value: object) -> object:
    text = value if isinstance(value, str) else None
    if text and text[0] in "=+-@":
        return "'" + text
    return value


async def _load(root: Path):  # noqa: ANN202 - Context
    project = Project(name=root.name, root_path=str(root), created_at=datetime.now(UTC).isoformat())
    return await ContextRegistry().load_context(project)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--size", type=int, default=150)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()

    context = asyncio.run(_load(args.project_root))
    rows: list[dict[str, object]] = []
    strata: dict[str, list[dict[str, object]]] = {}
    base = _common_base(
        [doc.source_path for domain in context.domains for doc in domain.documents]
        + [doc.source_path for doc in context.unclassified_details]
    )
    for domain in context.domains:
        for doc in domain.documents:
            strata.setdefault(domain.slug, []).append(
                {
                    "documento": _relative(doc.source_path, args.project_root, base),
                    "titulo": doc.title,
                    "tipo_fichero": doc.document_type,
                    "dominio_doc_organize": domain.slug,
                    "tipo_material_doc_organize": doc.material_type,
                    "clasificado_por": doc.classified_by,
                    "confianza": round(doc.confidence, 3),
                }
            )
    for doc in context.unclassified_details:
        strata.setdefault("(sin clasificar)", []).append(
            {
                "documento": _relative(doc.source_path, args.project_root, base),
                "titulo": doc.title,
                "tipo_fichero": doc.document_type,
                "dominio_doc_organize": None,
                "tipo_material_doc_organize": None,
                "clasificado_por": f"sin clasificar ({doc.reason})",
                "confianza": doc.rules_confidence,
            }
        )

    total = sum(len(items) for items in strata.values())
    rng = random.Random(args.seed)
    for name, items in sorted(strata.items()):
        quota = max(1, round(args.size * len(items) / total)) if total else 0
        rows.extend(rng.sample(items, min(quota, len(items))))
    rng.shuffle(rows)
    rows = rows[: args.size]

    if args.manifest:
        info = parse_taxonomy_template(args.manifest.read_text(encoding="utf-8"), source="manifiesto")
        domains = [(entry.slug, entry.name) for entry in info.domains]
        materials = [(entry.slug, entry.name) for entry in info.material_types]
    else:
        domains = [(domain.slug, domain.name) for domain in context.domains]
        materials = sorted(
            {
                (doc.material_type, doc.material_type_name or doc.material_type)
                for d in context.domains
                for doc in d.documents
                if doc.material_type
            }
        )

    book = Workbook()
    sheet = book.active
    sheet.title = "Referencia"
    sheet.append(COLUMNS)
    for index, row in enumerate(rows, start=1):
        sheet.append(
            [_excel_safe(value) for value in (index, *(row.get(c) for c in COLUMNS[1:8]), None, None, None, None)]
        )
    catalog = book.create_sheet("Catálogo")
    catalog.append(("dominio_slug", "dominio_nombre", "tipo_slug", "tipo_nombre"))
    for i in range(max(len(domains), len(materials))):
        d = domains[i] if i < len(domains) else (None, None)
        m = materials[i] if i < len(materials) else (None, None)
        catalog.append((*d, *m))
    last = len(rows) + 1
    if domains:
        rule = DataValidation(type="list", formula1=f"='Catálogo'!$A$2:$A${len(domains) + 1}", allow_blank=True)
        sheet.add_data_validation(rule)
        rule.add(f"I2:I{last}")
    if materials:
        rule = DataValidation(type="list", formula1=f"='Catálogo'!$C$2:$C${len(materials) + 1}", allow_blank=True)
        sheet.add_data_validation(rule)
        rule.add(f"J2:J{last}")
    book.save(args.out)
    print(f"{len(rows)} documentos de {total} en {len(strata)} estratos -> {args.out}")


if __name__ == "__main__":
    main()
