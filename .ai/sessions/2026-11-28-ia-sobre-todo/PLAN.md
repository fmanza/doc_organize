# PLAN y AUDIT_PLAN · P3 «La IA sobre todos los documentos» (`ai_scope="all"`)

Fase siguiente a F0 (cierre: `.ai/sessions/2026-11-27-precision-contexto/CIERRE_F0.md`). Propuesta de partida: P3 de
`ANALISIS_MEJORAS.md` §5, recortada a lo que F0 midió.

## Inputs (`/new-feature`)

| Campo | Valor |
|---|---|
| **Objetivo** | Que la IA pueda clasificar todos los documentos en los ejes organizadores (dominio y tipo de material), sustituyendo lo que propusieron las reglas, como opción explícita. Es la configuración que F0 midió: 0,53-0,64 en dominio y 0,66-0,79 en tipo, frente a 0,20 y 0,20 de las reglas |
| **Módulos** | `src/doc_organize/core/models.py` (`AiScope`, `DomainDocument`, `AiPhaseStats`), `src/doc_organize/context/context_builder.py` (`missing()`, `_apply_manifest_ai`, validación), `scripts/benchmark/run.py` (`ai_all`), `docs/`. `dry_run.py` pasa `ai_scope` tal cual y no cambia |
| **API pública** | `AiScope` gana `"all"`. Campos nuevos con valor por defecto: `DomainDocument.rules_material_type`, `DomainDocument.rules_material_type_confidence`, `AiPhaseStats.replaced`. Ninguna firma cambia; el valor por defecto de `ai_scope` sigue siendo `"off"` |
| **Contrato de entrada** | `ContextBuilder.build(..., llm=..., ai_scope="all", taxonomy_manifest=...)`. Sin manifiesto, `"all"` es un `ValueError` |
| **Contrato de salida** | Todo documento legible con presupuesto recibe de la IA sus dos ejes organizadores (`classified_by="ai"`); lo que proponían las reglas queda en `rules_domain`/`rules_confidence` y `rules_material_type`/`rules_material_type_confidence`. Los que no llegan a la IA (presupuesto, fallo, parada) conservan lo de las reglas. `AiPhaseStats.replaced` cuenta los ejes en los que la IA sustituyó un valor que las reglas habían asignado |
| **Reglas de negocio** | «Las personas mandan» intacta: lo decidido por una persona no se pregunta ni se sustituye. «La IA es fallback» y «la IA solo rellena ejes vacíos» se mantienen con `unclassified` y `missing_axes`, y se relajan **solo** con `"all"`. La IA sigue eligiendo solo del catálogo. Nada cambia por defecto (A5) |
| **Restricciones técnicas** | Sin dependencias nuevas. Mismo camino de IA que hoy (caché, presupuesto, concurrencia, redacción de credenciales, progreso, cancelación). Async como el resto de `build`. `tests/unit/test_library_architecture.py` sin cambios |
| **Motores / formatos** | `context.json` (valor nuevo de `ai_stats.scope` y campos nuevos de `DomainDocument`), la caché de IA (la petición es la misma que con `unclassified` para los documentos sin clasificar, así que sus entradas se reutilizan) |
| **Archivos relevantes** | Sí: ver «Rutas afectadas» |

---

## PLAN

### Objetivo

Hoy la IA solo ve lo que las reglas dejan en `sin-clasificar`. F0 midió que las reglas aciertan un 20 %, por debajo
de asignar siempre el valor más frecuente, y que la IA sobre todos los documentos acierta entre 2,5 y 4 veces más. El
benchmark lo consiguió con un truco (umbral de reglas 2,0, para que nunca clasifiquen); P3 lo convierte en una opción
de la librería, con la propuesta de las reglas guardada y contada.

**Fuera de alcance** (y por qué):

- `ai_scope="low_margin"` (P3.1): necesita el margen de las reglas por eje (`RuleDecision`, P6.1, F2). Sin él, «poco
  margen» es lo mismo que «poca confianza», que ya va a la IA con `unclassified`.
- Pista de reglas en el prompt (P3.2): no se midió. Se puede medir después como opción del benchmark sin tocar la API.
- Fusión de evidencias (P3.3): F4.
- Cambiar el valor por defecto (F5): exige segundo corpus (Revisión 18).

### Rutas afectadas

| Ruta | Cambio |
|---|---|
| `src/doc_organize/core/models.py` | `AiScope` + `"all"`; `DomainDocument.rules_material_type` y `rules_material_type_confidence`; `AiPhaseStats.replaced`; docstrings |
| `src/doc_organize/context/context_builder.py` | `build()`: validación de `"all"` sin manifiesto y docstring de `ai_scope`; `_classify_with_manifest`: guardar la propuesta de tipo de las reglas; `missing()`: con `"all"`, los dos organizadores de todo documento no decidido por una persona; `_apply_manifest_ai`: con `"all"`, sustituir y contar |
| `src/doc_organize/context/review_queue.py` | Sin cambios de código (ver AUDIT_PLAN F-2); test que fija el comportamiento |
| `scripts/benchmark/run.py` | `ai_all = true` usa `ai_scope="all"` en vez del umbral 2,0; el truco se conserva solo para comparar con mediciones anteriores (`ai_all_legacy`) si hace falta |
| `tests/unit/` | `test_context_builder.py` (o un fichero nuevo `test_ai_scope_all.py`), `test_benchmark_script.py`, compatibilidad de `context.json` de 2.6 |
| `docs/functional/context.md` §2 | Reglas de negocio: la excepción de `"all"` |
| `docs/api/` y `docs/guides/medir_clasificacion.md` | `ai_scope="all"`, coste y cuándo usarlo |
| `CHANGELOG.md`, `COMPATIBILITY.md` | 2.7.0 (`[Unreleased]` ya tiene la puerta de F1 macro) |

### Componentes implicados

1. **`AiScope`** (`core/models.py:1157`): `Literal["off", "unclassified", "missing_axes", "all"]`.
2. **Validación** (`build`, junto a la de `llm`): `ai_scope == "all"` sin `taxonomy_manifest` → `ValueError`. La vía sin
   manifiesto (`_classify_with_ai`) es de 1.x, de un solo eje, y no se amplía.
3. **Propuesta de las reglas por eje** (A9): en `_classify_with_manifest`, al asignar `material_type`, guardar también
   `rules_material_type` y `rules_material_type_confidence`, como ya se hace con `rules_domain`. Se rellena con
   cualquier alcance (también `off`), para que la comparación reglas/IA sea posible siempre.
4. **`missing()`** (`context_builder.py:867`): con `"all"`, `[folder.key, subfolder.key]` para todo documento, menos
   los ejes que decidió una persona (`locked`, como hoy). Los ejes que solo etiquetan no se piden (lo medido).
5. **`_apply_manifest_ai`** (`:1061`): con `"all"` la condición «solo si estaba vacío» (`old_domain_slug ==
   _UNCLASSIFIED_SLUG`, `material_type == _UNCLASSIFIED_SLUG`) pasa a «si la IA eligió algo». Si el valor anterior lo
   habían asignado las reglas y es distinto, `run.replaced += 1`. El movimiento de bucket ya existe.
6. **`_AiRun` / `AiPhaseStats`**: contador `replaced` (ejes, no documentos), en `stats()`.
7. **Benchmark**: `ai_all` → `ai_scope="all"` con el umbral normal. `_incomplete` sigue valiendo (todo legible debe
   quedar `classified_by="ai"`).

### Tipos necesarios

```python
AiScope = Literal["off", "unclassified", "missing_axes", "all"]

class DomainDocument(BaseModel):
    ...
    rules_material_type: str | None = None              # 2.7.0, como rules_domain
    rules_material_type_confidence: float | None = Field(default=None, ge=0.0, le=1.0)

class AiPhaseStats(BaseModel):
    ...
    replaced: int = Field(default=0, ge=0)              # ejes en que la IA sustituyó un valor de las reglas (2.7.0)
```

### Riesgos (para la auditoría)

Coste (todo el corpus a la IA), cola de revisión inundada, compatibilidad de `context.json` y de la web, diferencia
entre lo medido (truco del umbral) y lo implementado, y semántica con `semantic=True`.

---

## AUDIT_PLAN

### Riesgos funcionales

| Id | Gravedad | Riesgo | Mitigación |
|---|---|---|---|
| F-1 | Alta | **Lo implementado no es lo medido.** El benchmark usó umbral 2,0: además de que las reglas no clasificaran, `_ai_value` y la cola usaban ese umbral. Con `"all"` y umbral normal, las confianzas de la IA y los avisos de la cola cambian | La asignación (lo que mide la exactitud) es la misma: la IA elige el valor en los dos casos. **Condición C1**: repetir qwen2.5:14b en calibración con `ai_scope="all"`; la exactitud debe quedar dentro del ruido medido (±0,02) de la medición con el truco |
| F-2 | Alta | **La cola de revisión se inunda.** Con las reglas acertando un 20 %, la IA las contradice en la mayoría de los documentos: un aviso `rules_ai_disagreement` por cada uno convertiría la cola en el corpus entero | Con `"all"` no se añade aviso por discrepar de las reglas: las reglas pierden a propósito. La cola sigue recibiendo lo de siempre (confianza baja, cita no verificada, sin clasificar). El aviso actual (`ai_domain != dominio`) no salta porque el dominio ya es el de la IA. Lo discrepante queda contado en `replaced` y guardado por eje, para medirlo o mostrarlo después. Test que fija esto |
| F-3 | Media | **Sustituir con poca confianza.** La IA puede sustituir un valor de reglas por uno con confianza bajo el umbral | Es lo medido. El valor bajo el umbral va a la cola como `low_confidence`, como cualquier valor de IA. Alternativa (solo sustituir por encima del umbral): no medida; se puede medir como variante del benchmark antes de F5 |
| F-4 | Media | **Presupuesto a medias.** Con `ai_max_documents`, una parte del corpus queda de la IA y otra de las reglas, con precisiones muy distintas | Es el comportamiento actual de cualquier fase de IA (`stopped="budget"`). Se documenta: con `"all"`, un tope bajo da un contexto mixto; `ai_stats` dice cuántos llegaron |
| F-5 | Baja | **Semántica.** Con `semantic=True`, la semántica rellena antes de la IA, y con `"all"` la IA la sustituye | Coherente con «la IA decide los organizadores»; los ejemplos y la preselección de la semántica siguen llegando a la IA. Se cuenta en `replaced` solo si lo sustituido era de reglas (`classified_by="rules"`); lo de la semántica, no |

### Riesgos técnicos (LSP/ISP incluidos)

| Id | Riesgo | Mitigación |
|---|---|---|
| T-1 | **`context.json` hacia atrás.** Un contexto con `ai_stats.scope="all"` no lo lee la 2.6 (`Literal`) | Es el mismo caso que cualquier valor nuevo de un `Literal` en una MINOR. `COMPATIBILITY.md`: contextos de 2.7 con `"all"` necesitan 2.7. Hacia delante, sin problema (campos con valor por defecto). Test de carga de un contexto de 2.6 |
| T-2 | **Web.** `operations.py:251` y `:318` validan `ai_scope` con su propio `Literal`; mostrar o pedir `"all"` exige cambiarlo | La web no se rompe: no pide `"all"` hasta que lo añada. Aviso en su PLAN (W-nuevo): ofrecer `"all"`, mostrar `replaced` y el tiempo estimado. `classified_by` no cambia de valores (`"ai"` ya existe) |
| T-3 | **Caché.** La petición de un documento con `"all"` es la misma que con `unclassified` cuando se le piden los mismos ejes | Las entradas se reutilizan entre alcances, que es lo deseable. Test: reconstruir con `"all"` sin cambios no envía nada |
| T-4 | **LSP/ISP.** No hay interfaz nueva ni cambia ningún contrato síncrono/asíncrono; `AiScope` crece en un valor y los consumidores que hacen `match` exhaustivo sobre él lo notarían | Verificado con grep: ni la librería ni la web hacen `match` sobre el alcance. La web lo guarda como `str` en resultados (`results.py:402`) |
| T-5 | **`rules_material_type` en contextos viejos.** Es `None` en contextos de 2.6 | Igual que `rules_domain` en 1.5.0: `None` significa «no se sabe» |

### Riesgos de seguridad y privacidad

| Id | Riesgo | Mitigación |
|---|---|---|
| S-1 | **Más documentos salen hacia el modelo.** Con `"all"`, todo el corpus pasa por la IA, no solo lo dudoso | Opción explícita, nunca por defecto. Mismo extracto, delimitadores y redacción de credenciales que hoy (`credential_findings` lo registra). Documentar que con un modelo comercial el corpus entero sale del equipo |
| S-2 | Nada más cambia en superficie de ataque | — |

### Simplificaciones posibles

- **No añadir `rules_material_type`** y medir las sustituciones solo en el benchmark: descartado, porque sin él la
  información de las reglas se pierde en el contexto (A9) y `replaced` no se podría auditar.
- **No añadir `replaced`**: posible (se deduce comparando campos), pero es el dato que la web mostrará y cuesta un
  contador.
- **Quitar el truco del benchmark**: sí, tras C1. Mantener dos caminos para lo mismo confunde.

### Veredicto

### 🟡 GO_CONDICIONAL

El cambio es pequeño (un valor de `Literal`, dos condiciones, tres campos), queda detrás de una opción explícita y
reutiliza todo el camino de IA existente. Lo que lo justifica está medido en F0.

**Condiciones**:

1. **C1 (F-1)**: medir qwen2.5:14b con `ai_scope="all"` en calibración antes de cerrar la versión; exactitud dentro de
   ±0,02 de la medición con el truco del umbral, en los dos ejes.
2. **C2 (F-2)**: test que fija que `"all"` no añade avisos `rules_ai_disagreement` por discrepar de las reglas, y que
   `replaced` y la propuesta de reglas por eje quedan guardados.
3. **C3 («las personas mandan»)**: test con una decisión humana en un eje: con `"all"` no se pregunta ni se sustituye.
4. **C4 (T-1, T-2)**: `COMPATIBILITY.md` y CHANGELOG (Added), aviso a la web, y test de carga de un `context.json` de
   2.6.
5. **C5 (A5)**: el valor por defecto de `ai_scope` no cambia, y con `unclassified`/`missing_axes` el resultado es
   idéntico al de 2.6 (los tests existentes pasan sin tocarlos, salvo los que comprueben el nuevo campo).

**Orden de implementación** (por capas): L1 `models.py` (tipos y campos) → L2 `context_builder.py` (propuesta de
reglas por eje, `missing`, `_apply_manifest_ai`, validación) y tests → L3 benchmark y medición C1 → docs, CHANGELOG,
`zensical build --strict`.

**Rama**: `feat/ia-sobre-todo` desde `develop` (PR con `--base develop`).

---

## Resultado de C1 (2026-11-28)

qwen2.5:14b, calibración (100 documentos), 1 repetición, `ai_scope="all"` real frente al truco del umbral de 2.6.0:

| Eje | Truco (2.6.0) | `ai_scope="all"` | Diferencia | Dentro de ±0,02 |
|---|---|---|---|---|
| Dominio | 0,53 (F1 0,49) | 0,53 (F1 0,48) | 0,00 | sí |
| Tipo | 0,79 (F1 0,65) | 0,78 (F1 0,63) | −0,01 | sí |

**C1 cumplida.** Cola de revisión (riesgo abierto en AUDIT_CODE): 16 elementos para 100 documentos, todos
`unverified_evidence`; ningún `low_confidence` ni `rules_ai_disagreement`. La IA sustituyó 146 de los 200 ejes
organizadores que habían asignado las reglas. La cola no se inunda.
