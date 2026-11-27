# PLAN y AUDIT_PLAN · F0 «Medir bien» (precisión del contexto)

> Fecha: 2026-11-27 · Flujo: `/new-feature` (PLAN → **AUDIT_PLAN** → IMPLEMENT → AUDIT_CODE → VERSION) · Estado:
> **PLAN auditado, GO_CONDICIONAL, sin implementar**
>
> Parte de [`ANALISIS_MEJORAS.md`](ANALISIS_MEJORAS.md) (análisis auditado, §9). Este documento **no** vuelve a auditar
> las propuestas P1-P12: concreta y audita la **implementación de la primera fase** de su hoja de ruta (§6, F0), la que
> §9.5 recomienda como primer paso. F1-F5 tendrán su propio PLAN cuando F0 haya dado sus números (§9.5: «su resultado
> decide si la palanca principal es P1 o P3, y puede reordenar F1-F2»).
>
> Base: doc_organize **2.5.0** (`develop`, `ae63f52`); doc_organize_web 3.1.0. Versión objetivo: **2.6.0** (MINOR:
> solo API nueva y una corrección de estado).

---

## Inputs (`/new-feature`)

| Campo | Valor |
|---|---|
| **Objetivo** | Poder medir con rigor la clasificación del contexto antes de cambiarla: métricas por valor, comparación pareada con intervalo de confianza y un benchmark reproducible; y dejar de presentar el marcador `sin-clasificar` como un dominio confirmado |
| **Módulos** | `src/doc_organize/context/evaluation.py`, `src/doc_organize/context/context_builder.py` (estado del marcador), `src/doc_organize/core/models.py` (`Domain`), `src/doc_organize/context/review_queue.py` (P6.6), `src/doc_organize/__init__.py`, `scripts/benchmark/` (nuevo, fuera del paquete), `docs/` |
| **API pública** | Nuevos: `compare_classifications`, `ClassificationComparison`, `AxisComparison`, `ValueMetrics`, `ConfidenceBin`, `UNCLASSIFIED_SLUG`, `Domain.is_placeholder`. Campos nuevos con valor por defecto en `AxisEvaluation`. Ninguna firma existente cambia |
| **Contrato de entrada** | `Context` ya construido (o el de `DryRunResult.context`) + `GoldStandard` (`load_gold_xlsx`, `gold_from_decisions`) + `roots` opcionales, como `evaluate_classification` |
| **Contrato de salida** | Modelos Pydantic deterministas (misma entrada y semilla → mismo resultado, orden estable); no escriben nada |
| **Reglas de negocio** | No cambia ninguna clasificación (A5: nada cambia el comportamiento por defecto antes de F5). No se inventan etiquetas: lo no etiquetado no cuenta. «Las personas mandan» intacta. La referencia real nunca entra en el repositorio |
| **Restricciones técnicas** | Sin dependencias nuevas (bootstrap con `random.Random`, sin numpy/scipy); síncrono (evaluar es CPU puro y barato); compatible con contextos y referencias de 2.x; `tests/unit/test_library_architecture.py` sin cambios |
| **Motores / formatos** | `context.json` (estado del dominio marcador), informes Pydantic/JSON que la web guarda (`extra="allow"` en `backend/app/domain/runs/results.py:323`), Markdown de los informes |
| **Archivos relevantes** | Sí: ver «Rutas afectadas» |

---

## PLAN

### Objetivo

Implementar en la librería lo que F0 necesita y no es trabajo del mantenedor:

| # | Qué | Origen |
|---|---|---|
| E1 | `AxisEvaluation` con precisión/recall/F1 **por valor**, F1 macro, precisión sobre lo asignado, matriz de confusión completa y exactitud por tramo de confianza (separada por fase) | P9.1, §9.3.3 |
| E2 | `compare_classifications(baseline, candidate, gold)`: diferencia pareada por documento con bootstrap (IC 95 %), conteos de McNemar y veredicto de no inferioridad / mejora | P9.2, §9.3.4 |
| E3 | `scripts/benchmark/`: entrada única que construye en seco cada configuración, evalúa, compara y escribe un informe Markdown; partición con tramo bloqueado; ablaciones de v1 y «IA sobre toda la referencia» **sin tocar la librería** | P9.3, §6 F0, §9.3.2/5/6/7/10 |
| E4 | Exportar `UNCLASSIFIED_SLUG`; `Domain.is_placeholder`; el dominio marcador deja de nacer `CONFIRMED` | W1 (parte librería), §6 F0 |
| E5 | Cola de revisión: `unclassified` también para el eje de subcarpeta vacío cuando el dominio tiene valor | P6.6 (V4) |
| E6 | Casos de regresión que fijan los defectos de `score_catalog` (§A del análisis) con el resultado **actual** de v1 | P9.4 |
| E7 | Protocolo de medición (§9.3) como guía en `docs/` y entrada en `.ai/DECISIONS_LOG.md` («sin fine-tuning por proyecto», P12.4) | §9.3, P12.4 |

**Fuera de alcance de este PLAN** (y por qué):

- **Trabajo del mantenedor, no código**: recuperar la referencia de M0, etiquetar a ciegas ≥ 50 documentos (kappa),
  conseguir un segundo corpus, confirmar el umbral de las mediciones (V29). Son condición para **cerrar** F0, no para
  implementar E1-E7.
- **P6.5** (umbral por eje en dominio y tipo): cambia la clasificación de quien ya lo declara → contradice A5; va con
  `rules_version="2"` en F2.
- **Web (W1, W4, W5)**: otro repositorio, otro PLAN; este deja la API que necesita (E1, E2, E4).
- **P1-P5, P7, P8, P11, P12**: F1-F5.

### Rutas afectadas

| Ruta | Cambio |
|---|---|
| `src/doc_organize/context/evaluation.py` | E1 (campos y cálculo), E2 (función y modelos nuevos), `to_markdown` ampliado |
| `src/doc_organize/core/models.py` | `Domain.is_placeholder` (propiedad, no campo) |
| `src/doc_organize/context/context_builder.py:565` | E4: el marcador nace `DRAFT` |
| `src/doc_organize/context/review_queue.py:163-166` | E5 |
| `src/doc_organize/__init__.py` | Exportar los nombres nuevos (`_EXPORTS`, `__all__`, bloque `TYPE_CHECKING`) |
| `scripts/benchmark/{run.py,configs/*.toml,README.md}` | E3 (nuevo; no se empaqueta) |
| `.gitignore` | `scripts/benchmark/out/` y `*.xlsx` bajo `scripts/benchmark/` |
| `tests/unit/test_evaluation*.py`, `tests/unit/test_review_queue*.py`, `tests/unit/test_score_catalog_regression.py` (nuevo), `tests/unit/test_public_api.py` | E1, E2, E4, E5, E6 |
| `docs/api/evaluation.md`, `docs/api/publica.md`, `docs/guides/medir_clasificacion.md` (nuevo), `docs/functional/revision_clasificacion.md`, `zensical.toml` (nav), `CHANGELOG.md` | Documentación |
| `.ai/DECISIONS_LOG.md` | Decisión P12.4 |

### Componentes implicados

**E1 · Métricas por valor** (`evaluation.py`)

- `_predictions` conserva también la **confianza** del primer valor de cada eje (hoy la descarta).
- Por valor `v` del eje (unión de valores de la referencia y asignados, sin `ninguno`): TP = documentos con `v` en
  ambos; FP = asignado y no en la referencia; FN = en la referencia y no asignado. Vale igual para ejes de un valor y
  de varios.
- `macro_f1`: media de F1 de los valores con soporte (`support > 0` en la referencia). Los valores solo asignados (sin
  soporte) aparecen en `per_value` con F1 0 pero no entran en la media (convención de scikit-learn con
  `labels=` de la referencia; documentarla).
- `selective_accuracy`: exactitud sobre los documentos con algún valor asignado (la «precisión sobre lo asignado» de
  §9.3.3; con `coverage` forma el punto riesgo-cobertura). Una abstención no cuenta como error.
- `confusion_matrix`: `dict[referencia, dict[asignado, int]]` completa (las `confusions` actuales siguen siendo el
  top 10).
- `accuracy_by_confidence`: `list[ConfidenceBin(classified_by, lower, upper, labelled, accuracy)]` con tramos fijos
  `[0, 0,5) [0,5, 0,6) … [0,9, 1,0]`, **por fase** (§4.4 del análisis: un 0,6 de reglas y un 0,6 de IA no son
  comparables). Los ejes vacíos (`unclassified`) no tienen tramo.
- `to_markdown()` mantiene la tabla actual (compatibilidad con quien la pegue) y añade un `to_markdown(detail=True)`
  con la tabla por valor.

**E2 · Comparación pareada** (`evaluation.py`)

```python
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
) -> ClassificationComparison: ...
```

- Por eje, solo los documentos etiquetados **presentes en los dos** contextos (los demás se cuentan en
  `unpaired`). Para cada uno, acierto sí/no en cada contexto (misma definición que `accuracy`).
- `AxisComparison`: `paired`, `baseline_accuracy`, `candidate_accuracy`, `difference`, `ci_low`, `ci_high`
  (bootstrap por percentiles, remuestreando documentos), `discordant_baseline_only` / `discordant_candidate_only`
  (conteos de McNemar), `p_value_mcnemar` (binomial exacta con `math.comb`, sin scipy), `non_inferior`
  (`ci_low ≥ -margin`) y `improved` (`ci_low > 0`). Lo mismo para `selective_accuracy` y `coverage` (riesgo-cobertura).
- `ClassificationComparison.non_inferior` / `.improved` agregan sobre todos los ejes (la puerta de §9.3.4) y
  `to_markdown()`.
- Recibe `Context` (no `EvaluationReport`) porque el informe agrega y la comparación necesita el acierto de cada
  documento; así `EvaluationReport` no crece con un campo por documento que la web guardaría en cada ejecución.

**E3 · Benchmark** (`scripts/benchmark/`, fuera de `src/`)

- `run.py --project-root … --gold ref.xlsx --config configs/rules_v1.toml [--config …] --out <dir fuera del repo>
  [--split holdout|calibrate|all] [--repeat N] [--seed S]`.
- Cada `.toml` describe una configuración de `dry_run_classify` (plantilla o manifiesto, `threshold`, `ai_scope`,
  `semantic`, alias de modelo, prompts) y, opcionalmente, una **ablación** (`ablation = "whole_word" | "no_divide" |
  "head_only" | "tie_abstain"`) que el script aplica parcheando `DomainClassifier.score_catalog` **solo dentro del
  proceso del script** (como hacía `measure_rules_only.py` de M0 con métodos internos: herramienta de medición, no API).
- **IA sobre toda la referencia** (§9.3.6) sin cambiar la librería: `threshold > 1` (p. ej. `1.01`) hace que ningún
  valor de reglas en dominio y tipo llegue al umbral, así que con `ai_scope="unclassified"` todos los documentos van a
  la IA, que en esos ejes no está limitada por el umbral (`context_builder.py:1081-1094`). El script **comprueba**
  `ai_stats.classification.sent == documentos` y aborta si no; y documenta que los ejes que etiquetan quedan vacíos en
  ese modo (sí se filtran por umbral, `:1101`).
- Partición (§9.3.2): tramo bloqueado ~1/3 estratificado por el valor de dominio de la referencia, semilla fija, lista
  de claves guardada en `--out`; validación cruzada de 5 pliegues sobre el resto. Lógica en el script, no en la API.
- Ruido de la IA (§9.3.7): `--repeat N` sin caché; el informe da la dispersión entre repeticiones junto al efecto.
- Registro (§9.3.10): por ejecución, versión de doc_organize, modelo, huella del prompt, del catálogo y del perfil,
  semilla y duración, en `run.json`; el informe Markdown resume en las tres vistas de §9.3.1 (toda la referencia, solo
  filas revisadas por personas si la hoja trae la columna, reponderada por estratos si la trae).
- Mantiene la convención de M0 (`--path-map` para rutas del contenedor).

**E4 · Marcador `sin-clasificar`**

- `UNCLASSIFIED_SLUG` en `_EXPORTS` → `doc_organize.core.constants`.
- `Domain.is_placeholder` (`@property`: `self.slug == UNCLASSIFIED_SLUG`). Propiedad y no campo: no cambia el JSON, vale
  para contextos antiguos sin migración y no puede contradecir al slug.
- `context_builder.py:565`: `DRAFT` cuando `slug == UNCLASSIFIED_SLUG`, aunque haya catálogo. La web ya pinta el estado
  que recibe (`ContextDomains.tsx:112-113`): pasará de «Confirmado» a «Borrador» sin tocarla. El texto correcto («Por
  debajo del umbral») es W1, en la web.

**E5 · Cola** (`review_queue.py`): tras el bloque del eje de carpeta, si hay eje de subcarpeta y el documento no tiene
valor en él → `unclassified` con `axis=<subcarpeta>`. Mismo motivo y prioridad que el de dominio; ningún motivo nuevo
(la web valida los motivos).

**E6 · Regresión** (`tests/unit/test_score_catalog_regression.py`): los cuatro casos de §A.1 del análisis con la
plantilla empaquetada `sgi-integrado`, afirmando el resultado **actual** de v1 (incluidos sus errores: «ley» ⊂
«leyenda», 0,50 → 0,17 al añadir palabras clave, empate → primera entrada). Cada test lleva en el docstring el defecto
que fija y que v2 debe corregir; con `rules_version="2"` (F2) se añadirá la expectativa de v2 al lado. Protege a v1 de
cambios accidentales (A5).

**E7 · Documentación**: guía `docs/guides/medir_clasificacion.md` con el protocolo de §9.3 (referencia, partición,
métricas, comparación, ablación, ruido, presupuesto, privacidad de la referencia) y cómo usar `scripts/benchmark/`.

### Tipos necesarios

```python
class ValueMetrics(BaseModel):
    value: str
    support: int            # documentos con el valor en la referencia
    assigned: int           # documentos con el valor asignado
    precision: float | None
    recall: float | None
    f1: float | None

class ConfidenceBin(BaseModel):
    classified_by: str
    lower: float
    upper: float
    labelled: int
    accuracy: float | None

class AxisEvaluation(BaseModel):          # campos nuevos, todos con valor por defecto
    selective_accuracy: float | None = None
    macro_f1: float | None = None
    per_value: list[ValueMetrics] = []    # ordenado por valor
    confusion_matrix: dict[str, dict[str, int]] = {}
    accuracy_by_confidence: list[ConfidenceBin] = []

class MetricComparison(BaseModel):
    baseline: float | None
    candidate: float | None
    difference: float | None
    ci_low: float | None
    ci_high: float | None

class AxisComparison(BaseModel):
    axis: str
    paired: int
    accuracy: MetricComparison
    selective_accuracy: MetricComparison
    coverage: MetricComparison
    discordant_baseline_only: int
    discordant_candidate_only: int
    p_value_mcnemar: float | None
    non_inferior: bool
    improved: bool

class ClassificationComparison(BaseModel):
    axes: dict[str, AxisComparison]
    unpaired: list[str]
    resamples: int
    seed: int
    margin: float
    confidence_level: float
    non_inferior: bool       # en todos los ejes
    improved: bool           # en alguno
    def to_markdown(self) -> str: ...
```

### Riesgos (para la auditoría)

- Funcional: confundir «herramienta de medida correcta» con «medida fiable»: con 150 documentos el IC sigue siendo
  ±7 puntos.
- Funcional: el cambio de estado del marcador se ve en la web y en `context.json`.
- Técnico: el script depende de métodos internos y de un umbral > 1 no validado.
- Técnico: crecimiento de los informes que la web guarda por ejecución.
- Seguridad/privacidad: la referencia y los informes contienen nombres de documentos reales.

---

## AUDIT_PLAN

Auditoría con la convención del repo sobre el PLAN anterior, contrastando cada afirmación con el código (`ae63f52`) y
con doc_organize_web (`e04de0a`).

### Riesgos funcionales

| ID | Sev. | Hallazgo | Disposición |
|---|---|---|---|
| F-1 | Alta | **La herramienta no arregla la referencia.** E1-E3 miden bien sobre una referencia que en su mayoría propuso Claude (A1) y que tiene 150 filas (±7). Si F0 se cierra con solo E1-E7, se decidirá con la misma debilidad que §9 señaló | **Condición C1**: F0 no se da por cerrada sin el acuerdo humano medido (≥ 50 filas a ciegas) y sin que el informe del benchmark muestre las tres vistas. E1-E7 pueden mergearse antes: solo añaden medida |
| F-2 | Media | **`DRAFT` en el marcador no es neutro.** Cambia `status` en `context.json` (se persiste, `context_registry.py:227`) y la web pasará de «Confirmado» a «Borrador», que tampoco es exacto. Verificado: ningún otro código de la librería lee `DomainStatus` (solo `context_builder.py:565` lo escribe), así que no altera clasificación, reorganización ni sitio | Aceptado como corrección: CHANGELOG «Changed» + aviso a la web. La etiqueta buena es W1 |
| F-3 | Media | **E5 cambia los recuentos de la cola** (más elementos `unclassified`): con CALIDAD_VD, cada tipo vacío con dominio asignado aparecerá. Es justo el error silencioso que V4 describe, pero la web lo verá como un salto | Aceptado. CHANGELOG «Fixed»; la web no necesita cambios (motivo existente) |
| F-4 | Media | **Macro F1 con clases sin soporte** en una referencia estratificada por lo que asignaron las reglas: valores raros con 1-2 documentos dominan la media y la hacen inestable | Documentar `support` junto a cada F1; el informe del benchmark marca valores con `support < 5`. No cambiar la definición |
| F-5 | Media | **«IA sobre toda la referencia» con `threshold=1.01`** cambia también la fase semántica (no: usa `semantic_threshold`, separado; verificado `context_builder.py:519`) y vacía los ejes que etiquetan. Además el contexto guarda `ai_fallback_threshold=1.01`, así que todos los valores de la IA (confianza ≤ 1,0) saldrían como `low_confidence` en la cola (irrelevante en prueba en seco, pero ese contexto no debe reutilizarse ni persistirse) | Aceptado con la comprobación de `sent == documentos` y la nota en el README del script; medir solo dominio y tipo en ese modo |
| F-6 | Baja | `accuracy_by_confidence` mezclaría fases si no se separa | Ya separado por `classified_by` en el PLAN |
| F-7 | Baja | Comparar dos contextos construidos con **distintas `roots`** daría claves distintas y todo «sin parear» | `compare_classifications` usa las mismas `roots` para los dos; si `unpaired` supera el 10 % de la referencia, el informe lo avisa |

### Riesgos técnicos (LSP/ISP incluidos)

| ID | Sev. | Hallazgo | Disposición |
|---|---|---|---|
| T-1 | Media | **Contrato sync/async (LSP)**: `evaluate_classification` es síncrona y `dry_run_classify` asíncrona. `compare_classifications` debe ser síncrona (CPU puro, ~150 × 1000 operaciones) para no forzar `await` donde no hay E/S | Síncrona. Verificado: la web la llamará desde una operación de la cola (hilo), como `evaluate_classification` |
| T-2 | Media | **ISP**: tentación de meter partición, pliegues, ablaciones y repeticiones en la API pública. Son decisiones del protocolo y cambiarán con él | Fuera de la API: en `scripts/benchmark/`. La API solo gana dos piezas estables (métricas y comparación) |
| T-3 | Media | **El script usa internos** (`DomainClassifier.score_catalog`, `_classify_with_manifest`) y un umbral > 1 que `build` no valida (solo valida `semantic_threshold`, `:471`). Un cambio interno o una validación futura de `threshold ∈ [0, 1]` lo rompería sin que falle el CI (`ruff`/`mypy` solo miran `src tests`) | Aceptado: es una herramienta de medición, como las de M0. El script falla en voz alta (comprobación de `sent`, `getattr` con error claro). **No** se añade un test que convierta `threshold > 1` en contrato |
| T-4 | Media | **Tamaño de los informes en la web**: `per_value` y `confusion_matrix` añaden ~10 × 10 celdas por eje y ejecución. La web guarda el `model_dump` con `extra="allow"` (`results.py:323`): valida y conserva los campos nuevos | Aceptado; tamaño acotado por el catálogo, no por el corpus. Sin campo por documento en `EvaluationReport` (por eso E2 recibe `Context`) |
| T-5 | Baja | **Compatibilidad de lectura**: informes de 2.5 sin los campos nuevos deben validar con 2.6 | Todos los campos nuevos con valor por defecto; test de ida y vuelta con un JSON de 2.5 |
| T-6 | Baja | **Determinismo**: el bootstrap con `random.Random(seed)` es estable entre ejecuciones de la misma versión de Python. Ruff marcará `S311` | `# noqa: S311` con motivo (no es criptografía). Orden estable de documentos antes de remuestrear (ordenar por clave) |
| T-7 | Baja | McNemar con `math.comb` para n grande es exacto pero puede ser lento; con n ≤ 1000 discordantes es trivial | Exacta hasta 1000 discordantes; por encima, aproximación normal con corrección de continuidad. Documentado |
| T-8 | Baja | La propiedad `is_placeholder` no aparece en `model_dump`: un consumidor que lea el JSON no la ve | Aceptado: quien lee JSON tiene el slug exportado (E4) |

### Riesgos de seguridad y privacidad

| ID | Sev. | Hallazgo | Disposición |
|---|---|---|---|
| S-1 | Media | **Fuga de la referencia**: el script lee un Excel con rutas y nombres reales y escribe informes con claves de documento. Si `--out` está dentro del repo, un `git add .` lo publica | `--out` obligatorio y **rechazado si está dentro del repositorio**; `.gitignore` para `scripts/benchmark/out/` y `*.xlsx` ahí; el README lo explica |
| S-2 | Baja | Las configuraciones `.toml` podrían llevar claves del proxy | Solo alias de modelo; credenciales por entorno como en el resto (`LlmSettings`); el script nunca imprime `LlmSettings` (ya sin claves en `repr()`, 2.4.2) |
| S-3 | Baja | Medir con modelos Claude contra una referencia propuesta por Claude favorece a esos modelos (§9.3.9) | El `run.json` registra el modelo; el informe separa los resultados de modelos Claude |
| S-4 | — | Sin entrada nueva de usuario en el manifiesto ni en la web; sin red nueva | Nada que añadir |

### Simplificaciones posibles

1. **Sin `ai_scope` de prueba**: «IA sobre toda la referencia» con `threshold > 1` en el script (F-5, T-3) en lugar de un
   valor nuevo de `AiScope`, que la web valida con un `Literal` cerrado (A12). **Adoptada.**
2. **Sin función de partición pública**: estratificar y plegar en el script. **Adoptada.**
3. **`is_placeholder` como propiedad**, sin campo nuevo ni migración. **Adoptada.**
4. **Sin motivo nuevo en la cola** para E5: se reutiliza `unclassified`. **Adoptada.**
5. **ECE, curvas completas de riesgo-cobertura y calibración**: fuera; los tramos de confianza por fase bastan para
   F0 y la calibración es P6.2 (F2). **Adoptada.**
6. Posible: **posponer E5** a F2 junto a P6. No se adopta: no cambia la clasificación, cuesta ~10 líneas y hace
   visible el error del eje que peor funciona justo cuando se va a medir.
7. Posible: **no mover los scripts de M0** sino reescribir uno solo. Se adopta: `run.py` sustituye a
   `measure_baseline.py`, `measure_rules_only.py` y `measure_with_ai.py` (todos se reducen a `dry_run_classify` +
   `evaluate_classification`, que no existían en M0); `prepare_reference.py` se queda en su sesión (generó la
   referencia una vez y depende de su procedencia).

### Veredicto

### 🟡 GO_CONDICIONAL

E1-E7 añaden medida sin cambiar ninguna clasificación, con dos correcciones visibles y acotadas (estado del marcador,
`unclassified` en el eje de subcarpeta). El diseño respeta LSP/ISP (funciones nuevas síncronas, nada del protocolo en
la API) y no añade dependencias.

**Condiciones**:

1. **C1 (F-1)**: F0 se cierra solo con la referencia de M0 recuperada, el acuerdo humano medido (≥ 50 filas a ciegas,
   kappa por eje) y el informe del benchmark en las tres vistas. La implementación de E1-E7 no espera a esto.
2. **C2 (S-1)**: el script rechaza `--out` dentro del repositorio y `.gitignore` cubre sus salidas, antes de ejecutarlo
   con la referencia real.
3. **C3 (A5)**: E6 fija el comportamiento actual de v1 y pasa sin tocar `domain_classifier.py`; cualquier diff en
   `domain_classifier.py`, `axis_rules.py` o `semantic.py` en esta rama es motivo de NO_GO en AUDIT_CODE.
4. **C4 (F-2, F-3)**: CHANGELOG con «Changed» (estado `borrador` del marcador) y «Fixed» (cola), y aviso en el PLAN de
   la web para W1.
5. **C5 (T-5)**: test de compatibilidad que carga un `EvaluationReport` serializado por 2.5.0.

**Orden de implementación** (por capas): L1 `evaluation.py` (E1, E2) y sus tests → L2 E4 + E5 + E6 → L3
`scripts/benchmark/` (E3) → docs (E7), `zensical build --strict`, `CHANGELOG`.

**Rama**: `feat/medir-clasificacion` desde `develop` (PR con `--base develop`).
