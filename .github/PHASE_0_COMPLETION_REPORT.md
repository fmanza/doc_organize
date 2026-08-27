# PHASE 0 Completion Report — SHARED_INSTRUCTIONS.md Repair

**Date**: 2026-08-27  
**Status**: ✅ **COMPLETE**

---

## Objective

Reparar la divergencia crítica entre `SHARED_INSTRUCTIONS.md` (legacy BD architecture) y el código real de `doc_organize` v0.1.0 (document extraction). Esta reparación es **bloqueante para todo uso de prompts IA de documentación**.

---

## Problems Identified (Pre-Repair)

### 🔴 Critical Divergence

**SHARED_INSTRUCTIONS.md described**:
- 15+ modules for multi-motor database operations (managers, bulk, metadata, comparar, doc, connection, factory, query, validators, analysis, executors, results, core, _core, _drivers)
- API with `SyncDatabaseManager`, `AsyncDatabaseManager`, `SchemaComparator`, `ConnectionFactory`, etc.
- Database-focused principles (SQLAlchemy, DataFrame, pool management, introspection)
- Testing strategy with SQLite in-memory, PostgreSQL, Oracle, SQL Server fixtures

**Actual code**:
- 3 files: `src/doc_organize/__init__.py` (minimal), `core/__init__.py` (empty), `utils/__init__.py` (empty)
- No classes, no API
- Project Status: v0.1.0 Alpha MVP incipient

**Impact**:
- ❌ `functional_doc.prompt.md` line 16 referenced "librería Python multimotor de bases de datos"
- ❌ `technical_doc.prompt.md` referenced database domain specialization
- ❌ Any IA-generated documentation would be 100% fabrication

---

## Repairs Applied

### 1. ✅ SHARED_INSTRUCTIONS.md Updated

#### Section: Rol esperado (Role Expected)
- ❌ Before: "operaciones de bases de datos, librerías multimotor, asyncio drivers async (asyncpg, aiosqlite)"
- ✅ After: "Extracción y conversión de documentos: PDF, DOCX, XLSX, PPTX → Markdown/JSON"

#### Section: Proyecto: doc_organize
- ❌ Before: "librería Python para operaciones con múltiples motores de base de datos"
- ✅ After: "librería Python (v0.1.0 Alpha) para extracción y conversión de documentos"
- ✅ Updated Capacidades principales: Scanner → Converter → Dedup → Cache → Workflow
- ✅ Removed all database capabilities

#### Section: Arquitectura real
- ❌ Before: 15+ modules (managers/, bulk/, metadata/, comparar/, etc.)
- ✅ After: 
  - **Implemented** (v0.1.0): core/, utils/, __init__.py (empty/minimal)
  - **Planned** (v0.1.0): scanner/, converter/, cache/, dedup/
  - **Planned** (v0.2.0): workflow/, web/

#### Section: Responsabilidades por módulo
- ❌ Before: Database-specific responsibilities (bulk CRUD, schema introspection, migration DDL)
- ✅ After: Document processing responsibilities with TODO v0.1.0 markers

#### Section: API pública recomendada
- ❌ Before: `SyncDatabaseManager`, `AsyncDatabaseManager`, `build_conn_params()`
- ✅ After: `DocumentScanner`, `DocumentConverter`, `CacheManager`, `DeduplicatorService`

#### Section: Principios de diseño
- ❌ Before: "operaciones de bases de datos", "SQLAlchemy", "pandas.DataFrame CRUD"
- ✅ After: "Procesamiento de documentos", validación de rutas, formato múltiple, asincronía I/O

#### Section: Calidad y pruebas
- ❌ Before: "Managers y bulk: SQLite in-memory", "PostgreSQL, Oracle fixtures"
- ✅ After: "Scanner, Converter, Dedup, Cache: tests con archivos locales", "fixtures de documentos mock"

#### Section: Documentación obligatoria
- ❌ Before: "Cambios en instrucciones IA → sincronizar todos los ficheros afectados"
- ✅ After: Clear sync requirements for SHARED_INSTRUCTIONS.md, copilot-instructions.md, CLAUDE.md

#### Section: Convención de nombres en docs/
- ✅ Updated structure: functional/, api/, examples/, guides/ (document-specific)

---

### 2. ✅ Prompts IA Updated with Guardrails

#### functional_doc.prompt.md
- **Before** (line 16): "doc_organize — librería Python multimotor de bases de datos (sync/async)"
- **After**: "doc_organize (v0.1.0 Alpha) — Librería Python para extracción y conversión de documentos"
- **Added**: `⚠️ GUARDRAIL CRÍTICO: No inventar módulos no implementados`

#### technical_doc.prompt.md
- **Added guardrail section** with explicit warnings:
  ```
  ⚠️ PROYECTO: doc_organize v0.1.0 Alpha (extracción/conversión, no bases de datos)
  ⚠️ GUARDRAIL: No inventar módulos no implementados
  
  Módulos IMPLEMENTADOS: core/, utils/, __init__.py
  Módulos PLANEADOS (TODO): scanner/, converter/, cache/, dedup/, workflow/, web/
  ```

---

### 3. ✅ CLAUDE.md and `.claude/settings.json` Audited

- **Status**: SAFE — No references to non-existent modules
- **settings.json.example**: Generic hooks (ruff, mypy, pytest) — all valid for v0.1.0
- **CLAUDE.md**: Commands and configuration are valid
- **Conclusion**: No changes needed; these files are compatible with v0.1.0

---

### 4. ✅ DOCUMENTATION_AUDIT.md Updated

- **Added section**: "Instrucciones IA divergentes del código real"
- **Elevated to Nivel 1 (Critical)**: SHARED_INSTRUCTIONS.md divergence now documented as blocker #0
- **Updated hallazgo count**: 6 → 7 Nivel 1 hallazgos
- **Added Fase 0 requirements**: 2-3 hours for instruction repair (completed)

---

## Files Modified

| File | Change | Status |
|------|--------|--------|
| `.github/SHARED_INSTRUCTIONS.md` | 8 major sections updated | ✅ Complete |
| `.github/prompts/functional_doc.prompt.md` | Especialización de dominio + guardrail | ✅ Complete |
| `.github/prompts/technical_doc.prompt.md` | Guardrail section added | ✅ Complete |
| `.github/DOCUMENTATION_AUDIT.md` | New Nivel 1 hallazgo + Fase 0 description | ✅ Complete |
| `CLAUDE.md` | Audited — no changes needed | ✅ Complete |
| `.claude/settings.json.example` | Audited — no changes needed | ✅ Complete |

---

## Verification Checklist

- [x] SHARED_INSTRUCTIONS.md no longer references non-existent modules
- [x] Especialización de dominio in prompts updated to match actual project
- [x] Guardrails added to prevent IA fabrication
- [x] All references to "[TODO vX.X]" modules marked explicitly
- [x] CLAUDE.md configuration validated as compatible
- [x] DOCUMENTATION_AUDIT.md updated with completion status
- [x] No references to database architecture (managers, bulk, metadata, comparar, etc.)
- [x] Architecture now correctly represents v0.1.0 Alpha state (3 modules, 5 planned)

---

## Status: ✅ READY FOR PHASE 1

**Next Steps**:
1. ✅ PHASE 0 (COMPLETE): Fix AI instructions infrastructure
2. 🟡 PHASE 1 (READY TO START): Implement Nivel 1 documentation (15 hours)
   - [1h] Restructure mkdocs.yml
   - [2h] Rewrite README.md
   - [2h] Complete docstrings (3 modules)
   - [4h] Create 6 functional docs
   - [5h] Create 5 technical docs

3. 🔲 PHASE 2 (BACKLOG): Create verified examples

---

## Key Accomplishment

🔴 **Before PHASE 0**: All IA-generated documentation would be 100% fabricated (referencing non-existent modules)  
✅ **After PHASE 0**: Prompts are safe to invoke; guardrails prevent inventing unimplemented modules

**Impact**: Enables safe, accurate documentation generation aligned with actual v0.1.0 Alpha codebase.

---

**Prepared by**: GitHub Copilot  
**Validated**: Documentation Audit Review  
**Ready for**: Feature Implementer (PHASE 1 execution)
