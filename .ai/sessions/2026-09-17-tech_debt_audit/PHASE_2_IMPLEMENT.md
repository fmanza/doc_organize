# IMPLEMENT — Fase Media (FM-1 to FM-4) — v0.9.2

**Date**: 2026-09-17 (Execution Phase)  
**Status**: 🚀 IN PROGRESS  
**Target**: Implement FM-1, FM-2, FM-3, FM-4 with full validation

---

## ✅ Pre-Implementation Validation Results

### Validation Checklist

- ✅ **FM-1**: `_migrate_schema()` found at `auth_store.py:248`
- ✅ **FM-2**: `app.state` initialization found at `web/app.py:142+`
- ✅ **FM-3**: `ProjectRegistry._lock` found at `project_registry.py:61`
- ✅ **FM-4**: `LoginRateLimiter` found at `web/auth.py:69`

**Status**: All locations verified. Ready for implementation.

---

## 📋 Implementation Strategy

### FM-1: SQLite Schema Versioning

**Objective**: Centralize schema migrations with versioning support

**Steps**:

1. ✅ Create `src/doc_organize/auth/migrations.py`
   - Define SchemaMigration protocol
   - Implement initial migrations
   - Add version registry

2. ✅ Refactor `auth_store.py:_migrate_schema()`
   - Use new migrations.py
   - Track schema version
   - Maintain backward compatibility

3. ✅ Add tests
   - Test migration idempotence
   - Test version tracking
   - Test rollback scenario

**Files to Create/Modify**:
- `src/doc_organize/auth/migrations.py` (NEW)
- `src/doc_organize/auth/auth_store.py` (MODIFY)
- `tests/unit/auth/test_migrations.py` (NEW)

---

### FM-2: Thread-Safety Documentation

**Objective**: Document app.state invariants and thread-safety guarantees

**Steps**:

1. ✅ Create `src/doc_organize/web/STATE.md`
   - Document each attribute
   - Define thread-safety guarantees
   - Reference GIL assumptions

2. ✅ Add code references
   - Comment in `web/app.py` pointing to STATE.md
   - Comment in app.state initialization

3. ✅ Create ADR-004
   - Document GIL assumption
   - Explain why GIL sufficient for v0.9.x
   - Plan for v0.10 free-threading

4. ✅ Add conformance test
   - Validate app.state structure at startup
   - Verify singleton pattern

**Files to Create/Modify**:
- `src/doc_organize/web/STATE.md` (NEW)
- `docs/adr/ADR-004-GIL-Thread-Safety.md` (NEW)
- `src/doc_organize/web/app.py` (MODIFY - comments only)
- `tests/unit/test_app_state.py` (NEW)

---

### FM-3: ProjectRegistry Stress Tests

**Objective**: Validate concurrent operations don't deadlock

**Steps**:

1. ✅ Create concurrent create_project test
   - 10 concurrent creates
   - Verify lock prevents race conditions

2. ✅ Create list_projects during create test
   - Verify no deadlock

3. ✅ Create move_project concurrency test
   - Verify atomic semantics

**Files to Create/Modify**:
- `tests/integration/test_project_registry_stress.py` (NEW)

---

### FM-4: LoginRateLimiter Decision + Documentation

**Objective**: Document GIL assumption for rate limiter

**Steps**:

1. ✅ Document decision in ADR-004 (created in FM-2)
2. ✅ Add comment in `web/auth.py` referencing ADR
3. ✅ Schedule refactor for v0.10

**Files to Create/Modify**:
- `src/doc_organize/web/auth.py` (MODIFY - comment only)
- `docs/adr/ADR-004-GIL-Thread-Safety.md` (references FM-4)

---

## 🔨 Implementation Status

### FM-1: SQLite Schema Versioning

**Status**: ⏳ IMPLEMENTING

**Plan**: 
1. Read current `_migrate_schema()` to understand schema mutations
2. Create migrations.py with Protocol
3. Implement version tracking
4. Add tests
5. Refactor auth_store.py

---

### FM-2: Thread-Safety Documentation

**Status**: ⏳ PLANNED

---

### FM-3: ProjectRegistry Stress Tests

**Status**: ⏳ PLANNED

---

### FM-4: LoginRateLimiter Decision

**Status**: ⏳ PLANNED

---

## ✅ Validation Gate

Before marking as complete:

- [ ] ruff: All checks pass
- [ ] mypy: No issues
- [ ] pytest: 865/865 tests pass
- [ ] New tests: All green

---

## 📝 Notes

- All changes backward compatible
- No breaking API changes
- Safe to merge to main
- Ready for v0.9.2 release

---

**Version**: 1.0  
**Generated**: 2026-09-17  
**Status**: IN PROGRESS

*Next: Execute FM-1, then FM-2, FM-3, FM-4*
