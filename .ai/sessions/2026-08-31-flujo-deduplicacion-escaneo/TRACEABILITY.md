# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-08-31
- **Tipo**: `feature` (PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE, con varias correcciones e
  iteraciones de alcance pedidas explícitamente por el usuario tras la primera implementación)
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA

## Objetivo
El usuario pidió mejorar el proceso de escaneo: separar "buscar duplicados" de "escanear", y que
el escaneo cubra siempre todas las carpetas guardadas del proyecto (no una selección manual). La
primera implementación asumió que la deduplicación debía ser automática e incondicional dentro del
propio escaneo — el usuario corrigió explícitamente: la deduplicación es una acción independiente,
a petición del usuario ("Buscar duplicados"), que bloquea "Escanear" hasta ejecutarse en esa misma
visita a la página; el CLI también necesita poder deduplicar por su cuenta. Además, cada ejecución
de deduplicación debe quedar en una lista incremental consultable (no solo la última). Tras cerrar
esa funcionalidad, una auditoría independiente (`/audit-code`) encontró tres mejoras, dos de las
cuales se aplicaron a petición del usuario en un segundo momento. Finalmente se pidieron tres
ajustes de UI sobre la página "Duplicados": reordenar secciones, mostrar el detalle completo de
archivos de **cada** ejecución del histórico (no solo la última), refrescar la página tras resolver
un conflicto, y convertir cada ejecución del histórico en un bloque colapsable (acordeón).

## Cambios Ejecutados

### ✅ 1. PLAN + AUDIT_PLAN — deduplicación automática dentro del escaneo (primera iteración, corregida después)
**Descripción**: primera interpretación del pedido — deduplicar siempre, sin pedir permiso, dentro
de `ScanCommand.run_streaming()`, y escanear siempre todas las carpetas guardadas. El usuario
corrigió esta interpretación en el punto 3 (ver abajo): la deduplicación debía ser una acción
separada y explícita, no automática dentro del escaneo.
**Status**: ✅ implementado y luego revertido/rediseñado según la corrección del usuario.

### ✅ 2. IMPLEMENT — escaneo siempre sobre todas las carpetas guardadas (se mantiene)
**Archivo(s)**: `src/doc_organize/web/routes/scan.py`, `src/doc_organize/web/templates/folder_selector.html.j2`.
**Descripción**: el WebSocket de escaneo ya no acepta `paths` del cliente — resuelve siempre
`ScannedFoldersStore.list_folders(project)` server-side. Se quitaron los checkboxes por carpeta;
el botón pasa a ser "Escanear todas las carpetas guardadas". `mark_used()` se corrigió para marcar
solo las rutas ya validadas por `FolderValidator` (evita marcar como `used` permanentemente una
carpeta que ya no existe en disco). Esta parte del rediseño **no** se corrigió después — sigue
vigente tal cual.
**Status**: ✅ cubierto por tests, sin cambios en iteraciones posteriores.

### ✅ 3. CORRECCIÓN DEL USUARIO + PLAN + AUDIT_PLAN — deduplicación separada, gateada y con CLI propio
**Descripción**: el usuario corrigió explícitamente la iteración 1 — "Buscar duplicados" debe ser
una acción a petición del usuario, sobre las mismas carpetas que se van a escanear (todas las
guardadas), y "Escanear" debe quedar bloqueado hasta que esa acción se haya ejecutado con éxito en
la misma visita a la página (gate solo de cliente, sin persistencia entre visitas — no es una
barrera de seguridad). Además, el CLI también necesita poder deduplicar de forma independiente.
Preguntas cerradas resueltas con el usuario antes de codificar: alcance de "carpetas
seleccionadas" para deduplicar (= mismo conjunto que escanear, sin checkboxes nuevos), persistencia
del gate (se resetea en cada intento/visita), y forma del histórico (log incremental consultable).
**Veredicto**: GO tras resolver la única condición pendiente (si el CLI necesitaba deduplicar
también — el usuario confirmó que sí).

### ✅ 4. IMPLEMENT — `ScanCommand.deduplicate()` + subcomando CLI + endpoint web
**Archivo(s)**: `src/doc_organize/scan/scan_command.py`, `src/doc_organize/scan/__init__.py`,
`src/doc_organize/main.py`, `src/doc_organize/web/routes/scan.py`,
`src/doc_organize/web/templates/folder_selector.html.j2`, `src/doc_organize/core/models.py`,
`src/doc_organize/core/constants.py`.
**Descripción**: `run()`/`run_streaming()` pierden `deduplicate: bool` y `duplicates_dir: Path` —
dejan de deduplicar. Nuevo método `ScanCommand.deduplicate(paths, duplicates_dir, folders_json)`,
compartido por el CLI (subcomando `deduplicate`, con su propia `_resolve_dedup_paths` — no exige
`--output-dir`/`--cache-file` como sí exige `_resolve_scan_paths`, porque deduplicar no convierte
ni cachea) y la web (`POST /api/projects/{name}/scan/deduplicate`). `folder_selector.html.j2` gana
un botón "Buscar duplicados" (paso 1) y "Escanear" nace `disabled` hasta que el paso 1 responda con
éxito. `ScanEventType.DEDUPLICATED` se eliminó del enum (ya no se emite ningún evento de
deduplicación durante el escaneo). Nueva constante `SCAN_FOLDERS_JSON_NAME` en `core/constants.py`
(evita duplicar el literal `"folders.json"`, aviso de IDE SonarLint S1192).
**Status**: ✅ cubierto por tests nuevos en `test_main.py` (parser + end-to-end del subcomando
`deduplicate`) y `test_web_scan.py` (endpoint `/scan/deduplicate`, incluyendo rechazo sin carpetas
guardadas y fuera de `allowed_scan_roots`).

### ✅ 5. IMPLEMENT — histórico incremental `DEDUP_HISTORY.jsonl`
**Archivo(s)**: `src/doc_organize/dedup/deduplication.py`, `src/doc_organize/web/routes/duplicates.py`,
`src/doc_organize/web/templates/duplicates_resolver.html.j2`.
**Descripción**: `DeduplicationManager.resolve_duplicates()` añade una línea a
`duplicados/DEDUP_HISTORY.jsonl` (JSON Lines, append-only) además de seguir escribiendo
`DEDUP_REPORT.json` (solo el último run). Alimentan el mismo histórico tanto "Buscar duplicados"
como el formulario interactivo de resolución manual. La página "Duplicados" gana una sección
"Histórico de deduplicaciones" que lista todas las ejecuciones, más reciente primero.
**Status**: ✅ cubierto por tests en `test_deduplication.py` (acumulación entre ejecuciones) y
`test_web_duplicates.py` (renderizado del histórico, líneas corruptas se ignoran sin tumbar la
página).

### ✅ 6. AUDIT_CODE (inline, dentro del ciclo PLAN→IMPLEMENT) — hallazgos y correcciones
**Descripción**: revisión de todo lo implementado en los puntos 2, 4 y 5. Encontrado y corregido:
(a) los avisos de `FolderValidator` (carpeta guardada que ya no existe en disco) se perdían en
silencio al quitar el preflight `/folders/validate` del cliente — se añadieron al evento `SCANNED`
del WebSocket, visibles en el cuadro de progreso; (b) `mark_used()` marcaba como usada una carpeta
no validada (ver punto 2).
**Status**: ✅ ambos corregidos y verificados.

### ✅ 7. `/audit-code` (skill dedicado, independiente) — auditoría técnica formal
**Descripción**: auditoría fresca (no reciclando conclusiones previas) de los 8 ficheros
principales tocados. Hallazgos:
- **Performance**: `_load_dedup_history()`/`_load_last_dedup_report()`/`_detect_duplicates()` hacían
  I/O síncrono de fichero dentro de un handler `async` — se agrava con `DEDUP_HISTORY.jsonl`, un
  fichero de crecimiento no acotado. **Aplicado de inmediato**: las tres funciones se invocan ahora
  vía `asyncio.to_thread`.
- **Edge case**: `resolve_duplicates()` escribe `DEDUP_REPORT.json` y `DEDUP_HISTORY.jsonl` en dos
  pasos no atómicos — un crash entre ambos deja "último report" e "histórico" desincronizados.
  **Aplicado después, a petición del usuario**: `_load_last_dedup_report()` se eliminó;
  `last_dedup_report` se deriva ahora de `history[0]` (misma fuente que el histórico, no puede
  desincronizarse consigo misma). `DEDUP_REPORT.json` se sigue escribiendo (contrato externo,
  `audit_json_path` apunta ahí) pero la web ya no lo lee.
- **Edge case**: `ScanCommand.deduplicate()` solo llamaba a `resolve_duplicates()` si había grupos
  — una ejecución de "Buscar duplicados" que no encontraba nada no dejaba rastro en el histórico.
  **Aplicado después, a petición del usuario**: se quitó el guard `if groups:` — toda ejecución
  queda registrada, incluso con cero duplicados.
**Veredicto**: APROBADO CON CONDICIONES → condiciones aplicadas → sesión cerrada en verde.
**Status**: ✅ los tres hallazgos aplicados; tests actualizados (`test_web_duplicates.py`,
`test_main.py`) para reflejar el nuevo comportamiento (histórico completo, sin `DEDUP_REPORT.json`
como fuente de lectura de la página).

### ✅ 8. IMPLEMENT — UI: orden de secciones + fusión "Duplicados ya resueltos" en el histórico
**Archivo(s)**: `src/doc_organize/web/routes/duplicates.py`, `src/doc_organize/web/templates/duplicates_resolver.html.j2`.
**Descripción**: primero se reordenó "Histórico de deduplicaciones" para que apareciera antes que
"Duplicados ya resueltos". Inmediatamente después, el usuario pidió que **cada** ejecución del
histórico mostrara el detalle completo de archivos (conservado/movido) — no solo la última, como
hacía "Duplicados ya resueltos". Se fusionaron ambas secciones: "Duplicados ya resueltos"
desapareció como sección aparte (quedaba redundante), y cada entrada de `history_entries` lleva
ahora su propio `resolved_groups` con el detalle completo. El contador y el buscador se extendieron
para cubrir los grupos de **todas** las ejecuciones (`total_resolved_groups`), no solo la última.
**Status**: ✅ cubierto por tests reescritos/ampliados en `test_web_duplicates.py`.

### ✅ 9. IMPLEMENT — UX: refresco tras resolver + acordeón nativo por ejecución
**Archivo(s)**: `src/doc_organize/web/templates/duplicates_resolver.html.j2`.
**Descripción**: (a) al resolver un conflicto desde el formulario interactivo, la página ahora hace
`window.location.reload()` en el camino de éxito (antes solo mostraba un texto, sin refrescar el
estado de pendientes/histórico) — mismo patrón que `reloadFolderList()` en `folder_selector.html.j2`.
(b) cada ejecución de "Histórico de deduplicaciones" pasa de `<div>` a `<details>`/`<summary>`
(acordeón nativo, sin JS ni librería), colapsado por defecto. El filtro de búsqueda existente se
amplió: una coincidencia dentro de una ejecución colapsada expande automáticamente su `<details>`
cuando hay una búsqueda activa (no se vuelve a colapsar al borrar la búsqueda).
**Status**: ✅ verificado por lectura de código y por la suite HTTP existente (ninguna ejecuta JS de
navegador). **No verificado visualmente en navegador real** (ver Riesgos Residuales).

### ✅ 10. VERSION — bump 0.3.0 → 0.4.0
**Archivo(s)**: `CHANGELOG.md`, `pyproject.toml`, este fichero.
**Descripción**: siguiendo `.github/instructions/sync.instructions.md` (tabla de SemVer: "Breaking
change en API pública → MAJOR"), esta sesión rompe contratos públicos reales (firma de
`ScanCommand`, flags del CLI `scan`, payload del WS de escaneo, enum `ScanEventType`) — la tabla,
tomada al pie de la letra, pediría `1.0.0`. Se preguntó explícitamente al usuario: eligió `0.4.0`,
siguiendo el patrón real ya usado en el proyecto (0.1.0→0.2.0→0.3.0, MINOR incluso con cambios de
comportamiento observable) y la autodescripción "Alpha temprana" del propio proyecto — en 0.x,
cualquier cosa puede cambiar. `CHANGELOG.md` documenta explícitamente el carácter breaking con un
aviso `⚠️` bajo el encabezado de versión, y separa `Added`/`Changed`/`Removed` para que cada
ruptura de contrato sea localizable.

`docs/CHANGELOG.md` no existe, pero su ítem del checklist de `sync.instructions.md` es
explícitamente condicional ("si existe copia en docs/") — no es un hueco, simplemente no aplica.
`COMPATIBILITY.md` es distinto: su ítem del checklist NO lleva esa condición (se espera que
exista), el fichero no existe en ningún sitio del repo, y `.github/DOCUMENTATION_AUDIT.md`
(2026-08-27) ya lo había señalado como hallazgo Nivel 1 antes de esta sesión. Por el propio
proceso definido en `sync.instructions.md`, poblar `COMPATIBILITY.md` es un paso obligatorio de
cada cierre de VERSION. Se preguntó explícitamente al usuario si crear el fichero (decisión de
gobernanza, no algo a asumir dentro de un VERSION en curso) — confirmó que sí. Se creó
`COMPATIBILITY.md` en la raíz con la tabla `Versión | Python | Dependencias clave | Estado`
pedida por el checklist, poblada verificando cada fila contra `git show <commit>:pyproject.toml`
(no de memoria) para las cuatro versiones existentes (0.1.0–0.4.0) — incluye una nota al pie sobre
el suelo mínimo de Python subiendo de `3.10` a `3.11` **dentro** de la propia 0.2.0 (commit
`83504cc`, sesión `2026-08-29-python-3-11`), en vez de asumir que el suelo fue estable.
**Status**: ✅ `mkdocs build --strict` limpio tras ambos cambios; sin nuevas páginas de `docs/`
(no hace falta tocar `mkdocs.yml`). `COMPATIBILITY.md` cerrado — gap heredado ya resuelto.

---

## Impacto

### Código
- **Archivos modificados**: `src/doc_organize/scan/scan_command.py`, `src/doc_organize/scan/__init__.py`,
  `src/doc_organize/main.py`, `src/doc_organize/core/constants.py`, `src/doc_organize/core/models.py`,
  `src/doc_organize/dedup/deduplication.py`, `src/doc_organize/web/routes/scan.py`,
  `src/doc_organize/web/routes/duplicates.py`, `src/doc_organize/web/templates/folder_selector.html.j2`,
  `src/doc_organize/web/templates/duplicates_resolver.html.j2`, `tests/unit/test_main.py`,
  `tests/unit/test_deduplication.py`, `tests/unit/test_web_scan.py`, `tests/unit/test_web_duplicates.py`,
  `.ai/glossary.md`, `.ai/product.md`, `.ai/runtime.md`, `docs/api/dedup.md`, `docs/functional/dedup.md`,
  `docs/functional/index.md`, `docs/functional/projects.md`, `docs/guides/quick_start.md`,
  `CHANGELOG.md`, `pyproject.toml`.
- **Archivos nuevos**: `COMPATIBILITY.md` (gobernanza, no existía en el repo antes de esta sesión).
- **Cambios funcionales**: sí, sustanciales — nuevo flujo de dos pasos (deduplicar → escanear) en
  web y CLI, histórico incremental de deduplicaciones, página "Duplicados" rediseñada.

### Compatibilidad
- **BREAKING**:
  - `ScanCommand.run()`/`run_streaming()` pierden los parámetros `deduplicate: bool` y
    `duplicates_dir: Path`.
  - Nuevo método público `ScanCommand.deduplicate(paths, duplicates_dir, folders_json) -> DeduplicationSummary`.
  - CLI: `scan` pierde `--deduplicate` y `--duplicates-dir`; nuevo subcomando `deduplicate --paths ... [--project ...] [--duplicates-dir ...]`.
  - Contrato WS `POST/WS /api/projects/{name}/scan`: el payload ya no acepta ni necesita `paths` ni
    `deduplicate` — el servidor resuelve siempre todas las carpetas guardadas del proyecto.
  - Nuevo endpoint `POST /api/projects/{name}/scan/deduplicate`.
  - `ScanEventType.DEDUPLICATED` eliminado del enum público (`core/models.py`).
  - Página web "Duplicados": la sección "Duplicados ya resueltos" ya no existe como tal (fusionada
    en "Histórico de deduplicaciones", con detalle completo por ejecución).
- **NO BREAKING**:
  - `DeduplicationManager.find_duplicates()`/`resolve_duplicates()` (Nivel 2) sin cambios de firma
    — `resolve_duplicates()` gana un efecto secundario nuevo (escribe además `DEDUP_HISTORY.jsonl`),
    pero su contrato de entrada/salida no cambia.
  - `DEDUP_REPORT.json` se sigue escribiendo igual en disco (contrato externo preservado).
  - `GET /api/projects/{name}/duplicates` y `POST /api/projects/{name}/duplicates/resolve` sin
    cambios de contrato.

---

## Verificación
```
python -m ruff check src tests
  → All checks passed!
python -m mypy src
  → Success: no issues found in 45 source files
python -m pytest -q
  → 294 passed (283 rápidos + 11 lentos, Docling/dedup real), 96% cobertura total
python -m mkdocs build --strict
  → Documentation built, sin warnings de links/anchors rotos
```
Verificación adicional: ninguna comprobación visual en navegador real (Playwright) en esta sesión —
los cambios de plantilla se verificaron por lectura de código y por la suite HTTP (que no ejecuta
JS de navegador). Ver Riesgos Residuales.

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| `DEDUP_HISTORY.jsonl` crece sin límite ni rotación durante toda la vida del proyecto | Aceptado a corto plazo (decisión explícita en AUDIT_PLAN); `_load_dedup_history` ya corre en thread aparte (`asyncio.to_thread`) para no bloquear el event loop mientras crece | Pendiente si se vuelve un problema real — considerar paginación o límite de entradas |
| `DEDUP_REPORT.json` (contrato externo) sigue sin escritura atómica (write directo, sin escribir-a-temporal-y-renombrar) — heredado de sesión anterior | La web ya no depende de él para "última deduplicación" (deriva de `DEDUP_HISTORY.jsonl`), así que un corrupt/truncated `DEDUP_REPORT.json` ya no afecta la página; el fichero en sí sigue siendo responsabilidad de consumidores externos | Mitigado para la web; sin cambios para consumidores externos del fichero |
| Gate "Escanear bloqueado hasta deduplicar" es solo de cliente (JS, sin persistencia de servidor) | Decisión explícita y documentada: no es una barrera de seguridad, es una guía de flujo — saltársela llamando al WS directamente no expone nada nuevo | Aceptado, sin acción pendiente |
| Autoescape de Jinja2 desactivado en todas las plantillas `.html.j2` del proyecto (heredado de la sesión `2026-08-31-duplicados-resolver-ui`) | Documentado en esa sesión; no se ha tocado en esta | Pendiente — recomendado `/security-review` dedicado |
| Cambios de UI de esta sesión (acordeón `<details>`, refresco tras resolver, gate de botones) sin verificación visual en navegador real | Solo verificado por lectura de código y tests HTTP (no ejecutan JS) | Pendiente si se quiere una pasada con Playwright antes de publicar |
| ~~`COMPATIBILITY.md` no existía en el repo, aunque `sync.instructions.md` lo trata como paso obligatorio de todo cierre de VERSION~~ | Creado en esta sesión, a petición confirmada del usuario, con las 4 versiones (0.1.0–0.4.0) verificadas contra `git show <commit>:pyproject.toml` (no de memoria) | ✅ Resuelto en esta misma sesión |

---

## Siguientes Pasos (Recomendado)
1. Confirmar con el usuario el commit de esta sesión (mensaje sugerido abajo) — no se ha ejecutado
   `git commit` todavía.
2. Opcional: verificación visual en navegador real (Playwright) del flujo completo — botón "Buscar
   duplicados" deshabilitando/habilitando "Escanear", acordeón del histórico, refresco tras resolver
   un conflicto.
3. Abrir una sesión `/security-review` dedicada al autoescape de Jinja2 (heredado, ver Riesgos
   Residuales) — sigue siendo el hallazgo de seguridad más importante sin cerrar en el proyecto.
4. Vigilar el tamaño de `DEDUP_HISTORY.jsonl` en proyectos con uso intensivo de "Buscar duplicados";
   valorar paginación si se vuelve un problema real.
5. Mantener `COMPATIBILITY.md` actualizado en cada VERSION futura (instrucciones de mantenimiento
   ya incluidas al final del propio fichero) — no dejar que vuelva a quedar desactualizado.

---

## Directrices para Futuras IAs

- **[Deduplicación separada del escaneo, no automática]**: `ScanCommand.run()`/`run_streaming()`
  YA NO deduplican — la deduplicación vive en `ScanCommand.deduplicate(paths, duplicates_dir,
  folders_json)`, una acción independiente a petición del usuario, compartida por el CLI
  (subcomando `deduplicate`) y la web (`POST /api/projects/{name}/scan/deduplicate`). Si se pide
  "que el escaneo deduplique", **no asumir que hay que volver a fusionarlo** — confirmar con el
  usuario, porque ya se intentó así en esta misma sesión y se corrigió explícitamente a lo
  contrario.
- **[Gate "Escanear" es solo de cliente y se resetea siempre]**: en `folder_selector.html.j2`, el
  botón `#scan-submit-btn` nace `disabled` en cada carga de página y solo se habilita tras un
  `POST /scan/deduplicate` exitoso en esa misma visita — no hay memoria de servidor ni de sesión.
  Es una decisión de UX deliberada (guiar el flujo), no una barrera de seguridad.
- **["Última deduplicación" se deriva de `DEDUP_HISTORY.jsonl`, no de un fichero aparte]**:
  `web/routes/duplicates.py::duplicates_resolver_page` calcula `last_dedup_report = history[0] if
  history else None`. No existe ya `_load_last_dedup_report()` — se eliminó deliberadamente para
  que "el último report" y "el histórico" no puedan desincronizarse entre sí (antes eran dos
  lecturas de dos ficheros distintos, escritos en dos pasos no atómicos).
  `DEDUP_REPORT.json` se sigue escribiendo en disco (contrato externo, `audit_json_path` apunta
  ahí) pero la página web ya no lo lee — si se necesita volver a leerlo, es un cambio de diseño
  explícito, no un descuido a "corregir".
- **[El histórico registra TODA ejecución, incluso sin duplicados]**: `ScanCommand.deduplicate()`
  llama a `DeduplicationManager.resolve_duplicates()` incondicionalmente (sin `if groups:`) para
  que cada "Buscar duplicados" quede en `DEDUP_HISTORY.jsonl`, aunque no mueva nada. Si se necesita
  lo contrario (no registrar ejecuciones vacías), es una regresión intencional a discutir con el
  usuario, no un bug a "arreglar" reintroduciendo el guard.
- **["Duplicados ya resueltos" ya no existe como sección aparte]**: se fusionó dentro de "Histórico
  de deduplicaciones" — cada ejecución (`history_entries` en el contexto de la plantilla) lleva su
  propio `resolved_groups` con el detalle completo de archivos, no solo la más reciente. El
  contador/buscador de la página (`total_resolved_groups`) suma los grupos de **todas** las
  ejecuciones, no solo la última.
- **[Cada ejecución del histórico es un `<details>`/`<summary>` colapsado por defecto]**: acordeón
  nativo, sin JS de terceros. El filtro de búsqueda (`#duplicates-search`) expande automáticamente
  el `<details>` que contiene una coincidencia cuando hay una query activa — si se toca ese JS, no
  romper esa expansión automática o las coincidencias quedarán "contadas pero invisibles".
- **[`SCAN_FOLDERS_JSON_NAME`]**: constante en `core/constants.py` para el literal `"folders.json"`
  — usarla en vez de repetir el string, ya centralizada en `main.py`, `web/routes/scan.py` y
  `web/routes/duplicates.py`.
- **[`main.py` tiene dos resolvers de rutas distintos a propósito]**: `_resolve_scan_paths` (para
  `scan`, exige `--output-dir`/`--cache-file` sin `--project`) y `_resolve_dedup_paths` (para
  `deduplicate`, no los exige — esa acción no convierte ni cachea). No fusionarlos sin darse cuenta
  de que validan requisitos distintos deliberadamente.
- **[Cambios de UI de esta sesión sin verificación visual en navegador real]**: el acordeón, el gate
  de botones y el refresco tras resolver se verificaron por lectura de código y por la suite HTTP
  (que no ejecuta JS) — si se toca `duplicates_resolver.html.j2` o `folder_selector.html.j2` de
  nuevo, considerar una pasada con Playwright antes de dar por buena la UX.
- **[`COMPATIBILITY.md` existe desde esta sesión — mantenerlo, no dejarlo caducar]**: raíz del
  repo, tabla `Versión | Python | Dependencias clave | Estado` verificada contra
  `git show <commit>:pyproject.toml` para 0.1.0–0.4.0 (no de memoria — el checklist de
  `.github/instructions/sync.instructions.md` lo pide sin excepción "si existe", a diferencia de
  `docs/CHANGELOG.md`, que sí es condicional y con razón no existe). Al cerrar la siguiente
  versión, añadir una fila nueva siguiendo las instrucciones al final del propio fichero — no
  copiar la fila anterior sin comprobar Python/dependencias contra el `pyproject.toml` real de ese
  commit.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ Cada corrección de alcance pedida explícitamente por el usuario (deduplicación no automática,
  CLI propio, histórico incremental, orden de secciones, detalle completo por ejecución, refresco
  tras resolver, acordeón) se implementó tal cual se pidió, aclarando primero cualquier ambigüedad
  real antes de codificar (varias rondas de `AskUserQuestion` documentadas en la conversación).
- ✅ PLAN/AUDIT_PLAN antes de cada cambio no trivial, con veredicto explícito (GO / GO_CONDICIONAL
  resuelto) antes de tocar código.
- ✅ Auditoría independiente (`/audit-code`) ejecutada sobre el resultado, con hallazgos reales
  (no cosméticos) aplicados a petición del usuario.
- ✅ `ruff`, `mypy`, `pytest` (294 tests, 96% cobertura), `mkdocs build --strict` — todos en verde
  tras cada cambio.
- ✅ VERSION cerrada: `pyproject.toml` y `CHANGELOG.md` en `0.4.0`, con el carácter breaking
  documentado explícitamente (decisión de versión consultada con el usuario, ver punto 10).
- ✅ `COMPATIBILITY.md` creado y con checklist de `sync.instructions.md` cumplido en su totalidad
  para esta VERSION (no quedó ningún ítem obligatorio sin resolver).
- ⬜ Verificación visual en navegador real (Playwright) de los cambios de UI — pendiente, señalado
  como riesgo residual, no bloqueante.
- ⬜ Commit: pendiente de confirmación explícita del usuario.

**Evidencia**:
- Branch: `develop`
- Commits: ninguno todavía (working tree con cambios sin confirmar — 24 ficheros modificados +
  `TRACEABILITY.md` y `COMPATIBILITY.md` nuevos)
- Tests: 294 passed (283 rápidos + 11 lentos con Docling/dedup real), 96% cobertura total
- Versión: `0.3.0` → `0.4.0`

**Sesión cerrada**: 2026-08-31 16:44 UTC

---

## Commit sugerido (pendiente de confirmación del usuario)

```
feat: separar deduplicación del escaneo con histórico incremental

Rediseña el flujo de escaneo: "Buscar duplicados" pasa a ser una acción
independiente y explícita (CLI `deduplicate` + botón web) que bloquea
"Escanear" hasta ejecutarse en esa visita. Cada ejecución queda registrada
en duplicados/DEDUP_HISTORY.jsonl, consultable en la página "Duplicados"
con detalle completo por ejecución en bloques colapsables.

BREAKING CHANGE: ScanCommand.run()/run_streaming() pierden `deduplicate`
y `duplicates_dir`; CLI `scan` pierde --deduplicate/--duplicates-dir
(usar el nuevo subcomando `deduplicate`); el WS de escaneo ya no acepta
`paths` del cliente; ScanEventType.DEDUPLICATED se elimina.

Añade COMPATIBILITY.md (no existía en el repo, requerido por
sync.instructions.md en cada cierre de VERSION).

Bump 0.3.0 -> 0.4.0.
```
