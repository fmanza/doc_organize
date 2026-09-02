# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-02
- **Tipo**: `feature` (ciclo `/new-feature`: PLAN → AUDIT_PLAN → IMPLEMENT; AUDIT_CODE
  cubierto vía `ruff`/pytest + verificación manual en navegador real, sin hallazgos)
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (implementación y tests en verde; commit pendiente de
  confirmación del usuario, ver "Siguientes Pasos")

## Objetivo
El usuario pidió replicar en la pestaña "Duplicados" el mismo patrón visual que ya
existe en "Escanear": semáforo de estado (Inicio/Ejecución/Finalización/Error),
bloqueo de la pestaña "Histórico de deduplicaciones" y bloqueo del botón "Buscar
duplicados" mientras la operación está en curso. Pidió explícitamente generar solo
las fases PLAN y AUDIT_PLAN primero; tras resolver 3 decisiones abiertas vía
`AskUserQuestion`, autorizó continuar a IMPLEMENT.

## Cambios Ejecutados

### ✅ 1. PLAN — investigación del patrón existente
**Descripción**: agente `Explore` en background localizó el patrón completo de
Escanear en `folder_selector.html.j2` (markup `#scan-semaforo`, constantes
`SCAN_PHASE`, `lockCacheTab`/`unlockCacheTab`, wiring sobre el WebSocket de
escaneo) y el estado de partida de `duplicates_resolver.html.j2` (sin semáforo,
`deduplicateBtn` hacía `window.location.reload()` en éxito, sin bloqueo cruzado
con `resolve-form`). También confirmó la política de JS inline del proyecto
(`.github/SHARED_INSTRUCTIONS.md`: sin bundler, constantes solo a partir de 3+
usos) y que `/scan/deduplicate` es un POST síncrono sin eventos intermedios (a
diferencia del WebSocket de escaneo).
**Status**: ✅ alcance acotado a un único fichero de producción.

### ✅ 2. AUDIT_PLAN — 3 decisiones abiertas resueltas por el usuario
**Descripción**: planteadas vía `AskUserQuestion`:
- Semáforo de 4 fases (igual que Escanear) — aceptando que `RUNNING` se marca de
  forma optimista porque el POST de dedup no emite un evento intermedio real.
- Sustituir `window.location.reload()` por una actualización in-place, para que
  la luz verde ("Finalización") no se pierda en una navegación.
- Incluir bloqueo cruzado entre "Buscar duplicados" (acción masiva) y el
  `resolve-form` (resolución individual por grupo).
**Status**: ✅ veredicto GO con las 3 condiciones resueltas explícitamente.

### ✅ 3. IMPLEMENT
**Archivo(s)**:
- `src/doc_organize/web/templates/duplicates_resolver.html.j2` — único fichero de
  producción modificado:
  - `tab-btn-history` con clases Tailwind `disabled:*` (igual que `tab-btn-cache`
    en Escanear).
  - Markup nuevo `#dedup-semaforo` (3 luces + texto de estado), calcado de
    `#scan-semaforo`.
  - Nuevo contenedor `#resolve-results-container` envolviendo "Resultado de los
    duplicados", para poder refrescarlo sin tocar el botón/semáforo que quedan
    fuera de él.
  - JS: `DEDUP_PHASE`, `paintLight()`/`resetDedupSemaforo()`/`setDedupSemaforo()`
    (adaptación 1:1 del patrón de Escanear); `lockDedupControls()`/
    `unlockDedupControls()` con flag compartido `dedupOperationInProgress` que
    bloquea a la vez `tab-btn-history`, `deduplicateBtn` y el submit de
    `resolve-form`; `extractElementHtml()`/`refreshDynamicPanels()` (fetch +
    `DOMParser`, sin `reload()`) que sustituye el `innerHTML` de
    `#resolve-results-container` y `#tab-panel-history` tras cada operación;
    `setupResolveForm()`/`setupHistorySearch()` convertidas de bloques
    ejecutados una vez a funciones nombradas re-invocables tras cada refresco
    parcial (los listeners del DOM sustituido se pierden con los nodos).
- `tests/unit/test_web_duplicates.py` — 3 tests nuevos, server-rendered
  únicamente (política del proyecto: sin infraestructura de test JS):
  markup del semáforo presente, clases `disabled:*` en `tab-btn-history`,
  `#resolve-results-container` envolviendo el resultado.
**Status**: ✅ sin cambios de backend — el POST `/scan/deduplicate` y
`/duplicates/resolve` existentes cubrían todo lo necesario.

### ✅ 4. Verificación manual en navegador real
**Descripción**: `chromium-cli` no está disponible en este entorno Windows; se
usó Playwright Python (ya instalado en el entorno) contra un servidor local real
(`python -m doc_organize web`, tenant+usuario admin provisionados, proyecto con 2
ficheros duplicados). Confirmado: el semáforo llega a verde "Finalización" sin
recargar la página (URL sin cambios), la pestaña "Histórico" y el botón "Buscar
duplicados" se bloquean durante la operación y se reactivan al terminar, tanto
"Resultado de los duplicados" como "Histórico de deduplicaciones" se actualizan
in-place, y 0 errores de consola JS.
**Status**: ✅ confirmado visualmente (capturas en scratchpad de sesión, no
versionadas).

---

## Impacto

### Código
- **Archivos modificados**: `src/doc_organize/web/templates/duplicates_resolver.html.j2`,
  `tests/unit/test_web_duplicates.py`.
- **Cambios funcionales**: sí, pero solo de UI/JS de cliente; no cambia la API
  pública de Python ni el protocolo de los endpoints existentes (mismo
  `POST /api/projects/{name}/scan/deduplicate` y
  `POST /api/projects/{name}/duplicates/resolve` de antes).

### Compatibilidad
- **BREAKING**: ninguno.
- **NO BREAKING**: cambio aditivo de plantilla; ningún `id` ni contrato existente
  se eliminó o renombró (`deduplicateBtn` sigue disparando el mismo POST, solo se
  le añaden fases visuales al flujo).

---

## Verificación
```
python -m ruff check src tests                                        → sin salida (limpio)
python -m pytest tests/unit/test_web_duplicates.py -q                 → 25 passed
python -m pytest tests/unit/test_web_scan.py tests/unit/test_web_duplicates.py -q → 62 passed
Verificación manual en navegador (Playwright) contra servidor real     → 0 errores de consola
```
No se relanzó `mypy` ni la suite completa por ser un cambio exclusivo de
plantilla Jinja2/JS + tests del módulo `web/duplicates`; el fichero de tests
relevante confirma que la plantilla renderiza sin errores de Jinja2.

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| `RUNNING` se marca de forma optimista (el POST de dedup no emite ningún evento intermedio real, a diferencia del WebSocket de escaneo) | Decisión explícita del usuario vía `AskUserQuestion`, aceptando el patrón visual aunque no refleje un evento de servidor | Aceptado, no mitigado |
| JS casi idéntico duplicado entre `folder_selector.html.j2` y `duplicates_resolver.html.j2` (`paintLight`, semáforo, lock/unlock) | Aceptado por política del proyecto (JS inline sin bundler/módulos compartidos entre plantillas, ver `SHARED_INSTRUCTIONS.md`) | Aceptado, no mitigado |
| `refreshDynamicPanels()` depende de que los ids `resolve-results-container`/`tab-panel-history` coincidan entre el HTML recién fetcheado y el DOM vivo | Acoplamiento interno al mismo fichero; documentado con comentario en el JS | Aceptado, riesgo bajo |

---

## Siguientes Pasos (Recomendado)
1. Confirmar con el usuario el mensaje de commit preparado en la respuesta del
   turno y ejecutar `git add`/`git commit` — el usuario pidió expresamente "solo
   mensaje", `git commit` no se ha ejecutado.
2. **Hay otros cambios sin commitear en el árbol de trabajo, ajenos a esta
   sesión** (`cache_manager.py`, `core/models.py`, `scan_command.py`,
   `web/routes/cache.py`, `folder_selector.html.j2`, `test_cache_manager.py`,
   `test_web_scan.py`) — pertenecen a sesiones previas (semáforo de Escanear,
   forzar rescan completo) y deberían revisarse/commitearse por separado, no
   mezclarse con el commit de esta sesión.
3. Si en el futuro `/scan/deduplicate` gana streaming real (WebSocket, como
   Escanear), sustituir la fase `RUNNING` optimista por una señal real del
   servidor.

---

## Directrices para Futuras IAs

- **[Duplicados ya tiene el mismo patrón de semáforo/bloqueo que Escanear, con
  dos diferencias clave]**: `DEDUP_PHASE`/`#dedup-semaforo`/
  `lockDedupControls`/`unlockDedupControls` en `duplicates_resolver.html.j2`
  están calcados de `SCAN_PHASE`/`#scan-semaforo`/`lockCacheTab`/
  `unlockCacheTab` en `folder_selector.html.j2`, pero: (a) usan un flag único
  `dedupOperationInProgress` compartido entre "Buscar duplicados" y
  `resolve-form` (bloqueo cruzado entre dos flujos, no solo uno); (b) `RUNNING`
  se marca de forma optimista justo tras lanzar el `fetch`, no tras un evento
  real del servidor, porque `/scan/deduplicate` es un POST síncrono sin
  streaming.
- **[Patrón de refresco parcial sin `reload()`]**: `refreshDynamicPanels()` en
  `duplicates_resolver.html.j2` hace `fetch(window.location.pathname)` +
  `DOMParser` para extraer el `innerHTML` de `#resolve-results-container` y
  `#tab-panel-history`, y los sustituye en el DOM vivo sin navegar. Tras cada
  sustitución hay que reinvocar `setupResolveForm()`/`setupHistorySearch()`
  (funciones nombradas, no IIFEs) porque los listeners del DOM anterior se
  pierden junto con los nodos reemplazados. Cualquier contenido dinámico nuevo
  dentro de esos contenedores debe seguir este mismo patrón (función `setup*`
  reinvocable) en vez de enlazar listeners una sola vez al cargar la página.
- **[Cómo probar la UI manualmente en este entorno Windows sin `chromium-cli`]**:
  usar Playwright Python (ya instalado). Provisionar con
  `python -m doc_organize tenant create <Nombre>` (crea automáticamente
  `admin`/`admin` con `must_change_password=True` — hay que manejar el
  redirect a `/change-password` en el primer login), `project create` para el
  proyecto, y **`ScannedFoldersStore().add_folder(project, path)`** para la
  carpeta — no basta con escribir `folders.json` a mano, porque el botón
  "Buscar duplicados"/"Escanear" se deshabilita server-side según
  `has_saved_folders`/`folders`, que lee de `scanned_folders.json`
  (`ScannedFoldersStore`), un fichero distinto de `folders.json`.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ Las 3 decisiones de alcance (fases del semáforo, reload vs. in-place,
  bloqueo cruzado) resueltas explícitamente por el usuario vía
  `AskUserQuestion`, no asumidas
- ✅ Cambio aditivo de solo-frontend + tests, sin tocar backend ni romper
  ningún `id`/contrato existente
- ✅ `ruff` limpio; 62 tests en verde (`test_web_scan.py` + `test_web_duplicates.py`)
- ✅ Verificación manual en navegador real (Playwright) sin errores de consola
- ⬜ Commit: pendiente de confirmación explícita del usuario (pidió "solo
  mensaje")

**Evidencia**:
- Branch: `develop`
- Commits: ninguno todavía — cambios en working tree, mensaje preparado en la
  respuesta del turno
- Tests: 62 passed (`test_web_scan.py` + `test_web_duplicates.py`)

**Sesión cerrada**: 2026-09-02
