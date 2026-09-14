# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-15
- **Tipo**: `feature` (`/new-feature`)
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA

## Objetivo
Añadir una tercera estrategia de detección de duplicados por similitud aproximada
de nombre de archivo (RapidFuzz), complementaria a las dos existentes (hash exacto
y conflicto de versión por nombre normalizado). El porcentaje mínimo de similitud
es parametrizable (`fuzzy_threshold`, 0-100) y los grupos resultantes
(`DuplicateReason.FUZZY_NAME_MATCH`) nunca se auto-resuelven: quedan excluidos de
la acción masiva "Buscar duplicados" y solo se resuelven desde el formulario
interactivo de "Revisar Duplicados", donde el usuario elige explícitamente qué
archivo conservar de cada grupo.

**Ampliación pedida dentro de la misma sesión**: además de elegir *qué* archivo
conservar, el usuario debe poder decidir, grupo a grupo, *si* un grupo fuzzy se
ve afectado en absoluto al enviar el formulario de resolución — un checkbox por
grupo ("incluir en esta resolución"), desactivado por defecto.

## Cambios Ejecutados

### ✅ 1. `DeduplicationManager.find_duplicates(fuzzy_threshold=None)` + `_build_fuzzy_groups()`
**Archivo(s)**: `src/doc_organize/dedup/deduplication.py`,
`src/doc_organize/core/models.py` (`DuplicateReason.FUZZY_NAME_MATCH`).
**Descripción**: `fuzzy_threshold: int | None = None` (retrocompatible, cero
regresiones). Cuando se indica, tras las dos pasadas actuales se ejecuta una
tercera SOLO sobre los documentos que sigan sin agrupar: compara
`display_name.lower()` (mismo criterio que `_extract_base_name`) vía
`rapidfuzz.process.cdist` (vectorizado en C, `scorer=fuzz.ratio`,
`score_cutoff=fuzzy_threshold`, `workers=-1`) y agrupa por componentes conexas
del grafo de similitud (union-find sobre las aristas extraídas, también
vectorizado, con `numpy.argwhere`/`numpy.triu` — sin doble bucle Python), sin
exigir transitividad estricta par a par. `canonical_doc` se calcula igual que en
las otras dos pasadas (más antiguo por `modified_time`), pero es solo una
propuesta en estos grupos.
**Status**: ✅ 8 tests nuevos en `tests/unit/test_deduplication.py`
(retrocompatibilidad sin el parámetro, agrupación por encima/debajo del umbral,
exclusión de documentos ya agrupados por hash, componentes conexas sin
transitividad estricta, case-insensitivity, `<2` documentos restantes).

### ✅ 2. `fuzzy_threshold` en la capa web (`GET`/`POST` de Duplicates Resolver)
**Archivo(s)**: `src/doc_organize/web/routes/duplicates.py`.
**Descripción**: `GET /api/projects/{name}/duplicates`,
`GET /projects/{name}/duplicates` y `POST .../duplicates/resolve` ganan
`fuzzy_threshold: int | None` (0-100, `Query`/`Field` con `ge=0, le=100`),
reenviado a `_detect_duplicates()` → `find_duplicates()`. El `POST /resolve`
necesita el MISMO `fuzzy_threshold` con el que el cliente detectó (`GET`) los
grupos que resuelve — decisión no explícita en el pedido original pero necesaria
para que la regla de negocio "resolución manual explícita" funcione end-to-end
(documentado en el docstring de la ruta). `ScanCommand.deduplicate_streaming()`
(WS `/scan/deduplicate`, "Buscar duplicados") sigue llamando a
`find_duplicates()` sin este parámetro — confirmado sin tocar `scan_command.py`,
con test de regresión explícito (ver 4).
**Status**: ✅ 5 tests nuevos en `tests/unit/test_web_duplicates.py`.

### ✅ 3. Control de umbral en `duplicates_resolver.html.j2`
**Archivo(s)**: `src/doc_organize/web/templates/duplicates_resolver.html.j2`.
**Descripción**: input numérico (0-100) + botones "Aplicar"/"Quitar" (navegación
completa vía query param, mismo patrón que `?tab=`). El `fuzzy_threshold` activo
viaja como `data-fuzzy-threshold` en `#resolve-form` para que el `POST /resolve`
lo reenvíe. Fix necesario para que el umbral sobreviva a los refrescos parciales:
`refreshDynamicPanels()` hacía `fetch(window.location.pathname)` sin
querystring — se perdía `?fuzzy_threshold=` tras cada operación. Nombrado
`{% endblock content %}` (antes anónimo) al tocar la plantilla, por la
convención de `SHARED_INSTRUCTIONS.md` para bloques largos.
**Status**: ✅ cubierto por los tests de (2); sin infraestructura de test JS en
el proyecto (política existente, ver `SHARED_INSTRUCTIONS.md`).

### ✅ 4. Dependencia `rapidfuzz` + regresión explícita de la regla de negocio 3
**Archivo(s)**: `pyproject.toml`, `GUIA_ACTUALIZAR_DEPENDENCIAS.md`,
`tests/unit/test_web_scan.py`.
**Descripción**: `rapidfuzz>=3.0` añadido a `dependencies` (no opcional).
`numpy` se usa sin declararlo aparte: es dependencia transitiva garantizada de
`pandas>=2.0` (ya directa). Test nuevo en `test_web_scan.py`
(`test_deduplicate_websocket_never_groups_by_fuzzy_name_match`) con nombres
deliberadamente muy parecidos (ratio RapidFuzz ~85.7) para que la única forma de
que `groups_found > 0` sea que la pasada fuzzy se hubiera colado por error en la
acción masiva — bloquea cualquier regresión futura de la regla CRÍTICA del
pedido.
**Status**: ✅ `test_deduplicate_websocket_never_groups_by_fuzzy_name_match`.

### ✅ 5. Documentación (`docs/functional`, `docs/api`, `docs/examples`)
**Archivo(s)**: `docs/functional/dedup.md`, `docs/api/dedup.md`,
`docs/examples/dedup-resolve.md`.
**Descripción**: tercera pasada documentada en el flujo funcional (con su propia
sección y 2 filas nuevas en la tabla de reglas de negocio), firma/arquitectura
actualizada en la referencia técnica (incluye `rapidfuzz`/`numpy` en la tabla de
dependencias), ejemplo ejecutable de uso con `fuzzy_threshold` añadido al
ejemplo existente. `mkdocs.yml` no necesitaba `nav:` nuevo (las 3 páginas ya
existían).
**Status**: ✅ `mkdocs build --strict` limpio, sin warnings ni links rotos.

### ✅ 6b. Toggle por grupo fuzzy: "incluir en esta resolución" (desactivado por defecto)
**Archivo(s)**: `src/doc_organize/web/routes/duplicates.py`,
`src/doc_organize/web/templates/duplicates_resolver.html.j2`.
**Descripción**: petición de seguimiento del usuario tras cerrar la entrega
inicial — hasta este punto, `POST /duplicates/resolve` resolvía (movía)
**todos** los grupos detectados, incluidos los fuzzy, en cuanto se enviaba el
formulario (el radio de cada fila solo elegía qué archivo conservar, nunca si
el grupo se tocaba). Se añadió `ResolveDuplicatesRequest.fuzzy_group_toggles:
dict[str, bool] | None = None` (`group_key` → activado), que filtra —SOLO para
grupos `reason=fuzzy_name_match`— cuáles se pasan a
`DeduplicationManager().resolve_duplicates()`. Semántica fail-safe: con el
dict presente, cualquier clave ausente se trata como "no activado" (nunca al
revés). `None` (campo ausente del payload) preserva el comportamiento anterior
sin cambios — retrocompatible con cualquier caller que no conozca el campo.
`ResolveDuplicatesResponse` gana `groups_excluded: int = 0`. En la plantilla,
cada `<fieldset>` de un grupo fuzzy lleva ahora un checkbox propio dentro del
`<legend>` (`class="fuzzy-toggle-checkbox" data-group-key="..."`),
**desactivado por defecto** (decisión explícita del usuario, confirmada antes
de implementar vía pregunta directa: los grupos fuzzy nunca se auto-resuelven,
ahora también a nivel de grupo individual, no solo de página) — el JS de
`setupResolveForm()` lee su estado real recorriendo el DOM (no vía `FormData`,
que omite checkboxes sin marcar) y lo envía siempre como
`fuzzy_group_toggles`, reflejando el estado real de la página.
**Status**: ✅ 6 tests nuevos en `tests/unit/test_web_duplicates.py`: toggle
desactivado dejar pendiente, clave ausente del dict = excluido (fail-safe),
toggle activado sí resuelve, un intento de excluir un grupo `exact_duplicate`
vía este mecanismo se ignora (seguridad — el filtro nunca aplica fuera de
`fuzzy_name_match`), checkbox sin `checked` en el HTML servido. Ajustada
también la aserción de igualdad exacta de
`test_duplicates_resolve_no_duplicates_is_noop` (campo nuevo con default,
cambio de forma del payload sin cambio de comportamiento).

### ✅ 6. Hallazgos de AUDIT_CODE corregidos dentro de la propia sesión
**Archivo(s)**: `web/routes/duplicates.py`,
`web/templates/duplicates_resolver.html.j2`.
**Descripción**:
1. **Disponibilidad**: `_detect_duplicates()` llamaba a `find_duplicates()` de
   forma síncrona directamente en el hilo del event loop async. Las dos pasadas
   originales son O(n) (baratas), pero la pasada fuzzy es O(n²) sobre los
   documentos sin agrupar — en un proyecto con miles de ficheros sin agrupar,
   una petición con `fuzzy_threshold` habría bloqueado el servidor **entero**
   (todas las conexiones concurrentes) durante el cálculo. Corregido envolviendo
   la llamada en `asyncio.to_thread()` en el *call site* de la capa web —
   `find_duplicates()` en sí sigue siendo síncrona, tal como exige el pedido.
2. **Gap de bloqueo cruzado en UI**: `lockDedupControls()`/`unlockDedupControls()`
   (mecanismo existente contra operaciones de dedup concurrentes) no cubrían los
   nuevos botones "Aplicar"/"Quitar" — un usuario podía navegar fuera de la
   página a mitad de una operación en curso. Corregido añadiéndolos al
   lock/unlock, con el mismo guard `if (dedupOperationInProgress) return;` que
   ya usa el resto de controles.
**Status**: ✅ verificado con `asyncio.to_thread` ejecutado manualmente
end-to-end + suite completa relanzada tras el fix (104/104 en los 3 ficheros
afectados).

---

## Impacto

### Código
- **Archivos modificados**: 12 (ver `git diff --stat`: +804/-38 líneas tras
  ambas entregas de esta sesión). Ninguno creado, ninguno eliminado.
- **Cambios funcionales**: sí — nuevo `DuplicateReason.FUZZY_NAME_MATCH`, nuevo
  parámetro opcional en `find_duplicates()`, nuevos query params/campos de body
  en 3 rutas web (`fuzzy_threshold` + `fuzzy_group_toggles`), nuevos controles
  en la UI (umbral a nivel de página + activación a nivel de grupo).

### Compatibilidad
- **BREAKING**: ninguno. `fuzzy_threshold` y `fuzzy_group_toggles` son
  opcionales con default `None` en todas las firmas tocadas (Python y HTTP) —
  comportamiento idéntico al actual si no se usan (LSP respetado).
- **NO BREAKING**: `DuplicateReason` gana un miembro nuevo (aditivo);
  `ResolveDuplicatesRequest` gana 2 campos opcionales con default seguro;
  `ResolveDuplicatesResponse` gana `groups_excluded: int = 0` (aditivo — un
  test que comparaba el payload completo por igualdad exacta se actualizó para
  incluir el campo nuevo, sin cambio de comportamiento real).

---

## Verificación
```
python -m ruff check src tests          → limpio
python -m ruff format --check           → limpio (solo los 2 ficheros tocados
                                           por esta sesión que requerían
                                           reformateo, aplicado; otros 2 ficheros
                                           con drift preexistente ajeno,
                                           NO tocados)
python -m mypy src                      → limpio (75 ficheros)
python -m pytest                        → 854 passed (31 tests nuevos de esta
                                           sesión incluidos, entre las tres
                                           entregas: detección fuzzy + toggle
                                           por grupo + AUDIT_CODE de
                                           coexistencia fuzzy/no-fuzzy)
python -m mkdocs build --strict         → build limpio, sin warnings ni links
                                           rotos
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| La pasada fuzzy sigue siendo O(n²) en el número de documentos sin agrupar — para proyectos muy grandes (decenas de miles de ficheros sin agrupar) una detección con `fuzzy_threshold` puede tardar, aunque ya no bloquea el resto del servidor | `asyncio.to_thread()` en el call site (hallazgo 6.1) evita que bloquee a OTRAS peticiones; la petición propia sigue tardando lo que tarde `cdist` | Aceptado — mismo orden de magnitud que cualquier operación O(n²) opt-in, sin mitigación adicional pedida en el alcance |
| `fuzz.ratio` (similitud literal) elegido sobre `fuzz.WRatio` sin que el pedido especificara el scorer | Documentado en el docstring de `_build_fuzzy_groups`; razonamiento: `WRatio` está pensado para strings largos tipo direcciones y es más propenso a falsos positivos por coincidencia parcial en nombres de fichero cortos | Decisión de diseño razonada, no una ambigüedad sin resolver |
| `CHANGELOG.md`/`COMPATIBILITY.md`/`pyproject.toml` (bump de versión) no se tocaron en esta sesión | Ninguna todavía — pendiente de una pasada de `/version-closure` explícita, no pedida en este `/new-feature` | Pendiente, ver "Siguientes Pasos" |

---

## Siguientes Pasos (Recomendado)
1. Commitear los cambios (working tree limpio de commit por ahora, ver
   "Evidencia") — mensaje sugerido:
   `feat: añadir deteccion de duplicados por similitud aproximada de nombre (RapidFuzz)`.
2. Si se quiere cerrar versión formalmente: `CHANGELOG.md`, `COMPATIBILITY.md` y
   bump de `pyproject.toml` (checklist completo en
   `.github/instructions/sync.instructions.md`) — no se hizo aquí porque el
   pedido fue `/new-feature`, no `/version-closure`.
3. Si en producción se observa que `fuzz.ratio` produce demasiados falsos
   positivos/negativos para cierto tipo de nombres, revisar si un scorer
   distinto (o una normalización previa, p. ej. quitar dígitos/fechas) encaja
   mejor — no había señal real para decidirlo en esta sesión.

---

## Directrices para Futuras IAs

- **[La pasada fuzzy opera SOLO sobre documentos sin agrupar por las dos pasadas
  anteriores]**: `find_duplicates()` calcula `grouped_paths` (todos los
  `full_path` ya en algún `DuplicateGroup` de hash/versión) y filtra
  `unique_hash_docs` contra ese set antes de llamar a `_build_fuzzy_groups()` —
  un documento nunca pertenece a más de un grupo. No fusionar esta pasada con
  las anteriores en un único bucle sin preservar este filtro.
- **[Los grupos `FUZZY_NAME_MATCH` están excluidos por diseño de "Buscar
  duplicados"]**: `ScanCommand.deduplicate_streaming()`
  (`scan/scan_command.py`) llama a `find_duplicates()` SIN `fuzzy_threshold` —
  deliberadamente no tocado en esta sesión. Si alguna vez se plantea pasarlo
  ahí, releer la regla de negocio 3 del pedido original (coincidencias
  probabilísticas por nombre no deben moverse sin confirmación humana) antes de
  hacerlo — sería un cambio de política, no un bug a corregir.
- **[`POST /duplicates/resolve` necesita el MISMO `fuzzy_threshold` que el `GET`
  que mostró los grupos]**: el re-escaneo de esa ruta es independiente del `GET`
  anterior; sin el mismo umbral, un grupo `fuzzy_name_match` no reaparece y la
  resolución del usuario para ese grupo se ignora en silencio (mismo mecanismo
  que ya existía para un `group_key` manipulado). El campo vive en
  `ResolveDuplicatesRequest.fuzzy_threshold` y en el frontend como
  `data-fuzzy-threshold` en `#resolve-form`.
- **[`find_duplicates()` se invoca desde la capa web vía `asyncio.to_thread`, no
  directamente]**: sigue siendo una función síncrona (contrato explícito del
  pedido), pero desde que existe la pasada fuzzy (O(n²)) llamarla directamente
  en una ruta `async def` bloquearía el event loop entero. Cualquier nuevo call
  site de `find_duplicates()` en código async debería seguir el mismo patrón que
  `_detect_duplicates()` en `web/routes/duplicates.py`.
- **[`score_cutoff=fuzzy_threshold` en `cdist` + el filtro explícito posterior
  `score_matrix >= fuzzy_threshold` NO es redundante]**: con `fuzzy_threshold=0`,
  RapidFuzz desactiva el cutoff internamente (semántica documentada de
  `score_cutoff=0`) — el filtro explícito es el que real­mente aplica "conectar
  todo" en ese caso límite. No simplificar quitando uno de los dos sin volver a
  probar ese caso.
- **[`numpy` se usa en `dedup/deduplication.py` sin declararlo como dependencia
  propia]**: es transitiva garantizada de `pandas>=2.0` (dependencia directa
  existente, no opcional) — verificado que `rapidfuzz.process.cdist` siempre
  devuelve `numpy.ndarray`. Si `pandas` deja de ser dependencia obligatoria en
  el futuro, este import dejaría de estar garantizado y habría que añadir
  `numpy` explícitamente.
- **[`fuzzy_group_toggles` es un filtro de la capa web, `DeduplicationManager`
  no sabe que existe]**: `resolve_duplicates()` (la ruta, no el manager)
  construye `groups_to_resolve` filtrando `groups` ANTES de llamar a
  `DeduplicationManager().resolve_duplicates()` — el manager sigue recibiendo
  exactamente la misma forma de `list[DuplicateGroup]` que antes de esta
  entrega. Cualquier cambio futuro a esta lógica de activación/desactivación
  debe mantenerse en `web/routes/duplicates.py`, no filtrarse hacia `dedup/`.
- **[Semántica fail-safe de `fuzzy_group_toggles`: clave ausente = excluido,
  NUNCA incluido]**: con el dict presente (`is not None`), `.get(group_key,
  False)` es la única lectura -- no hay ninguna ruta de código que trate una
  clave ausente como "activado". Esto aplica tanto si el JS omite un grupo por
  error como si el usuario nunca tocó su checkbox. El filtro SOLO se evalúa
  para `group.reason == DuplicateReason.FUZZY_NAME_MATCH`; para cualquier otro
  `reason` el dict se ignora por completo, incluso si contiene una clave que
  coincide con el `group_key` de un grupo `exact_duplicate`/`version_conflict`
  real (test de regresión explícito:
  `test_duplicates_resolve_fuzzy_group_toggles_never_exclude_exact_duplicate_group`).
  No "simplificar" esto a un único chequeo `fuzzy_group_toggles.get(key,
  False)` sin la guarda de `reason` primero -- rompería esa garantía de
  seguridad.
- **[El checkbox de cada grupo fuzzy nace SIEMPRE desactivado en el HTML
  servido]**: decisión de producto confirmada explícitamente con el usuario
  antes de implementar (no asumida). Si se cambia este default, actualizar a
  la vez el test
  `test_duplicates_resolver_page_fuzzy_group_checkbox_unchecked_by_default` y
  la documentación funcional (`docs/functional/dedup.md`).

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ Las 5 reglas de negocio del pedido implementadas y con test explícito cada
  una (un documento por grupo como máximo, `fuzzy_threshold` 0-100 por
  componentes conexas sin transitividad estricta, exclusión de "Buscar
  duplicados", retrocompatibilidad total sin el parámetro, comparación solo
  sobre `display_name`)
- ✅ Restricciones técnicas respetadas: `find_duplicates()` síncrona y sin I/O a
  disco; `rapidfuzz.process.cdist` vectorizado (sin doble bucle Python para el
  cálculo de scores); sin patrón strategy/plugin nuevo (parámetro explícito,
  mismo estilo que el resto de `DeduplicationManager`)
- ✅ 2 hallazgos reales de AUDIT_CODE (bloqueo del event loop, gap de lock en
  UI) encontrados y corregidos dentro de la propia sesión, verificados
  manualmente y con la suite completa relanzada después
- ✅ Petición de seguimiento del usuario (toggle "incluir en esta resolución"
  por grupo fuzzy, desactivado por defecto) implementada con PLAN/AUDIT_PLAN
  previos y confirmación explícita del default antes de tocar código
- ✅ Un segundo AUDIT_CODE (a petición del usuario) verificó empíricamente la
  coexistencia grupo-fuzzy-excluido + grupo-no-fuzzy-resuelto en el MISMO
  envío (no solo por razonamiento sobre el código) con un test nuevo
- ✅ Suite completa en verde (854 tests, 31 nuevos de esta sesión),
  `ruff`/`mypy`/`mkdocs build --strict` limpios
- ✅ Commit creado a petición explícita del usuario

**Evidencia**:
- Branch: `develop`
- Commit: `dcc35ec` — "feat: añadir deteccion de duplicados por similitud
  aproximada de nombre (RapidFuzz)" (13 files changed, +1188/-38)
- Tests: `tests/unit/test_deduplication.py` (+8),
  `tests/unit/test_web_duplicates.py` (+12: 5 de detección fuzzy + 6 del
  toggle por grupo + 1 de coexistencia fuzzy/no-fuzzy del segundo AUDIT_CODE),
  `tests/unit/test_web_scan.py` (+1) — suite completa 854 passed
- Docs: `docs/functional/dedup.md`, `docs/api/dedup.md`,
  `docs/examples/dedup-resolve.md` actualizados; `mkdocs build --strict` limpio

**Sesión cerrada**: 2026-09-15
