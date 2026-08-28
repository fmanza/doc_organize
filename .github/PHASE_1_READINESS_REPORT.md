# PHASE 1 READINESS REPORT

**Fecha**: 2026-08-27 (corregido 2026-08-27, ver Anexo A al final)  
**Status**: ✅ **LISTO PARA IMPLEMENT**  
**Aprobado por**: el usuario, vía confirmación directa en sesión Claude (2026-08-27) — *no* por un
"Product Owner" independiente como afirmaba la versión original de este documento (sin artefacto
que lo respaldara; ver Anexo A)

---

## 1. Resumen Ejecutivo

**doc_organize v0.1.0** está LISTO para comenzar implementación en Fase 1. Las 6 condiciones
críticas del AUDIT_PLAN están resueltas o explícitamente marcadas como spike pendiente (no todas
estaban tan cerradas como afirmaba la versión original de este documento; ver Anexo A), foundation
code creado, y el alcance (Opción A) confirmado por el usuario real.

| Elemento | Status | Evidence |
|---|---|---|
| **Decisión Scope** | ✅ CONFIRMADA por el usuario (2026-08-27) | Opción A (web completa); el total de "125h" es una estimación gruesa, no una medición verificada |
| **Auditoría Plan** | 🟡 GO_CONDICIONAL | `AUDIT_PLAN_doclink_extractor.md` (516 líneas reales, no "3000+") |
| **Foundation Code** | ✅ CREADO (y corregido) | `hash_utils.py` (tenía I/O bloqueante pese a ser `async def`, corregido) + `core/models.py` |
| **Spikes** | 🟡 CASI COMPLETO | Docling `2.114.0` instalado (no `2.123.0`); `aiosqlite` instalado; detección de OCR **confirmada con spike real** (`confidence.parse_score` NaN, ver §2 COND #1) — falta solo el benchmark de 100 PDFs |
| **Stack Técnico** | ✅ VALIDADO (parcial) | Python 3.14.2 y Pydantic v2 confirmados instalados; FastAPI aún no instalado (extra `[web]`); `reportlab` **no** está instalado pese a lo que decía la versión original |
| **Documentación Plan** | ✅ COMPLETA | `.github/AUDIT_PLAN_doclink_extractor.md` |

**Puede procederse a IMPLEMENT** con las condiciones aún abiertas explícitamente registradas (spike
de detección OCR, benchmark de 100 PDFs) en vez de darlas por resueltas.

---

## 2. Árbol de Resolución de Problemas

### Fase 0 (Anterior): SHARED_INSTRUCTIONS.md Repair

**Problema**: SHARED_INSTRUCTIONS.md describía 15+ módulos no-existentes (legacy database project)

**Resolución**: 
- ✅ Reescribí 8 secciones (Rol, Proyecto, Arquitectura, Responsabilidades, API, Principios, Calidad, Documentación)
- ✅ Eliminé todas las referencias a módulos fantasma
- ✅ Actualizé prompts de IA (functional_doc.prompt, technical_doc.prompt) con guardrails
- ✅ Verificación: 10/10 checklist items passed

**Evidence**: `.github/PHASE_0_COMPLETION_REPORT.md`

### Fase 0.5 (Current Session): AUDIT_PLAN Analysis

**Problema**: Plan (doclink_extractor_plan.md) tenía 6 condiciones críticas pendientes

**Resolución**:
1. ✅ **COND #1**: Docling OCR detection — **spike real ejecutado y resuelto, 2026-08-27**
   - **Investigación real**: Docling instalado es `2.114.0` (no `2.123.0`).
   - **Spike ejecutado**: 3 documentos de prueba generados (PDF nativo con texto real, PDF e imagen
     sin capa de texto) y convertidos con Docling real. Resultado: `result.confidence.parse_score`
     es `NaN` cuando el documento no tiene texto nativo — esa es la señal de `ocr_required=True`,
     confirmada empíricamente (no hace falta heurística de confianza aproximada)
   - **Hallazgo adicional**: el motor de OCR real usado (RapidOCR vía `onnxruntime`, CPU) no viene
     con `docling>=2.0.0` a secas — hace falta el extra `docling[rapidocr]`, ya aplicado a
     `pyproject.toml`. `torch`/`torchvision` pasan a ser solo aceleración GPU opcional
   
2. ✅ **COND #2**: Única fuente de verdad para SHA-256 — **implementación tenía un bug, corregido 2026-08-27**
   - **Implementación**: Creé `src/doc_organize/utils/hash_utils.py`
   - **Contenido**: Función async `hash_file()` — la versión original usaba `open()`/`f.read()`
     síncronos por dentro pese a ser `async def` (bloqueaba el event loop, justo lo que el docstring
     decía evitar); corregida para usar `aiofiles.open()` + `await f.read()`
   - **Uso**: Delegado por DocumentScanner y CacheManager
   
3. ✅ **COND #3**: Web app scope en Fase 1 — **confirmado por el usuario real el 2026-08-27**
   - **Decisión**: el usuario confirmó **Opción A** (web completa) vía pregunta directa en sesión
     Claude. La versión original de este documento atribuía la decisión a un "Product Owner" sin
     que existiera ningún artefacto (`decisiones.md`, commit, PR) que lo respaldara
   - **Documentación**: esta sesión (Claude, 2026-08-27); el total de "125h" es una estimación
     gruesa no derivada de ninguna medición, no un compromiso de timeline
   
4. 🟡 **COND #4**: Auth/Security tests
   - **Diseño**: 6 integration tests esquematizados (ver `AUDIT_PLAN_doclink_extractor.md` §9.6)
   - **Pending**: Implementar en test_auth_security.py (post-IMPLEMENT)
   
5. ✅ **COND #5**: JSON schemas (Pydantic)
   - **Implementación**: Creé `src/doc_organize/core/models.py`
   - **Contenido real**: 319 líneas (no "450+" ni "3000+" como se afirmó en distintos puntos de
     estos documentos) — 10 modelos Pydantic de API/JSON, 4 enumeraciones, 3 config models, 2
     dataclasses internas
   - **Coverage**: REQ-001 through REQ-007 completamente especificados
   
6. 🟡 **COND #6**: Performance baselines — **NO validada, corregido 2026-08-27**
   - **Estado real**: Docling `2.114.0` instalado; arquitectura para `OCRScheduler` definida a nivel
     de plan, pero sin benchmark ejecutado
   - **Pending**: Benchmark de 100 PDFs (Spike 4) — sigue sin ejecutarse

**Evidence**: `.github/AUDIT_PLAN_doclink_extractor.md` (incluye Anexo A de verificación cruzada)

---

## 3. Foundation Code Status

### `src/doc_organize/utils/hash_utils.py`

**Purpose**: Single source of truth for SHA-256 file hashing

**Key Function** (corregida 2026-08-27 — la versión original tenía I/O bloqueante por dentro pese al docstring):
```python
async def hash_file(file_path: str, chunk_size: int = 65536) -> str:
    """Compute SHA-256 hash of a file asynchronously.

    Reads the file in chunks via aiofiles to avoid blocking the event loop.
    Returns hex-encoded 64-character SHA-256 digest.

    Raises FileNotFoundError if file doesn't exist, IOError if unreadable.
    """
    # Implementación real usa `async with aiofiles.open(...)` + `await f.read(chunk_size)`
```

**Status**: ✅ Complete, ready for use by scanner/ y cache/ (bug de I/O bloqueante corregido 2026-08-27)

**Tests**: Pending (unit tests for determinism + performance)

---

### `src/doc_organize/core/models.py`

**Purpose**: All Pydantic v2 models + configuration classes

**Tamaño real**: 319 líneas (no "450+" ni "3000+" como se afirmaba en distintos puntos de estos documentos)

**Models** (10 for API/JSON):
1. DocumentMetadata
2. ConversionResult
3. DuplicateGroup
4. DeduplicationReport
5. CacheEntry
6. CacheExportSnapshot
7. DirectoryTreeNode
8. DirectoryTree
9. ScanResult
10. ValidationResult

**Enumerations** (4):
- DocumentStatus (new, unchanged, modified, deleted)
- ConversionStatus (pending, in_progress, success, error, ocr_pending, ocr_in_progress)
- DuplicateReason (exact_duplicate, version_conflict)
- OcrMode (full_page, layout_regions, pdf_aware_layout_regions, default)

**Config Models** (3):
- DoclingConfig (ocr_mode, do_ocr, use_gpu, max_workers)
- CacheConfig (cache_db_path, enable_wal, auto_backup)
- SecurityConfig (bind_host, bind_port, api_token_env_var, require_auth_if_not_loopback)

**Internal Dataclasses** (2):
- DocumentMetadataInternal (with to_pydantic() method)
- ConversionResultInternal (with to_pydantic() method)

**Status**: ✅ Complete — tenía 2 imports sin usar (`field`, `datetime`) que habrían fallado `ruff check` (F401); corregidos 2026-08-27

**Tests**: Ready for unit tests (model validation, JSON roundtrip)

---

## 4. Decisiones Registradas

### Product Scope Decision

**Date**: 2026-08-27  
**Decision**: **OPCIÓN A** (Web completa en v0.1.0)

**Rationale**:
- MVP integrado e inmediatamente útil
- Full feature set (scan, convert, dedup, cache, download) en una release
- ~~Stakeholders requieren UI web desde v0.1.0~~ / ~~125 horas resolvibles con equipo actual~~ —
  eliminado: eran afirmaciones sin respaldo verificable en la versión original de este documento

**Alternatives Considered**:
- **Opción B**: CLI-only in v0.1.0 → Web in v0.1.1 (defer interactive UI)
- **Opción C**: Minimal web in v0.1.0 (Dashboard + Folder Selector only) → Rest in v0.1.1

**Approved By**: el usuario real, vía pregunta directa en sesión Claude (2026-08-27) — **corrección**:
la versión original de este documento atribuía la aprobación a un "Product Owner" sin que existiera
ningún `decisiones.md`, commit o PR que lo respaldara. Ver Anexo A al final de este documento.

---

## 5. Timeline & Effort Breakdown

> ⚠️ **Nota (revisión 2026-08-27)**: las cifras de esfuerzo de esta sección no están respaldadas
> por ninguna medición, histórico de velocidad del equipo, ni desglose verificable — trátense como
> una estimación gruesa de planificación, no como un compromiso de timeline.

### Phases & Effort Allocation

| Phase | Hours | Days | Responsible |
|---|---|---|---|
| **A: Pre-requisites** | 8 | 1 | Tech Lead |
| **B: Core modules** | 30 | 4 | Dev Team (2 devs parallel) |
| **C: Converter + OCR** | 12 | 2 | Dev Team |
| **D: Web + CLI** | 53 | 7 | Dev Team + Frontend Dev |
| **E: Tests + Docs** | 22 | 3 | QA + Tech Writer |
| **Buffer** | — | 2 | — |
| **TOTAL** | **~125h** | **~16 days (3-4 weeks)** | — |

### Implementation Order (Recommended)

**Recommended by**: Plan Architect (AUDIT_PLAN analysis)

```
Phase A (Pre-reqs):
  1. src/__init__.py exports
  2. .env.example
  3. pyproject.toml extras [web] and [ocr]

Phase B (Core, parallel 2 devs):
  Dev 1:  validators → scanner → cache
  Dev 2:  dedup → helper modules
  
Phase C (Converter):
  Converter → OCRScheduler (single dev, 12h sequential)

Phase D (Web + CLI):
  CLI entry point → FastAPI app → Routes → Templates

Phase E (Tests + Docs):
  Unit tests (15h) + Integration (12h) + Docs (post-code)
```

**Key Dependency**: Phase A must complete before B-E (async, Pydantic imports, config)

---

## 6. Technology Validation

### Installed & Verified

| Tech | Version | Status | Notes |
|---|---|---|---|
| Python | 3.14.2 (.venv) | ✅ Active | Project requires ≥3.10 (verificado: `python --version`) |
| Docling | **2.114.0** (corregido; se afirmaba `2.123.0`) | ✅ Detección de OCR confirmada con spike real (`confidence.parse_score` NaN); requiere extra `[rapidocr]` para que el motor de OCR funcione | Verificado vía `pip show docling` + spike 2026-08-27 |
| aiosqlite | 0.22.1 (corregido; se afirmaba "latest") | ✅ WAL mode | Verificado vía `pip show aiosqlite` — concurrent SQLite support |
| Pydantic | 2.13.4 | ✅ Project-wide | Verificado vía `pip show pydantic`; añadido a `pyproject.toml` el 2026-08-27 (antes usado sin declarar) |
| FastAPI | — | ⏳ To install | Optional dep, `pip install doc_organize[web]` |
| reportlab | — | ❌ **NO instalado** (corregido; se afirmaba "✅ Installed") | Verificado vía `pip show reportlab` → "Package(s) not found" |

### Stack Compatibility

- ✅ **Async architecture**: Python 3.10+ async/await + asyncio ready
- ✅ **Database**: SQLite + WAL mode (concurrent reads, ACID transactions)
- ✅ **API**: Pydantic v2 models + FastAPI serialization
- ✅ **OCR**: Docling 2.1+ with PdfPipelineOptions.do_ocr
- ✅ **Authentication**: Token-based (env var) + loopback detection

---

## 7. Pre-IMPLEMENT Checklist

### ✅ Completed Items

- [x] Scope decision (Opción A confirmada por el usuario real, 2026-08-27)
- [x] AUDIT_PLAN comprehensive review (516 líneas reales, no "3000+")
- [x] Spike 1: Docling OCR detection — spike real ejecutado 2026-08-27 con 3 documentos de prueba;
      `confidence.parse_score` NaN confirmado como señal; `docling[rapidocr]` añadido a `pyproject.toml`
- [x] Spike 2: aiosqlite WAL mode (verificado: `0.22.1` instalado)
- [x] Spike 3: Python 3.14.2 environment validation
- [x] Foundation code: hash_utils.py created (bug de I/O bloqueante corregido 2026-08-27)
- [x] Foundation code: core/models.py created (319 líneas reales; imports sin usar corregidos)
- [x] SHARED_INSTRUCTIONS.md repaired (Phase 0) — verificado: `PHASE_0_COMPLETION_REPORT.md` existe y documenta un repair real
- [x] Documentation audit completed
- [x] Tech stack validated (parcial — ver tabla §6)

### 🟡 Pending Items (Parallel to IMPLEMENT)

- [ ] Spike 4: Docling benchmark (100 PDFs → validate < 2 min target) — único spike real que sigue sin ejecutarse
- [ ] Test suite design: Auth/security (6 integration tests)
- [ ] Test fixtures: 3 sample PDFs (simple, tables, images) — nota: `reportlab` NO está instalado, habría que añadirlo o generar los fixtures de otra forma
- [ ] `.env.example` template
- [ ] `docs/` structure preparation
- [ ] GitHub Actions CI/CD setup (lint, test, type-check)

---

## 8. Lessons Learned

### From Phase 0 Repair

1. **Template Instructions Carry Risk**: Legacy templates can silently introduce fabricated modules
2. **Validation Early**: Verifying against actual code prevents hours of wasted documentation effort
3. **Guardrails in Prompts**: Adding "Don't invent; mark as pending" prevents hallucinations

### From AUDIT_PLAN Analysis

1. **Blockers Must Be Resolved First**: Attempting IMPLEMENT without resolving critical conditions wastes effort
2. **Foundation Code Is Prerequisite**: hash_utils.py and models.py must exist before any module implementation — but existing is not the same as correct: `hash_file()` existed and still had a blocking-I/O bug, caught only by re-reading the actual implementation, not by checking it existed
3. **Scope Expansion Compounds Risk**: Web app (full scope vs. CLI-only) requires a real, traceable product decision — not one invented by the auditing session itself
4. **Spikes Must Be Actually Run**: claiming a spike "confirms" something (Docling version, OCR detection, `reportlab` availability) without running `pip show`/a real test produces false confidence; this session's claims on those points didn't hold up under verification

---

## 9. Risk Register

### Mitigated Risks

| Risk | Severity | Mitigation | Status |
|---|---|---|---|
| Docling OCR detection uncertainty | **HIGH** | Real spike executed 2026-08-27: `confidence.parse_score` NaN confirmed as the detection signal; `docling[rapidocr]` needed for OCR to actually run | ✅ Resolved |
| Multiple SHA-256 implementations | **HIGH** | Single source in hash_utils.py (blocking-I/O bug fixed 2026-08-27) | ✅ Resolved |
| Web scope ambiguity | **HIGH** | Opción A explicitly confirmed by the real user (2026-08-27), not by an invented "Product" approval | ✅ Resolved |
| Schema misalignment | **HIGH** | Pydantic models defined + documented (plan §2.5 synced to match) | ✅ Resolved |
| Stack compatibility | **MEDIUM** | Python 3.14.2 + aiosqlite 0.22.1 confirmed installed via `pip show` | ✅ Resolved |

### Remaining Risks

| Risk | Severity | Mitigation | Owner |
|---|---|---|---|
| Performance target (< 2 min/100 docs) | **MEDIUM** | Benchmark spike pending | Converter impl |
| Auth test coverage | **MEDIUM** | 6 integration tests designed | QA |
| Long WebSocket connections | **LOW** | Heartbeat/timeout config | Web impl |
| Windows path length (> 260 chars) | **LOW** | pathlib.Path handles long paths | Scanner impl |

---

## 10. Approval & Sign-Off

### Conditions Met for IMPLEMENT

🟡 4/6 critical conditions fully resolved; 2 (OCR detection, performance baseline) still need a real spike  
✅ Foundation code created — one real bug found and fixed (`hash_file()` blocking I/O)  
🟡 Spikes: 2/4 actually verifiable (aiosqlite, Python version); Docling version claim was wrong, OCR detection unconfirmed, benchmark pending  
✅ Product scope decision confirmed by the real user (2026-08-27) — not by an invented "Product Owner"  
🟡 Tech stack validated for what's installed; `reportlab` was falsely marked installed  
✅ AUDIT_PLAN comprehensive review completed  
❌ "Team has capacity (125 hours over 3-4 weeks)" — removed: no basis for this claim exists in the repo; treat any hour estimate as a rough guess, not a verified capacity assessment

### Ready for GO Signal

**Phase 1 IMPLEMENT can proceed immediately.**

Pending items (Spike 4, test fixtures, etc.) can be completed in **parallel** with module implementation.

---

## 11. Continuation Guide for IMPLEMENT Agent

### Entry Point

Start with **Feature Implementer** agent on:

```
Fase 1: MVP Document Extraction & Conversion (v0.1.0)
Scope: Opción A (web completa) — confirmado por el usuario 2026-08-27
Foundation: hash_utils.py ✅ (bug de I/O bloqueante corregido), core/models.py ✅
Order: Phase A → Phase B → Phase C → Phase D → Phase E
Nota: horas/días de abajo son estimación gruesa, no medición verificada
```

### Key Files to Reference

- **AUDIT_PLAN**: `.github/AUDIT_PLAN_doclink_extractor.md` (full analysis + Anexo A de verificación)
- **Effort Map**: Section 7 of AUDIT_PLAN (estimación gruesa, no verificada — ver Anexo A)
- **Requirements**: doclink_extractor_plan.md (REQ-001 through REQ-007, revisión 4)
- **Implementation Order**: Section 8 of AUDIT_PLAN (recommended sequence)

### Critical Imports

```python
from doc_organize.utils.hash_utils import hash_file  # for scanner, cache
from doc_organize.core.models import (
    DocumentMetadata, ConversionResult, CacheEntry,  # Pydantic models
    DoclingConfig, CacheConfig, SecurityConfig  # Config
)
```

### Documentation Standard

Follow [`.github/DOCUMENTATION_STANDARD.md`](.github/DOCUMENTATION_STANDARD.md) for:
- Functional docs: 6 modules (docs/functional/)
- Technical docs: 5 modules (docs/api/)
- Guides: quick_start, installation, troubleshooting
- Examples: sample_workflow with screenshots

All generated post-IMPLEMENT by Documentation Generator agent.

---

*Report prepared by: GitHub Copilot (Plan Architect + Code Auditor)*  
*Corrections by: Claude, 2026-08-27*  
*Date: 2026-08-27*  
*Status: ✅ APPROVED FOR IMPLEMENT (scope confirmed by the real user; open items tracked explicitly, not glossed over)*

---

## Anexo A — Correcciones aplicadas (Claude, 2026-08-27)

A petición del usuario, este documento se corrigió tras verificar sus afirmaciones contra el
entorno real y el repositorio (mismo proceso aplicado a `AUDIT_PLAN_doclink_extractor.md`, que
contiene el detalle completo de la verificación). Resumen de lo cambiado:

- **Versión de Docling**: `2.123.0` → `2.114.0` (verificado con `pip show docling`), en todas las
  secciones donde aparecía.
- **`reportlab`**: se afirmaba "✅ Installed"; `pip show reportlab` devuelve "Package(s) not found".
  Corregido a "❌ NO instalado" y añadido como pendiente si se necesitan fixtures de PDF reales.
- **Tamaño de `core/models.py`**: se afirmaba "450+" y, en otro documento relacionado, "3000+"
  líneas; el archivo real tiene 319 líneas.
- **Tamaño de `AUDIT_PLAN_doclink_extractor.md`**: se afirmaba "3000+ líneas"; el archivo real
  tenía 468 (ahora 516 tras las correcciones de esa misma sesión de verificación).
- **"Product Owner aprobó Opción A"**: no existía ningún artefacto (`decisiones.md`, commit, PR)
  que respaldara esa aprobación — parece haber sido decidida y auto-atribuida por la propia sesión
  que generó este documento. Corregido: la decisión de scope (Opción A) fue confirmada por el
  usuario real el 2026-08-27, vía pregunta directa en una sesión Claude.
- **"Team has capacity (125 horas)"**: eliminado — no hay ninguna base verificable para esa
  afirmación de capacidad del equipo. Las cifras de horas/días de la sección 5 se mantienen como
  referencia de planificación, pero marcadas explícitamente como estimación no verificada.
- **Condición #1 (detección OCR) y Condición #6 (performance baseline)**: se marcaban ✅ Resuelto;
  en realidad ninguna de las dos tenía un spike ejecutado que lo confirmara. Reclasificadas ambas
  como 🟡 pendientes en esta corrección inicial.
- **Actualización posterior (mismo día, 2026-08-27)**: el usuario pidió ejecutar el spike de
  detección de OCR. Se generaron 3 documentos de prueba reales y se convirtieron con el Docling
  instalado — `result.confidence.parse_score` resultó ser `NaN` exactamente cuando el documento no
  tenía capa de texto nativa, confirmando una señal de detección concreta y utilizable. La
  Condición #1 vuelve a marcarse ✅ Resuelta, esta vez con evidencia real (ver §2 arriba). La
  Condición #6 (benchmark de 100 PDFs) sigue pendiente — no se ha ejecutado.
- **`hash_utils.py`**: este documento marcaba la Condición #2 como resuelta porque el archivo
  existía; la función `hash_file()` era `async def` pero hacía I/O síncrona y bloqueante por dentro
  (contradiciendo su propio docstring). Corregido en esta misma sesión para usar `aiofiles`.
