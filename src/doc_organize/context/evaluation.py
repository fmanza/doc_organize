"""
Evaluación de la clasificación contra una referencia etiquetada a mano (2.0.0, G3).

La referencia (`GoldStandard`) dice, para algunos documentos, qué valores son los correctos en cada eje; `NONE_LABEL`
(«ninguno») significa que ningún valor del catálogo encaja y que dejar el eje vacío es lo correcto. La evaluación compara
un `Context` con ella eje a eje: exactitud, cobertura, precisión y *recall*, exactitud según quién clasificó
(`rules`, `ai`, `human`... o `unclassified` si el eje quedó vacío) y las confusiones más frecuentes. Sirve para medir un
cambio de reglas, prompt, perfil o modelo antes de adoptarlo.

Los documentos se identifican por su **clave** (`document_key`): la ruta del original relativa a la raíz de escaneo de
la que cuelga, en POSIX. Así una referencia hecha con la web (rutas del contenedor, `/mnt/...`) vale en el equipo y al
revés.
"""

from __future__ import annotations

import re

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field

from doc_organize.core.exceptions import MissingDependencyError
from doc_organize.core.models import Context
from doc_organize.projects.layout import relative_source_path

#: Etiqueta de «ningún valor del catálogo encaja»: el eje vacío es lo correcto.
NONE_LABEL = "ninguno"
#: Quién clasificó un eje que quedó vacío.
UNCLASSIFIED = "unclassified"
#: Columnas de la hoja de referencia por eje, como las escribe la línea base (M0).
DEFAULT_GOLD_COLUMNS: Mapping[str, str] = {"domains": "dominio_ok", "material_types": "tipo_ok"}
_SEPARATORS = re.compile(r"[,;]")
_MAX_CONFUSIONS = 10


class GoldLabel(BaseModel):
    """Los valores correctos de un documento en los ejes etiquetados (lista vacía = «ninguno»)."""

    document: str = Field(..., description="Clave del documento (`document_key`)")
    axes: dict[str, list[str]] = Field(default_factory=dict, description="Valores correctos por eje; solo los ejes etiquetados")


class GoldStandard(BaseModel):
    """Referencia etiquetada a mano: un `GoldLabel` por documento.

    Example:
        >>> gold = GoldStandard(labels=[GoldLabel(document="a/x.pdf", axes={"domains": ["calidad"]})])
        >>> gold.by_document()["a/x.pdf"].axes["domains"] == ["calidad"]
        True
    """

    labels: list[GoldLabel] = Field(default_factory=list)

    def by_document(self) -> dict[str, GoldLabel]:
        """Las etiquetas por clave de documento (si una clave se repite, gana la última)."""
        return {label.document: label for label in self.labels}


class LabelConfusion(BaseModel):
    """Un error frecuente: lo que decía la referencia y lo que se asignó (`NONE_LABEL` si nada)."""

    label: str
    assigned: str
    count: int


class AxisEvaluation(BaseModel):
    """Métricas de un eje sobre los documentos etiquetados que están en el contexto.

    Attributes:
        axis (str): Clave del eje.
        multiple (bool): Si el eje admite varios valores.
        labelled (int): Documentos etiquetados en el eje y presentes en el contexto.
        accuracy (float | None): Fracción con exactamente los valores de la referencia (`None` sin etiquetados).
        coverage (float | None): Fracción con algún valor asignado.
        precision (float | None): Valores asignados que son correctos, sobre todos los asignados (`None` si no hay).
        recall (float | None): Valores correctos que se asignaron, sobre todos los de la referencia (`None` si no hay).
        accuracy_by_classified_by (dict[str, float]): Exactitud según quién clasificó el eje.
        labelled_by_classified_by (dict[str, int]): Documentos etiquetados según quién clasificó el eje.
        confusions (list[LabelConfusion]): Los errores más frecuentes, de más a menos.
    """

    axis: str
    multiple: bool = False
    labelled: int = 0
    accuracy: float | None = None
    coverage: float | None = None
    precision: float | None = None
    recall: float | None = None
    accuracy_by_classified_by: dict[str, float] = Field(default_factory=dict)
    labelled_by_classified_by: dict[str, int] = Field(default_factory=dict)
    confusions: list[LabelConfusion] = Field(default_factory=list)


class EvaluationReport(BaseModel):
    """Resultado de `evaluate_classification`.

    Attributes:
        axes (dict[str, AxisEvaluation]): Métricas por eje etiquetado.
        documents (int): Documentos del contexto.
        matched (int): Documentos de la referencia que están en el contexto.
        missing_documents (list[str]): Claves de la referencia que no están en el contexto (¿otro corpus?).
    """

    axes: dict[str, AxisEvaluation] = Field(default_factory=dict)
    documents: int = 0
    matched: int = 0
    missing_documents: list[str] = Field(default_factory=list)

    def to_markdown(self) -> str:
        """Una tabla con las métricas de cada eje (para pegar en un informe).

        Example:
            >>> print(EvaluationReport(axes={"domains": AxisEvaluation(axis="domains", labelled=2, accuracy=0.5, coverage=1.0)}).to_markdown())
            | Eje | Etiquetados | Exactitud | Cobertura | Precisión | Recall |
            |---|---|---|---|---|---|
            | domains | 2 | 0.5 | 1.0 | — | — |
        """
        lines = ["| Eje | Etiquetados | Exactitud | Cobertura | Precisión | Recall |", "|---|---|---|---|---|---|"]
        for axis in self.axes.values():
            metrics = (axis.accuracy, axis.coverage, axis.precision, axis.recall)
            lines.append(f"| {axis.axis} | {axis.labelled} | " + " | ".join("—" if value is None else str(value) for value in metrics) + " |")
        return "\n".join(lines)


def document_key(source_path: str, roots: Sequence[str]) -> str:
    """La clave de un documento: su ruta relativa a la raíz de `roots` de la que cuelga, en POSIX (solo el nombre del
    fichero si no cuelga de ninguna).

    Example:
        >>> document_key("/mnt/documentation/entrada/ENS/plan.pdf", ["/mnt/documentation/entrada"])
        'ENS/plan.pdf'
    """
    return relative_source_path(source_path, roots)


def common_root(paths: Iterable[str]) -> str | None:
    """La carpeta común más profunda de `paths` (la raíz de escaneo cuando no se conoce), o `None` si no hay al menos dos
    rutas o no comparten carpeta.

    Example:
        >>> common_root(["/mnt/e/ENS/a.pdf", "/mnt/e/ISO/b.pdf"])
        '/mnt/e'
    """
    posix = [path.replace("\\", "/") for path in paths]
    if len(posix) < 2:
        return None
    prefix = posix[0].rsplit("/", 1)[0]
    for other in posix[1:]:
        while prefix and not other.startswith(prefix + "/"):
            prefix = prefix.rsplit("/", 1)[0] if "/" in prefix else ""
    return prefix or None


def load_gold_xlsx(
    path: str | Path,
    *,
    columns: Mapping[str, str] | None = None,
    sheet: str = "Referencia",
    document_column: str = "documento",
) -> GoldStandard:
    """Lee una referencia de un Excel: una fila por documento, la clave en `document_column` y, por eje, una columna
    con el valor correcto (varios separados por `,` o `;`; `ninguno` si ninguno encaja; vacía = sin etiquetar).

    Args:
        path: El `.xlsx` (p. ej. el de la línea base, con `dominio_ok` y `tipo_ok`).
        columns: Eje → columna (por defecto `DEFAULT_GOLD_COLUMNS`). Una columna que no está en la hoja se ignora.
        sheet: Hoja con las filas.
        document_column: Columna con la clave del documento (un `'` inicial, de neutralizar fórmulas, se quita).

    Raises:
        MissingDependencyError: Falta `openpyxl` (extra `export`).
        ValueError: La hoja o la columna del documento no existen.
    """
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise MissingDependencyError("openpyxl", "export") from exc
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet not in workbook.sheetnames:
            raise ValueError(f"La referencia no tiene la hoja '{sheet}'")
        rows = workbook[sheet].iter_rows(values_only=True)
        header = [str(cell).strip() if cell is not None else "" for cell in next(rows, ())]
        if document_column not in header:
            raise ValueError(f"La hoja '{sheet}' no tiene la columna '{document_column}'")
        wanted = {axis: header.index(column) for axis, column in (columns or DEFAULT_GOLD_COLUMNS).items() if column in header}
        key_index = header.index(document_column)
        labels = []
        for row in rows:
            key = str(row[key_index] or "").strip().lstrip("'") if key_index < len(row) else ""
            axes = {axis: values for axis, index in wanted.items() if index < len(row) and (values := _gold_values(row[index])) is not None}
            if key and axes:
                labels.append(GoldLabel(document=key, axes=axes))
    finally:
        workbook.close()
    return GoldStandard(labels=labels)


def evaluate_classification(context: Context, gold: GoldStandard, *, roots: Sequence[str] | None = None) -> EvaluationReport:
    """Compara la clasificación de `context` con la referencia `gold`, eje a eje.

    Args:
        context: El contexto a evaluar (de `ContextRegistry.load_context` o recién construido).
        gold: La referencia (`load_gold_xlsx` o construida a mano).
        roots: Raíces de escaneo para calcular las claves de los documentos; por defecto, la carpeta común de todos
            los originales del contexto (como la línea base).

    Example:
        >>> context = Context(project_name="p", created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00")
        >>> report = evaluate_classification(context, GoldStandard(labels=[GoldLabel(document="a.pdf", axes={"domains": []})]))
        >>> report.matched, report.missing_documents
        (0, ['a.pdf'])
    """
    predictions = _predictions(context, roots)
    multiple = {axis.key: axis.multiple for axis in context.taxonomy_axes}
    labels = gold.by_document()
    rows: dict[str, list[tuple[list[str], list[str], str]]] = {}
    for key, label in labels.items():
        assigned = predictions.get(key)
        if assigned is None:
            continue
        for axis, correct in label.axes.items():
            values, who = assigned.get(axis, ([], UNCLASSIFIED))
            rows.setdefault(axis, []).append((correct, values, who))
    return EvaluationReport(
        axes={axis: _axis_metrics(axis, multiple.get(axis, False), axis_rows) for axis, axis_rows in rows.items()},
        documents=len(predictions),
        matched=sum(1 for key in labels if key in predictions),
        missing_documents=sorted(key for key in labels if key not in predictions),
    )


def _gold_values(cell: object) -> list[str] | None:
    """Los valores de una celda de la referencia: `None` si está vacía, `[]` si dice «ninguno»."""
    text = str(cell).strip().lstrip("'") if cell is not None else ""
    if not text:
        return None
    values = [value.strip() for value in _SEPARATORS.split(text) if value.strip()]
    return [] if values == [NONE_LABEL] else [value for value in values if value != NONE_LABEL]


def _predictions(context: Context, roots: Sequence[str] | None) -> dict[str, dict[str, tuple[list[str], str]]]:
    """Por clave de documento y eje: los valores asignados y quién los asignó."""
    documents = [document for domain in context.domains for document in domain.documents]
    unclassified = context.unclassified_details
    if roots is None:
        root = common_root([document.source_path for document in documents] + [document.source_path for document in unclassified])
        roots = [root] if root else []
    found: dict[str, dict[str, tuple[list[str], str]]] = {}
    for document in documents:
        found[_key(document.source_path, roots)] = {
            axis: ([value.slug for value in values], values[0].classified_by if values else UNCLASSIFIED)
            for axis, values in document.classification.axes.items()
        }
    for detail in unclassified:
        found[_key(detail.source_path, roots)] = {}
    return found


def _key(source_path: str, roots: Sequence[str]) -> str:
    # `relative_source_path` compara rutas del sistema; las del contenedor (`/mnt/...`) se comparan como texto POSIX.
    posix = source_path.replace("\\", "/")
    for root in roots:
        base = root.replace("\\", "/").rstrip("/")
        if posix.startswith(base + "/"):
            return posix[len(base) + 1 :]
    return document_key(source_path, roots) if roots else PurePosixPath(posix).name


def _axis_metrics(axis: str, multiple: bool, rows: list[tuple[list[str], list[str], str]]) -> AxisEvaluation:
    hits = [set(correct) == set(assigned) for correct, assigned, _ in rows]
    by_who: dict[str, list[bool]] = {}
    for (_, _, who), hit in zip(rows, hits, strict=True):
        by_who.setdefault(who, []).append(hit)
    true_positives = sum(len(set(correct) & set(assigned)) for correct, assigned, _ in rows)
    assigned_total = sum(len(set(assigned)) for _, assigned, _ in rows)
    correct_total = sum(len(set(correct)) for correct, _, _ in rows)
    confusions = Counter((_joined(correct), _joined(assigned)) for (correct, assigned, _), hit in zip(rows, hits, strict=True) if not hit)
    return AxisEvaluation(
        axis=axis,
        multiple=multiple,
        labelled=len(rows),
        accuracy=_ratio(sum(hits), len(rows)),
        coverage=_ratio(sum(1 for _, assigned, _ in rows if assigned), len(rows)),
        precision=_ratio(true_positives, assigned_total),
        recall=_ratio(true_positives, correct_total),
        accuracy_by_classified_by={who: _ratio(sum(values), len(values)) or 0.0 for who, values in sorted(by_who.items())},
        labelled_by_classified_by={who: len(values) for who, values in sorted(by_who.items())},
        confusions=[
            LabelConfusion(label=label, assigned=assigned, count=count) for (label, assigned), count in confusions.most_common(_MAX_CONFUSIONS)
        ],
    )


def _joined(values: list[str]) -> str:
    return ", ".join(sorted(set(values))) or NONE_LABEL


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


__all__ = [
    "DEFAULT_GOLD_COLUMNS",
    "NONE_LABEL",
    "UNCLASSIFIED",
    "AxisEvaluation",
    "EvaluationReport",
    "GoldLabel",
    "GoldStandard",
    "LabelConfusion",
    "common_root",
    "document_key",
    "evaluate_classification",
    "load_gold_xlsx",
]
