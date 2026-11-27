"""
Evaluación de la clasificación contra una referencia etiquetada a mano (2.0.0, G3).

La referencia (`GoldStandard`) dice, para algunos documentos, qué valores son los correctos en cada eje; `NONE_LABEL`
(«ninguno») significa que ningún valor del catálogo encaja y que dejar el eje vacío es lo correcto. La evaluación compara
un `Context` con ella eje a eje: exactitud, cobertura, precisión y *recall*, exactitud según quién clasificó
(`rules`, `ai`, `human`... o `unclassified` si el eje quedó vacío) y las confusiones más frecuentes. Sirve para medir un
cambio de reglas, prompt, perfil o modelo antes de adoptarlo.

Desde 2.6.0 (F0 de `.ai/sessions/2026-11-27-precision-contexto/PLAN.md`) da también métricas por valor (F1 y F1 macro),
exactitud sobre lo asignado, matriz de confusión completa y exactitud por tramo de confianza y fase; y
`compare_classifications` compara dos clasificaciones de los mismos documentos con un intervalo de confianza pareado,
para decidir si un cambio mejora de verdad o es ruido.

Los documentos se identifican por su **clave** (`document_key`): la ruta del original relativa a la raíz de escaneo de
la que cuelga, en POSIX. Así una referencia hecha con la web (rutas del contenedor, `/mnt/...`) vale en el equipo y al
revés.
"""

from __future__ import annotations

import math
import random
import re

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
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
#: Límites de los tramos de confianza de `AxisEvaluation.accuracy_by_confidence` (el último incluye el 1,0).
CONFIDENCE_BIN_EDGES: tuple[float, ...] = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
#: Por encima de estos pares discordantes, McNemar usa la aproximación normal en vez de la binomial exacta.
_MCNEMAR_EXACT_LIMIT = 1000


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


class ValueMetrics(BaseModel):
    """Precisión, *recall* y F1 de un valor de un eje (2.6.0).

    Attributes:
        value (str): Slug del valor.
        support (int): Documentos que lo tienen en la referencia.
        assigned (int): Documentos a los que se asignó.
        correct (int): Documentos que lo tienen en la referencia y se les asignó.
        precision (float | None): `correct / assigned` (`None` si nunca se asignó).
        recall (float | None): `correct / support` (`None` si no está en la referencia).
        f1 (float): `2·correct / (support + assigned)`; 0 si nunca acierta.
    """

    value: str
    support: int = 0
    assigned: int = 0
    correct: int = 0
    precision: float | None = None
    recall: float | None = None
    f1: float = 0.0


class ConfidenceBin(BaseModel):
    """Exactitud de los valores asignados por una fase con la confianza en un tramo (2.6.0).

    La confianza de las reglas, la semántica y la IA no significa lo mismo, así que cada tramo es de una sola fase.

    Attributes:
        classified_by (str): Quién asignó el valor (`rules`, `semantic`, `ai`, `human`).
        lower (float): Límite inferior (incluido).
        upper (float): Límite superior (excluido salvo en el último tramo, que incluye el 1,0).
        labelled (int): Documentos etiquetados en el tramo.
        accuracy (float | None): Fracción con exactamente los valores de la referencia.
    """

    classified_by: str
    lower: float
    upper: float
    labelled: int = 0
    accuracy: float | None = None


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
        selective_accuracy (float | None): Exactitud solo sobre los documentos con algún valor asignado: una abstención
            (eje vacío) no cuenta como error. Con `coverage` da el punto riesgo-cobertura (2.6.0).
        macro_f1 (float | None): Media de `ValueMetrics.f1` de los valores que están en la referencia (`support > 0`);
            los que solo se asignaron salen en `per_value` pero no entran en la media (2.6.0).
        per_value (list[ValueMetrics]): Métricas de cada valor de la referencia o asignado, ordenadas por valor (2.6.0).
        confusion_matrix (dict[str, dict[str, int]]): Referencia → asignado → documentos, incluidos los aciertos; varios
            valores se juntan como en `confusions` y `NONE_LABEL` es el eje vacío (2.6.0).
        accuracy_by_confidence (list[ConfidenceBin]): Exactitud por fase y tramo de confianza del primer valor asignado
            (`CONFIDENCE_BIN_EDGES`); solo tramos con documentos (2.6.0).
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
    selective_accuracy: float | None = None
    macro_f1: float | None = None
    per_value: list[ValueMetrics] = Field(default_factory=list)
    confusion_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)
    accuracy_by_confidence: list[ConfidenceBin] = Field(default_factory=list)


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

    def to_markdown(self, *, detail: bool = False) -> str:
        """Una tabla con las métricas de cada eje (para pegar en un informe).

        Args:
            detail: Añadir, por eje, la exactitud sobre lo asignado, el F1 macro y una tabla por valor (2.6.0).

        Example:
            >>> print(EvaluationReport(axes={"domains": AxisEvaluation(axis="domains", labelled=2, accuracy=0.5, coverage=1.0)}).to_markdown())
            | Eje | Etiquetados | Exactitud | Cobertura | Precisión | Recall |
            |---|---|---|---|---|---|
            | domains | 2 | 0.5 | 1.0 | — | — |
        """
        lines = ["| Eje | Etiquetados | Exactitud | Cobertura | Precisión | Recall |", "|---|---|---|---|---|---|"]
        for axis in self.axes.values():
            metrics = (axis.accuracy, axis.coverage, axis.precision, axis.recall)
            lines.append(f"| {axis.axis} | {axis.labelled} | " + " | ".join(_cell(value) for value in metrics) + " |")
        if detail:
            for axis in self.axes.values():
                lines += [
                    "",
                    f"**{axis.axis}**: exactitud sobre lo asignado {_cell(axis.selective_accuracy)} · F1 macro {_cell(axis.macro_f1)}",
                    "",
                    "| Valor | Referencia | Asignados | Aciertos | Precisión | Recall | F1 |",
                    "|---|---|---|---|---|---|---|",
                ]
                lines += [
                    f"| {m.value} | {m.support} | {m.assigned} | {m.correct} | {_cell(m.precision)} | {_cell(m.recall)} | {m.f1} |"
                    for m in axis.per_value
                ]
        return "\n".join(lines)


class MetricComparison(BaseModel):
    """Una métrica en dos clasificaciones de los mismos documentos, con el intervalo de confianza de su diferencia (2.6.0).

    Attributes:
        baseline (float | None): Valor en la clasificación de partida.
        candidate (float | None): Valor en la candidata.
        difference (float | None): `candidate - baseline`.
        ci_low (float | None): Límite inferior del intervalo de la diferencia (bootstrap pareado por percentiles).
        ci_high (float | None): Límite superior.
    """

    baseline: float | None = None
    candidate: float | None = None
    difference: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None


class AxisComparison(BaseModel):
    """Comparación pareada de un eje entre dos clasificaciones (2.6.0).

    Attributes:
        axis (str): Clave del eje.
        paired (int): Documentos etiquetados en el eje presentes en las dos clasificaciones.
        accuracy (MetricComparison): Exactitud (valores exactamente iguales a la referencia).
        selective_accuracy (MetricComparison): Exactitud solo sobre lo asignado (cada clasificación sobre lo suyo).
        coverage (MetricComparison): Fracción con algún valor asignado.
        discordant_baseline_only (int): Documentos que solo acierta la de partida (McNemar).
        discordant_candidate_only (int): Documentos que solo acierta la candidata (McNemar).
        p_value_mcnemar (float): Prueba de McNemar bilateral sobre la exactitud (binomial exacta hasta 1000 pares
            discordantes; aproximación normal con corrección de continuidad por encima). 1,0 sin discordantes.
        non_inferior (bool): El límite inferior del intervalo de la diferencia de exactitud no baja de `-margin`.
        improved (bool): El intervalo de la diferencia de exactitud excluye el 0 por arriba.
    """

    axis: str
    paired: int = 0
    accuracy: MetricComparison = Field(default_factory=MetricComparison)
    selective_accuracy: MetricComparison = Field(default_factory=MetricComparison)
    coverage: MetricComparison = Field(default_factory=MetricComparison)
    discordant_baseline_only: int = 0
    discordant_candidate_only: int = 0
    p_value_mcnemar: float = 1.0
    non_inferior: bool = False
    improved: bool = False


class ClassificationComparison(BaseModel):
    """Resultado de `compare_classifications` (2.6.0).

    La puerta de una fase (`.ai/sessions/2026-11-27-precision-contexto/ANALISIS_MEJORAS.md` §9.3) es
    `non_inferior and improved`: no empeora ningún eje más allá de `margin` y mejora alguno.

    Attributes:
        axes (dict[str, AxisComparison]): Por eje etiquetado, ordenados por clave.
        unpaired (list[str]): Claves de la referencia que faltan en alguna de las dos clasificaciones.
        resamples (int): Remuestreos del bootstrap.
        seed (int): Semilla del bootstrap (mismo resultado con la misma semilla).
        margin (float): Margen de no inferioridad (fracción: 0,03 = 3 puntos).
        confidence_level (float): Nivel del intervalo (0,95).
        non_inferior (bool): Todos los ejes (con documentos pareados) son no inferiores.
        improved (bool): Algún eje mejora.
    """

    axes: dict[str, AxisComparison] = Field(default_factory=dict)
    unpaired: list[str] = Field(default_factory=list)
    resamples: int = 0
    seed: int = 0
    margin: float = 0.0
    confidence_level: float = 0.95
    non_inferior: bool = False
    improved: bool = False

    def to_markdown(self) -> str:
        """Una tabla con la diferencia de exactitud de cada eje y su intervalo (para pegar en un informe).

        Example:
            >>> comparison = ClassificationComparison(axes={"domains": AxisComparison(axis="domains", paired=3)}, margin=0.03)
            >>> print(comparison.to_markdown().splitlines()[2])
            | domains | 3 | — | — | — | — | 1.0 | no | no |
        """
        level = round(self.confidence_level * 100)
        lines = [
            f"| Eje | Pareados | Partida | Candidata | Diferencia | IC {level} % | McNemar p | No inferior (−{self.margin}) | Mejora |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for axis in self.axes.values():
            accuracy = axis.accuracy
            interval = "—" if accuracy.ci_low is None else f"[{accuracy.ci_low}, {accuracy.ci_high}]"
            lines.append(
                f"| {axis.axis} | {axis.paired} | {_cell(accuracy.baseline)} | {_cell(accuracy.candidate)} | {_cell(accuracy.difference)} | "
                f"{interval} | {axis.p_value_mcnemar} | {_yes(axis.non_inferior)} | {_yes(axis.improved)} |"
            )
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
    predictions = _scored_predictions(context, roots)
    multiple = {axis.key: axis.multiple for axis in context.taxonomy_axes}
    labels = gold.by_document()
    rows = _rows(predictions, labels)
    return EvaluationReport(
        axes={axis: _axis_metrics(axis, multiple.get(axis, False), list(axis_rows.values())) for axis, axis_rows in rows.items()},
        documents=len(predictions),
        matched=sum(1 for key in labels if key in predictions),
        missing_documents=sorted(key for key in labels if key not in predictions),
    )


def compare_classifications(
    baseline: Context,
    candidate: Context,
    gold: GoldStandard,
    *,
    roots: Sequence[str] | None = None,
    resamples: int = 1000,
    seed: int = 0,
    margin: float = 0.03,
    confidence_level: float = 0.95,
) -> ClassificationComparison:
    """Compara dos clasificaciones de los mismos documentos contra `gold`, documento a documento (2.6.0).

    Con 150 documentos y una exactitud del 25 %, el intervalo de una sola exactitud es de ±7 puntos: dos evaluaciones
    sueltas no dicen si un cambio mejora. Esta función empareja cada documento etiquetado en las dos clasificaciones y
    remuestrea documentos (bootstrap) para dar el intervalo de la **diferencia**, más la prueba de McNemar.

    Args:
        baseline: La clasificación de partida (p. ej. `DryRunResult.context` con la configuración actual).
        candidate: La clasificación candidata (con el cambio que se quiere medir).
        gold: La referencia.
        roots: Raíces de escaneo para las claves, las mismas para las dos (por defecto, la carpeta común de los
            originales de cada contexto: pásalas si los dos no tienen exactamente los mismos documentos).
        resamples: Remuestreos del bootstrap (≥ 1).
        seed: Semilla: misma entrada y semilla, mismo resultado.
        margin: Margen de no inferioridad, en fracción (0,03 = 3 puntos; ≥ 0).
        confidence_level: Nivel del intervalo (entre 0 y 1).

    Raises:
        ValueError: `resamples`, `margin` o `confidence_level` fuera de rango.

    Example:
        >>> context = Context(project_name="p", created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00")
        >>> comparison = compare_classifications(context, context, GoldStandard(labels=[GoldLabel(document="a.pdf", axes={"domains": []})]))
        >>> comparison.unpaired, comparison.axes
        (['a.pdf'], {})
    """
    if resamples < 1:
        raise ValueError(f"resamples debe ser al menos 1, no {resamples}")
    if margin < 0:
        raise ValueError(f"margin no puede ser negativo: {margin}")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError(f"confidence_level debe estar entre 0 y 1, no {confidence_level}")
    labels = gold.by_document()
    before, after = _scored_predictions(baseline, roots), _scored_predictions(candidate, roots)
    rows_before, rows_after = _rows(before, labels), _rows(after, labels)
    axes: dict[str, AxisComparison] = {}
    for axis in sorted(set(rows_before) & set(rows_after)):
        keys = sorted(set(rows_before[axis]) & set(rows_after[axis]))
        if keys:
            pairs = [(rows_before[axis][key], rows_after[axis][key]) for key in keys]
            rng = random.Random(f"{seed}:{axis}")  # noqa: S311 - remuestreo del bootstrap, no criptografía
            axes[axis] = _axis_comparison(axis, pairs, rng, resamples, margin, confidence_level)
    return ClassificationComparison(
        axes=axes,
        unpaired=sorted(key for key in labels if key not in before or key not in after),
        resamples=resamples,
        seed=seed,
        margin=margin,
        confidence_level=confidence_level,
        non_inferior=bool(axes) and all(axis.non_inferior for axis in axes.values()),
        improved=any(axis.improved for axis in axes.values()),
    )


def _gold_values(cell: object) -> list[str] | None:
    """Los valores de una celda de la referencia: `None` si está vacía, `[]` si dice «ninguno»."""
    text = str(cell).strip().lstrip("'") if cell is not None else ""
    if not text:
        return None
    values = [value.strip() for value in _SEPARATORS.split(text) if value.strip()]
    return [] if values == [NONE_LABEL] else [value for value in values if value != NONE_LABEL]


def document_keys(source_paths: Iterable[str], roots: Sequence[str] | None = None) -> dict[str, str]:
    """La clave de cada original (`source_path` → clave): su ruta relativa a la raíz de escaneo que la contiene.

    Es la clave de las decisiones (`ClassificationDecision.document_key`), de la cola de revisión, de la referencia de
    la evaluación y de `dry_run_classify`. Pasa como `roots` las mismas raíces que a `ContextBuilder.build(scan_roots=)`
    (las carpetas que se escanearon): así la clave no cambia aunque cambie el corpus. Sin `roots` se usa la carpeta común
    de todos los originales, que sí puede cambiar al añadir o quitar documentos.

    Example:
        >>> document_keys(["/mnt/e/ENS/a.pdf", "/mnt/e/ISO/b.pdf"])
        {'/mnt/e/ENS/a.pdf': 'ENS/a.pdf', '/mnt/e/ISO/b.pdf': 'ISO/b.pdf'}
        >>> document_keys(["/mnt/e/ENS/a.pdf"], roots=["/mnt/e"])  # con la raíz: estable
        {'/mnt/e/ENS/a.pdf': 'ENS/a.pdf'}
    """
    paths = list(source_paths)
    if roots is None:
        root = common_root(paths)
        roots = [root] if root else []
    return {path: _key(path, roots) for path in paths}


def _predictions(context: Context, roots: Sequence[str] | None) -> dict[str, dict[str, tuple[list[str], str]]]:
    """Por clave de documento y eje: los valores asignados y quién los asignó."""
    return {key: {axis: (values, who) for axis, (values, who, _) in axes.items()} for key, axes in _scored_predictions(context, roots).items()}


def _scored_predictions(context: Context, roots: Sequence[str] | None) -> dict[str, dict[str, tuple[list[str], str, float | None]]]:
    """Como `_predictions`, con la confianza del primer valor (`None` si el eje quedó vacío)."""
    documents = [document for domain in context.domains for document in domain.documents]
    unclassified = context.unclassified_details
    keys = document_keys([document.source_path for document in documents] + [detail.source_path for detail in unclassified], roots)
    found: dict[str, dict[str, tuple[list[str], str, float | None]]] = {}
    for document in documents:
        found[keys[document.source_path]] = {
            axis: ([value.slug for value in values], values[0].classified_by, values[0].confidence) if values else ([], UNCLASSIFIED, None)
            for axis, values in document.classification.axes.items()
        }
    for detail in unclassified:
        found[keys[detail.source_path]] = {}
    return found


@dataclass(frozen=True)
class _Row:
    """Un documento etiquetado en un eje: lo correcto, lo asignado, quién y con qué confianza."""

    correct: tuple[str, ...]
    assigned: tuple[str, ...]
    who: str
    confidence: float | None

    @property
    def hit(self) -> bool:
        return set(self.correct) == set(self.assigned)


def _rows(predictions: dict[str, dict[str, tuple[list[str], str, float | None]]], labels: Mapping[str, GoldLabel]) -> dict[str, dict[str, _Row]]:
    """Por eje y clave: la fila de cada documento etiquetado que está en `predictions` (orden de la referencia)."""
    rows: dict[str, dict[str, _Row]] = {}
    for key, label in labels.items():
        assigned = predictions.get(key)
        if assigned is None:
            continue
        for axis, correct in label.axes.items():
            values, who, confidence = assigned.get(axis, ([], UNCLASSIFIED, None))
            rows.setdefault(axis, {})[key] = _Row(tuple(correct), tuple(values), who, confidence)
    return rows


def _key(source_path: str, roots: Sequence[str]) -> str:
    # `relative_source_path` compara rutas del sistema; las del contenedor (`/mnt/...`) se comparan como texto POSIX.
    posix = source_path.replace("\\", "/")
    for root in roots:
        base = root.replace("\\", "/").rstrip("/")
        if posix.startswith(base + "/"):
            return posix[len(base) + 1 :]
    return document_key(source_path, roots) if roots else PurePosixPath(posix).name


def _axis_metrics(axis: str, multiple: bool, rows: list[_Row]) -> AxisEvaluation:
    hits = [row.hit for row in rows]
    by_who: dict[str, list[bool]] = {}
    for row, hit in zip(rows, hits, strict=True):
        by_who.setdefault(row.who, []).append(hit)
    true_positives = sum(len(set(row.correct) & set(row.assigned)) for row in rows)
    assigned_total = sum(len(set(row.assigned)) for row in rows)
    correct_total = sum(len(set(row.correct)) for row in rows)
    confusions = Counter((_joined(row.correct), _joined(row.assigned)) for row, hit in zip(rows, hits, strict=True) if not hit)
    per_value = _per_value(rows)
    supported = [metrics.f1 for metrics in per_value if metrics.support]
    return AxisEvaluation(
        axis=axis,
        multiple=multiple,
        labelled=len(rows),
        accuracy=_ratio(sum(hits), len(rows)),
        coverage=_ratio(sum(1 for row in rows if row.assigned), len(rows)),
        precision=_ratio(true_positives, assigned_total),
        recall=_ratio(true_positives, correct_total),
        accuracy_by_classified_by={who: _ratio(sum(values), len(values)) or 0.0 for who, values in sorted(by_who.items())},
        labelled_by_classified_by={who: len(values) for who, values in sorted(by_who.items())},
        confusions=[
            LabelConfusion(label=label, assigned=assigned, count=count) for (label, assigned), count in confusions.most_common(_MAX_CONFUSIONS)
        ],
        selective_accuracy=_ratio(sum(1 for row in rows if row.assigned and row.hit), sum(1 for row in rows if row.assigned)),
        macro_f1=round(sum(supported) / len(supported), 4) if supported else None,
        per_value=per_value,
        confusion_matrix=_confusion_matrix(rows),
        accuracy_by_confidence=_confidence_bins(rows),
    )


def _per_value(rows: list[_Row]) -> list[ValueMetrics]:
    support: Counter[str] = Counter(value for row in rows for value in set(row.correct))
    assigned: Counter[str] = Counter(value for row in rows for value in set(row.assigned))
    correct: Counter[str] = Counter(value for row in rows for value in set(row.correct) & set(row.assigned))
    return [
        ValueMetrics(
            value=value,
            support=support[value],
            assigned=assigned[value],
            correct=correct[value],
            precision=_ratio(correct[value], assigned[value]),
            recall=_ratio(correct[value], support[value]),
            f1=round(2 * correct[value] / (support[value] + assigned[value]), 4),
        )
        for value in sorted(set(support) | set(assigned))
    ]


def _confusion_matrix(rows: list[_Row]) -> dict[str, dict[str, int]]:
    counts = Counter((_joined(row.correct), _joined(row.assigned)) for row in rows)
    matrix: dict[str, dict[str, int]] = {}
    for (label, assigned), count in sorted(counts.items()):
        matrix.setdefault(label, {})[assigned] = count
    return matrix


def _confidence_bins(rows: list[_Row]) -> list[ConfidenceBin]:
    buckets: dict[tuple[str, int], list[bool]] = {}
    last = len(CONFIDENCE_BIN_EDGES) - 2
    for row in rows:
        if not row.assigned or row.confidence is None:
            continue
        index = next((i for i in range(last) if row.confidence < CONFIDENCE_BIN_EDGES[i + 1]), last)
        buckets.setdefault((row.who, index), []).append(row.hit)
    return [
        ConfidenceBin(
            classified_by=who,
            lower=CONFIDENCE_BIN_EDGES[index],
            upper=CONFIDENCE_BIN_EDGES[index + 1],
            labelled=len(hits),
            accuracy=_ratio(sum(hits), len(hits)),
        )
        for (who, index), hits in sorted(buckets.items())
    ]


def _axis_comparison(
    axis: str, pairs: list[tuple[_Row, _Row]], rng: random.Random, resamples: int, margin: float, confidence_level: float
) -> AxisComparison:
    """La comparación de un eje: estimaciones puntuales, intervalos por bootstrap pareado y McNemar."""
    metrics = {"accuracy": _accuracy, "selective_accuracy": _selective_accuracy, "coverage": _coverage}
    samples: dict[str, list[float]] = {name: [] for name in metrics}
    indexes = range(len(pairs))
    for _ in range(resamples):
        sample = [pairs[index] for index in rng.choices(indexes, k=len(pairs))]
        for name, metric in metrics.items():
            before, after = metric([pair[0] for pair in sample]), metric([pair[1] for pair in sample])
            if before is not None and after is not None:
                samples[name].append(after - before)
    alpha = (1.0 - confidence_level) / 2
    compared = {}
    for name, metric in metrics.items():
        before, after = metric([pair[0] for pair in pairs]), metric([pair[1] for pair in pairs])
        differences = sorted(samples[name])
        compared[name] = MetricComparison(
            baseline=_rounded(before),
            candidate=_rounded(after),
            difference=_rounded(after - before) if before is not None and after is not None else None,
            ci_low=_rounded(_percentile(differences, alpha)),
            ci_high=_rounded(_percentile(differences, 1.0 - alpha)),
        )
    baseline_only = sum(1 for before, after in pairs if before.hit and not after.hit)
    candidate_only = sum(1 for before, after in pairs if after.hit and not before.hit)
    low = compared["accuracy"].ci_low
    return AxisComparison(
        axis=axis,
        paired=len(pairs),
        accuracy=compared["accuracy"],
        selective_accuracy=compared["selective_accuracy"],
        coverage=compared["coverage"],
        discordant_baseline_only=baseline_only,
        discordant_candidate_only=candidate_only,
        p_value_mcnemar=_mcnemar(baseline_only, candidate_only),
        non_inferior=low is not None and low >= -margin,
        improved=low is not None and low > 0,
    )


def _accuracy(rows: list[_Row]) -> float | None:
    return sum(row.hit for row in rows) / len(rows) if rows else None


def _selective_accuracy(rows: list[_Row]) -> float | None:
    assigned = [row for row in rows if row.assigned]
    return _accuracy(assigned)


def _coverage(rows: list[_Row]) -> float | None:
    return sum(1 for row in rows if row.assigned) / len(rows) if rows else None


def _percentile(ordered: list[float], q: float) -> float | None:
    """Percentil `q` (0-1) de una lista ordenada, con interpolación lineal; `None` si está vacía."""
    if not ordered:
        return None
    position = q * (len(ordered) - 1)
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _mcnemar(baseline_only: int, candidate_only: int) -> float:
    """p bilateral de McNemar: binomial exacta hasta `_MCNEMAR_EXACT_LIMIT` discordantes, normal por encima."""
    discordant = baseline_only + candidate_only
    if discordant == 0:
        return 1.0
    if discordant <= _MCNEMAR_EXACT_LIMIT:
        tail = sum(math.comb(discordant, i) for i in range(min(baseline_only, candidate_only) + 1))
        return round(min(1.0, 2 * tail / (1 << discordant)), 4)
    statistic = (abs(baseline_only - candidate_only) - 1) ** 2 / discordant
    return round(math.erfc(math.sqrt(statistic / 2)), 4)


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _cell(value: float | None) -> str:
    return "—" if value is None else str(value)


def _yes(flag: bool) -> str:
    return "sí" if flag else "no"


def _joined(values: Iterable[str]) -> str:
    return ", ".join(sorted(set(values))) or NONE_LABEL


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


__all__ = [
    "CONFIDENCE_BIN_EDGES",
    "DEFAULT_GOLD_COLUMNS",
    "NONE_LABEL",
    "UNCLASSIFIED",
    "AxisComparison",
    "AxisEvaluation",
    "ClassificationComparison",
    "ConfidenceBin",
    "EvaluationReport",
    "GoldLabel",
    "GoldStandard",
    "LabelConfusion",
    "MetricComparison",
    "ValueMetrics",
    "common_root",
    "compare_classifications",
    "document_key",
    "document_keys",
    "evaluate_classification",
    "load_gold_xlsx",
]
