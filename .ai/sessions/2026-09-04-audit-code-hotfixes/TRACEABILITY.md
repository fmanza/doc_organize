# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-03/04 (iniciada 2026-09-03, cerrada 2026-09-04)
- **Tipo**: `audit` (`/audit-code de todo el proyecto`) + `hotfix` (PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE) de los 5 bugs reales confirmados
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (auditoría + 5 fixes + tests en verde)

## Objetivo
El usuario pidió `/audit-code de todo el proyecto`: 4 agentes en paralelo
cazaron bugs/edge cases concretos (no arquitectura/proceso, ya cubierto por el
`/maturity-assessment` de la sesión anterior) en los 52 ficheros de `src/`.
Veredicto: **RECHAZADO** — 2 bloqueantes con pérdida de datos/crash
reproducible, más 3 bugs reales de manejo de errores ausente. El usuario
confirmó corregir los 5 vía `/hotfix`.

## Cambios Ejecutados

### ✅ 1. HOTFIX BLOQUEANTE — `ProjectRegistry`/`ScannedFoldersStore`: el lock no protegía nada en producción
**Archivo(s)**: `web/app.py`, `web/dependencies.py`, `tests/unit/test_web_app.py`.
**Causa raíz**: `get_project_registry()`/`get_scanned_folders_store()`
construían una instancia **nueva por request** — cada una con su propio
`asyncio.Lock()` (`ProjectRegistry.__init__`/`ScannedFoldersStore.__init__`),
así que el lock no serializaba nada entre peticiones concurrentes. Confirmado
por **dos agentes independientes** de la auditoría, uno con reproducción
empírica: dos requests concurrentes podían perder en silencio uno de los dos
proyectos/carpetas creados (el `os.replace()` final de uno pisaba al otro), o
reventar con un `WinError 32` crudo.
**Fix**: `create_app()` crea una única instancia de `ProjectRegistry` por app
(`app.state.project_registry`, sustituye el antiguo `app.state.registry_path`
de solo-lectura); `get_project_registry()` la devuelve tal cual (con `cast`
explícito, ya que `app.state` es un namespace dinámico sin tipo estático para
mypy). `ScannedFoldersStore` no tiene parámetros de configuración por app, así
que un singleton de módulo en `dependencies.py` basta.
**Test**: `test_concurrent_project_creation_does_not_lose_either_project` —
dos `POST /api/projects` concurrentes (mismo `app`, `asyncio.gather`), ambos
deben sobrevivir en el registro. Sin este fix, el test es flaky/falla
intermitentemente (reproducción confirmada por los auditores antes del fix).
**Status**: ✅.

### ✅ 2. HOTFIX BLOQUEANTE — `deduplicate_streaming()` sin `try/finally`: trabajo parcial se perdía sin registrar
**Archivo(s)**: `scan/scan_command.py`.
**Causa raíz**: a diferencia de `run_streaming()` (que sí tiene `try/finally`
para persistir un `ScanRunReport(completed=False)` en caso de aborto, ya
testeado), `deduplicate_streaming()` no tenía protección — un fallo real en
`move_group()` (fichero bloqueado, borrado, etc.) o una desconexión del
cliente a mitad de la iteración de grupos abortaban el generador sin llamar
nunca a `finalize_report()`. Los grupos ya movidos con éxito quedaban
físicamente en `duplicados/` sin ninguna línea en `DEDUP_REPORT.json`/
`DEDUP_HISTORY.jsonl` que lo reflejara.
**Fix**: bucle envuelto en `try/finally`, mismo patrón que `run_streaming()`.
El `finally` (solo si `not completed_ok`) persiste, best-effort (captura
`OSError`, loguea warning, nunca enmascara la excepción original), un
`DeduplicationReport` con lo conseguido hasta el aborto (`exact_moved`/
`version_resolved` acumulados, `groups` visto hasta ese punto).
**Test**: `test_deduplicate_streaming_persists_partial_report_on_abort` —
`DeduplicationManager.move_group` parcheado para fallar en el 2º grupo de 2;
verifica que el 1º queda registrado en `DEDUP_HISTORY.jsonl` pese al aborto.
**Status**: ✅.

### ✅ 3. HOTFIX — `_move_to_duplicates`: la garantía "nunca sobrescribe" era falsa en una segunda colisión
**Archivo(s)**: `dedup/deduplication.py`.
**Causa raíz**: tras añadir el sufijo de hash al destino colisionado, no se
revalidaba `target.exists()` una segunda vez. Verificado empíricamente en
Windows por el auditor: `shutil.move` cae a un fallback copy+unlink cuando
`os.rename` falla por destino existente, y ese fallback sobrescribe sin avisar
— si el destino ya-sufijado también existía, se perdía en silencio.
**Fix**: segunda comprobación explícita; si el destino sufijado también
existe, `raise FileExistsError` en vez de arriesgar la sobrescritura (el
`try/finally` del punto 2 asegura que esto no deja el histórico sin
constancia).
**Test**: `test_move_to_duplicates_raises_on_double_collision_instead_of_overwriting`.
**Status**: ✅.

### ✅ 4. HOTFIX — `DocumentScanner`: un único fichero desaparecido abortaba TODO el escaneo (TOCTOU)
**Archivo(s)**: `scanner/document_scanner.py`.
**Causa raíz**: `_build_node()` (`.stat()` tras `iterdir()`) y `_hash_all()`/
`_hash_one()` (segunda fase, ventana aún mayor) no capturaban
`FileNotFoundError`/`OSError` si un fichero desaparecía entre el
descubrimiento y el hash/stat (fichero temporal de otra app, borrado por el
usuario a mitad de un escaneo de miles de documentos) — abortaba el escaneo
completo por un único fichero.
**Fix**: `_build_node()` devuelve `DirectoryTreeNode | None` (omite el hijo si
`stat()` falla; `_walk_sync` degrada a un nodo vacío en el caso extremo de que
la propia raíz desaparezca); `_hash_one()` devuelve `None` si `hash_file()`
falla, filtrado del resultado final. Ambos loguean un warning, ninguno aborta.
**Test**: `test_scan_skips_file_that_disappears_before_stat`,
`test_scan_skips_file_that_disappears_before_hashing` (ambos parchean el punto
de fallo para un fichero concreto entre varios, verifican que el resto del
escaneo sobrevive).
**Status**: ✅.

### ✅ 5. HOTFIX — `scan_websocket`: payload malformado crasheaba en vez de cerrar limpio
**Archivo(s)**: `web/routes/scan.py`.
**Causa raíz**: solo se capturaba `WebSocketDisconnect` al leer el payload
inicial; un texto no-JSON lanzaba `json.JSONDecodeError` sin capturar, y un
JSON válido pero no-dict (p. ej. una lista) lanzaba `AttributeError` al llamar
`.get()` — ambos sin el patrón `websocket.close(code=1008, reason=...)` que sí
usa el resto de la función ante otras entradas inválidas.
**Fix**: `except json.JSONDecodeError` + comprobación explícita
`isinstance(request_payload, dict)`, ambos cerrando con `code=1008` y un
motivo explicativo.
**Test**: `test_scan_websocket_rejects_non_json_payload`,
`test_scan_websocket_rejects_non_dict_json_payload`.
**Status**: ✅.

---

## Impacto

### Código
- **Archivos modificados**: `dedup/deduplication.py`, `scan/scan_command.py`,
  `scanner/document_scanner.py`, `web/app.py`, `web/dependencies.py`,
  `web/routes/scan.py`, y 5 ficheros de test (`test_deduplication.py`,
  `test_document_scanner.py`, `test_main.py`, `test_web_app.py`,
  `test_web_scan.py`).
- **Cambios funcionales**: sí, los 5 descritos arriba — todos correcciones de
  manejo de errores/concurrencia, ninguno cambia el comportamiento del camino
  feliz (458 tests, incluidos todos los `@slow`, siguen en verde sin
  modificar ningún test preexistente).

### Compatibilidad
- **BREAKING**: ninguno en API pública. `_build_node()` (privado) cambia su
  tipo de retorno a `DirectoryTreeNode | None` — sin impacto fuera de
  `document_scanner.py`.
- **NO BREAKING**: `app.state.registry_path` (antes solo-lectura, string)
  sustituido por `app.state.project_registry` (instancia) — ningún código
  fuera de `web/app.py`/`web/dependencies.py` lo leía.

---

## Verificación
```
python -m ruff check src tests           → All checks passed!
python -m ruff format --check src tests  → 86 files already formatted
python -m mypy src                       → Success: no issues found in 52 source files
python -m pytest -q --no-cov             → 458 passed (451 + 7 tests nuevos de regresión)
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| `_move_to_duplicates` sigue sin capturar `OSError`/`PermissionError` por fichero individual (fix 2 solo asegura que el aborto se registra, no evita el aborto en sí) | Decisión deliberada del hotfix: aislar el fallo por fichero (como hace `converter.py` por documento) es un cambio de comportamiento mayor, fuera del alcance de "fix mínimo" — señalado explícitamente en la sesión, no implementado | Aceptado, diferido |
| `main.py::_run_deduplicate` sigue sin traducir excepciones no-`DocOrganizeError` a un mensaje limpio (crashea con traceback) | Comportamiento consistente con el resto del CLI (ningún subcomando traduce excepciones inesperadas) — no es una regresión específica de esta sesión, fuera de alcance | Aceptado, no mitigado |
| `ScannedFoldersStore` como singleton de módulo serializa escrituras entre proyectos *distintos* sin necesidad (mismo lock para todos) | Trade-off aceptado deliberadamente ("prohibido optimizar" en hotfix) — las escrituras son poco frecuentes, la serialización cruzada es inocua, no un cuello de botella real | Aceptado por diseño |

---

## Directrices para Futuras IAs

- **[Cualquier `asyncio.Lock` en `__init__` de una clase instanciada por
  request en `web/` es sospechoso]**: protege algo solo si todas las
  peticiones comparten la misma instancia. Antes de confiar en un lock así,
  verificar cómo se construye el objeto en el `Depends`/factory real de
  producción — un test que instancia una única vez y llama dos veces (como el
  test de concurrencia preexistente de `ProjectRegistry` antes de esta sesión)
  da falsa confianza si el patrón real de producción crea una instancia por
  llamada.
- **[Cualquier generador async que mueve/escribe recursos con `yield` entre
  medias necesita `try/finally` si existe un pipeline hermano que ya lo
  tiene]**: `deduplicate_streaming()` se escribió sin él pese a que
  `run_streaming()` (su hermano directo, incluso citado en su propio
  docstring como "mismo criterio") sí lo tenía desde antes — revisar el
  patrón del hermano más cercano antes de dar un generador nuevo por
  completo.
- **[`shutil.move` no es atómico ni seguro-por-defecto frente a colisión de
  destino en Windows]**: su fallback interno (copy+unlink cuando
  `os.rename` falla) sobrescribe sin avisar. Cualquier código que dependa de
  "el destino no existe, luego no hay riesgo" debe revalidar la existencia
  justo antes de mover, no solo una vez al principio.
- **[Cualquier fase de un escaneo/recorrido de disco que pueda tardar
  (miles de ficheros) debe tratar `FileNotFoundError`/`OSError` por
  ítem individual como algo normal, no excepcional]**: un fichero puede
  desaparecer legítimamente entre el descubrimiento y su procesamiento
  (fichero temporal de otra app, el propio usuario borrándolo) — no es un
  bug del sistema de ficheros, es una condición esperable en cualquier
  operación de larga duración sobre un directorio real.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ `/audit-code` completo (4 agentes en paralelo, veredicto RECHAZADO, 5
  bugs reales confirmados con evidencia archivo:línea)
- ✅ `/hotfix` con PLAN+AUDIT_PLAN (breve, investigación ya hecha) + IMPLEMENT
  de los 5, cada uno con test de regresión que habría fallado antes del fix
- ✅ Suite completa en verde (458 passed), `ruff`/`mypy` verificados
- ✅ Ningún fix introduce cambios de comportamiento en el camino feliz
- ⬜ Commit: pendiente de esta misma sesión (ver siguiente paso inmediato)
- ⬜ Push: pendiente de confirmación explícita del usuario

**Evidencia**:
- Branch: `develop`
- Commits: pendiente de crear en esta sesión
- Tests: 458 passed (`python -m pytest -q --no-cov`)

**Sesión cerrada**: 2026-09-04
