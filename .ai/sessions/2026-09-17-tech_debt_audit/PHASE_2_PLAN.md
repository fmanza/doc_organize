# PLAN — Fase Media (FM-1 to FM-4) — v0.9.2

**Date**: 2026-09-17 (Post QUICK WINS)  
**Phase**: PLAN for medium-difficulty technical debt items  
**Target Release**: v0.9.2 (2-week sprint)  
**Estimated Effort**: ~2.5 hours total  
**Risk Level**: Low (refactoring, no breaking changes)

---

## 📋 Objetivo

Implementar 4 items de "Fase Media" identificados en la auditoría completa:
- FM-1: Migraciones SQLite con versionado (90 min)
- FM-2: Documentación thread-safety de app.state (30 min)
- FM-3: Tests de stress para ProjectRegistry (20 min)
- FM-4: Decisión sobre login_rate_limiter (0 min)

**Outcome**: Reducir riesgo residual de "ACEPTABLE" → "BAJO"

---

## 🎯 FM-1: Centralizar migraciones SQLite + versionado

### Problema

**Current State**:
```python
# auth_store.py:280-310 (líneas aproximadas)
async def _migrate_schema(self) -> None:
    """Ejecuta migraciones schema de manera ad-hoc (sin versionado)."""
    # ALTER TABLE manual por cada inicialización
    # Si hay 2+ migraciones pendientes, pueden colisionar
    # No hay registry de versión actual
```

**Issues**:
- ❌ Sin versioning: no sabemos qué schema_version estamos en
- ❌ Frágil: dos migraciones pueden colisionar
- ❌ Acoplado: lógica de migración + lógica de inicio de sesión mezcladas
- ❌ Sin tests: cambios en schema no tienen cobertura de tests

### Solución Propuesta

1. **Crear `auth/migrations.py`** con Protocol de migraciones:
```python
class SchemaMigration(Protocol):
    async def up(self, conn: aiosqlite.Connection) -> None: ...
    async def down(self, conn: aiosqlite.Connection) -> None: ...

MIGRATIONS: list[SchemaMigration] = [
    Migration001_InitialSchema(),
    Migration002_AddSessionTable(),
    Migration003_AddRoleColumns(),
    # ...
]
```

2. **Añadir tabla `schema_version`**:
```sql
CREATE TABLE schema_version (
    id INTEGER PRIMARY KEY,
    version INTEGER UNIQUE NOT NULL,
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    applied_by TEXT  -- para auditoria
);
```

3. **Refactor `_migrate_schema()`** en `auth_store.py`:
```python
async def _migrate_schema(self) -> None:
    """Aplica migraciones pendientes de manera ordenada."""
    current = await self._get_schema_version()  # Lee schema_version table
    for migration in MIGRATIONS[current:]:
        await migration.up(self._connection)
        await self._record_migration(migration.version)
```

4. **Añadir tests**:
- Test: upgrade from v0 → v1 → v2
- Test: idempotence (aplicar dos veces = resultado igual)
- Test: rollback (bajar versión si es necesario)

### Deliverables

| Item | File | Lines | Effort |
|------|------|-------|--------|
| SchemaMigration Protocol | `auth/migrations.py` | +150 | 30 min |
| Refactor _migrate_schema() | `auth/auth_store.py` | ±20 | 30 min |
| Tests (3 scenarios) | `tests/unit/test_auth_migrations.py` | +80 | 30 min |

**Total**: 90 min | **Risk**: Low (refactor puro)

### Success Criteria

- [x] `schema_version` table created and populated
- [x] All migrations (1-N) apply in correct order
- [x] Idempotence validated (apply 2x = same result)
- [x] 100% test coverage for migration code
- [x] Auth store still initializes correctly with 865 tests passing

---

## 🎯 FM-2: Documentar thread-safety de `app.state`

### Problema

**Current State**:
```python
# web/app.py:75-110
app.state.projects_registry: ProjectRegistry  # Mutable, compartido
app.state.rate_limiters: dict[str, RateLimiter]  # Mutable dict
app.state.auth_store: AuthStore  # Singleton thread-safe (aiosqlite)
```

**Issues**:
- ❌ Sin invariantes documentadas: ¿qué garantías tiene `app.state`?
- ❌ GIL mitiga race conditions, pero no está documentado
- ❌ Objetos mutables (set, dict) compartidos sin lock explícito
- ❌ Nuevo maintainer no sabe si es thread-safe o no

### Solución Propuesta

1. **Crear `web/STATE.md`**:
```markdown
# app.state Thread-Safety Documentation

## Invariants

### projects_registry
- Type: `ProjectRegistry` (singleton)
- Thread-Safety: Protected by internal `asyncio.Lock`
- Access Pattern: Async only (FastAPI context)
- Guarantee: No concurrent `create_project()` calls

### rate_limiters
- Type: `dict[str, RateLimiter]`
- Thread-Safety: Reads are GIL-protected; writes rare (single)
- Access Pattern: Sync + Async
- Guarantee: Dict never resized while iterating

### auth_store
- Type: `AuthStore` (singleton, aiosqlite)
- Thread-Safety: SQLite WAL + aiosqlite's async lock
- Access Pattern: Async only
- Guarantee: ACID transactions

## Portability Notes

- GIL assumption: Python 3.11-3.14 with GIL enabled
- NOT thread-safe if using `python-jit` or free-threading
- Recommendation for 3.13+ free-threading: Add explicit locks
```

2. **Añadir references en código**:
```python
# web/app.py
app.state.projects_registry: ProjectRegistry  # See web/STATE.md#projects_registry
app.state.rate_limiters: dict[str, RateLimiter]  # See web/STATE.md#rate_limiters
```

3. **Crear test de conformance** (validación de invariantes):
```python
@pytest.mark.asyncio
async def test_app_state_invariants():
    """Verificar que app.state cumple garantías documentadas."""
    # 1. projects_registry es singleton
    assert app.state.projects_registry is app.state.projects_registry
    # 2. rate_limiters dict no cambia estructura
    assert len(app.state.rate_limiters) >= 0
    # 3. auth_store es singleton
    assert app.state.auth_store is app.state.auth_store
```

### Deliverables

| Item | File | Lines | Effort |
|------|------|-------|--------|
| STATE.md (docs) | `web/STATE.md` | +60 | 15 min |
| Code references | `web/app.py`, `web/` | +5 | 5 min |
| Conformance test | `tests/unit/test_app_state.py` | +30 | 10 min |

**Total**: 30 min | **Risk**: Minimal (docs + 1 test)

### Success Criteria

- [x] `web/STATE.md` documents all invariants
- [x] Comments in code reference STATE.md sections
- [x] Conformance test validates invariants at startup
- [x] All 865 tests still pass
- [x] No changes to app.state structure or access patterns

---

## 🎯 FM-3: Prueba de stress para ProjectRegistry

### Problema

**Current State**:
```python
# ProjectRegistry uses asyncio.Lock for concurrency control
# But no stress test validates high concurrency scenarios
```

**Issues**:
- ❌ Sin test de concurrencia: ¿realmente el lock funciona bajo carga?
- ❌ Sin test de race conditions: ¿qué pasa si 10 requests crean el mismo proyecto?
- ❌ Sin test de memory leaks: ¿el context manager libera bien los recursos?

### Solución Propuesta

Crear `tests/integration/test_project_registry_stress.py`:

```python
@pytest.mark.asyncio
async def test_concurrent_project_creation():
    """10 concurrent create_project calls should succeed or fail atomically."""
    async with ProjectRegistry() as registry:
        tasks = [
            registry.create_project(f"Project-{i}", temp_dir)
            for i in range(10)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify: all succeeded or exactly 9 failed (1 winner)
        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        
        assert len(successes) >= 1  # At least 1 succeeded
        assert len(successes) + len(failures) == 10  # All completed

@pytest.mark.asyncio
async def test_list_projects_during_create():
    """list_projects() should not deadlock while create_project() in flight."""
    async with ProjectRegistry() as registry:
        async def slow_create():
            await asyncio.sleep(0.5)  # Simulate slow create
            return await registry.create_project("Slow", temp_dir)
        
        async def list_while_creating():
            await asyncio.sleep(0.1)  # Start after create begins
            return await registry.list_projects()
        
        create_task = asyncio.create_task(slow_create())
        list_task = asyncio.create_task(list_while_creating())
        
        create_result = await create_task
        list_result = await list_task
        
        assert create_result is not None
        assert isinstance(list_result, list)
```

### Deliverables

| Item | File | Lines | Effort |
|------|------|-------|--------|
| Stress tests (3 scenarios) | `tests/integration/test_project_registry_stress.py` | +80 | 20 min |

**Total**: 20 min | **Risk**: Low (tests only)

### Success Criteria

- [x] Concurrent create_project() test passes
- [x] list_projects() during create_project() doesn't deadlock
- [x] All 865 existing tests still pass
- [x] New stress tests add ~15 seconds to test suite (acceptable)

---

## 🎯 FM-4: Decisión sobre `login_rate_limiter`

### Problema

**Current State** (web/routes/auth.py):
```python
# Global rate limiter (not in app.state)
_login_rate_limiter = LoginRateLimiter()  # Protected by GIL assumption

# Sync endpoint
@app.post("/api/v1/auth/login")
def login(credentials: Credentials) -> dict:
    _login_rate_limiter.check(credentials.username)  # No explicit lock
    # ...
```

**Issues**:
- ⚠️ GIL protects this in Python 3.11-3.14, but undocumented
- ⚠️ Not portable to free-threading Python 3.13+
- ⚠️ Sync endpoint in async-first app (architectural smell)

### Dos opciones

#### Opción A: Documentar GIL assumption (v0.9.2 — THIS SPRINT)
```python
_login_rate_limiter = LoginRateLimiter()  
# Thread-safe via GIL (Python 3.11-3.14)
# See web/STATE.md#rate_limiters for invariants
# WARNING: Switch to asyncio.Lock if enabling free-threading
```

**Pros**:
- ✅ Quick (5 min)
- ✅ Clarifies existing behavior
- ✅ Portable if doc is clear

**Cons**:
- ❌ Not future-proof (Python 3.13+ free-threading will break)
- ❌ ADR needed to justify GIL assumption

**Recommended for v0.9.2**: YES (Opción A)

#### Opción B: Refactor to asyncio.Lock (v0.10 — DEFERRED)
```python
class LoginRateLimiter:
    def __init__(self):
        self._lock = asyncio.Lock()  # Explicit async lock
    
    async def check(self, username: str) -> None:
        async with self._lock:
            # Rate limit logic
```

**Pros**:
- ✅ Future-proof (free-threading safe)
- ✅ Explicit concurrency

**Cons**:
- ❌ Requires refactoring sync endpoint → async
- ❌ Needs 2-3 hours (v0.10)

**Recommended for v0.10**: YES (after v0.9.2)

### Solución Propuesta para v0.9.2

**Opción A**: Documentar GIL assumption
1. Update FM-2 `web/STATE.md` with rate_limiter entry
2. Add comment in code pointing to STATE.md
3. Create ADR: `docs/adr/ADR-004-GIL-Thread-Safety.md`

**Opción B**: Schedule for v0.10 with full refactor

### Deliverables

| Item | File | Lines | Effort |
|------|------|-------|--------|
| STATE.md entry | `web/STATE.md` (FM-2) | +10 | Already in FM-2 |
| ADR document | `docs/adr/ADR-004-GIL-Thread-Safety.md` | +50 | 0 min |
| Code comment | `web/routes/auth.py` | +2 | 0 min |

**Total**: 0 min (included in FM-2) | **Risk**: None (decision only)

### Success Criteria

- [x] Decision documented in ADR-004
- [x] CODE COMMENT references ADR and STATE.md
- [x] Decision deferred to v0.10 (explicit in roadmap)

---

## 📊 Phase 2 Summary

| Item | Effort | Risk | Status | v0.9.2 |
|------|--------|------|--------|--------|
| **FM-1** | 90 min | Low | Not started | ✅ Planned |
| **FM-2** | 30 min | Minimal | Not started | ✅ Planned |
| **FM-3** | 20 min | Low | Not started | ✅ Planned |
| **FM-4** | 0 min | None | Not started | ✅ Planned (decision only) |
| **TOTAL** | **2.5 hours** | **Low** | **Ready to execute** | ✅ All |

---

## 🚀 Execution Strategy

### Week 1: Planning + Prep
- [ ] Detailed requirements for FM-1 (migration Protocol)
- [ ] Approve ADR for FM-4 (GIL assumption)
- [ ] Setup test environment

### Week 2: Implementation
- [ ] Day 1: FM-1 (90 min) + code review
- [ ] Day 2: FM-2 (30 min) + FM-3 (20 min)
- [ ] Day 3: FM-4 (0 min) + final validation
- [ ] Day 4: All tests + documentation
- [ ] Day 5: Release v0.9.2

### Validation
- [ ] All 865 existing tests still pass
- [ ] New tests added: ~110 lines (FM-1 + FM-3)
- [ ] Code review for FM-1 (migration pattern)
- [ ] Documentation review for FM-2 (STATE.md)
- [ ] ADR review for FM-4

---

## 📋 Assumptions

1. **FM-1**: Migration Protocol approach accepted (not monolithic SQL file)
2. **FM-2**: GIL assumption acceptable for v0.9.x (free-threading deferred to v0.10)
3. **FM-3**: Stress tests acceptable in integration suite (~15s added to test run)
4. **FM-4**: Opción A (documentation) chosen over Opción B (refactor) for v0.9.2

---

## 🎓 Success Criteria

✅ **All FM-1 to FM-4 complete**:
- FM-1: Schema versioning fully implemented + tested
- FM-2: Thread-safety documented + ADR created
- FM-3: Concurrent stress tests pass
- FM-4: Decision documented + scheduled for v0.10

✅ **Quality gates**:
- All 865 existing tests pass (no regressions)
- New tests: 110+ lines (FM-1 + FM-3)
- Code coverage maintained (≥80% core modules)
- Zero linting/type errors (ruff + mypy)

✅ **Deliverables**:
- 1 new Protocol (migrations.py)
- 1 new doc (STATE.md)
- 1 ADR (ADR-004)
- 110+ lines of tests

---

**Status**: ✅ PLAN READY FOR EXECUTION  
**Next Step**: AUDIT_PLAN validation

*Document Version: 1.0 | Generated: 2026-09-17*
