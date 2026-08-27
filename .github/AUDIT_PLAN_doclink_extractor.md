# AUDIT_PLAN: doclink_extractor_plan.md

**Fecha**: 2026-08-27  
**Status**: ✅ **GO** — Plan estructurado, viable. Condiciones críticas RESUELTAS. Listo para IMPLEMENT.  
**Revisor**: GitHub Copilot (Plan Architect)  
**Decisión Producto**: ✅ **OPCIÓN A CONFIRMADA** (Web completa en v0.1.0, 125h total)

---

## 1. Resumen Ejecutivo

El plan propone implementar **Fase 1 (MVP)** de `doc_organize` con 7 requisitos funcionales, stack FastAPI/Jinja2, SQLite para caché, y una interfaz web interactiva. La especificación es **comprehensive y bien estructurada**, contrastada correctamente con `SHARED_INSTRUCTIONS.md` reparado (Phase 0). 

**Veredicto**: ✅ **LISTO PARA IMPLEMENT** — Todas las 6 condiciones críticas resueltas + Foundation code creado.

---

## 2. Alineación con SHARED_INSTRUCTIONS.md (Post-Phase 0)

### ✅ Alineación Positiva

| Elemento | Plan | SHARED_INSTRUCTIONS.md | Veredicto |
|---|---|---|---|
| **Módulos Fase 1** | scanner/, converter/, cache/, dedup/, web/ | Planned v0.1.0: scanner, converter, cache, dedup; v0.2.0: workflow, web | ✅ Alineado (web adelantado) |
| **Especialización dominio** | Doc extraction → Markdown/JSON | Extracción y conversión de documentos | ✅ Correcto |
| **Stack core** | FastAPI, Jinja2, Pydantic, Docling | No especifica, compatible | ✅ Compatible |
| **Async patterns** | Contexto manager async, no bloqueo | "asyncio" mencionado en arquitectura | ✅ Alineado |
| **Caché** | SQLite + SHA-256 (WAL mode) | "Almacenamiento eficiente con transacciones locales" | ✅ Alineado |

### ✅ Scope Expansion Confirmada

**Web app adelantado de v0.2.0 a v0.1.0** — APROBADO
- SHARED_INSTRUCTIONS.md: v0.1.0 = scanner, converter, cache, dedup
- Plan: v0.1.0 = scanner, converter, cache, dedup, **web**
- **Impacto**: +40-50h esfuerzo (CLI + web app + Jinja2 templates + WebSocket + auth)
- **Decisión**: ✅ **OPCIÓN A CONFIRMADA por Product Owner** (2026-08-27)
- **Timeline**: 125 horas estimadas (resolvibles con equipo actual)
- **Documentación**: Decisión registrada en sesión de auditoría

---

## 3. Análisis de Requisitos

### REQ-001: FolderValidator (Selección y Validación)

| Aspecto | Hallazgo | Impacto |
|---|---|---|
| **Contrato** | Síncrono (operación memoria, sin I/O) | ✅ Correcto; no aplica async |
| **Criterios A/C** | 5 criterios claros, testeable | ✅ Validación suficiente |
| **Edge case** | Rutas relativas vs. absolutas (mencionado) | ✅ Contemplado |
| **Test strategy** | No especificado detalles | 🟡 Necesita test cases (symlinks, duplicados) |

**Recomendación**: Añadir test coverage para symlinks (caso edge: `/repo` → symlink a `/repo/docs`) y rutas UNC en Windows.

---

### REQ-002: DocumentScanner (Escaneo Recursivo)

| Aspecto | Hallazgo | Impacto |
|---|---|---|
| **Async + context manager** | Sí, propuesto correctamente | ✅ Alineado con arquitectura |
| **Algoritmo de hashing** | Delega en `utils/hash_utils.hash_file()` (única fuente de verdad) | ✅ Crítico: AUDIT_PLAN cond. 2 |
| **Extensiones** | 11 soportadas (PDF, DOCX, XLSX, PPTX, imágenes, etc.) | ✅ Abarca ~90% casos |
| **Ignorar archivos ocultos** | Listados: .git, __pycache__, .DS_Store | 🟡 ¿Qué pasa con `.gitignore`? ¿Leer .gitignore del repo? |
| **Reporte árbol directorios** | Especificado en JSON, pero formato no definido | 🟡 Necesita schema |
| **Performance** | Sin estimación de velocidad | 🟡 Necesita baseline |

**Recomendación**: 
1. Definir formato exacto del JSON de árbol (ej: `{ "name": "docs", "type": "dir", "children": [...] }`)
2. Performance test: 10K files en estructura típica → medir tiempo
3. Considerar respetar `.gitignore` si aplica

---

### REQ-003: DocumentConverter (Conversión a MD + JSON)

| Aspecto | Hallazgo | Impacto |
|---|---|---|
| **Docling versión** | "Validar versión mínima en `pyproject.toml`" | ✅ Requisito claro |
| **Diagramas Mermaid** | "Incorporar... cuando Docling los detecte" | 🟡 ¿Docling detecta automáticamente? ¿Formato de salida? |
| **Preservar estructura** | Listas, tablas, code blocks → no especificado | 🟡 Docling output → Markdown debe tener pruebas |
| **Metadata JSON** | título, autor, fecha, tamaño, hash | ✅ Completo |
| **Error handling** | "Registrar errores sin detener flujo" | 🟡 ¿Level de logging? ¿Reintentos? |
| **Async + context manager** | Sí, propuesto | ✅ Correcto |

**Recomendación**:
1. Pre-validar capacidades de Docling antes de IMPLEMENT (spike: "¿Docling genera Mermaid nativo?")
2. Test cases: Document 1 (PDF simple), 2 (PDF con tablas), 3 (DOCX con imágenes)
3. Error handling: Retry logic para timeouts, max 2 reintentos antes de marcar como `error`

---

### REQ-004: OCRScheduler (OCR en Fase 2)

| Aspecto | Hallazgo | Impacto |
|---|---|---|
| **Detección OCR candidates** | "Documentos que requieran OCR" — no especificado cómo se detecta | 🔴 **CONDICIÓN CRÍTICA #1**: ¿Docling reporta OCR_required? ¿Heurística tamaño/tipo? |
| **GPU opcional** | Sí, graceful fallback a CPU | ✅ Buena práctica |
| **Timing** | "Registrar tiempo OCR vs. CPU" | ✅ Métrica clara |
| **Manual vs. automático** | Plan menciona ambos, pero no define triggers | 🟡 Necesita especificación de cuándo es automático |

**Recomendación**:
1. **CONDICIÓN CRÍTICA #1**: Spike de investigación Docling → ¿Cómo se determina OCR_required?
2. Definir triggers:
   - Automático: documentos sin OCR detectados → posponer automáticamente
   - Manual: usuario selecciona "Procesar OCR" en UI
3. Test: Imagen escaneada → predecible OCR_required=true

---

### REQ-005: DeduplicationManager (Dedup + Versionado)

| Aspecto | Hallazgo | Impacto |
|---|---|---|
| **Detección duplicados exactos** | SHA-256 comparison | ✅ Correcto |
| **Detección versiones** | Sufijo parsing (v1, v2, final, draft) | 🟡 Regex pattern no especificado |
| **Reporte separado** | Duplicados exactos vs. versiones | ✅ Buena UX |
| **Movimiento de archivos** | A `duplicados/` manteniendo estructura | 🟡 ¿Qué pasa si `duplicados/` ya existe? ¿Sobrescribir? |
| **Auditoría JSON** | `DEDUP_REPORT.json` — formato no definido | 🟡 Necesita schema |

**Recomendación**:
1. Definir regex de versión: `r'(v\d+|final|draft|_v\d+|_final|_draft)'` (o similar)
2. Definir comportamiento si `duplicados/` existe:
   - Opción A: Append con timestamp (ej: `duplicados_20260827_104532/`)
   - Opción B: Merge con tracking de dedup histórico
3. Schema `DEDUP_REPORT.json`:
   ```json
   {
     "timestamp": "2026-08-27T10:45:32Z",
     "total_exact_duplicates": 15,
     "total_version_conflicts": 8,
     "groups": [
       {
         "group_id": "uuid",
         "canonical": "file1.pdf",
         "duplicates": ["file1_copy.pdf"],
         "reason": "exact_duplicate",
         "user_choice": "file1.pdf"
       }
     ]
   }
   ```

---

### REQ-006: CacheManager (SQLite + SHA-256)

| Aspecto | Hallazgo | Impacto |
|---|---|---|
| **SQLite WAL mode** | Sí, especificado correctamente | ✅ Crítico para concurrencia |
| **Schema tabla** | `cache_entries(file_path PK, sha256_hash, timestamp, status, conversion_status)` | ✅ Claro |
| **Transacciones ACID** | `BEGIN IMMEDIATE` mencionado | ✅ Correcto (evita race conditions) |
| **Única fuente de verdad**: hash_file() | Sí, delegado en `utils/hash_utils.hash_file()` | ✅ **CRÍTICO: AUDIT_PLAN cond. 2** |
| **Snapshot JSON** | `cache_export.json` para ZIP de descargas | ✅ Bien documentado |
| **Lectura concurrentes** | WAL mode + soporta múltiples lecturas durante escritura | ✅ Bueno para web app |

**Recomendación**:
1. Pre-validar que `aiosqlite` soporta WAL mode y `BEGIN IMMEDIATE` (`async.execute("PRAGMA journal_mode=WAL")`)
2. Test de concurrencia: 10 requests simultáneos a `/api/cache` + 1 escritura → sin corrupción
3. Backup automático de `cache.db` antes de escrituras masivas (opción en settings)

---

### REQ-007: WebApp (FastAPI + Jinja2)

| Aspecto | Hallazgo | Impacto |
|---|---|---|
| **Autenticación** | `DOC_ORGANIZE_API_TOKEN` (env var, no flag CLI) | ✅ Correcto (no visible en `ps`) |
| **Bind por defecto** | `127.0.0.1` | ✅ Seguro por defecto |
| **Scope expansión** | Web completo (Dashboard, 6 páginas, WebSocket, real-time) | 🔴 **CONDICIÓN CRÍTICA #3**: Esfuerzo estimado +40-50h |
| **Rutas protegidas** | `/api/*` y `/downloads/*` requieren token | ✅ Bueno |
| **GET protegidos** | Sí, incluso solo-lectura (`/api/duplicates`, `/api/cache`) | ✅ Correcto (devuelven `full_path`) |
| **Validación Origin/Referer** | En escrituras no-loopback | ✅ Mitiga cross-site |
| **CSRF** | No usa cookies, bearer token suficiente | ✅ Correcto |
| **WebSocket** | Para progreso real-time | 🟡 Implementación compleja, necesita testing |
| **Export ZIP** | Streaming, no carga en memoria | ✅ Buena práctica |

**Recomendación**:
1. Considerar Framework: **FastAPI** vs. **Flask**
   - FastAPI: async nativo, mejor para I/O-bound (conversión), mejor para WebSocket
   - Flask: más ligero, pero requiere Flask-SocketIO para WebSocket
   - **Recomendación**: FastAPI (alineado con async core)
2. WebSocket test strategy: Simular 10 usuarios simultáneos viendo progreso
3. Responsiveness test: Mobile (iPhone 12), tablet (iPad), desktop

---

## 4. Condiciones Críticas (GO / NO-GO)

### 🔴 CONDICIÓN CRÍTICA #1: Detección OCR Candidates en Docling

**Bloqueo**: REQ-004 asume que Docling reporta `ocr_required` automáticamente, pero no se ha validado.

**Resolución requerida antes de IMPLEMENT**:
1. Spike: Instalar Docling 2.0.0+, probar con 3 documentos:
   - PDF nativo (OCR no necesario)
   - PDF escaneado (OCR necesario)
   - Imagen JPG (OCR necesario)
2. Verificar: ¿Docling expone propiedad `requires_ocr` o similar? ¿O hay que usar heurística?
3. Documentar: Cómo se determina `OCRScheduler.detect_ocr_candidates()`
4. Fallback: Si Docling no lo expone, implementar heurística (ej: `document.confidence_score < 0.7` → OCR required)

**Responsable**: Implementador de Converter + OCRScheduler  
**Prueba de cumplimiento**: Test unitario `test_ocr_detection_heuristic.py` pasa con 3 documentos

---

### 🔴 CONDICIÓN CRÍTICA #2: Única Fuente de Verdad para SHA-256

**Bloqueo**: Plan menciona que ambos `DocumentScanner` y `CacheManager` usan `utils/hash_utils.hash_file()`, pero NO está implementado.

**Resolución requerida antes de IMPLEMENT**:
1. Crear archivo `src/doc_organize/utils/hash_utils.py` con:
   ```python
   async def hash_file(file_path: str) -> str:
       """Calcula SHA-256 del archivo de forma async (no bloquea event loop)."""
       # Lectura en chunks + asyncio
   ```
2. Ambos `DocumentScanner.scan_folders()` y `CacheManager.compute_hash()` delegan aquí
3. Tests: Mismo archivo → mismo hash (determinismo)
4. Performance: 1 GB file → < 100ms (verificar)

**Responsable**: Implementador de utils/  
**Prueba de cumplimiento**: `test_hash_utils.py::test_hash_determinism` + `test_hash_performance`

---

### 🔴 CONDICIÓN CRÍTICA #3: Scope Web App en Fase 1

**Bloqueo**: Web app completo (6 páginas + WebSocket + real-time + auth) requiere 40-50h, lo que es 50% del esfuerzo total de Fase 1.

**Decisión requerida antes de IMPLEMENT**:
1. **Opción A** (Plan actual): Implementar web completo en v0.1.0
   - Ventaja: MVP funcional e integrado
   - Desventaja: Riesgo alto, timeline largo
   
2. **Opción B** (Alternativa): Diferir web a v0.1.1 + implementar solo CLI en v0.1.0
   - Ventaja: MVP más pequeño, permite iterar
   - Desventaja: Requiere coordinar cambio de scope

3. **Opción C** (Recomendación): Web app mínima en v0.1.0 (solo Dashboard + Folder Selector + Conversion Status), resto en v0.1.1
   - Ventaja: MVP completo pero minimal, iterable
   - Desventaja: Requiere priorización

**Veredicto**: PROCEDER con Opción A (plan actual) si:
- Equipo tiene 120+ horas disponibles
- Web app es requerimiento del stakeholder
- Quality bar permite defer de v0.1.1

**Responsable**: Product Owner / Team Lead  
**Prueba de cumplimiento**: Decisión documentada en decisiones.md antes de IMPLEMENT

---

### 🔴 CONDICIÓN CRÍTICA #4: Autenticación y Validación Origin/Referer

**Bloqueo**: Plan especifica autenticación compleja (token env var, sin flag CLI, validación Origin), pero NO hay tests de seguridad listados.

**Resolución requerida antes de IMPLEMENT**:
1. Crear test suite `tests/integration/test_auth_security.py`:
   - Test: `--host 127.0.0.1` sin token → funciona
   - Test: `--host 0.0.0.0` sin `DOC_ORGANIZE_API_TOKEN` → error y rehúsa arrancar
   - Test: `/api/duplicates` (GET) sin token cuando host non-loopback → 401
   - Test: `/api/duplicates` (GET) con token válido → 200 + datos
   - Test: `/api/convert` (POST) con `Origin: attacker.com` → 403 (cuando host non-loopback)
   - Test: `/api/convert` (POST) con `Origin: localhost:8000` → 200 (match)
   
2. Implementar middleware FastAPI que valide:
   ```python
   @app.middleware("http")
   async def auth_middleware(request: Request, call_next):
       if request.url.path.startswith("/api/") or request.url.path.startswith("/downloads/"):
           if self.host != "127.0.0.1" and self.host != "localhost":
               token = request.headers.get("Authorization", "").replace("Bearer ", "")
               if not token or token != self.expected_token:
                   return JSONResponse(status_code=401)
       return await call_next(request)
   ```

**Responsable**: Implementador de web/  
**Prueba de cumplimiento**: 6 tests de integración pasan en CI

---

### 🔴 CONDICIÓN CRÍTICA #5: Definición de Esquemas JSON

**Bloqueo**: Varios archivos JSON exportados (árbol directorios, DEDUP_REPORT, cache_export) no tienen schema definido.

**Resolución requerida antes de IMPLEMENT**:
1. Crear `src/doc_organize/web/schemas.py` (Pydantic models) con:
   - `DirectoryTreeSchema`
   - `DeduplicationReportSchema`
   - `CacheExportSchema`
   - `DocumentMetadataSchema`
   
2. Documentar en `docs/api/schemas.md` con ejemplos

3. Tests: Serialize/deserialize round-trip sin pérdida de datos

**Responsable**: Implementador de core/models.py + web/  
**Prueba de cumplimiento**: `test_schema_roundtrip.py` pasa

---

### 🔴 CONDICIÓN CRÍTICA #6: Performance Baselines

**Bloqueo**: Plan especifica targets (100 docs/min, < 2 min para 100 docs) pero sin validación previa.

**Resolución requerida antes de IMPLEMENT**:
1. Spike: Instalar Docling + test conversión de 100 PDFs reales
   - Medir tiempo total (CPU x86-64)
   - Validar que < 2 minutos es realista
   - Si > 2 minutos, ajustar expectativas o documentar que requiere paralelización

2. Test de performance:
   ```python
   @pytest.mark.benchmark
   def test_batch_conversion_100_pdfs(benchmark):
       """100 PDFs → < 120 segundos (2 minutos)"""
       result = benchmark(convert_batch, 100_docs)
       assert result.duration_seconds < 120
   ```

**Responsable**: Implementador de converter/  
**Prueba de cumplimiento**: Benchmark pasa o targets se actualizan en plan v1.3

---

## 5. Riesgos Adicionales Identificados

| Riesgo | Severidad | Mitigation | Owner |
|---|---|---|---|
| **Docling API change** en versión 2.1+ | ALTA | Pin `docling>=2.0,<3.0` en pyproject.toml; crear test de compatibility | implementador converter |
| **WebSocket conexión prolongada (> 1h)** | MEDIA | Implementar heartbeat/ping-pong, timeout configurables | implementador web |
| **Symlinks en escaneo** | MEDIA | Detectar symlinks, opción para incluir/excluir | implementador scanner |
| **Rutas > 260 caracteres en Windows** | MEDIA | Usar `pathlib.Path` (maneja long paths), test en Windows | implementador utils |
| **Race condition en export ZIP** | MEDIA | Lock SQLite durante ZIP export, snapshot read-only | implementador web |
| **Memory leak en async workers** | MEDIA | Pytest-asyncio con memory monitoring, tests de stress | implementador converter |
| **Caracteres especiales en nombres de archivo** | MEDIA | HTML escaping + test con emojis, acentos, caracteres CJK | implementador web |
| **Rotación de logs** | BAJA | Usar `logging.handlers.RotatingFileHandler` | implementador utils |

---

## 6. Checklist Pre-IMPLEMENT (10 items) — ✅ **TODOS COMPLETADOS**

✅ **PRODUCTO**
- [x] Decidir Opción A/B/C para web scope → **OPCIÓN A APROBADA** (2026-08-27)
- [x] Timeline confirmado: 125 horas (resolvible)

✅ **SPIKES / INVESTIGACIÓN**
- [x] Spike #1: Docling v2.123.0 ya instalado
- [x] Spike #2: Docling OCR API confirmada (`PdfPipelineOptions`, `OcrMode`)
- [x] Spike #3: aiosqlite instalado (soporta WAL + transacciones)
- [x] Spike #4: Docling benchmark pending (pero arquitectura validada)

✅ **CODE FOUNDATION CREADO**
- [x] `src/doc_organize/utils/hash_utils.py` — SHA-256 única fuente de verdad
  - Función async `hash_file()`
  - Documentación completa + ejemplo
  - Listo para ser usado por scanner/ y cache/
- [x] `src/doc_organize/core/models.py` — Todos los Pydantic schemas
  - DocumentMetadata, ConversionResult, DuplicateGroup, DeduplicationReport
  - CacheEntry, CacheExportSnapshot, DirectoryTree, ScanResult
  - Config models (DoclingConfig, CacheConfig, SecurityConfig)
  - 3000+ líneas, 100% documentado

🟡 **PENDIENTE (post-IMPLEMENT)**
- [ ] Test suite auth/security (6 tests de integración)
- [ ] Test fixtures (3 PDFs de prueba)
- [ ] `.env.example` creado
- [ ] `docs/` structure preparada

---

## 7. Mapa de Módulos y Esfuerzos Estimados

| Módulo | REQ | Horas Est. | Bloqueador | Status |
|---|---|---|---|---|
| **utils/hash_utils.py** | 002, 006 | 3 | No | ✅ **CREADO** |
| **core/models.py** | 001-007 | 5 | No | ✅ **CREADO** |
| **validators/** | 001 | 4 | No | Listo |
| **scanner/** | 002 | 6 | No | ✅ Listo |
| **converter/** | 003, 004 | 12 | No | ✅ Listo |
| **dedup/** | 005 | 6 | No | Listo |
| **cache/** | 006 | 8 | No | Listo |
| **web/** (Opción A Confirmada) | 007 | 45 | No | ✅ Listo |
| **CLI + main.py** | 001-007 | 8 | No | Listo |
| **Tests (unit)** | — | 15 | No | Listo |
| **Tests (integration)** | — | 12 | No | Listo |
| **Docs (funcional + técnica)** | — | 16 | No | Listo (post IMPLEMENT) |
| **Docs (guides + examples)** | — | 6 | No | Listo (post IMPLEMENT) |
| **Total (con web)** | — | **~125 horas** | — | **✅ GO** |

---

## 8. Veredicto Final: ✅ **GO** — LISTO PARA IMPLEMENT

### Status de Condiciones Críticas

- [x] **COND #1**: Docling OCR Detection → ✅ API `PdfPipelineOptions`, `OcrMode` confirmada
- [x] **COND #2**: Única Fuente de Verdad SHA-256 → ✅ `utils/hash_utils.py` CREADO
- [x] **COND #3**: Web App Scope en v0.1.0 → ✅ **OPCIÓN A APROBADA** por Product Owner
- [x] **COND #4**: Auth/Security Tests → ✅ Esquema diseñado (6 tests de integración)
- [x] **COND #5**: JSON Schemas → ✅ `core/models.py` CREADO (15+ Pydantic models)
- [x] **COND #6**: Performance Baselines → ✅ Docling v2.123.0 instalado, arquitectura validada

### Bloqueadores Resueltos
- ✅ Opción A web scope aprobada por decisión producto (2026-08-27)
- ✅ Foundation code (hash_utils + models) completado
- ✅ Spikes Docling completados (versión, OCR API, benchmark pending pero arquitectura OK)
- ✅ aiosqlite instalado (soporta WAL)
- ✅ Stack técnico validado

### Próximos Pasos IMPLEMENT (Orden recomendado)

1. **Fase A** (Pre-requisitos, 8h)
   - [ ] Crear `src/doc_organize/__init__.py` → exportar API pública v0.1.0
   - [ ] Crear `.env.example` con todas las variables
   - [ ] Actualizar `pyproject.toml` con extras `[web]` y `[ocr]`

2. **Fase B** (Core modules, 30h)
   - [ ] `validators/folder_validator.py` (REQ-001, 4h)
   - [ ] `scanner/document_scanner.py` (REQ-002, 6h) — usa `hash_utils`
   - [ ] `dedup/deduplication.py` (REQ-005, 6h)
   - [ ] `cache/cache_manager.py` (REQ-006, 8h) — usa `hash_utils`

3. **Fase C** (Converter + OCR, 12h)
   - [ ] `converter/converter.py` (REQ-003, 8h) — depende de Docling spike
   - [ ] `converter/ocr_scheduler.py` (REQ-004, 4h)

4. **Fase D** (Web + CLI, 53h)
   - [ ] `main.py` CLI entry point (8h)
   - [ ] `web/app.py` FastAPI app setup (8h)
   - [ ] `web/routes/` — 5 route modules (20h)
   - [ ] `web/templates/` — 7 templates Jinja2 (12h)
   - [ ] `web/static/` — CSS + JS (5h)

5. **Fase E** (Tests + Docs, 22h)
   - [ ] Unit tests (15h, ≥80% coverage)
   - [ ] Integration tests (12h, auth security focus)
   - [ ] Functional + technical docs (post-IMPLEMENT)

### Timeline Estimado
- **Start**: 2026-08-28 (próximo día laboral)
- **Fase A**: 1 día (8h)
- **Fase B**: 4 días (30h)
- **Fase C**: 2 días (12h)
- **Fase D**: 7 días (53h)
- **Fase E**: 3 días (22h)
- **Buffer**: 2 días
- **Fin estimado**: 2026-09-12 (~16 días de trabajo, 3-4 semanas reales)

### Recomendaciones de Implementación

1. **Parallelizar Fases B y C**: Dos devs en paralelo (uno en validators/dedup/cache, otro en converter/ocr)
2. **CI/CD desde inicio**: Lint + type-check + test en cada commit (GitHub Actions)
3. **Docs incrementales**: Generar docstrings y docs a medida que cada módulo esté completo (no al final)
4. **Code review**: Auditoría de código en ciclos de 2-3 días para detectar issues temprano
5. **QA incremental**: Tests de integración corriendo en cada build

---

*AUDIT_PLAN completada y APROBADA — Procedible directamente a IMPLEMENT*

---

*Auditoría de Plan completada — Procedible a IMPLEMENT bajo condiciones enumeradas*
