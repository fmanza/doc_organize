# SPIKE — Zensical para el sitio sin conexión (F3, hito M0 del plan único 2.0.0)

Fecha: 2026-11-18. Zensical **0.1.1** (`zensical-ui`), Windows 11, Python 3.14. Script reproducible:
[`spike_zensical_offline.py`](spike_zensical_offline.py) (sin red; sitio sintético en una carpeta temporal).

## Resultados

| Pregunta | Resultado | Consecuencia para F3 |
|---|---|---|
| ¿`offline` se declara en `zensical.toml`? | **Sí**: `[project.plugins.offline]`. Fuerza `use_directory_urls = false` y genera `search.js` (índice en JS para `file://`) además de `search.json` | Sin spike adicional: `SiteGenerator.generate(offline=True)` escribe ese bloque |
| ¿Quedan terceros en el HTML? | Sin shim local, el plugin añade `https://unpkg.com/iframe-worker/shim`. **Con un polyfill local cuya ruta contenga `iframe-worker`, no lo añade** (comprobado: `extra.polyfills = ["assets/vendor/iframe-worker/shim.js"]`) | Empaquetar el shim (como doc_ia, `iframe-worker-shim-1.0.4`) y declararlo en `extra.polyfills` |
| ¿Terceros en el JS del tema? | `bundle.*.min.js` carga **bajo demanda** desde unpkg.com: `resize-observer-polyfill` (solo navegadores sin `ResizeObserver`), `ace-builds` y Mermaid (si una página tiene un bloque `mermaid`) | Mermaid empaquetado (plan) y CSP que bloquee el resto; sin red, un bloque Mermaid sin Mermaid local no se pinta |
| ¿CSP en `<meta>`? | **Sí**: `theme.custom_dir` con `main.html` que extiende `base.html` y rellena el bloque `extrahead`; la `<meta http-equiv="Content-Security-Policy">` sale en todas las páginas | D6(b) es viable en la plantilla. **Falta** comprobar en Edge, Chrome y Firefox con `file://` que tema y búsqueda funcionan con ella (el tema usa scripts en línea: hace falta `'unsafe-inline'` en `script-src`, lo que resta valor a la CSP frente al HTML incrustado) |
| ¿Build reproducible? | **Sí**: dos builds seguidos dan el mismo `site/` (hash de rutas y contenidos), con 50 y con 2600 páginas | El ZIP puede ser reproducible (orden y fechas fijas al empaquetar) |
| ¿HTML hostil? | `<script>`, `onerror=`, `href="javascript:"` e imágenes remotas llegan **tal cual** al HTML | Confirma D6(a): neutralizar la copia es imprescindible (la CSP con `'unsafe-inline'` no frena un `<script>` en línea) |
| Enlaces a carpetas | Ninguno interno con `offline` (el único `…/` es `https://zensical.org/` del pie) | La comprobación `check_site_offline` debe ignorar enlaces externos |

## Tamaño: hallazgo que afecta también al sitio actual

| Sitio sintético (400 palabras por página) | Sin `navigation.prune` | Con `navigation.prune` |
|---|---|---|
| 1000 páginas en **una** sección | 303 MB (292 KB/página) | 302 MB (igual: toda la sección es visible) |
| 2600 páginas en **20 dominios × 130** | **1960 MB** (744 KB/página), build 31 s | **173 MB** (57 KB/página), build 26 s |

Cada página lleva el **`nav` entero**: el tamaño crece con el cuadrado del número de documentos. El índice de búsqueda es
lo de menos (11,5 MB `search.js` + 11,5 MB `search.json` con 2600 páginas).

- **Afecta a `SiteGenerator` hoy** (no solo a F3): un contexto de ~2600 documentos genera un `site/` de ~2 GB en el
  destino. `features = ["navigation.prune"]` lo reduce ~11× con la estructura por dominios.
- **Propuesta**: añadir `navigation.prune` a la configuración generada **ya** (cambio pequeño; ¿PATCH 1.7.1?) y, en
  F3, tenerlo siempre. Con un dominio muy grande (todos sus documentos son visibles), prune no basta: valorar
  subsecciones (por tipo de material ya existen con manifiesto) o un tope de documentos por sección.

## Pendiente (no se puede en este equipo sin el corpus o sin navegador)

- HTML que emite docling en un corpus real (¿hace falta lista blanca de etiquetas en D6 a?): con CALIDAD_VD.
- CSP en `file://` con los tres navegadores (D6 b).
- Tamaño del ZIP comprimido con un corpus real.
