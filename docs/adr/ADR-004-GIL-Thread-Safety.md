# ADR-004: GIL-Based Thread-Safety for Application State (v0.9.2)

**Status**: Accepted (v0.9.2)  
**Context**: doc_organize v0.9.0 uses mutable application state (`app.state`) shared across FastAPI handlers. Some attributes are mutated during request handling (rate limiting, scan tracking, project metadata) without explicit locking.  
**Decision**: Accept reliance on Python GIL for thread-safety in v0.9.2; document assumptions; plan migration path for v0.10+.

---

## Problem Statement

### Background

FastAPI applications use `app.state` to store shared data accessible across all request handlers. In doc_organize, `app.state` holds:
- `project_registry` (mutated during scan/create/move/archive operations)
- `login_rate_limiter` (mutated on every login attempt)
- `active_project_operations` (mutated to track in-progress scans)

### Concurrency Challenge

Python's **Global Interpreter Lock (GIL)** ensures that only one thread executes Python bytecode at a time within a single process. This makes certain dict and set operations atomic:
- `dict.__setitem__(key, value)` → single bytecode instruction
- `set.add(element)` → single bytecode instruction

**However**:
- **FastAPI async**: Handlers are coroutines, not threads; GIL doesn't directly protect across multiple coroutines in the same thread
- **uvicorn workers**: Default 1 worker (single process, single thread). GIL is active and provides atomic dict/set operations
- **Multiple workers**: If deployed with `uvicorn --workers 4`, each process has its own GIL; `app.state` is **not** shared (each worker has its own instance)
- **Free-threading (Python 3.13+)**: Experimental feature disables GIL; atomic operations are no longer guaranteed

### Current Risk

1. **Single-worker deployment (default)**: ✅ Safe (GIL protects mutations)
2. **Multi-worker deployment**: ⚠️ State isolated per worker (no cross-worker consistency)
3. **Python 3.13+ free-threading**: ❌ UNSAFE (GIL absent; race conditions possible)

---

## Decision

**Accept GIL-based thread-safety for v0.9.2** with the following commitments:

### Option A (Selected for v0.9.2): GIL-Based Approach

**Approach**:
- Rely on Python GIL to make dict/set mutations atomic
- Document all assumptions in `src/doc_organize/web/STATE.md`
- Add compiler hints/comments at mutation sites referencing ADR-004
- Plan migration path for v0.10

**Affected attributes**:
- `login_rate_limiter`: dict-based counter + timestamp logic (mutations atomic under GIL)
- `active_project_operations`: set of active project keys (add/discard atomic under GIL)
- `project_registry`: per-project `asyncio.Lock` already protects; minimal GIL reliance

**Deployment constraints**:
- ✅ Recommended: `uvicorn --workers 1` (default; single-threaded)
- ⚠️ Acceptable: `uvicorn --workers N` (each worker isolated; state not shared)
- ❌ Unsupported: Multi-threaded access to shared `app.state` without explicit locks
- ❌ Unsupported: Python 3.13+ free-threading mode (would break GIL assumptions)

**Documentation**:
- `src/doc_organize/web/STATE.md`: Thread-safety invariants per attribute
- `web/app.py`: Comments referencing STATE.md at each `app.state` assignment
- This document: Design rationale and migration path

---

## Alternatives Considered

### Option B: Explicit asyncio.Lock Wrappers (v0.10+)

**Approach**:
```python
class AppState:
    def __init__(self):
        self._login_rate_limiter_lock = asyncio.Lock()
        self._login_rate_limiter = {}  # wrapped dict
    
    async def check_rate_limit(self, key):
        async with self._login_rate_limiter_lock:
            return self._login_rate_limiter.get(key, 0)
```

**Pros**:
- Explicit synchronization; no GIL dependency
- Works with free-threading (Python 3.13+)
- Clearer intent in code

**Cons**:
- Every access requires `async with` lock (performance overhead)
- Refactoring required: all mutation sites must use locks
- Code complexity increases

**Decision**: Defer to v0.10; acceptable for now given single-worker default deployment.

---

### Option C: Distributed State (Redis, v0.11+)

**Approach**:
```python
# app.state.rate_limiter → Redis cached wrapper
class RedisRateLimiter:
    def __init__(self, redis_url):
        self.redis = redis.from_url(redis_url)
    
    async def check_limit(self, key):
        return await self.redis.incr(key)
```

**Pros**:
- Shared state across multiple workers
- Built-in expiration (Redis TTL)
- Scales to multi-process/multi-machine deployments

**Cons**:
- External dependency (Redis)
- Performance: Redis round-trip for each mutation
- Adds operational complexity

**Decision**: Defer to v0.11+; out of scope for v0.9.2.

---

## Consequences

### Positive

1. ✅ No immediate code changes required (v0.9.2 ships with status quo)
2. ✅ Single-worker deployment (default) remains safe
3. ✅ Minimal performance overhead (no locks needed)
4. ✅ Clear migration path documented

### Negative

1. ⚠️ Relies on GIL assumption (breaks with free-threading)
2. ⚠️ Multi-worker deployments have isolated state (no sharing)
3. ⚠️ Code doesn't make synchronization intent explicit
4. ⚠️ Requires Python version constraint (no free-threading support)

### Mitigation

1. **pyproject.toml**: Constrain to `python>=3.11,<3.13` initially; plan 3.13 support in v0.10
   ```toml
   python = ">=3.11,<3.13"
   ```

2. **Documentation**: `COMPATIBILITY.md` to clarify deployment constraints
   - ✅ Supported: Single-worker (default)
   - ⚠️ Limited: Multi-worker (state not shared)
   - ❌ Unsupported: Free-threading mode

3. **Test suite**: Add warnings for future GIL removal
   ```python
   import sys
   if sys.flags.no_gil:
       raise RuntimeError("Free-threading mode requires ADR-004 migration (v0.10+)")
   ```

4. **Monitoring**: Log concurrency events for rate-limiter and active-operations
   ```python
   logger.warning(f"Concurrent rate-limit check: {key} (GIL may serialize)")
   ```

---

## Implementation Timeline

| Version | Action | Details |
|---------|--------|---------|
| **v0.9.2** (current) | Document assumptions | STATE.md, ADR-004, inline comments |
| **v0.10** (Q4 2026) | Add explicit locks | Wrap rate-limiter and active-ops in asyncio.Lock |
| **v0.11** (Q1 2027) | Distributed state | Optional Redis for multi-worker deployments |
| **v0.12+** | Free-threading support | Migrate to standard library locks if 3.14+ stabilizes |

---

## Acceptance Criteria

✅ `src/doc_organize/web/STATE.md` created with thread-safety invariants  
✅ `src/doc_organize/web/app.py` comments reference STATE.md + ADR-004  
✅ `pyproject.toml` specifies Python version constraints (optional for v0.9.2)  
✅ `COMPATIBILITY.md` documents deployment constraints  
✅ Test suite passes with no race condition failures on single-worker setup  
✅ Code review: Thread-safety assumptions validated by team lead  

---

## References

- [Python GIL Behavior](https://docs.python.org/3/faq/library/threading.html#global-interpreter-lock)
- [asyncio Thread-Safety](https://docs.python.org/3/library/asyncio-sync.html)
- [Python 3.13 Free-Threading PEP-703](https://www.python.org/dev/peps/pep-0703/)
- `src/doc_organize/web/STATE.md` — Application state thread-safety invariants
- `src/doc_organize/web/app.py` — Inline comments at state initialization

---

*Decision Date*: 2026-09-17  
*Author*: doc_organize architecture team  
*Status*: ✅ Accepted for v0.9.2
