# FastAPI Application State (app.state) — Thread-Safety Invariants

## Overview

`app.state` is a namespace object attached to FastAPI's application instance for storing shared application-level data. In doc_organize, we use `app.state` to cache expensive resources and avoid repeated initialization.

**CRITICAL**: This document defines the thread-safety guarantees for each attribute. Do NOT modify without understanding GIL implications.

---

## Thread-Safety Guarantee by Attribute

### 1. `app.state.project_registry` → `ProjectRegistry`

**Type**: `doc_organize.projects.project_registry.ProjectRegistry`
**Initialization**: Line 142 in `app.py`
**Lifecycle**: Set once at app startup, mutated via project lifecycle operations (create, move, archive, scan)
**Thread-Safety**: ⚠️ CONDITIONAL
- **Operations with per-project locking** (`create_project`, `move_project`, `archive_project`): ✅ SAFE
  - ProjectRegistry uses `asyncio.Lock` per project (line 61 in `project_registry.py`)
  - Locks are held across the operation, preventing concurrent mutations of same project
  - **Limitation**: No global lock; cross-project operations can race
- **Unprotected reads** (`list_projects`, `get_project`): ✅ GIL-protected at dict-level
  - Dict reads protected by GIL; consistent snapshot visible
  - Slightly stale data acceptable for list/get (eventual consistency)
- **Known race condition**: Rename + move + archive on same project can interleave
  - **Severity**: Low (affects project metadata only, not data loss)
  - **Mitigation**: Single-tenant installations unaffected; multi-tenant rare in current usage
- **Future**: Global ProjectRegistry lock or distributed state (see ADR-004)

### 2. `app.state.auth_db_path` → `str`

**Type**: `str | None`
**Initialization**: Line 143 in `app.py`
**Lifecycle**: Set once at app startup, never mutated
**Thread-Safety**: ✅ SAFE
- Read-only string path; immutable after initialization
- GIL protects reference reads

### 3. `app.state.taxonomy_template_registry` → `TaxonomyTemplateRegistry`

**Type**: `doc_organize.context.taxonomy_template_registry.TaxonomyTemplateRegistry`
**Initialization**: Line 148 in `app.py`
**Lifecycle**: Set once at app startup, read-only (disk templates only)
**Thread-Safety**: ✅ SAFE
- TaxonomyTemplateRegistry is **stateless** after initialization
- All reads are idempotent (template lookup from memory)
- No mutation after startup; GIL protects reads

### 4. `app.state.security` → `SecurityContext`

**Type**: `doc_organize.web.dependencies.SecurityContext` (or similar auth object)
**Initialization**: Line 152 in `app.py`
**Lifecycle**: Set once at app startup, read-only reference
**Thread-Safety**: ✅ SAFE
- Security context is immutable after creation
- Read-only access in middleware and handlers
- GIL protects reference reads

### 5. `app.state.login_rate_limiter` → `LoginRateLimiter`

**Type**: `doc_organize.web.auth.LoginRateLimiter`
**Initialization**: Line 156 in `app.py`
**Lifecycle**: Set once at app startup, mutated on every login attempt via increment/check
**Thread-Safety**: ✅ SAFE (under GIL only; see ADR-004)
- **Implementation**: Uses dict + timestamp logic, **protected by Python GIL**
- GIL ensures `dict.__setitem__()` and read-modify-write on timestamps are atomic for a single interpreter thread
- **CRITICAL ASSUMPTION**: CPython GIL presence (guaranteed in CPython 3.11, 3.12, 3.13, 3.14)
- **Risk**: Python 3.13+ free-threading mode will break this; see ADR-004 for migration plan

### 6. `app.state.active_project_operations` → `set[str]`

**Type**: `set[str]` (keys: `"tenant_id:project_name"`)
**Initialization**: Line 164 in `app.py`
**Lifecycle**: Set once at app startup, mutated during scan/dedup operations to track in-progress projects
**Thread-Safety**: ⚠️ CONDITIONAL (GIL-protected)
- **Used for**: Rejecting concurrent scan/dedup on same project (web/routes/scan.py)
- **Operations**: `add()`, `discard()`, `contains()` on set
- **GIL protection**: Python GIL protects set mutationas atomic operations
- **Known limitation**: No explicit locking; multiple concurrent operations can still race
- **Mitigation**: Set is used for "best-effort" concurrency control, not strict serialization
- **Future**: Replace with `asyncio.Lock` per operation key (see ADR-004)

---

## Design Decision

All `app.state` attributes are initialized **once at startup** (synchronously in `async def lifespan()`) and then treated as immutable references. **Mutation is discouraged**; attributes should be treated as read-only after initialization.

**Exception**: Some endpoints perform controlled mutations:
- Scan operations → mutate `app.state.active_project_operations` (add/remove project keys)
- Rate limiting → mutate `app.state.login_rate_limiter` internal dict

These mutations are **protected by the GIL alone** (no explicit locks). This is a **conscious tradeoff** documented in **ADR-004-GIL-Thread-Safety.md**.

---

## Lint/Type Rules

- ✅ **No type annotations required** (dynamic namespace)
- ✅ **Docstrings optional** for `app.state` assignments (use thread-safety comments instead)
- ✅ **Thread-safety comments required** for any attribute mutated after initialization
- ❌ **Never assign new attributes to app.state during request handling** (violates initialization contract)

---

## Future Migration (v0.10+)

See **ADR-004-GIL-Thread-Safety.md** for options:
- **Option A (v0.9.2, current)**: Accept GIL; document assumptions
- **Option B (v0.10)**: Introduce `asyncio.Lock` wrappers for mutable state
- **Option C (v0.11)**: Switch to distributed state (Redis) for multi-worker deployments

---

*Last updated: 2026-09-17*  
*Applies to: doc_organize v0.9.2+*

