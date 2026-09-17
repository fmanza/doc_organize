# AUDIT_CODE: Deuda Técnica Detallada — doc_organize v0.9.0

**Fecha**: 2026-09-17  
**Objetivo**: Presentar hallazgos de deuda técnica por prioridad, con código exacto, impacto, y estrategia de remediación

---

## Veredicto Final Preliminar

**Estado**: `DEUDA_MENOR` (hallazgos presentes, pero no críticos; v0.9.0 es usable)

**Justificación**:
- ✅ Tipado: Pydantic v2 fuerte (salvo excepciones deliberadas por Docling)
- ✅ Excepciones: Jerárquica y específica (salvo 2-3 casos de excepciones amplias justificadas)
- ✅ Testing: Suite completa (251 tests)
- ⚠️ Documentación: Bugs inline, sin GitHub Issues centralizados
- ⚠️ Thread-safety: No explícitamente documentada en `app.state`
- ⚠️ Migraciones SQLite: Manual pero funcional

**Impacto en producción**: Bajo (librería estable, no hay crashloops o data corruption).  
**Impacto en mantenibilidad**: Medio (deuda acumulada, requiere refactor en v0.10+).

---

## QUICK WINS (< 1h, sin riesgo, implementables ahora)

### QW-1: Documentar `Any` en `taxonomy_classification_client.py:243`

**Localización**: `src/doc_organize/ai/taxonomy_classification_client.py:243`

**Código actual**:
```python
def _clamp_confidence(raw: Any) -> float:
    """Restringe confidencia del modelo al rango [0, 1] inclusivo."""
    ...
```

**Problema**: Sin comentario explicativo sobre por qué `Any` es necesario.

**Impacto**: Bajo (solo afecta a este método local, no es parte de API pública).

**Remediación**:
```python
def _clamp_confidence(raw: Any) -> float:  # type: ignore[misc]
    """Restringe confidencia del modelo al rango [0, 1] inclusivo.
    
    Args:
        raw: Valor de confidencia del modelo (sin tipo conocido, puede ser float, int, o string numérica).
    
    Returns:
        float en [0, 1].
    """
    ...
```

**Effort**: 1 línea de comentario.  
**Risk**: Ninguno.

---

### QW-2: Añadir logging en `auth_store.py:547`

**Localización**: `src/doc_organize/auth/auth_store.py:547-550`

**Código actual**:
```python
try:
    ...  # _backfill_instance_admins() logic
except Exception:
    # Rollback silencioso en caso de error (no aborta apertura de BD)
    pass
```

**Problema**: Sin logging, difícil debuguear si la backfill falló.

**Impacto**: Bajo (fallback defensivo en inicialización).

**Remediación**:
```python
try:
    ...  # _backfill_instance_admins() logic
except Exception as exc:
    # Rollback silencioso en caso de error (no aborta apertura de BD)
    # pero registramos el evento para debugging.
    self.logger.warning(f"No se pudo completar backfill de instance admins: {exc}", exc_info=True)
```

**Effort**: 1 línea de logging + contexto.  
**Risk**: Ninguno.

---

### QW-3: Especificar excepciones en `project_registry.py:139`

**Localización**: `src/doc_organize/projects/project_registry.py:135-145`

**Código actual**:
```python
try:
    with open(self._projects_path, "r", encoding="utf-8") as f:
        data = json.load(f)
except FileNotFoundError:
    return []  # Proyecto nuevo, sin projects.json todavía
except OSError as exc:
    self.logger.error(f"No se puede leer projects.json: {exc}")
    raise
except Exception:
    # Cualquier otra excepción (JSON malformado, encoding, etc.)
    self.logger.error(f"Error inesperado leyendo projects.json")
    return []
```

**Problema**: `except Exception` es amplia; debería especificarse `json.JSONDecodeError`.

**Impacto**: Bajo (fallback defensivo).

**Remediación**:
```python
try:
    with open(self._projects_path, "r", encoding="utf-8") as f:
        data = json.load(f)
except FileNotFoundError:
    return []  # Proyecto nuevo, sin projects.json todavía
except OSError as exc:
    self.logger.error(f"No se puede leer projects.json: {exc}")
    raise
except json.JSONDecodeError as exc:
    self.logger.error(f"projects.json está malformado (JSON inválido): {exc}")
    return []
```

**Effort**: Cambio de `except Exception` a `except json.JSONDecodeError`.  
**Risk**: Bajo (mejora captura de errores específicos).

---

### QW-4: Documentar `type: ignore` en `web/auth.py:159`

**Localización**: `src/doc_organize/web/auth.py:155-165`

**Código actual**:
```python
class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, security: SecurityConfig, auth_db_path: str | None):
        super().__init__(app)  # type: ignore[arg-type]
```

**Problema**: Sin justificación de por qué `type: ignore` es necesario.

**Impacto**: Bajo (solo afecta a inicialización de middleware).

**Remediación**:
```python
class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, security: SecurityConfig, auth_db_path: str | None):
        # type: ignore[arg-type] → BaseHTTPMiddleware.__init__ espera `Callable` sin parámetros,
        # pero Starlette acepta app directamente. Mypy no lo entiende, ignoramos.
        super().__init__(app)
```

**Effort**: 1-2 líneas de comentario explicativo.  
**Risk**: Ninguno.

---

### QW-5: Centralizar documentación de bugs reales en GitHub Issues

**Problema**: 8+ bugs reales documentados como comentarios inline, sin issue centralizado.

**Ejemplos**:
- `converter.py:183` → "bug real: sesión 2026-09-16" (Docling `.xls` con LibreOffice)
- `converter.py:223` → "bug real: informe ZAP" (documento .docx grande)
- `converter.py:293` → "bug real: `.docx` con nombre especiales"

**Remediación**:
Crear GitHub Issues de referencia para cada bug:
- [ ] Issue #XXX: "Docling `.xls` sin LibreOffice falla sin mensaje claro" → ref. sesión 2026-09-16
- [ ] Issue #XXX: "Excepciones sin mensaje en .docx grande (~60 MB)" → ref. sesión 2026-09-05
- [ ] Issue #XXX: "Archivo `.docx` con nombre con caracteres especiales"
- ... (4+ más)

Luego actualizar comentarios de código para referenciar el issue:
```python
# Before:
# bug real: sesion 2026-09-16, Docling falla con .xls sin LibreOffice

# After:
# GitHub Issue #XXX: Docling `.xls` sin LibreOffice falla sin mensaje claro
# Workaround: detect_office_status() en línea 185
```

**Effort**: ~30 min (crear issues, actualizar referencias).  
**Risk**: Ninguno (solo documenta).

---

## FASE MEDIA (1-2h, con test requerido, cambios acotados)

### FM-1: Centralizar migraciones SQLite con versionado

**Localización**: `src/doc_organize/auth/auth_store.py:280-310` (`_migrate_schema`, `_migrate_roles_schema`, `_backfill_missing_roles`, `_backfill_instance_admins`)

**Problema**:
1. Lógica de migración distribuida en múltiples métodos
2. Sin versionado de schema (imposible rastrear qué versión ejecutó qué migración)
3. Ejecutada en `__aenter__` cada vez (ineficiente)
4. Difícil de testear aisladamente

**Código actual** (fragmento):
```python
async def __aenter__(self):
    self._connection = await aiosqlite.connect(...)
    await self._connection.execute("PRAGMA journal_mode=WAL")
    await self._ensure_default_tenant_bootstrap()
    await self._migrate_schema()  # ← varias migraciones inline
    await self._migrate_roles_schema()
    await self._backfill_missing_roles()
    await self._backfill_instance_admins()
    ...
```

**Impacto**: Medio (arquitectura de BD frágil para evoluciones futuras).

**Remediación** (PLAN + estrategia, no IMPLEMENT):

**Paso 1**: Crear `src/doc_organize/auth/migrations.py`
```python
# auth/migrations.py
from typing import Protocol
from aiosqlite import Connection

class Migration(Protocol):
    """Contrato para una migración de schema."""
    version: int
    description: str
    
    async def up(self, conn: Connection) -> None:
        """Ejecutar migración hacia arriba."""
        ...
    
    async def down(self, conn: Connection) -> None:
        """Ejecutar migración hacia atrás (rollback)."""
        ...

class M001_InitialSchema(Migration):
    version = 1
    description = "Schema inicial (tenants, roles, users, sessions)"
    
    async def up(self, conn: Connection) -> None:
        # La lógica actual de _SCHEMA en auth_store.py
        ...

class M002_AddRoleFields(Migration):
    version = 2
    description = "Añadir is_admin, created_at a roles; eliminar tenant_id"
    
    async def up(self, conn: Connection) -> None:
        # La lógica actual de _migrate_roles_schema()
        ...

# Etc.

MIGRATIONS = [M001_InitialSchema(), M002_AddRoleFields(), ...]
```

**Paso 2**: Crear tabla de control de versiones:
```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    executed_at TEXT NOT NULL
);
```

**Paso 3**: Refactor de `AuthStore.__aenter__`:
```python
async def __aenter__(self):
    self._connection = await aiosqlite.connect(...)
    await self._connection.execute("PRAGMA journal_mode=WAL")
    
    # Nueva llamada centralizada
    await self._run_pending_migrations()
    
    # Operaciones normales de bootstrap
    await self._ensure_default_tenant_bootstrap()
    ...

async def _run_pending_migrations(self):
    """Ejecuta todas las migraciones pendientes (versiones > `schema_version.max`)."""
    from doc_organize.auth.migrations import MIGRATIONS
    
    cursor = await self._connection.execute("SELECT MAX(version) FROM schema_version")
    (current_version,) = await cursor.fetchone() or (0,)
    
    for migration in MIGRATIONS:
        if migration.version > current_version:
            await migration.up(self._connection)
            await self._connection.execute(
                "INSERT INTO schema_version (version, description, executed_at) VALUES (?, ?, ?)",
                (migration.version, migration.description, datetime.now(UTC).isoformat())
            )
            self.logger.info(f"Migración M{migration.version:03d}: {migration.description}")
```

**Testing**:
- [ ] Unit test: `test_migrations_run_in_order()`
- [ ] Unit test: `test_migration_M002_adds_role_fields()`
- [ ] Integration test: `test_no_pending_migrations_after_init()`

**Effort**: ~90 min (refactor + tests).  
**Risk**: Bajo (refactor puro, lógica sin cambios).  
**Benefits**: Schema versioning, facilita evoluciones futuras, mejor testabilidad.

---

### FM-2: Documentar thread-safety de `app.state`

**Localización**: `src/doc_organize/web/app.py:75-110` (inicialización de `app.state.*`)

**Problema**:
1. Sin documentación explícita de qué es thread-safe y qué no
2. GIL proporciona protección implícita, pero no documentada
3. Futura migración a ASGI worker con múltiples procesos podría romper invariantes

**Remediación** (solo documentación):

Crear `src/doc_organize/web/STATE.md`:
```markdown
# Thread-Safety de `app.state`

## Invariantes garantizadas

### `app.state.project_registry` (ProjectRegistry)
- **Protección**: `asyncio.Lock` interno (reentrante desde el mismo coroutine)
- **Acceso**: Vía context manager `async with get_project_registry(request):`
- **Garantía**: No hay escrituras concurrentes a `projects.json`
- **Nota**: Cada request abre/cierra la instancia UNA vez (no hay nido múltiple)

### `app.state.login_rate_limiter` (LoginRateLimiter)
- **Protección**: Python GIL (operaciones atómicas)
- **Acceso**: Directo desde `/login`
- **Riesgo**: Dos intentos fallidos casi simultáneos podrían contar solo uno
- **Plan v0.10+**: Considerar asyncio.Lock explícito

### `app.state.active_project_operations` (set)
- **Protección**: Python GIL (operaciones `add()`, `discard()` atómicas)
- **Acceso**: Desde rutas de scan/dedup
- **Garantía**: Sin corrupción de set, pero orden no garantizado
- **Plan v0.10+**: Considerar asyncio.Lock si necesita garantías de ordering

### Campos inmutables (sin protección necesaria)
- `app.state.auth_db_path` (str)
- `app.state.security` (SecurityConfig)
- `app.state.taxonomy_template_registry` (TaxonomyTemplateRegistry)

## Notas

1. Este documento es válido solo para ejecución con uvicorn de un solo worker.
2. Si migramos a Gunicorn (múltiples workers), el estado compartido se pierde.
3. Revisar antes de implementar caché distribuida.
```

Luego actualizar `app.py` con referencia:
```python
# web/app.py
"""
FastAPI app factory.

NOTA: Lee web/STATE.md para entender la thread-safety de app.state
(reentrancia, GIL, invariantes garantizadas).
"""
```

**Effort**: ~30 min (documento + referencias).  
**Risk**: Ninguno (solo documenta).  
**Benefits**: Claridad arquitectónica, facilita futuras migraciones.

---

### FM-3: Añadir prueba de stress para ProjectRegistry reentrancia

**Localización**: `tests/unit/test_project_registry.py` (agregar prueba)

**Código de prueba propuesto**:
```python
import asyncio
import pytest

@pytest.mark.asyncio
async def test_project_registry_reentrancy_stress(tmp_path):
    """Verificar que ProjectRegistry es seguro bajo carga concurrente."""
    from doc_organize.projects.project_registry import ProjectRegistry
    
    registry = ProjectRegistry(tmp_path / "projects.json")
    
    async def create_and_list_project(i: int):
        """Crear un proyecto y listarlo."""
        async with registry:
            await registry.create_project(
                name=f"proj-{i}",
                root_path=tmp_path / f"proj-{i}"
            )
        
        # Segunda operación en proyecto mismo (genera stress en lock)
        async with registry:
            projects = await registry.list_projects()
            assert any(p.name == f"proj-{i}" for p in projects)
    
    # Crear 10 proyectos en paralelo (stress test)
    await asyncio.gather(*[create_and_list_project(i) for i in range(10)])
    
    # Verificar que ningún proyecto se perdió
    async with registry:
        projects = await registry.list_projects()
    assert len(projects) == 10
```

**Effort**: ~20 min (escribir + ejecutar test).  
**Risk**: Ninguno (test no destructivo).  
**Benefits**: Garantía de que lock + context manager funcionan bajo presión.

---

### FM-4: Considerar lock explícito para `login_rate_limiter`

**Localización**: `src/doc_organize/web/auth.py` (clase `LoginRateLimiter`)

**Problema**: GIL no garantiza orden de operaciones a través de múltiples intentos fallidos casi simultáneos.

**Código actual** (fragmento):
```python
class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, lockout_minutes: int = 15):
        self.max_attempts = max_attempts
        self.lockout_minutes = lockout_minutes
        self.failed_attempts: dict[str, int] = {}  # ← sin lock
        self.lockout_times: dict[str, datetime] = {}  # ← sin lock
```

**Remediación** (PLAN, no IMPLEMENT):

Opción A (Conservadora, actual):
- Mantener GIL como protección, documentar en STATE.md ✅ (recomendado)
- Añadir comentario: "thread-safe gracias a GIL, pero no garantiza orden"

Opción B (Robusta, v0.10+):
```python
class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, lockout_minutes: int = 15):
        self.max_attempts = max_attempts
        self.lockout_minutes = lockout_minutes
        self._lock = asyncio.Lock()  # ← nuevo
        self.failed_attempts: dict[str, int] = {}
        self.lockout_times: dict[str, datetime] = {}
    
    async def record_failed_attempt(self, username: str) -> bool:
        async with self._lock:  # ← protección explícita
            ...
```

**Decision**: Implementar Opción A (conservadora) ahora, dejar Opción B como tech debt documented.

---

## DEUDA ESTRUCTURAL (refactor amplio, aprobación previa)

### DS-1: Middleware custom para WebSocket

**Localización**: `src/doc_organize/web/routes/scan.py::websocket_scan_progress`, `context.py::websocket_build_context`

**Problema**:
1. `BaseHTTPMiddleware` NO protege rutas WebSocket
2. Autenticación manual requerida en handler (duplicación de lógica)
3. Sin barrera de defensa en profundidad

**Impacto**: Medio (funcional, pero frágil).

**Remediación** (PLAN, no IMPLEMENT):

**Opción A (v0.9.1, quick fix)**: Documentar que WebSocket requiere autenticación manual + refactor mínimo:
```python
# web/websocket_auth.py (nuevo módulo)
from fastapi import WebSocket, status

async def authenticate_websocket(websocket: WebSocket, auth_db_path: str) -> tuple[str, str]:
    """Autentica WebSocket y retorna (tenant_id, username).
    
    Raises:
        ConnectionRefusedError: Si el token no es válido.
    """
    await websocket.accept()
    try:
        msg = await websocket.receive_json()
        token = msg.get("token")
        if not token:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Token requerido")
            raise ConnectionRefusedError("Token faltante")
        
        # Verificar token...
        return tenant_id, username
    except Exception as exc:
        await websocket.close(code=status.WS_1011_SERVER_ERROR)
        raise
```

Luego importar en handlers:
```python
# web/routes/scan.py
@scan_router.websocket("/ws/scan/{project_name}")
async def websocket_scan_progress(websocket: WebSocket, ...):
    tenant_id, username = await authenticate_websocket(websocket, auth_db_path)
    # resto de la lógica...
```

**Opción B (v0.10+, robust)**: Crear middleware custom que NO es BaseHTTPMiddleware:
```python
# web/middleware.py
from starlette.middleware.base import Middleware
from starlette.routing import WebSocketRoute

class AuthWebSocketMiddleware:
    """Middleware que autentica WebSocket sin usar BaseHTTPMiddleware."""
    
    def __init__(self, app, security_config):
        self.app = app
        self.security_config = security_config
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            # Lógica de autenticación ASGI-level
            ...
        else:
            await self.app(scope, receive, send)
```

**Decision**: Implementar Opción A en v0.9.1 (30 min), planificar Opción B para v0.10 (refactor más amplio).

---

### DS-2: Stub parcial para Docling (sin tipo conocido)

**Localización**: `src/doc_organize/converter/converter.py` (múltiples `Any` de Docling)

**Problema**: Docling no proporciona `.pyi` stubs → `Any` sin restricción

**Remediación** (PLAN, no IMPLEMENT):

**Opción A (v0.9.1)**: Crear stub parcial local:
```python
# typings/docling.pyi
from typing import Any, Protocol

class Document(Protocol):
    """Placeholder: interfaz mínima de DoclingDocument."""
    def get_text() -> str: ...

# typings/docling_converter.pyi
...
```

Luego en `converter.py`:
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docling import Document as DoclingDocument
else:
    DoclingDocument = Any

def _build_chunks(self, document: DoclingDocument, ...) -> list[dict]:
    ...
```

**Opción B (v0.10+)**: Contribuir stubs a pyright/typeshed.

**Decision**: Documentar la limitación en ADR (ver abajo), no prioridad de remediación.

---

## Hallazgos por módulo (matriz de impacto)

| Módulo | Hallazgo | Prioridad | Impacto | Effort | Risk |
|--------|----------|-----------|--------|--------|------|
| `ai/taxonomy_classification_client.py` | `Any` sin comentario | QW-1 | Bajo | 1 min | 0 |
| `auth/auth_store.py` | `except Exception` sin log | QW-2 | Bajo | 1 min | 0 |
| `auth/auth_store.py` | Migraciones SQLite manual | FM-1 | Medio | 90 min | Bajo |
| `projects/project_registry.py` | `except Exception` ampla | QW-3 | Bajo | 5 min | 0 |
| `web/auth.py` | `type: ignore` sin doc | QW-4 | Bajo | 2 min | 0 |
| `web/app.py` | `app.state` sin thread-safety doc | FM-2 | Medio | 30 min | 0 |
| `web/app.py` | Lock + context manager frágil | FM-3 | Medio | 20 min | 0 |
| `web/auth.py` | `login_rate_limiter` sin lock | FM-4 | Bajo | 0 (documentar) | 0 |
| `web/routes/scan.py` | WebSocket sin middleware | DS-1 | Medio | 30 min | Bajo |
| `converter/converter.py` | Docling `Any` sin stubs | DS-2 | Bajo | 0 (ADR) | 0 |
| `converter/converter.py` | 8+ bugs reales inline | QW-5 | Medio (docs) | 30 min | 0 |

---

## Matriz de riesgos residuales

### Riesgos por severidad

| Riesgo | Severidad | Mitigation | Status |
|--------|-----------|------------|--------|
| Crash de batch por excepción no capturada | Baja | GIL + specific exception types | Mitigado |
| Data corruption en cache.db | Mínima | Transacciones SQLite + WAL | Protegido |
| Auth bypass vía WebSocket | Baja | Autenticación manual implementada | Actual |
| Concurrencia en app.state | Baja | GIL + bajo contention | Mitigado |
| Tipo-checking fallido en tipo-stubs externos | Baja | Docling sin stubs públicos | Aceptado |

### Recomendaciones de mitigación

1. ✅ Implementar todos los **quick wins** inmediatamente (sin risk)
2. ⚠️ Planificar **fase_media** en v0.9.1 (1-2 week sprint)
3. 📋 Documentar **deuda_estructural** como ADR y tech_debt para v0.10

---

## ADRs recomendadas

### ADR-001: Por qué `Any` en Docling es aceptable

**Contexto**: Docling no proporciona type stubs (.pyi).

**Decisión**: Aceptamos `Any` para parámetros/retornos de Docling, pero con comentarios explícitos.

**Consecuencias**:
- ✅ Sin bloqueo en type-checking
- ❌ Pérdida de información de tipo en esos boundaries
- 📋 Futura contribución a typeshed es posible

---

### ADR-002: Por qué excepciones amplias en batch processing

**Contexto**: Un documento bloqueado (permiso denegado, fichero en uso) no debe abortar la conversión de todo el batch.

**Decisión**: Capturar `except Exception` en `converter.convert()`, registrar en `ConversionResult(success=False, error=...)`.

**Consecuencias**:
- ✅ Robustez de batch mejorada
- ✅ Error reporting granular por documento
- ⚠️ Excepciones inesperadas quedan silenciosas (mitigado por logging)

---

### ADR-003: Thread-safety en app.state bajo GIL

**Contexto**: `app.state` contiene objetos mutables (dict, set) accedidos por múltiples coroutines.

**Decisión**: Confiar en GIL para operaciones atómicas, pero documentar explícitamente.

**Consecuencias**:
- ✅ Sin overhead de locks explícitos
- ❌ No portátil a PyPy, no-GIL, Jython, IronPython
- 📋 Revisar antes de migraciones a múltiples workers (Gunicorn)

---

## Acciones recomendadas (por fases)

### v0.9.1 (1 week)
- [ ] Implementar QW-1 (documentar `Any`)
- [ ] Implementar QW-2 (logging en `auth_store`)
- [ ] Implementar QW-3 (especificar excepciones)
- [ ] Implementar QW-4 (documentar `type: ignore`)
- [ ] Implementar QW-5 (crear GitHub Issues)

### v0.9.2 (2 weeks)
- [ ] Implementar FM-1 (migraciones SQLite)
- [ ] Implementar FM-2 (documentación app.state)
- [ ] Implementar FM-3 (prueba de stress)
- [ ] Implementar FM-4 (decision sobre login_rate_limiter)

### v0.10 (future)
- [ ] Implementar DS-1 (WebSocket middleware)
- [ ] Implementar DS-2 (Docling stubs)
- [ ] Revisar y consolidar todas las ADRs

---

## Conclusión

**Estado**: `DEUDA_MENOR` — manejable, no bloquea producción.

**Veredicto**: ✅ **Aprobado para producción** con tareas de documentación inmediatas (QW-1 a QW-5).

**Next**: Ejecutar PLAN de remediación secuencial, beginning con quick wins.

---

*Documento final de AUDIT_CODE. Procede a VERSION para cierre.*
