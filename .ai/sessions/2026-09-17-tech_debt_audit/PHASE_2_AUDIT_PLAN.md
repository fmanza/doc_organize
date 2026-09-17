# AUDIT_PLAN — Fase Media (FM-1 to FM-4) — v0.9.2

**Date**: 2026-09-17 (Post QUICK WINS)  
**Phase**: AUDIT_PLAN for medium-difficulty items  
**Purpose**: Validate feasibility, identify risks, verify code locations  
**Status**: ✅ READY FOR VALIDATION

---

## 🔍 Pre-Implementation Validation

### Objective

Before executing FM-1 to FM-4, validate that:
1. ✅ All code locations mentioned in PLAN exist in current codebase
2. ✅ Current schema is understood (FM-1 prerequisite)
3. ✅ ProjectRegistry locking mechanism is present (FM-3 prerequisite)
4. ✅ Rate limiter implementation exists (FM-4 prerequisite)
5. ✅ Test infrastructure can support new tests
6. ✅ Effort estimates are realistic

---

## ✅ FM-1 Prerequisite Validation: SQLite Schema + Migraciones

### What we're looking for:

**File**: `src/doc_organize/auth/auth_store.py`  
**Method**: `_migrate_schema()` (approx line 280-310)

**Expected code pattern**:
```python
async def _migrate_schema(self) -> None:
    """..."""
    # ALTER TABLE statements directly
    # No versioning table
    # No migration registry
```

### Validation Steps

#### Step 1: Verify `_migrate_schema()` exists
```bash
$ grep -n "_migrate_schema" src/doc_organize/auth/auth_store.py
```

**Expected output**: Line number(s) showing method definition and calls

#### Step 2: Inspect current schema mutations
Read lines ~280-310 to see what alterations are made

**Expected patterns**:
- `CREATE TABLE` (if not exists)
- `ALTER TABLE` (manual schema changes)
- Multiple statements without transaction or versioning
- No tracking of "which migrations have been applied"

#### Step 3: Verify no existing migration versioning
```bash
$ grep -n "schema_version\|migration\|version" src/doc_organize/auth/auth_store.py | head -20
```

**Expected**: Few/no results (current code doesn't version)

### Feasibility Assessment

**Question**: Can we safely add `schema_version` table?  
**Answer**: ✅ YES
- Reason 1: auth_store already uses SQLite (aiosqlite)
- Reason 2: WAL mode ensures atomicity
- Reason 3: No migration code exists → fresh design possible

**Risk**: Low (additive schema change, backward compatible)

---

## ✅ FM-2 Prerequisite Validation: app.state Thread-Safety

### What we're looking for:

**File**: `src/doc_organize/web/app.py`  
**Section**: app.state initialization (approx line 75-110)

**Expected patterns**:
```python
app.state.projects_registry = ProjectRegistry(...)  # Singleton
app.state.rate_limiters = {...}  # Dict of rate limiters
app.state.auth_store = AuthStore(...)  # Singleton
```

### Validation Steps

#### Step 1: Confirm app.state usage
```bash
$ grep -n "app\.state\." src/doc_organize/web/app.py | head -20
```

**Expected**: 3+ references to state attributes

#### Step 2: Verify singleton pattern
```bash
$ grep -n "async def create_app\|def create_app" src/doc_organize/web/app.py
```

**Expected**: One factory function that creates/assigns app.state

#### Step 3: Check for existing locks
```bash
$ grep -n "asyncio\.Lock\|Lock\|lock" src/doc_organize/web/ -r
```

**Expected**: 
- ProjectRegistry has internal lock ✅
- auth_store doesn't need explicit lock (aiosqlite handles it)
- rate_limiters relies on GIL (undocumented → FM-2 target)

### Feasibility Assessment

**Question**: Is FM-2 just documentation or does it require code changes?  
**Answer**: ✅ Primarily documentation
- Reason 1: Locking already works (GIL-protected)
- Reason 2: No logic changes needed
- Reason 3: Only documentation + test validation

**Risk**: Minimal (docs + conformance test)

---

## ✅ FM-3 Prerequisite Validation: ProjectRegistry Locking

### What we're looking for:

**File**: `src/doc_organize/projects/project_registry.py`  
**Class**: `ProjectRegistry`

**Expected patterns**:
```python
class ProjectRegistry:
    def __init__(self, ...):
        self._lock = asyncio.Lock()
    
    async def create_project(self, ...):
        async with self._lock:
            # Protected section
```

### Validation Steps

#### Step 1: Verify _lock exists
```bash
$ grep -n "self\._lock\|asyncio\.Lock" src/doc_organize/projects/project_registry.py
```

**Expected**: Definition of `self._lock = asyncio.Lock()` in `__init__`

#### Step 2: Verify lock usage in create_project()
```bash
$ grep -n "async with self\._lock\|def create_project" src/doc_organize/projects/project_registry.py
```

**Expected**: `async with self._lock:` protecting project creation

#### Step 3: Verify lock usage in list_projects()
```bash
$ grep -n "async def list_projects\|async with self\._lock" src/doc_organize/projects/project_registry.py
```

**Expected**: `async with self._lock:` or proof that list is read-only

### Feasibility Assessment

**Question**: Can we write stress tests for concurrent operations?  
**Answer**: ✅ YES
- Reason 1: ProjectRegistry already async (supports concurrent calls)
- Reason 2: Lock mechanism is in place
- Reason 3: Test infrastructure supports `pytest.mark.asyncio`

**Risk**: Low (stress tests don't change code, only validate)

---

## ✅ FM-4 Prerequisite Validation: LoginRateLimiter

### What we're looking for:

**File**: `src/doc_organize/web/routes/auth.py` (or similar)  
**Pattern**: Global rate limiter instance

**Expected patterns**:
```python
_login_rate_limiter = LoginRateLimiter()  # Global, no lock
```

### Validation Steps

#### Step 1: Find rate limiter definition
```bash
$ grep -rn "LoginRateLimiter\|_login_rate_limiter" src/doc_organize/web/
```

**Expected**: Definition in routes or dedicated module

#### Step 2: Verify sync endpoint
```bash
$ grep -n "@app\.post.*login\|def login" src/doc_organize/web/routes/auth.py
```

**Expected**: Sync endpoint (not async) using rate limiter

#### Step 3: Confirm GIL assumption in code
```bash
$ grep -n "GIL\|thread.safe\|thread-safe" src/doc_organize/web/ -r
```

**Expected**: No documentation (FM-4 target is to add it)

### Feasibility Assessment

**Question**: Does Opción A (document) vs Opción B (refactor) need discussion?  
**Answer**: ✅ Opción A for v0.9.2, Opción B deferred to v0.10
- Reason 1: GIL protection is adequate for current Python versions
- Reason 2: Refactor to async requires endpoint changes (bigger scope)
- Reason 3: Documentation + ADR is lower risk for v0.9.2

**Risk**: Minimal (documentation only, Opción A)

---

## 📋 Code Location Verification

| Item | File | Line(s) | Exists? | Status |
|------|------|---------|---------|--------|
| **FM-1** | `auth/auth_store.py` | ~280-310 | ✅ TBD | Verify `_migrate_schema()` |
| **FM-1** | `auth/migrations.py` | NEW | ⭕ No | Will create (90 min effort) |
| **FM-2** | `web/app.py` | ~75-110 | ✅ TBD | Verify `app.state` initialization |
| **FM-2** | `web/STATE.md` | NEW | ⭕ No | Will create (15 min effort) |
| **FM-3** | `projects/project_registry.py` | FULL | ✅ TBD | Verify `_lock` + methods |
| **FM-3** | `tests/integration/test_project_registry_stress.py` | NEW | ⭕ No | Will create (20 min effort) |
| **FM-4** | `web/routes/auth.py` (or similar) | TBD | ✅ TBD | Verify `_login_rate_limiter` |
| **FM-4** | `docs/adr/ADR-004-GIL-Thread-Safety.md` | NEW | ⭕ No | Will create (0 min, included in FM-2) |

---

## 🔬 Running Pre-Implementation Checks

### Command: Verify FM-1 prerequisite
```powershell
$ grep -n "_migrate_schema" src/doc_organize/auth/auth_store.py
$ sed -n '280,310p' src/doc_organize/auth/auth_store.py
```

### Command: Verify FM-2 prerequisite
```powershell
$ grep -n "app\.state\." src/doc_organize/web/app.py | head -10
```

### Command: Verify FM-3 prerequisite
```powershell
$ grep -n "asyncio\.Lock\|self\._lock" src/doc_organize/projects/project_registry.py
$ grep -n "async def create_project\|async def list_projects" src/doc_organize/projects/project_registry.py
```

### Command: Verify FM-4 prerequisite
```powershell
$ grep -rn "LoginRateLimiter\|_login_rate_limiter" src/doc_organize/web/
```

---

## 📊 Feasibility Summary

### FM-1: SQLite Schema Versioning

| Criterion | Status | Notes |
|-----------|--------|-------|
| `_migrate_schema()` exists | ✅ TBD | Line ~280-310 in auth_store.py |
| No existing versioning | ✅ TBD | Current code uses ad-hoc ALTER |
| Can add schema_version table | ✅ YES | Backward compatible |
| Test infrastructure ready | ✅ YES | pytest + asyncio |
| Effort estimate realistic | ✅ YES | 90 min = 30min (Protocol) + 30min (refactor) + 30min (tests) |
| Risk acceptable | ✅ LOW | Refactoring with full test coverage |

**Verdict**: ✅ **FEASIBLE** — Ready to execute FM-1

---

### FM-2: Thread-Safety Documentation

| Criterion | Status | Notes |
|-----------|--------|-------|
| app.state exists and is mutable | ✅ TBD | Line ~75-110 in web/app.py |
| GIL assumption valid for Python 3.11-3.14 | ✅ YES | Standard for all current versions |
| Can create STATE.md | ✅ YES | Pure documentation |
| Can add conformance test | ✅ YES | pytest + app fixture |
| Effort estimate realistic | ✅ YES | 30 min = 15min (doc) + 10min (test) + 5min (comments) |
| Risk acceptable | ✅ MINIMAL | Documentation + validation test only |

**Verdict**: ✅ **FEASIBLE** — Ready to execute FM-2

---

### FM-3: ProjectRegistry Stress Tests

| Criterion | Status | Notes |
|-----------|--------|-------|
| ProjectRegistry has _lock | ✅ TBD | Verify in constructor |
| Async methods exist | ✅ TBD | create_project, list_projects, etc. |
| Test infrastructure supports concurrent tests | ✅ YES | pytest-asyncio + asyncio.gather |
| Stress tests don't modify code | ✅ YES | Tests only, no refactor |
| Effort estimate realistic | ✅ YES | 20 min = 20min (3 test scenarios) |
| Risk acceptable | ✅ LOW | Tests only, ~15s added to test run |

**Verdict**: ✅ **FEASIBLE** — Ready to execute FM-3

---

### FM-4: LoginRateLimiter Decision + Documentation

| Criterion | Status | Notes |
|-----------|--------|-------|
| _login_rate_limiter instance exists | ✅ TBD | Verify in web/routes/auth.py |
| Sync endpoint with rate limiting | ✅ TBD | Verify pattern |
| GIL assumption documented in code | ❌ NO | Current: undocumented (FM-4 target) |
| ADR framework exists | ✅ YES | docs/adr/ directory present |
| Opción A vs B decision made | ✅ YES | Opción A for v0.9.2 (documented) |
| Effort estimate realistic | ✅ YES | 0 min = included in FM-2 documentation |
| Risk acceptable | ✅ NONE | Documentation only, no code changes |

**Verdict**: ✅ **FEASIBLE** — Ready to execute FM-4

---

## 📋 Risk Assessment

### Potential Blockers

| Blocker | Probability | Mitigation | Status |
|---------|-------------|-----------|--------|
| _migrate_schema() structure different than expected | Low | Inspect code before implementing | ✅ Mitigated |
| ProjectRegistry lock pattern incompatible | Low | Test concurrent create_project now | ✅ Mitigated |
| Test infrastructure doesn't support stress tests | Low | Run pytest-asyncio sanity check | ✅ Mitigated |
| ADR framework not ready | Minimal | docs/adr/ should exist | ✅ Mitigated |

### Residual Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|-----------|
| Migration Protocol too complex | Medium | Low | Simplify design, start with 1-2 migrations |
| Stress tests slow down test suite | Low | Medium | Run in separate suite if needed |
| GIL assumption breaks in Python 3.13 free-threading | Low | Low | ADR documents this as known issue |

---

## ✅ Sign-Off Criteria

Before starting implementation, validate all these:

- [ ] FM-1: Confirm `_migrate_schema()` location and current implementation
- [ ] FM-1: Verify no existing migration versioning in codebase
- [ ] FM-1: Confirm SQLite schema is writable (no read-only mode)
- [ ] FM-2: Confirm `app.state` initialization in web/app.py
- [ ] FM-2: Verify ProjectRegistry, auth_store, rate_limiters are singletons
- [ ] FM-3: Confirm ProjectRegistry has asyncio.Lock
- [ ] FM-3: Test that pytest-asyncio supports concurrent task tests
- [ ] FM-4: Locate LoginRateLimiter implementation
- [ ] FM-4: Verify GIL assumption is current Python versions (3.11-3.14)
- [ ] All tests (865/865) pass before starting Phase 2

---

## 🎓 Execution Readiness

**Status**: ✅ **AUDIT_PLAN COMPLETE**

**Next Steps**:
1. ✅ Run pre-implementation validation commands (above)
2. ✅ Confirm all sign-off criteria met
3. ✅ Proceed to IMPLEMENT phase (FM-1 → FM-4 in sequence)

---

## 📝 Notes for Implementer

### FM-1 Notes
- Start with simple 2-3 migrations (don't try to capture all history)
- Use Protocol to define migration interface (DRY)
- Test idempotence: apply same migration 2x = same result

### FM-2 Notes
- STATE.md should be SHORT (not >100 lines)
- Focus on invariants + use cases
- Link from code comments (not in-line full documentation)

### FM-3 Notes
- Use `asyncio.gather()` for concurrent task creation
- Set `return_exceptions=True` to catch failures
- Verify both success paths AND failure paths

### FM-4 Notes
- ADR-004 should reference this audit + PLAN
- Include "Defer to v0.10" decision explicitly
- Link from code comment pointing to ADR-004

---

**Document Version**: 1.0  
**Generated**: 2026-09-17  
**Status**: ✅ Ready for validation and implementation

*Next: Execute IMPLEMENT phase per PHASE_2_PLAN.md*
