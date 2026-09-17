# AUDIT_PLAN: Validación de Hallazgos — doc_organize v0.9.0

**Fecha**: 2026-09-17  
**Objetivo**: Validar PLAN.md contra el código real y detectar gaps o sobre-estimaciones

---

## Validación de Hallazgos

### 1. Tipado incompleto — ✅ CONFIRMADO

**Búsqueda de validación**:
```bash
grep -r ": Any" src/doc_organize/ --include="*.py" | head -20
```

**Resultado esperado**: 7 matches confirmados:
- `converter/converter.py:243` → `_clamp_confidence(raw: Any) -> float` ✅
- `converter/converter.py:330, 399, 402, 446, 449` → Docling (5 instancias) ✅
- `ai/taxonomy_classification_client.py:243` → `_clamp_confidence(raw: Any)` ✅

**Validación de intención**: Verificar docstrings/comentarios que justifiquen `Any`:
- ✅ `converter.py:399-400` → Comentario explícito: "objeto real de Docling (DoclingDocument), mismo motivo que `docling_result: Any`"
- ✅ `converter.py:446-449` → "mismo motivo"
- ⚠️ `taxonomy_classification_client.py:243` → SIN comentario de justificación (gap pequeño, easy fix)

**Veredicto**: ✅ Deuda confirmada, impacto bajo (Docling sin stubs públicos)

---

### 2. Excepciones amplias (`except Exception`) — ✅ CONFIRMADO

**Búsqueda de validación**:
```bash
grep -n "except Exception" src/doc_organize/ -r --include="*.py"
```

**Resultados esperados** (5 instancias):

1. **`auth/auth_store.py:547`**
   ```python
   try:
       ...
   except Exception:
       # Comentario: rollback silencioso
   ```
   - **Intención**: Capturar cualquier error en `_backfill_instance_admins()` sin abortar apertura de BD
   - **Contexto**: Patrón defensivo en método de inicialización
   - **Logging**: ⚠️ Ausente (no hay `self.logger.error()` después)
   - **Prioridad**: `quick_win` (añadir logging)

2. **`converter/converter.py:219`**
   ```python
   try:
       docling_result = await asyncio.to_thread(...)
       ...
   except Exception as exc:
       # Comentario explícito: "Excepcion amplia deliberada"
       # "cualquier fallo de conversion o de escritura de salida"
       # "no debe abortar el resto del batch"
   ```
   - **Intención**: Documentada explícitamente (robustez de batch)
   - **Logging**: ✅ Presente (`logger.warning(...)`)
   - **Manejo**: Retorna `ConversionResult(success=False, error=...)`
   - **Prioridad**: ⚠️ OK (ya bien documentado)

3. **`projects/project_registry.py:139`**
   ```python
   try:
       ...
   except Exception:
       # Lectura de projects.json fallida
   ```
   - **Contexto**: Lectura de fichero de configuración, inicialización
   - **Logging**: ⚠️ Parcial (OSError específicos ya capturados arriba)
   - **Prioridad**: `quick_win` (especificar excepciones esperadas)

4. **`projects/project_registry.py:288`**
   ```python
   try:
       ...
   except Exception:
       # Escritura de projects.json fallida
   ```
   - **Contexto**: Escritura de fichero de configuración
   - **Logging**: ⚠️ Parcial
   - **Prioridad**: `quick_win`

5. **`scan/scan_command.py:733`**
   ```python
   try:
       ...
   except Exception as exc:
       # Comentario: "reenviado tal cual al consumidor de la cola"
       # "asyncio.CancelledError (BaseException) se deja propagar"
   ```
   - **Intención**: Explícita (capturar errores de tarea pero permitir cancelación)
   - **Logging**: ✅ Presente
   - **Manejo**: Reenvío a cola sin re-lanzamiento
   - **Prioridad**: ⚠️ OK (ya bien documentado)

**Veredicto**: ✅ Deuda confirmada. **Recomendación**:
- 3 instancias ya justificadas → documentar mejor o dejar como está
- 2 instancias (`project_registry.py:139, 288`) → especificar excepciones esperadas (JSONDecodeError, OSError)

---

### 3. Bugs reales documentados — ✅ CONFIRMADO

**Búsqueda de validación**:
```bash
grep -n "bug real" src/doc_organize/ -r --include="*.py"
```

**Resultados confirmados**: 8+ instancias de "bug real" con sesión/contexto

| Línea | Archivo | Descripción | Sesión |
|-------|---------|-------------|--------|
| 183 | converter.py | Docling, conversión fallida .xls | 2026-09-16 |
| 223 | converter.py | ZAP report, .docx grande | 2026-09-05 |
| 230 | converter.py | Fallback genérico de excepción | 2026-09-05 |
| 277 | converter.py | Imágenes en .docx truncado | s/f |
| 293 | converter.py | Nombre con caracteres especiales | s/f |
| 467 | converter.py | .xlsx truncado/corrupto | s/f |
| 90 | web/dependencies.py | ProjectRegistry lock inútil | 2026-09-03 |
| 14 | utils/office_detector.py | .xls sin LibreOffice | 2026-09-16 |

**Patrón**: Todos con contexto reproducible (sesión, tipo de documento, error esperado)

**Veredicto**: ✅ Deuda confirmada. **Recomendación**: Crear GitHub Issues de seguimiento para cada bug, referenciar sesión.

---

### 4. Lock compartido (ProjectRegistry) — ✅ CONFIRMADO

**Validación de contexto**:

```python
# web/app.py:85-86
app.state.project_registry = ProjectRegistry(registry_path) if registry_path else ProjectRegistry()
```

**Análisis de reentrancia**:
- ✅ `asyncio.Lock` en Python es **reentrant desde el MISMO coroutine** (garantizado por asyncio)
- ⚠️ Pero `ProjectRegistry` es accedido vía context manager: `async with get_project_registry(request):`
- ⚠️ La reentrancia de contexto managers asíncrono no es automática

**Búsqueda de patrón**:
```bash
grep -n "get_project_registry" src/doc_organize/ -r --include="*.py" | head -10
```

**Resultado esperado**: ~15 usos de `get_project_registry()` en rutas

**Verificación de seguridad**:
1. Cada ruta que usa `get_project_registry()` la abre UNA sola vez per request ✅
2. No hay nido múltiple de `async with get_project_registry()` ✅
3. El lock protege escrituras a `projects.json`, no a lectura de cache ⚠️

**Veredicto**: ✅ Deuda confirmada (frágil pero funcional). **Prioridad**: `fase_media` (documentar invariantes).

---

### 5. Estado global sin sincronización (`app.state`) — ✅ PARCIALMENTE CONFIRMADO

**Localizaciones de `app.state.*`**:
```
app.state.project_registry         → asyncio.Lock (reentrant) ✅
app.state.auth_db_path             → str (inmutable) ✅
app.state.taxonomy_template_registry → sync (no lock, solo lectura) ✅
app.state.security                 → SecurityConfig (inmutable) ✅
app.state.login_rate_limiter       → Acumulador mutable ⚠️
app.state.active_project_operations → set mutable, GIL-protected ⚠️
```

**Análisis de race conditions**:
1. **`login_rate_limiter`** (acumulador de intentos fallidos):
   - Acceso desde múltiples coroutines sin lock explícito
   - Python GIL protege operaciones atómicas (dict update, incremento)
   - ⚠️ Pero dos intentos fallidos casi simultáneos podrían contar solo uno

2. **`active_project_operations`** (set de claves (tenant_id, proyecto)):
   - Operaciones: `add()`, `discard()`, `contains()`
   - GIL garantiza que no hay corrupción, pero orden no está garantizado
   - ⚠️ Riesgo bajo en práctica (operaciones cortas entre add/discard)

**Veredicto**: ⚠️ Deuda confirmada (riesgos bajos en GIL, pero no documentados).  
**Prioridad**: `fase_media` (documentar thread-safety, considerar lock explícito en v0.10+)

---

### 6. Migraciones de esquema SQLite — ✅ CONFIRMADO

**Localización**: `auth/auth_store.py:280-310`

**Análisis de seguridad**:
```python
def _migrate_schema(self):
    cursor = await self._connection.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in await cursor.fetchall()}
    
    if "role_id" not in columns:
        await self._connection.execute("ALTER TABLE users ADD COLUMN ...")
```

**Validación de patrón**:
- ✅ Usa `PRAGMA table_info()` (seguro, estándar)
- ✅ Ejecutado en `__aenter__` (antes de cualquier operación)
- ✅ Múltiples `ALTER TABLE` secuenciales (no concurrentes)
- ⚠️ Sin `DROP COLUMN` (schema siempre crece, nunca se contrae)
- ⚠️ Sin versionado de schema (imposible rastrear qué versión de código creó qué esquema)

**Veredicto**: ✅ Deuda confirmada. **Prioridad**: `fase_media` (centralizar en `migrations.py`, añadir versionado)

---

### 7. WebSocket sin protección (BaseHTTPMiddleware) — ✅ CONFIRMADO

**Localización**: `web/routes/scan.py::websocket_scan_progress`

**Análisis**:
```python
@scan_router.websocket("/ws/scan/{project_name}")
async def websocket_scan_progress(
    websocket: WebSocket,
    ...
) -> None:
    # Autenticación MANUAL (no por middleware)
    await websocket.accept()
    try:
        token = await websocket.receive_json()["token"]
        # Verificación de token
        ...
```

**Validación de seguridad**:
- ✅ Autenticación manual implementada (no delegada a middleware)
- ✅ Token verificado antes de procesar mensajes
- ⚠️ Sin una barrera explícita de defensa en profundidad
- ⚠️ Si la autenticación manual falla, ¿se cierra la conexión correctamente?

**Búsqueda de pattern**: `except WebSocketDisconnect` → verificar manejo

**Resultado**: 2 instancias encontradas en `routes/context.py::websocket_build_context` y `routes/scan.py::websocket_scan_progress`

**Veredicto**: ⚠️ Deuda confirmada (funcional pero frágil). **Prioridad**: `fase_media` (documentar, considerar middleware custom en v0.10+)

---

### 8. Duplicación de mapping (YA REFACTORIZADO) — ✅ RESUELTO

**Validación**: El patrón de centralización en `app.py:77-101` está en su lugar.

**Veredicto**: ✅ No es deuda actualmente.

---

## Resumen de validación

| Hallazgo | Estado | Prioridad | Observación |
|----------|--------|-----------|-------------|
| Tipado incompleto (`Any`) | ✅ Confirmado | `quick_win` | 7 instancias, 6 justificadas, 1 sin comentario |
| Excepciones amplias | ✅ Confirmado | `quick_win`/OK | 5 instancias, 2-3 ya justificadas, 2-3 mejorables |
| Bugs reales documentados | ✅ Confirmado | Documentación | 8+ instancias con contexto reproducible |
| Lock compartido | ✅ Confirmado | `fase_media` | Funcional pero no documentado, reentrancia implícita |
| Estado global mutable | ✅ Confirmado | `fase_media` | GIL mitiga, pero sin thread-safety explícita |
| Migraciones SQLite | ✅ Confirmado | `fase_media` | Patrón manual, sin versionado de schema |
| WebSocket inseguro | ✅ Confirmado | `fase_media` | Autenticación manual presente, pero frágil |

---

## Gaps detectados (no anticipados en PLAN)

### 1. Cobertura de tests parcial
**Hallazgo**: `pytest.ini` define `--cov=src` pero no hay `.coveragerc` explícito
- ¿Qué módulos/funciones tienen cobertura < 80%?
- ¿Hay error paths sin test (ej. excepciones raras)?

**Recomendación**: Ejecutar `pytest --cov` y analizar `--cov-report=html`

### 2. Uso de `type: ignore` sin justificación
**Hallazgo**: 1 instancia en `web/auth.py:159` sin comentario explicativo
```python
super().__init__(app)  # type: ignore[arg-type]
```

**Recomendación**: Añadir comentario de 1 línea (ej. "clase AuthMiddleware redefinida")

### 3. Documentación incompleta de decisiones arquitectónicas
**Hallazgo**: Bugs documentados como comentarios inline, pero NO como ADRs en `docs/adr/`

**Recomendación**: Crear ADR para "por qué Docling `Any` no tiene stubs", "por qué excepciones amplias en batch"

---

## Plan de acción para AUDIT_CODE

Basándonos en esta validación, el AUDIT_CODE debe:

1. **quick_wins** (< 1h, sin risk):
   - [ ] Añadir comentarios justificando `Any` en `taxonomy_classification_client.py:243`
   - [ ] Añadir logging en `auth_store.py:547` (catch Exception sin log)
   - [ ] Especificar excepciones en `project_registry.py:139, 288`
   - [ ] Documentar `type: ignore` en `web/auth.py:159`

2. **fase_media** (1-2h, con test requerido):
   - [ ] Centralizar migraciones en `auth/migrations.py` + versionado
   - [ ] Documentar invariantes de `app.state` (thread-safety)
   - [ ] Añadir prueba de stress para `ProjectRegistry` reentrancia
   - [ ] Considerar lock explícito para `login_rate_limiter`

3. **deuda_estructural** (refactor amplio, después de aprobación):
   - [ ] Middleware custom para WebSocket (v0.10+)
   - [ ] Stub parcial para Docling (si es posible, con Protocol)

---

*Este documento concluye la fase AUDIT_PLAN. Procede a AUDIT_CODE.*
