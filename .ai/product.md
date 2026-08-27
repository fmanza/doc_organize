# 📦 Product Context — Doclink Extractor

## Descripción Ejecutiva

**Doclink Extractor** es una aplicación Python full-stack para extracción y conversión de documentos heterogéneos (PDF, Word, Excel, imágenes, etc.) a formatos estándar (Markdown con Mermaid, JSON). Utiliza [Docling 2.0](https://docling.ai/) como motor de extracción, con interfaz web + CLI, caché inteligente, deduplicación automática y soporte OCR en GPU.

**Propósito Primario**: Equipos de documentación que necesitan normalizar repositorios heterogéneos en markdown versionado.

**Versión**: 1.0-MVP | **Estado**: PRE-IMPLEMENT (Blockers Resueltos) | **Python**: ≥3.10

---

## Capacidades Principales

### Core Processing
- ✅ **Extracción con Docling 2.0.1+**: Conversión batch PDF→Markdown + JSON con preservación de estructura
- ✅ **Soporte Multi-Formato**: PDF, DOCX, XLSX, PPTX, PNG, JPG, TIFF, BMP, HTML
- ✅ **Markdown Enriquecido**: Diagramas como bloques Mermaid, tablas, listas, código
- ✅ **JSON Estructurado**: Metadata (título, autor, fecha, tamaño), contenido, relaciones

### Inteligencia de Caché
- ✅ **Caché con SHA-3**: Detección automática new/modified/unchanged files
- ✅ **Incremental Processing**: Solo procesa documentos nuevos o modificados
- ✅ **Transacciones Atómicas**: Backup + rollback en caso de error (cache.json consistency)
- ✅ **State Machine Documentos**: pending → converting → success | error → recovered | final_error

### Deduplicación & Versioning
- ✅ **Duplicados Exactos**: Detección SHA-3, movimiento a carpeta `duplicados/`
- ✅ **Versiones Conflictivas**: Detección heurística (v1, v2, final, draft, etc.)
- ✅ **Resolución UI**: Usuario elige qué versión mantener (default: más viejo)
- ✅ **Reporte Auditoria**: DEDUP_REPORT.json con decisiones y timestamps

### OCR Inteligente
- ✅ **Detección Automática**: Identifica documentos que requieren OCR
- ✅ **Procesamiento en Dos Fases**: Fase 1 sin OCR (rápido), Fase 2 con GPU (opcional)
- ✅ **GPU Optional**: Funciona con CPU; graceful degradation si torch no disponible
- ✅ **Providers Extensibles**: Interfaz para múltiples motores OCR (Docling native, PaddleOCR, etc.)

### Interfaz Web
- ✅ **Dashboard**: Resumen estado, última ejecución, acciones rápidas
- ✅ **Folder Selector**: Selección inteligente de carpetas (valida no-redundancia)
- ✅ **Scan Results**: Tabla de documentos encontrados, conteo por extensión, tree visual
- ✅ **Conversion Status**: Progreso real-time via Server-Sent Events (SSE), errores visuales
- ✅ **Duplicates Resolver**: Compare lado-a-lado, selección interactiva
- ✅ **Cache Viewer**: Changelog (new/modified/unchanged), descarga cache.json
- ✅ **Settings**: Configuración de Docling, GPU, idioma OCR, version patterns
- ✅ **Export**: Descarga ZIP con conversión + reportes (Markdown, JSON, audit logs)

### CLI
- `doclink scan` — Escanear carpetas, generar reporte
- `doclink convert` — Conversión batch con progreso
- `doclink web` — Servidor web (uvicorn)
- `doclink dedup` — Deduplicación standalone
- `doclink status` — Ver estado caché y últimas ejecuciones

---

## Arquitectura Módular

```
src/doclink_extractor/
├── core/
│   ├── models.py              # Dataclasses (DocumentMetadata, CacheEntry, etc.)
│   ├── exceptions.py          # Jerarquía de excepciones
│   └── constants.py           # Extensiones soportadas, magic numbers
│
├── validators/                # Validación de entrada
│   └── folder_validator.py    # FolderValidator (no-redundancia)
│
├── scanner/                   # Escaneo de documentos
│   └── document_scanner.py    # DocumentScanner (SHA-3, estructura árbol)
│
├── converter/                 # Extracción Docling
│   ├── converter.py           # DocumentConverter (Markdown + JSON)
│   └── ocr_scheduler.py       # OCRScheduler (Fase 2, GPU optional)
│
├── dedup/                     # Deduplicación
│   └── deduplication.py       # DeduplicationManager (SHA-3, heurística versiones)
│
├── cache/                     # Gestión caché
│   └── cache_manager.py       # CacheManager (transactional I/O, backup/rollback)
│
├── workflow/                  # 🆕 Orquestación (Resolver B6)
│   ├── orchestrator.py        # Orchestrator (state machine, retry logic)
│   └── state_machine.py       # DocumentState enum + transitions
│
├── web/                       # API Web + UI
│   ├── app.py                 # FastAPI app + Uvicorn config
│   ├── routes/
│   │   ├── folders.py         # POST /api/folders/*, GET /documents
│   │   ├── conversion.py      # POST /api/convert (SSE), GET /api/status
│   │   ├── duplicates.py      # GET /api/duplicates, POST /api/duplicates/resolve
│   │   ├── cache.py           # GET /api/cache, endpoints cache
│   │   └── downloads.py       # GET /downloads/export.zip
│   ├── templates/             # Jinja2 templates (8 páginas)
│   │   ├── base.html
│   │   ├── index.html         # Dashboard
│   │   ├── folder_selector.html
│   │   ├── scan_results.html
│   │   ├── conversion_status.html
│   │   ├── duplicates_resolver.html
│   │   ├── cache_viewer.html
│   │   └── settings.html
│   └── static/
│       ├── css/style.css      # Bootstrap 5 customizaciones
│       └── js/app.js          # WebSocket/SSE client, interactividad
│
├── utils/
│   ├── logging.py             # Logging estructurado (JSON)
│   ├── path_utils.py          # Normalización rutas, validación
│   └── hash_utils.py          # SHA-3/SHA-2 compute
│
└── _core/
    └── async_utils.py         # maybe_await, streaming helpers
```

---

## Decisiones Arquitectónicas (ADRs)

### ADR-001: Server-Sent Events (SSE) para Progreso Conversión
- **Status**: ✅ ACEPTADO
- **Rationale**: Simplicidad MVP, testing fácil, stateless server
- **Trade-off**: Latencia 500ms vs. WebSocket 100ms
- **Migración v1.1**: A WebSocket si > 500 usuarios simultáneos
- **Doc**: `.github/adr/001-sse-vs-websocket.md`

### ADR-002: Centralized CacheManager con Orchestrator
- **Status**: ✅ ACEPTADO
- **Rationale**: Responsabilidad única, transacciones atómicas, debugging observable
- **Trade-off**: Mutex potential bottleneck en 10K+ docs
- **Migración v1.1**: A event-driven si > 5000 docs
- **Doc**: `.github/adr/002-cache-architecture.md`

---

## Stack Tecnológico (Validado)

| Componente | Versión | Razón |
|---|---|---|
| **Python** | ≥3.10 | Docling requirement |
| **Docling** | ≥2.0.1 | Extracción documentos (validado: stable, no CVEs) |
| **FastAPI** | ≥0.100 | API async, Jinja2 built-in |
| **Uvicorn** | ≥0.23 | ASGI server, compatible con FastAPI |
| **Pydantic** | ≥2.0 | Validación data models |
| **python-multipart** | ≥0.0.6 | Form uploads (AGREGADO post-audit) |
| **aiofiles** | ≥23.0 | Async I/O (no bloquea) |
| **Pillow** | ≥10.0 | Image processing (Docling dependency) |
| **pandas** | ≥2.0 | Data analysis (DuplicateGroup) |
| **torch** | ≥2.0 | GPU OCR (OPTIONAL, graceful degradation) |
| **pytest** | ≥7.4 | Testing |
| **pytest-asyncio** | ≥0.21 | Async testing |
| **ruff** | ≥0.1 | Linting + formatting |
| **mypy** | ≥1.5 | Type checking |

---

## Requisitos Funcionales (REQ-001-007)

| REQ | Descripción | Status |
|---|---|---|
| **REQ-001** | Selección + validación carpetas (no-redundancia) | ✅ ESPECIFICADO |
| **REQ-002** | Escaneo recursivo, conteo por extensión, ignorar ocultos | ✅ ESPECIFICADO |
| **REQ-003** | Conversión → Markdown + JSON, estructura preservada, Mermaid | ✅ ESPECIFICADO |
| **REQ-004** | Detección OCR, Fase 2 opcional, GPU optional | ✅ ESPECIFICADO |
| **REQ-005** | Deduplicación exacta + versiones, resolución UI, auditoria | ✅ ESPECIFICADO |
| **REQ-006** | Caché SHA-3/SHA-2, detección cambios, transaccional | ✅ ESPECIFICADO |
| **REQ-007** | Interfaz web (8 páginas) + Jinja2 + Bootstrap5 | ✅ ESPECIFICADO |

---

## Performance SLA (Validado en Blockers)

| Métrica | Target Inicial | Target Revisado | Validación |
|---|---|---|---|
| Batch 100 PDFs (sin OCR) | < 2 min ❌ | < 10 min ✅ | POC + analysis docling |
| Memory 100 docs | 500 MB | 600-800 MB ✅ | Sim. asyncio |
| WebSocket latency | n/a | SSE 200-500ms ✅ | RFC 6585 |
| Caché incremental | baseline | 90% skip rate ✅ | SHA-3 comparison |

---

## Requisitos No-Funcionales

- **Seguridad**: Path traversal prevention, CSRF tokens, Jinja2 escaping, SQL injection (N/A)
- **Observabilidad**: Logging estructurado (JSON), tiempos por fase, métricas Prometheus (opcional)
- **Reproducibilidad**: Hashes SHA-3 deterministas, cache.json versionado
- **Escalabilidad**: MVP < 100 usuarios; v1.1 WebSocket + Redis si > 500
- **Disponibilidad**: OCR graceful degradation, conversión sin GPU

---

## Riesgos Identificados & Mitigaciones

| Riesgo | Severidad | Mitigation | Status |
|---|---|---|---|
| **Path Traversal** | ALTA | Validación strict pathlib, tests OWASP | 📋 PENDING (IMPLEMENT) |
| **Performance 100 PDFs** | ALTA | Benchmark POC, ajustar SLA | ✅ RESUELTO (B2) |
| **Docling 2.0 stability** | ALTA | Changelog + CVE review | ✅ RESUELTO (B1) |
| **Cache.json corruption** | MEDIA | Backup + rollback + validation | ✅ RESUELTO (B6, B7) |
| **Dedup UI confusion** | MEDIA | Visual compare lado-a-lado | ✅ ESPECIFICADO (REQ-005) |
| **Memory leak async** | MEDIA | Workers limit, monitoring | ✅ ESPECIFICADO (NoFR) |
| **OCR without GPU** | MEDIA | Graceful degradation con CPU | ✅ ESPECIFICADO (REQ-004) |

---

## Blockers Resolution Summary

**7 Blockers Resueltos (2026-08-27)**:

| ID | Blocker | Status | Esfuerzo |
|---|---|---|---|
| B1 | Docling 2.0 estabilidad | ✅ | 2h |
| B2 | POC benchmark 100 PDFs | ✅ | 3h |
| B3 | SSE vs. WebSocket | ✅ ADR-001 | 2h |
| B4 | python-multipart | ✅ | 0.25h |
| B5 | Algoritmo versiones dedup | ✅ | 2h |
| B6 | Orchestrator workflow/ | ✅ ADR-002 | 4h |
| B7 | Error recovery + state machine | ✅ ADR-002 | 6h |

**Tiempo Total Blocker Resolution**: 14-16h ✅ COMPLETADO
**Artefactos**: `.github/BLOCKERS_RESOLUTION.md`, 2 ADRs, PLAN actualizado

---

## Criterios Definition of Done (Fase MVP)

### Code Quality
- [ ] Docstrings Google-style en 100% funciones públicas
- [ ] Type hints: 100% en firma de funciones
- [ ] Linting ruff: 0 errores
- [ ] Tests: ≥80% cobertura
- [ ] Tests pasan en Python 3.10, 3.11, 3.12

### Documentation
- [ ] README: instalación + quickstart
- [ ] docs/usage.md: CLI + Web guías
- [ ] docs/architecture.md: diagramas + responsabilidades
- [ ] API docstrings + examples

### Funcionalidad
- [ ] Todos REQ-001-007 pasados
- [ ] Web UI responsive (Chrome, Firefox)
- [ ] Export ZIP: Conversión/ + cache.json + DEDUP_REPORT.json
- [ ] OCR graceful degradation sin torch

### Performance
- [ ] Batch 100 PDFs < 10 min (4-8 workers)
- [ ] Memory < 800 MB peak (100 docs)
- [ ] SSE progreso < 500ms

### Security (Nice-to-Have MVP)
- [ ] Path traversal tests
- [ ] Jinja2 escaping validado
- [ ] CSRF tokens en forms
- [ ] No credentials en logs

---

## Próximos Pasos

### IMPLEMENT Phase
1. ✅ Plan + Blockers resueltos (este documento)
2. 📋 Crear proyecto `doclink-extractor` (nuevo workspace/repo)
3. 📋 Feature Implementer: Módulos base (core/ → validators/ → scanner/ → converter/ → dedup/ → cache/ → workflow/ → web/)
4. 📋 AUDIT_CODE: Verificación independiente
5. 📋 VERSION: Changelog + release

### Timeline Estimado (post-Blockers)
- **IMPLEMENT**: 40-60h
- **AUDIT_CODE**: 8-12h  
- **VERSION**: 4-6h
- **Total MVP**: 66-94h ✅ (14h saved con Blockers resolution)

---

## Referencias

- 📄 Especificación Completa: `.github/prompts/doclink_extractor_plan.md`
- 📋 Reporte Audit Plan: Incluido en archivo plan.md
- 🏗️ ADR-001 (SSE): `.github/adr/001-sse-vs-websocket.md`
- 🏗️ ADR-002 (Cache): `.github/adr/002-cache-architecture.md`
- 📊 Blockers Resolution: `.github/BLOCKERS_RESOLUTION.md`
- 🔗 Docling Docs: https://docling.ai/
- 🔗 FastAPI Docs: https://fastapi.tiangolo.com/

---

**Documento Actualizado**: 2026-08-27  
**Autor**: Plan Architect + Blockers Resolution  
**Clasificación**: INTERNAL — Team Only  
**Estado**: READY FOR IMPLEMENT
