# Benchmark de la clasificación del contexto

Herramienta de medición de F0 (`.ai/sessions/2026-11-27-precision-contexto/PLAN.md`). No se empaqueta ni es API: puede
usar internos de la librería. El protocolo que aplica está en
[`docs/guides/medir_clasificacion.md`](../../docs/guides/medir_clasificacion.md).

> **Privacidad**: la referencia y los informes llevan nombres de documentos reales. `--out` tiene que estar fuera del
> repositorio (el script lo rechaza si no) y la referencia no se sube nunca.

## 1. Comprobar la referencia (acuerdo humano)

```bash
# 50 documentos de la referencia, sin lo que asignó doc_organize ni lo que propuso nadie
python scripts/benchmark/run.py blind-sheet --gold <referencia.xlsx> --size 50 --out <carpeta>
# … una persona abre cada documento y rellena dominio_ok y tipo_ok en hoja_a_ciegas.xlsx …
python scripts/benchmark/run.py agreement --gold <referencia.xlsx> --blind <carpeta>/hoja_a_ciegas.xlsx --out <carpeta>
```

`acuerdo.md` da la kappa de Cohen por eje y las discrepancias. Con kappa < 0,6 la referencia no sirve para decidir:
hay que revisar las discrepancias (y la referencia) antes de medir nada.

## 2. Medir configuraciones

```bash
python scripts/benchmark/run.py run --project-root <raíz del proyecto> --gold <referencia.xlsx> \
    --config scripts/benchmark/configs/reglas_v1.toml \
    --config scripts/benchmark/configs/ablacion_whole_word.toml \
    --out <carpeta> [--split calibrate|holdout|all] [--repeat 3] [--seed 0] \
    [--path-map /mnt/documentation=C:/Desarrollo/documentation]
```

- La **primera** configuración es la de partida; cada una de las demás se compara con ella (`compare_classifications`).
- `--split`: la primera vez se crea `particion.json` en `--out` (un tercio bloqueado, estratificado por el valor de la
  referencia, y 5 pliegues del resto) y después se reutiliza siempre. Por defecto se mide en `calibrate`; `holdout`
  solo para pasar una puerta de fase.
- `--repeat N`: repite cada configuración (sin caché de IA) para ver el ruido de la IA.
- `--path-map`: el contexto guardado por la web tiene rutas del contenedor; así se leen las conversiones en el equipo.
- `--column eje=columna`: si la plantilla no usa los ejes `domains` y `material_types`.

Salida en `--out`: `informe.md` (métricas en las tres vistas de la referencia, comparación con la de partida, ruido) y
`run.json` (versión, modelo, huellas de la referencia, la plantilla, el perfil y los prompts, tokens y tiempos).

## Configuraciones (`configs/*.toml`)

| Clave | Por defecto | Qué hace |
|---|---|---|
| `name` | nombre del fichero | Nombre en el informe |
| `template` | — (obligatoria) | Plantilla o manifiesto de taxonomía (ruta relativa al `.toml` o absoluta) |
| `threshold` | `0.5` | Umbral de las reglas |
| `ai_scope` | `"off"` | `"unclassified"` o `"missing_axes"` para usar la IA (necesita LiteLLM en el entorno) |
| `ai_all` | `false` | IA sobre **todos** los documentos de la referencia (`ai_scope="all"`, 2.7.0; aborta si la IA no los vio todos) |
| `ai_all_legacy` | `false` | Lo mismo con el truco de 2.6.0 (umbral 1,01 y `ai_scope="unclassified"`), para comparar con mediciones anteriores |
| `classify_model` | entorno | Alias de LiteLLM para `classify` |
| `ai_cache` | `false` | Usar la caché de resultados de IA |
| `semantic`, `semantic_threshold` | `false`, librería | Fase semántica |
| `decisions` | `false` | Aplicar las decisiones de personas (falsea la medición si la referencia sale de ellas) |
| `ablation` | ninguna | Una o varias de `whole_word`, `no_divide`, `head_only`, `tie_abstain` (abajo) |
| `no_divide_k` | `2.0` | Con `no_divide`, nota = min(1, términos encontrados / k) |

## Ablaciones de v1

Cada una cambia **un** defecto de `score_catalog` (análisis §4.1) solo dentro del proceso del script:

| Ablación | Cambio |
|---|---|
| `whole_word` | Palabra o frase completa en vez de subcadena («ley» ya no encaja en «leyenda») |
| `no_divide` | La nota no se divide por el número de palabras clave |
| `head_only` | Solo título y comienzo (6000 caracteres), como los ejes que etiquetan |
| `tie_abstain` | En empate se abstiene (`sin-clasificar`) en vez de ganar la primera entrada del catálogo |

Una ablación por ejecución; combinarlas (`ablation = ["whole_word", "no_divide"]`) solo para confirmar.
