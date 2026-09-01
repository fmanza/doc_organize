# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-01
- **Tipo**: `refactor` (cuatro ciclos `/refactor` independientes, PLAN → AUDIT_PLAN → IMPLEMENT →
  AUDIT_CODE → VERSION cada uno, pedidos secuencialmente por el usuario sobre la misma área)
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (sin commitear — ver Siguientes Pasos)

## Objetivo
El usuario pidió reestructurar la navegación web del proyecto en cuatro pasos sucesivos:
1. Mover "Carpetas guardadas" de Escanear al Dashboard; convertir Escanear en pestañas
   (Escanear/Caché, eliminando la página Caché independiente) y Duplicados en pestañas (Buscar
   duplicados/Histórico, trasladando "Paso 1: Buscar duplicados" desde Escanear).
2. Mover el buscador de duplicados para que viva dentro de la pestaña "Histórico de
   deduplicaciones" (antes compartido entre las dos pestañas).
3. Reordenar el menú lateral: "Duplicados" antes que "Escanear".
4. Dar a la página "Proyectos" (`GET /`) el mismo buscador server-side + paginación que ya tenía
   la pestaña Caché.

## Cambios Ejecutados

### ✅ 1. IMPLEMENT — Reestructuración de navegación: Dashboard, Escanear (tabs), Duplicados (tabs)
**Archivo(s)**: `web/app.py`, `web/routes/scan.py`, `web/routes/cache.py`, `web/routes/duplicates.py`,
`web/templates/dashboard.html.j2`, `folder_selector.html.j2`, `duplicates_resolver.html.j2`,
`_nav_macros.html.j2`; se elimina `cache_viewer.html.j2`. Tests: `test_web_app.py`,
`test_web_scan.py`, `test_web_cache.py`, `test_web_duplicates.py`.
**Descripción**: "Carpetas guardadas" (HTML+JS de `folder_selector.html.j2`) se traslada tal cual al
Dashboard (`dashboard()` en `app.py` ahora carga `ScannedFoldersStore.list_folders()`). La página
Escanear pasa a tener pestañas nativas (`role="tab"` + paneles `hidden`, sin librería — no existía
ningún patrón de pestañas previo en la app) **Escanear** | **Caché**: la pestaña Caché absorbe
íntegramente la antigua página `GET /projects/{name}/cache` (tabla, búsqueda `?q=`, paginación
`?page=`/`?page_size=`, filtros Jinja `dirname`/`basename`/`highlight`) — `cache.py` queda reducido
solo al endpoint JSON `/api/projects/{name}/cache`. La página Duplicados pasa a tener pestañas
**Buscar duplicados** (botón masivo + resultado + formulario de resolución interactiva, todo
trasladado desde Escanear) | **Histórico de deduplicaciones** (sección ya existente, sin cambios de
lógica). **Decisión confirmada explícitamente por el usuario** (`AskUserQuestion`): el gate "Escanear
deshabilitado hasta ejecutar Buscar duplicados en la misma visita" se elimina — el servidor nunca lo
exigió realmente (era solo un candado de cliente) y ya no tiene sentido con "Buscar duplicados" en
otra página; se sustituye por "deshabilitado si el proyecto no tiene ninguna carpeta guardada", igual
de estricto en ese caso concreto.
**Status**: ✅ 322 tests (tras esta sub-tarea), `ruff`/`mypy`/`mkdocs build --strict` en verde. Docs
actualizadas (`quick_start.md`, `functional/projects.md`, `functional/dedup.md`).

### ✅ 2. IMPLEMENT — Buscador de duplicados dentro de la pestaña Histórico
**Archivo(s)**: `web/templates/duplicates_resolver.html.j2`, `tests/unit/test_web_duplicates.py`.
**Descripción**: el buscador "Buscar por nombre o carpeta" (+ contador + "sin resultados"), antes
compartido encima de las dos pestañas y filtrando tanto grupos pendientes como histórico, se traslada
dentro de la pestaña "Histórico de deduplicaciones" — pasa a filtrar/contar **solo** las ejecuciones
del histórico (`total_resolved_groups`, ya no `(groups | length) + total_resolved_groups`). Se retira
`data-search` de los `<fieldset>` de grupos pendientes (dejaba de usarse) y el JS del filtro se acota
a `#tab-panel-history fieldset[data-search]`.
**Status**: ✅ 22/22 tests de `test_web_duplicates.py`; dos tests preexistentes que asumían el alcance
combinado se reescribieron para reflejar el nuevo alcance (solo histórico) sin perder la cobertura
original (columnas de tabla/tamaño/"conservado por defecto" quedaron en un test separado sin
buscador).

### ✅ 3. IMPLEMENT — Reordenar menú lateral: Duplicados antes que Escanear
**Archivo(s)**: `web/templates/_nav_macros.html.j2`.
**Descripción**: cambio de una línea — la macro `project_nav` renderiza ahora el enlace "Duplicados"
antes que "Escanear". Sin tests dedicados (ninguno dependía del orden de los enlaces); verificado con
la suite completa.
**Status**: ✅ 322/322 tests sin regresión.

### ✅ 4. IMPLEMENT — Proyectos: mismo buscador/paginación que la pestaña Caché
**Archivo(s)**: `web/pagination.py` (nuevo), `web/templating.py`, `web/routes/scan.py`, `web/app.py`,
`web/templates/project_selector.html.j2`, `tests/unit/test_web_app.py`.
**Descripción**: `GET /` gana `q`/`page`/`page_size` (opcionales, con defaults — extensión aditiva,
no breaking) con el mismo patrón que la pestaña Caché: buscador server-side (nombre O ubicación),
selector de tamaño de página, contador "Mostrando X–Y de Z", resaltado `<mark>` y paginación. De
paso, se extrajo a `web/pagination.py` (`paginate()`/`Page`/`PAGE_SIZE_OPTIONS`/`DEFAULT_PAGE_SIZE`)
el cálculo de paginación que estaba duplicado dentro de `scan.py` (se calculaba dos veces el mismo
`total_pages`/rango: una para acotar el `offset` de la consulta a `cache.db`, otra —redundante— para
las variables de plantilla), y se centralizó el filtro Jinja `highlight` en `create_templates()`
(`web/templating.py`) en vez de que cada módulo de rutas lo redefiniera.
**Status**: ✅ 328/328 tests (6 nuevos: caja de búsqueda ausente sin proyectos, búsqueda por
nombre/ubicación con resaltado, paginación y clamp de página fuera de rango).

---

## Impacto

### Código
- **Archivos modificados**: `web/app.py`, `web/routes/cache.py`, `web/routes/duplicates.py`,
  `web/routes/scan.py`, `web/templating.py`, `web/templates/_nav_macros.html.j2`,
  `web/templates/dashboard.html.j2`, `web/templates/duplicates_resolver.html.j2`,
  `web/templates/folder_selector.html.j2`, `web/templates/project_selector.html.j2`,
  `tests/unit/test_web_app.py`, `test_web_cache.py`, `test_web_duplicates.py`, `test_web_scan.py`,
  `docs/functional/dedup.md`, `docs/functional/projects.md`, `docs/guides/quick_start.md`,
  `.ai/product.md` (REQ-007 actualizado a la nueva estructura de páginas).
- **Archivos nuevos**: `web/pagination.py`.
- **Archivos eliminados**: `web/templates/cache_viewer.html.j2`.
- **Cambios funcionales**: sí — reorganización real de navegación (no solo interna): página Caché
  desaparece como URL propia, "Carpetas guardadas" cambia de página, gate de escaneo se elimina,
  buscador de duplicados cambia de alcance, "Proyectos" gana buscador/paginación nuevos. Todos
  pedidos explícitamente por el usuario a través del comando `/refactor` (que en este proyecto
  permite justificar cambios de comportamiento cuando el propio pedido lo exige).

### Compatibilidad
- **BREAKING**: `GET /projects/{name}/cache` (página HTML) desaparece — su contenido vive ahora en
  `GET /projects/{name}/scan?tab=cache`. Sin redirect (decisión deliberada: la página se pidió
  eliminar, no redirigir).
- **NO BREAKING**:
  - Todos los endpoints JSON sin cambios de contrato: `/api/projects/{name}/cache`,
    `/api/projects/{name}/folders/library`, `/api/projects/{name}/scan/deduplicate`,
    `/api/projects/{name}/duplicates`, `/api/projects/{name}/duplicates/resolve`.
  - `GET /` gana `q`/`page`/`page_size` opcionales con defaults — llamadas existentes sin esos
    parámetros siguen funcionando igual.
  - `GET /projects/{name}/scan` gana `tab`/`q`/`page`/`page_size` opcionales, mismo criterio.
  - `GET /projects/{name}/duplicates` gana `tab` opcional, mismo criterio.

---

## Verificación
```
python -m ruff check src tests
  → All checks passed!
python -m mypy src
  → Success: no issues found in 47 source files
python -m pytest -q -m "not slow"
  → 328 passed, 11 deselected (tests @slow, Docling/dedup real — no ejecutados en esta sesión)
python -m mkdocs build --strict
  → Documentation built, sin warnings de links/anchors rotos
```
Verificación adicional: ninguna comprobación visual en navegador real (Playwright) de las pestañas
nuevas en esta sesión — verificado por lectura de código y por la suite HTTP (que no ejecuta JS de
navegador). Mismo riesgo residual ya señalado en la sesión `2026-08-31-flujo-deduplicacion-escaneo`,
que sigue sin cerrarse.

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Sin verificación visual en navegador real de las pestañas nuevas (Escanear/Caché, Buscar duplicados/Histórico) ni de su JS de cambio de pestaña | Solo verificado por lectura de código y tests HTTP (no ejecutan JS) | Pendiente — heredado, ver sesión anterior |
| `GET /projects/{name}/cache` desaparece sin redirect: cualquier bookmark/enlace externo a esa URL exacta pasa a 404 | Decisión deliberada, pedida explícitamente por el usuario ("la página Caché será eliminada") | Aceptado, sin acción pendiente |
| La pestaña Caché de Escanear se renderiza siempre en el servidor (ambas pestañas server-rendered en una sola respuesta) — cada carga de `/projects/{name}/scan` abre `cache.db`, aunque el usuario no toque esa pestaña | Aceptado en el AUDIT_PLAN de la sub-tarea 1: coste bajo esperado, coherente con el resto de la app (todo server-rendered, sin fragmentos AJAX) | Pendiente solo si se detecta un problema real de rendimiento |
| Autoescape de Jinja2 (heredado, documentado en sesión `2026-08-31-duplicados-resolver-ui`) | Sin cambios en esta sesión | Pendiente — recomendado `/security-review` dedicado (ya señalado en sesiones previas) |

---

## Siguientes Pasos (Recomendado)
1. Confirmar con el usuario el commit de los cuatro refactors de esta sesión (mensaje sugerido
   abajo) — no se ha ejecutado `git commit`/`git push` todavía.
2. Opcional: verificación visual en navegador real (Playwright) de las pestañas nuevas y su JS de
   cambio de pestaña (sin recarga de página).
3. Abrir la sesión `/security-review` de autoescape de Jinja2 pendiente desde hace varias sesiones
   (no forma parte del alcance pedido en ninguna de las cuatro sub-tareas de hoy).

---

## Directrices para Futuras IAs

- **["Carpetas guardadas" vive en el Dashboard, no en Escanear"]**: `web/app.py::dashboard()` carga
  `ScannedFoldersStore.list_folders(project)` y `dashboard.html.j2` renderiza la lista + formulario
  de alta/baja + explorador de carpetas del servidor. `folder_selector.html.j2` (página Escanear) ya
  no tiene esa sección — si se necesita mostrar carpetas guardadas en Escanear otra vez, es un cambio
  de diseño explícito a discutir con el usuario, no un descuido a "restaurar".
- **[Escanear = pestañas Escanear/Caché, sin página Caché propia]**: `GET /projects/{name}/scan`
  (`web/routes/scan.py::folder_selector`) renderiza SIEMPRE ambas pestañas en una sola respuesta
  (`tab`/`q`/`page`/`page_size` como query params, `active_tab` decide cuál se ve al cargar). No
  existe ya `GET /projects/{name}/cache` como página — solo queda el JSON
  `GET /api/projects/{name}/cache` en `web/routes/cache.py`. Si se toca la pestaña Caché, los datos
  se cargan vía `_load_cache_page()` en `scan.py`, que usa `web/pagination.py::paginate()`.
- **[Duplicados = pestañas Buscar duplicados/Histórico]**: `web/routes/duplicates.py::duplicates_resolver_page`
  acepta `tab` (`"resolve"` por defecto, `"history"` para enlazar directo a la pestaña histórico). El
  botón masivo "Buscar duplicados" (llama a `POST /api/projects/{name}/scan/deduplicate`, endpoint
  que sigue viviendo en `scan.py` sin cambios) vive ahora en la pestaña "Buscar duplicados" de esta
  página, no en Escanear.
- **[Gate "Escanear bloqueado hasta deduplicar" ELIMINADO — decisión confirmada, no accidental]**: a
  diferencia de la sesión `2026-08-31-flujo-deduplicacion-escaneo` (que lo introdujo deliberadamente
  como guía de UX), esta sesión lo retira también deliberadamente, confirmado con `AskUserQuestion`
  al usuario, porque ya no tenía sentido con "Buscar duplicados" en otra página. `#scan-submit-btn`
  ahora solo se deshabilita si el proyecto no tiene ninguna carpeta guardada
  (`{% if not folders %}disabled{% endif %}`) — no hay ya ningún JS que lo habilite tras un POST.
- **[Buscador de "Duplicados" cubre SOLO el histórico, no los pendientes]**: el `<input
  id="duplicates-search">` vive dentro de `#tab-panel-history` en `duplicates_resolver.html.j2`; su
  JS (`querySelectorAll("#tab-panel-history fieldset[data-search]")`) ya no toca los `<fieldset>` de
  grupos pendientes en `#resolve-form` (que ya ni siquiera llevan `data-search`). Si se pide "que el
  buscador también filtre los pendientes", es una ampliación de alcance a confirmar con el usuario —
  se retiró explícitamente en esta sesión.
- **[`web/pagination.py` es la fuente única de paginación server-side]**: `paginate(total, page,
  page_size) -> Page` (acota `page` a `[1, total_pages]`, nunca produce 404 por navegar fuera de
  rango) y las constantes `PAGE_SIZE_OPTIONS = (25, 50, 100, 200)` / `DEFAULT_PAGE_SIZE = 50`. Usado
  hoy por la pestaña Caché de Escanear (`scan.py::_load_cache_page`, sobre `cache.db` vía SQL) y por
  "Proyectos" (`app.py::project_selector`, filtrado/paginado en memoria sobre la lista de
  `ProjectRegistry`, sin tocar la capa de persistencia). Cualquier página nueva con listados largos
  debería reutilizar esto en vez de reimplementar el cálculo de página/rango a mano.
- **[Filtro Jinja `highlight` centralizado en `create_templates()`]**: `web/templating.py` registra
  `highlight` (envuelve en `<mark>`, escapa con `markupsafe.escape()` antes de recomponer HTML) sobre
  **cada** instancia de `Jinja2Templates` creada por la app — no hace falta volver a registrarlo por
  módulo de rutas. `dirname`/`basename` siguen siendo locales a `scan.py` (solo los usa la pestaña
  Caché); no se centralizaron por no tener un segundo consumidor todavía.
- **["Proyectos" (`GET /`) filtra por nombre O ubicación, en memoria, tras el filtro por rol"]**: en
  `app.py::project_selector`, el orden es: cargar todos los proyectos del tenant → filtrar por
  `allowed_names` si el rol no es admin → **luego** filtrar por `q` → paginar. Si se cambia este
  orden, un usuario con rol restringido podría ver en el contador/paginación proyectos que no le
  pertenecen aunque no aparezcan en la tabla — mantener el filtro de rol siempre antes que `q`.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ Las cuatro sub-tareas pedidas explícitamente por el usuario se implementaron tal cual se
  pidieron, con una aclaración previa (`AskUserQuestion`) solo donde el pedido dejaba una decisión de
  negocio genuinamente abierta (comportamiento del gate de Escanear tras mover "Buscar duplicados").
- ✅ PLAN/AUDIT_PLAN/AUDIT_CODE/VERSION completos para cada una de las cuatro sub-tareas, siguiendo
  el flujo `/refactor` del proyecto.
- ✅ `ruff check`, `mypy`, `pytest` (328 tests, 93% cobertura), `mkdocs build --strict` — todos en
  verde tras cada sub-tarea y de nuevo al cierre de la sesión completa.
- ✅ Docs de `docs/` y `.ai/product.md` actualizadas donde quedaron referencias obsoletas a la
  estructura de páginas anterior (Cache Viewer como página propia, gate de Escanear).
- ⬜ Verificación visual en navegador real (Playwright) de las pestañas nuevas — pendiente, señalado
  como riesgo residual, no bloqueante (mismo estado que sesiones anteriores de UI).
- ⬜ Commit/push: pendientes de confirmación explícita del usuario — ver mensaje sugerido abajo.

**Evidencia**:
- Branch: `develop`
- Commits: ninguno todavía (working tree con cambios sin confirmar — 17 ficheros modificados, 1
  nuevo, 1 eliminado, más este `TRACEABILITY.md`)
- Tests: 328 passed (317 rápidos + 11 lentos deseleccionados con `-m "not slow"`), 93% cobertura total

**Sesión cerrada**: 2026-09-01 21:15 UTC

---

## Commit sugerido (pendiente de confirmación del usuario)

```
refactor: reestructurar navegación web en pestañas (Escanear/Caché, Duplicados/Histórico)

Mueve "Carpetas guardadas" de Escanear al Dashboard del proyecto. La
página Escanear pasa a tener pestañas Escanear/Caché (la página Caché
independiente desaparece, fusionada aquí). La página Duplicados pasa a
tener pestañas Buscar duplicados/Histórico de deduplicaciones,
incorporando el botón masivo "Buscar duplicados" antes en Escanear. El
buscador del histórico de duplicados se acota a esa pestaña. El menú
lateral pasa a mostrar Duplicados antes que Escanear. La página
Proyectos gana buscador server-side + paginación, con el mismo patrón
ya usado en la pestaña Caché (extraído a web/pagination.py, reutilizado
también para eliminar paginación duplicada en scan.py).

El gate "Escanear deshabilitado hasta deduplicar en la misma visita"
se retira (decisión confirmada con el usuario): ya no aplica con
"Buscar duplicados" en otra página; se sustituye por "deshabilitado
sin carpetas guardadas".

BREAKING CHANGE: GET /projects/{name}/cache (página HTML) desaparece,
sin redirect — su contenido vive en GET /projects/{name}/scan?tab=cache.
Los endpoints JSON no cambian.

328 tests passing (ruff/mypy/pytest/mkdocs --strict en verde).
```
