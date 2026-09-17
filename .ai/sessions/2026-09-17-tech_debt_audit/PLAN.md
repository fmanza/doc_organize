# PLAN: Auditoría de Deuda Técnica — doc_organize v0.9.0

**Fecha**: 2026-09-17  
**Proyecto**: doc_organize (Python 3.11+, Pydantic v2, FastAPI + AsyncIO)  
**Alcance**: Módulos completos de `src/doc_organize/` (15 submódulos identificados)  
**Política de compatibilidad**: Conservadora (sin breaking changes de API pública)  
**Fases autorizadas**: PLAN + AUDIT_PLAN + AUDIT_CODE (sin IMPLEMENT)

---

## Supuestos declarados

| Supuesto | Valor | Ratificación |
|----------|-------|--------------|
| **Scope** | TODO el proyecto `src/doc_organize/` | Solicitud: "de todo el proyecto" |
| **Fases** | PLAN + AUDIT_PLAN + AUDIT_CODE | Sin "IMPLEMENT" en solicitud → análisis solo |
| **Política** | Conservadora (no breaking changes públicos) | Estándar de librerías Python |
| **Versión** | 0.9.0 (estable alpha) | Del `pyproject.toml` |
| **Python** | >= 3.11 (con 3.12, 3.13, 3.14 certificados) | Del `pyproject.toml` |
| **Alineación** | SHARED_INSTRUCTIONS.md §"Principios de diseño" | SOLID, clases para servicios, async/await |

---

## Contexto de referencia

### Proyecto
- **Descripción**: Librería Python de extracción, conversión y organización de documentos (PDF, DOCX, XLSX, PPTX) → Markdown/JSON con caché transaccional SQLite.
- **Madurez**: Alpha (v0.9.0), ~15 submódulos activos, 251 tests en 58 archivos.
- **Dependencias críticas**: `docling>=2.0.0`, `pydantic>=2.0`, `fastapi>=0.100`, `aiosqlite>=0.19`.

### Principios arquitectónicos actuales
- ✅ **SRP**: Módulos especializados (scanner, converter, cache, dedup, auth, web)
- ✅ **OCP**: Extensión vía clientes de IA (taxonomy_classification_client, domain_classification_client, etc.)
- ✅ **Async/await**: Operaciones IO con `asyncio`, context managers (`async with`)
- ✅ **Excepción jerárquica**: Base `DocOrganizeError`, excepciones específicas por módulo
- ⚠️ **Tipado**: Pydantic v2 fuerte, pero `Any` sin restricción en algunos puntos (Docling)
- ⚠️ **Testing**: Suite completa, pero gaps puntuales en cobertura de error paths

---

## Hallazgos iniciales (contexto de sesión)

### Por categoría de deuda

#### 1. Tipado incompleto (`Any` sin restricción)
- **Localizaciones**: 
  - `converter/converter.py:243` → `_clamp_confidence(raw: Any) -> float`
  - `converter/converter.py:330` → `docling_result: Any` (intentional: Docling sin stubs)
  - `converter/converter.py:399-402` → `_build_chunks(document: Any, ...)` (mismo)
  - `converter/converter.py:446-449` → `_needs_ocr(docling_result: Any)`
- **Impacto**: Bajo (Docling no tiene stubs públicos; es una dependencia no tipada)
- **Raíz**: Librería Docling (`docling>=2.0.0`) no proporciona `.pyi` type stubs
- **Estrategia**: Documentar la decisión en `ARCHITECTURE.md` (seguir comentarios inline ya presentes)

#### 2. Excepciones amplias (`except Exception` sin discriminación)
- **Localizaciones** (5 instancias):
  1. `auth/auth_store.py:547` → rollback silencioso en `_backfill_instance_admins`
  2. `converter/converter.py:219` → captura en `convert()` (deliberada: no abortar batch)
  3. `projects/project_registry.py:139` → lectura de JSON fallida
  4. `projects/project_registry.py:288` → escritura de JSON fallida
  5. `scan/scan_command.py:733` → reenvío de excepción a cola (deliberado: captura `asyncio.CancelledError`)
- **Impacto**: Bajo en runtime; riesgo: ocultación silenciosa de errores inesperados
- **Raíz**: Búsqueda de balance entre robustez (un fichero bloqueado no debe abortar el batch) y debugging
- **Prioridad**: `quick_win` (documentar intención en comentarios, mejorar logging)

#### 3. Bugs reales documentados (histórico acumulado)
- **8+ comentarios de "bug real"** en:
  - `converter.py:183` (Docling, sesión 2026-09-16)
  - `converter.py:223` (ZAP report, ~60 MB, sesión 2026-09-05)
  - `converter.py:230` (fallback genérico)
  - `converter.py:277` (imágenes en .docx truncado)
  - `converter.py:293` (nombre con caracteres especiales)
  - `converter.py:467` (.xlsx truncado/corrupto)
  - `office_detector.py:14` (test de .xls sin LibreOffice)
  - Varios en `auth/`, `context/`, `scan/` (histórico)
- **Impacto**: Medio (conocidos y con workarounds, pero no centralizados en issue tracker)
- **Raíz**: Migración incremental; bugs reportados ad-hoc en sesiones, no en GitHub Issues
- **Estrategia**: Crear GitHub Issues de referencia para cada bug documentado

#### 4. Lock compartido no serializable (ProjectRegistry)
- **Localización**: `web/app.py:85-86` (AUDIT_CODE 2026-09-03)
- **Problema**: Antes cada petición creaba su propio `ProjectRegistry()`; con su propio lock inútil. Ahora compartido en `app.state`, pero:
  - El lock protege escrituras a `projects.json`, no a lectura concurrente de cache
  - `web/dependencies.py::get_project_registry()` crea un **context manager** que no garantiza re-entancia
- **Impacto**: Bajo en práctica (Python GIL + SQLite WAL mitigan), pero arquitecturalmente frágil
- **Raíz**: Context manager asíncrono sin re-entrada explícita
- **Estrategia**: Documentar (asyncio.Lock es reentrant), añadir prueba de stress

#### 5. Estado global sin sincronización en FastAPI (`app.state`)
- **Localizaciones**:
  - `app.state.project_registry` (¿reentrante? → sí, but not documented)
  - `app.state.active_project_operations` (set mutable, raceCondition? → bajo riesgo, GIL)
  - `app.state.login_rate_limiter` (acumulador de fallos, no reseteado entre app reinits)
  - `app.state.security` (inmutable, ok)
- **Impacto**: Medio bajo (GIL en CPython mitiga, pero no documentado)
- **Raíz**: FastAPI `app.state` es el idioma estándar, pero sin contrato explícito
- **Estrategia**: Documentar invariantes (reentrancia, thread-safety, lifetime)

#### 6. Migraciones de esquema SQLite con lógica manual
- **Localización**: `auth/auth_store.py:280-310` (`_migrate_schema()`)
- **Problema**: 
  - SQLite no soporta `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
  - Código manual usa `PRAGMA table_info()` para verificar existencia
  - Se ejecuta en cada apertura de `AuthStore` (patrón "CREATE TABLE IF NOT EXISTS")
  - Riesgo: esquema divergente si se modifica manualmente o por terceros
- **Impacto**: Bajo en práctica (PRAGMA es seguro), pero frágil para evoluciones futuras
- **Raíz**: SQLite no tiene UPSERT de esquema nativamente
- **Estrategia**: Centralizar lógica de migración (crear `src/doc_organize/auth/migrations.py`)

#### 7. WebSocket sin protección de BaseHTTPMiddleware
- **Localización**: `web/app.py:159` (comentario), `web/routes/scan.py::websocket_scan_progress`
- **Problema**: `BaseHTTPMiddleware` NO protege rutas WebSocket → autenticación manual en handler
- **Impacto**: Medio (actualmente segura, pero sin una barrera de defense-in-depth)
- **Raíz**: Starlette/FastAPI limitación conocida (BaseHTTPMiddleware no ve WebSocket)
- **Estrategia**: Documentar, considerar middleware alternativo en v0.10+

#### 8. Duplicación de mapping de excepciones (histórico, ya refactorizado)
- **Localización**: `web/app.py:77-101` (centralizado desde 2026-08-29)
- **Estado**: ✅ RESUELTA (AUDIT_CODE sesión 2026-08-29)
- **Nota**: Este era un anti-patrón real (~30 repeticiones), ya corregido

---

## Estructura de auditoría

```
PLAN (este documento) ← estrategia y alcance
├─ AUDIT_PLAN → validar plan vs. código real
├─ AUDIT_CODE → hallazgos detallados (por módulo, archivo, línea)
└─ VERSION → resumen, veredicto final, acciones recomendadas
```

---

## Próximos pasos

1. **AUDIT_PLAN**: Validar hallazgos iniciales contra el código real (scan exhaustivo)
2. **AUDIT_CODE**: Clasificar por prioridad (quick_win, fase_media, deuda_estructural)
3. **VERSION**: Emitir veredicto (`LIMPIO | DEUDA_MENOR | DEUDA_SIGNIFICATIVA | CRÍTICO`)

---

*Este documento es el punto de partida del flujo de auditoría de deuda técnica.*
