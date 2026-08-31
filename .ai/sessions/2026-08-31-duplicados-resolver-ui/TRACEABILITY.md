# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-08-31
- **Tipo**: `hotfix` (mensaje engañoso en "Revisar Duplicados") seguido de `feature`
  (PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION) sobre esa página, extendida
  después con el mismo ciclo completo sobre la página "Caché"
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA

## Objetivo
El usuario reportó que la página web "Revisar Duplicados" mostraba "No se detectaron
duplicados" aunque sabía que había archivos duplicados. Tras diagnosticar la causa raíz,
se pidió además mejorar la visualización de esa página (ruta, listado completo, buscador),
y finalmente — tras un segundo reporte de "no se muestran los duplicados" — se aclaró
explícitamente el requisito real: los archivos duplicados deben verse en la página
**independientemente de que el re-escaneo en vivo encuentre algo pendiente o no**. Una
vez cerrada esa mejora, el usuario pidió aplicar la misma mejora de visualización
(buscador + separación carpeta/archivo) a la página "Caché".

## Cambios Ejecutados

### ✅ 1. HOTFIX — diagnóstico de "No se detectaron duplicados" siendo falso
**Archivo(s)**: `src/doc_organize/web/routes/duplicates.py`,
`src/doc_organize/web/templates/duplicates_resolver.html.j2`,
`tests/unit/test_web_duplicates.py`.
**Descripción**: causa raíz confirmada con el usuario (no asumida): al marcar
"Deduplicar" en la pantalla de Escaneo, `ScanCommand._deduplicate()` ya detecta Y mueve
los duplicados a `duplicados/` **durante el propio escaneo**. La página "Revisar
Duplicados" hace un re-escaneo en vivo de las mismas carpetas de origen — por eso no
encontraba nada, no porque no hubiera habido duplicados. Se añadió
`_load_last_dedup_report()`, que lee `duplicados/DEDUP_REPORT.json` cuando el
re-escaneo en vivo no encuentra grupos pendientes, y la plantilla explica lo ocurrido en
vez de decir simplemente "no se detectaron".
**Status**: ✅ cubierto por test (`test_duplicates_page_explains_already_resolved_by_scan_dedup`).

### ✅ 2. PLAN + AUDIT_PLAN — mejora de visualización
**Descripción**: alcance acordado con el usuario vía preguntas cerradas antes de
escribir código: filtro de búsqueda 100% cliente (sin round-trip), un texto no
coincidente oculta el `<fieldset>` del grupo completo, y la "ruta" se mantiene como
`full_path` completo (solo con mejor maquetación), no separada en columnas. Veredicto:
`GO`, sin condiciones bloqueantes salvo vigilar que el filtro use `hidden` y no
`disabled` (para no perder la selección del formulario al enviar).
**Status**: ✅ sin cambios de código en esta fase.

### ✅ 3. IMPLEMENT — tabla, carpeta/tamaño legible y buscador
**Archivo(s)**: `src/doc_organize/web/routes/duplicates.py` (filtros Jinja nuevos
`file_size`/`dirname`, sin tocar ningún modelo Pydantic ni contrato de rutas),
`src/doc_organize/web/templates/duplicates_resolver.html.j2` (tabla por grupo con
columnas Archivo/Carpeta/Tamaño, badge "conservado por defecto", buscador
`#duplicates-search` + mensaje "sin resultados"), `tests/unit/test_web_duplicates.py`
(tests nuevos).
**Status**: ✅ verificado además con una comprobación visual en navegador real
(Playwright headless): filtrado en vivo, sin errores de consola, sin problemas de
layout.

### ✅ 4. AUDIT_CODE
**Descripción**: revisión de todo lo tocado en la sesión. Encontrado y corregido:
(a) `_load_last_dedup_report()` podía lanzar una excepción sin capturar
(`json.JSONDecodeError`/`pydantic.ValidationError`) si `DEDUP_REPORT.json` estaba
truncado/corrupto, dejando la página con un 500 permanente — se envolvió en
`try/except`, degradando a `None`; (b) dos aserciones de test demasiado laxas
(coincidencia de dígitos sueltos "1"/"2" que casualmente aparecían en el timestamp de
prueba) se sustituyeron por aserciones ancladas al texto real. Encontrado y **no
corregido en esta sesión** (fuera de alcance, ver Riesgos Residuales): el autoescape de
Jinja2 está desactivado en **todas** las plantillas `.html.j2` del proyecto, no solo en
esta.
**Status**: ✅ ambos ajustes aplicados y verificados (ver Verificación).

### ✅ 5. IMPLEMENT (extensión) — "Duplicados ya resueltos" siempre visibles
**Archivo(s)**: mismos tres ficheros que el punto 3.
**Descripción**: el usuario reportó de nuevo "no se muestran los duplicados" tras el
punto 4; probado con un proyecto de ejemplo, la página funcionaba para el caso básico,
así que se preguntó el escenario exacto en vez de asumir una regresión — confirmó el
mismo caso de "Deduplicar" activado, pero esta vez pidió explícitamente que el detalle
de los archivos se vea siempre, no solo un resumen en texto. Se añadió una sección de
solo lectura ("Duplicados ya resueltos", sin `<form>` ni radios) que lista cada grupo de
`last_dedup_report.groups`, marcando "Conservado en su carpeta" vs. "Movido a
duplicados/". El buscador ahora filtra `document.querySelectorAll("fieldset[data-search]")`
(antes solo `form.querySelectorAll(...)`), cubriendo ambas secciones a la vez.
**Status**: ✅ cubierto por test nuevo
(`test_duplicates_page_shows_resolved_groups_detail_from_last_scan_dedup`) y verificado
manualmente sirviendo la página real con ambas secciones (pendientes + ya resueltos)
presentes a la vez.

### ✅ 6. VERSION (parcial, solo Duplicados)
**Archivo(s)**: `CHANGELOG.md`, `pyproject.toml`, este fichero.
**Descripción**: bump `MINOR` (0.2.0 → 0.3.0) — nueva capacidad observable para el
usuario final (buscador, listado de ya-resueltos) aunque no cambia ninguna API pública
de Python. Sin cambios en `docs/` (no se añadió ni movió ningún módulo/clase pública;
`docs/functional/dedup.md` documenta `DeduplicationManager`, que no se tocó) — verificado
con `mkdocs build --strict` limpio antes y después.
**Status**: ✅.

### ✅ 7. PLAN + AUDIT_PLAN + IMPLEMENT + AUDIT_CODE — misma mejora en "Caché"
**Archivo(s)**: `src/doc_organize/web/routes/cache.py` (filtros Jinja `dirname`/
`basename` nuevos — `CacheEntry` no tiene `display_name` como `DocumentMetadata`, así
que `basename` se dedujo aparte), `src/doc_organize/web/templates/cache_viewer.html.j2`
(columnas Archivo/Carpeta separadas, buscador `#cache-search`, contador dinámico
"X de Y entradas."), `tests/unit/test_web_cache.py` (tests nuevos).
**Descripción**: PLAN/AUDIT_PLAN sin ambigüedades nuevas que preguntar — todas las
decisiones de UX ya estaban fijadas por precedente directo de la sesión de Duplicados
(filtro 100% cliente, sin round-trip), y la tabla de Caché es más simple (sin grupos ni
formulario/radios), lo que elimina la única fuente real de ambigüedad de la vez
anterior: al filtrar se oculta la `<tr>` directamente, no hay que decidir "ocultar el
grupo completo o atenuar filas sueltas". AUDIT_CODE encontró un `id="cache-count"`
añadido sin conectar a nada (deuda técnica introducida en el propio IMPLEMENT, no
heredada) — el usuario decidió conectarlo (mostrar "X de Y entradas." al filtrar) en vez
de quitarlo; aplicado y verificado.
**Status**: ✅ cubierto por tests nuevos y por **dos** verificaciones visuales en
navegador real (Playwright headless): una del filtrado en sí (oculta `<tr>` sin romper
la alineación de columnas de la tabla, a diferencia del `<fieldset>` de Duplicados) y
una segunda, tras el fix del contador, confirmando los tres estados
("2 entradas." / "1 de 2 entradas." / "0 de 2 entradas.").

### ✅ 8. VERSION (Caché añadido al mismo 0.3.0 sin publicar)
**Archivo(s)**: `CHANGELOG.md`, este fichero.
**Descripción**: como 0.3.0 seguía sin commitear/publicar cuando se pidió esta
extensión, se añadió como un bullet más bajo el `### Added` del mismo
`## [0.3.0] - 2026-08-31` ya existente, en vez de abrir un `0.4.0` nuevo — una versión
no debe consumirse dos veces para trabajo que todavía no se ha liberado. `pyproject.toml`
se queda en `0.3.0` (sin cambios en este punto).
**Status**: ✅.

---

## Impacto

### Código
- **Archivos modificados**: `src/doc_organize/web/routes/duplicates.py`,
  `src/doc_organize/web/templates/duplicates_resolver.html.j2`,
  `tests/unit/test_web_duplicates.py`, `src/doc_organize/web/routes/cache.py`,
  `src/doc_organize/web/templates/cache_viewer.html.j2`, `tests/unit/test_web_cache.py`,
  `CHANGELOG.md`, `pyproject.toml`.
- **Cambios funcionales**: sí, en las páginas web "Revisar Duplicados" y "Caché" — cero
  cambios en modelos Pydantic, en `DeduplicationManager`/`ScanCommand`/`CacheManager`, o
  en los contratos JSON de `GET`/`POST /api/projects/{name}/duplicates...` ni
  `GET /api/projects/{name}/cache`.

### Compatibilidad
- **BREAKING**: ninguno.
- **NO BREAKING**: toda la API JSON y el CLI quedan intactos; el único fichero nuevo que
  se **lee** (no se escribe) desde `duplicates.py` es `duplicados/DEDUP_REPORT.json`, que
  ya existía desde antes (lo escribe `DeduplicationManager.resolve_duplicates()`).

---

## Verificación
```
python -m ruff check src/doc_organize/web/routes/duplicates.py src/doc_organize/web/routes/cache.py tests/unit/test_web_duplicates.py tests/unit/test_web_cache.py
  → All checks passed!
python -m mypy src/doc_organize/web/routes/duplicates.py src/doc_organize/web/routes/cache.py
  → Success: no issues found in 2 source files
python -m pytest tests/unit/test_web_duplicates.py tests/unit/test_web_cache.py -q
  → 20 passed (13 + 7), 100% cobertura en ambos módulos de ruta
python -m pytest -q
  → 277 passed, 96% cobertura total
python -m mkdocs build --strict
  → Documentation built, sin warnings de links/anchors rotos
```
Además: **tres** comprobaciones visuales en navegador real (Playwright headless) — el
buscador de Duplicados filtrando en vivo; el de Caché ocultando `<tr>` sin romper la
tabla; y una tercera tras el fix del contador de Caché confirmando sus tres estados
("2 entradas." / "1 de 2 entradas." / "0 de 2 entradas."). También smoke test manual
sirviendo la app real con un proyecto que tenía simultáneamente grupos de Duplicados
pendientes y un `DEDUP_REPORT.json` de un escaneo previo, para confirmar que ambas
secciones conviven correctamente.

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Autoescape de Jinja2 desactivado en **todas** las plantillas `.html.j2` del proyecto (`jinja2.select_autoescape()` decide por el sufijo literal del nombre de plantilla; `"algo.html.j2"` no termina en `.html` y por tanto no se escapa) — confirmado empíricamente. Riesgo de XSS almacenado vía nombre de archivo malicioso en Linux/macOS (Windows lo mitiga porque `< > "` son inválidos en nombres de archivo). El cambio de Caché de esta sesión amplía la misma superficie ya conocida: `entry.file_path` ahora también se interpola en `data-search`/`title`, dos sitios nuevos que no existían en la versión anterior de esa página | No corregido en esta sesión (afecta a todas las plantillas de `web/`, no solo a Duplicados/Caché — fuera de alcance de una feature sin refactor). Requiere un `/security-review` o `/hotfix` dedicado que fuerce `autoescape=True` explícito en cada `Jinja2Templates(...)` del proyecto, o renombrar las plantillas a `.html` puro | **Pendiente — recomendado como próxima sesión** |
| `DEDUP_REPORT.json` se escribe con `write_text` directo (sin patrón escribir-a-temporal-y-renombrar) | Mitigado en esta sesión solo del lado lectura (`_load_last_dedup_report` degrada a `None` si el JSON es inválido); la escritura sigue siendo no-atómica en `DeduplicationManager.resolve_duplicates()` | Mitigado parcialmente (lectura robusta; escritura sin cambios) |

---

## Siguientes Pasos (Recomendado)
1. Abrir una sesión de `/security-review` o `/hotfix` dedicada al autoescape de Jinja2
   desactivado app-wide (ver Riesgos Residuales) — es el hallazgo más importante de esta
   sesión y no se corrigió por estar fuera del alcance de "nueva funcionalidad sin
   refactor". Cubre tanto Duplicados como Caché (y el resto de `web/`).
2. Si se quiere robustecer más la escritura de `DEDUP_REPORT.json`, aplicar un patrón
   escribir-a-temporal-y-renombrar en `DeduplicationManager.resolve_duplicates()`
   (Level 2) — no se tocó en esta sesión por no ser el foco pedido.
3. Si aparece una tercera página con la misma necesidad de "carpeta + nombre de archivo
   separados", extraer `dirname`/`basename` a un módulo compartido (regla de tres) — hoy
   están deliberadamente duplicados en `duplicates.py` y `cache.py`, consistente con que
   cada ruta ya tiene su propia instancia `Jinja2Templates` autocontenida.
4. Confirmar con el usuario si procede el commit de esta sesión (mensaje sugerido más
   abajo) — no se ejecutó `git commit` todavía.

---

## Directrices para Futuras IAs

- **[Autoescape de Jinja2 desactivado en todo `web/`]**: `jinja2.select_autoescape()` se
  invoca sin argumentos en `starlette.templating.Jinja2Templates.__init__`, y decide
  escapar o no **según si el nombre de la plantilla termina literalmente en `.html`**
  (`endswith`, no `splitext`). Como este proyecto usa la extensión `.html.j2` para todas
  sus plantillas (adoptada en `d468507`), **ninguna plantilla de la app escapa HTML por
  defecto** — verificado con `jinja2.select_autoescape()('x.html.j2') == False` vs.
  `('x.html') == True`. Cualquier variable interpolada que pueda contener texto no
  controlado por el propio servidor (nombres de archivo escaneados, rutas, etc.) es un
  vector de XSS potencial en Linux/macOS. No asumir que Jinja2Templates escapa por
  defecto en este proyecto — hay que verificarlo explícitamente o forzar
  `autoescape=True`.
- **[`_group_key()` es estable entre peticiones, `group_id` no]**: `DuplicateGroup.group_id`
  es un `uuid4` nuevo en cada llamada a `find_duplicates()`. La correlación entre el
  `GET` inicial (que pinta el formulario) y el `POST /resolve` (que vuelve a escanear)
  se hace con `_group_key()` (sha256 de las rutas ordenadas), no con `group_id`. Esto ya
  existía antes de esta sesión, mantenido sin cambios.
- **[Duplicados "pendientes" vs. "ya resueltos" son fuentes de datos distintas]**: la
  página `/projects/{name}/duplicates` combina dos fuentes independientes:
  `_detect_duplicates()` (re-escaneo en vivo de `folders.json`, siempre al día) y
  `_load_last_dedup_report()` (snapshot de `duplicados/DEDUP_REPORT.json`, el estado en
  el momento del último escaneo con "Deduplicar" o de la última resolución manual vía
  `POST /resolve` — puede quedar desactualizado si se borra o mueve algo a mano en
  `duplicados/`). No colapsar ambas fuentes en una sola lista: la primera necesita
  formulario interactivo (aún se puede elegir qué conservar), la segunda es solo
  lectura (ya no hay nada que elegir).
- **[El filtro de búsqueda de Duplicados debe usar `hidden`, nunca `disabled`]**: en
  `duplicates_resolver.html.j2`, el filtro cliente oculta `<fieldset data-search="...">`
  completos con `fieldset.hidden = true`. Si algún cambio futuro lo reemplaza por
  `disabled` en los `<input type="radio">`, `FormData` dejaría de incluir la selección
  de un grupo filtrado al hacer submit — regresión silenciosa, sin error visible.
- **[`_format_file_size`/`_dirname` son filtros Jinja de presentación, no tocar
  `DocumentMetadata`]**: registrados en `web/routes/duplicates.py` vía
  `_templates.env.filters[...]`. Deliberadamente no se añadió ningún campo formateado a
  `DocumentMetadata` ni a `DuplicateGroup` (modelos Pydantic compartidos con la API
  JSON) — la presentación vive solo en la plantilla, para no acoplar el formato visual
  al contrato de datos.
- **[Cada ruta web tiene su propia instancia `Jinja2Templates`, sin filtros
  compartidos]**: `duplicates.py` y `cache.py` declaran cada uno su propio
  `_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))` apuntando al mismo
  directorio físico, pero son objetos `Environment` distintos — un filtro registrado en
  `duplicates.py` (`_templates.env.filters[...]`) **no** está disponible en las
  plantillas renderizadas por `cache.py`, y viceversa. Por eso `cache.py` declara su
  propio `_dirname` (y un `_basename` nuevo, porque `CacheEntry` no tiene
  `display_name` como `DocumentMetadata`) en vez de importar el de `duplicates.py`. Es
  el patrón ya existente en el proyecto, no una duplicación introducida por descuido.
- **[El filtro de búsqueda de Caché oculta `<tr>` directamente, no un contenedor]**: a
  diferencia de Duplicados (que oculta el `<fieldset>` de un grupo completo porque hay
  un formulario con radios cuyo contexto no se puede romper), la tabla de Caché es
  plana y de solo lectura — cada fila se oculta de forma independiente
  (`row.hidden = true`), sin necesidad de preservar ningún grupo. Verificado que ocultar
  `<tr>` no rompe la alineación de columnas de la tabla (el `<thead>` no se ve afectado).
- **[El contador "X de Y entradas." de Caché es responsabilidad del propio JS del
  filtro, no de la plantilla]**: `cache_viewer.html.j2` renderiza el texto inicial
  ("N entradas.") en Jinja, pero es el listener de `#cache-search` el que lo reescribe
  en cada tecla. Si se añade un filtro nuevo a esta página, hay que actualizar ese mismo
  bloque de JS (`countEl.textContent = ...`), no solo el bucle de `hidden`.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ Causa raíz del reporte original confirmada con el usuario antes de corregir, no
  asumida (dos veces: el hotfix inicial y la aclaración de alcance posterior)
- ✅ PLAN/AUDIT_PLAN con ambigüedades resueltas explícitamente por el usuario antes de
  escribir código, en ambas páginas (Duplicados y Caché)
- ✅ AUDIT_CODE encontró y corrigió problemas reales en ambas rondas: crash por JSON
  corrupto y aserciones de test débiles (Duplicados); `id` sin conectar en el contador
  (Caché, resuelto según preferencia explícita del usuario). El hallazgo de seguridad
  fuera de alcance (autoescape) quedó documentado, no ignorado, en ambas páginas
- ✅ `ruff`, `mypy`, `pytest` (277 passed), `mkdocs build --strict` — todos en verde
- ✅ Verificación visual real (Playwright, 3 pasadas) además de tests automatizados
- ✅ CHANGELOG.md sincronizado — ambas mejoras conviven en el mismo `## [0.3.0]` sin
  publicar; `pyproject.toml` en `0.3.0`
- ⬜ Commit: pendiente de confirmación explícita del usuario

**Evidencia**:
- Branch: `develop`
- Commits: ninguno todavía (working tree con cambios sin confirmar)
- Tests: 277 passed, 96% cobertura total, 100% en `web/routes/duplicates.py` y
  `web/routes/cache.py`

**Sesión cerrada**: 2026-08-31
