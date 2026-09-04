# 📦 Product Context — doc_organize

## Descripción Ejecutiva

**doc_organize** escanea carpetas de documentos heterogéneos (PDF, Word, Excel, PowerPoint,
imágenes), los convierte a Markdown + JSON con [Docling](https://github.com/docling-project/docling),
detecta y resuelve duplicados, y mantiene un caché incremental (SHA-256) para no reconvertir lo que
no ha cambiado. Se usa desde la línea de comandos, o desde una interfaz web opcional con
autenticación multi-usuario y multi-tenant.

**Propósito primario**: normalizar repositorios heterogéneos de documentos en Markdown versionado,
sin perder la estructura de carpetas original ni duplicar trabajo entre ejecuciones.

**Versión**: Fase 1 completa (A–D2c) | **Estado**: IMPLEMENT — ver `§13` del PLAN | **Python**: ≥3.11

> Este documento sustituye una versión anterior (fechada 2026-08-27) que describía un MVP
> "PRE-IMPLEMENT" con módulos (`workflow/`), rutas (SSE, 8 páginas web) y comandos CLI
> (`doclink scan`) que nunca llegaron a implementarse tal cual — pertenecía a la misma tanda de
> documentación fabricada por una sesión previa de GitHub Copilot que ya se corrigió en
> `.github/AUDIT_PLAN_doclink_extractor.md` y ficheros hermanos. Este documento describe **solo lo
> que existe realmente en el código**, verificado contra `src/doc_organize/`.

---

## Capacidades reales (verificadas contra el código)

### Escaneo y conversión
- `scanner/DocumentScanner` (REQ-002): recorrido recursivo + hash SHA-256 concurrente (único punto
  de hashing: `utils/hash_utils.hash_file()`).
- `converter/DocumentConverter` + `OCRScheduler` (REQ-003/REQ-004): conversión con Docling,
  estructura de carpetas replicada bajo `Conversión/`; detección de OCR empírica
  (`confidence.parse_score` `NaN`); dos fases (sin OCR → con OCR bajo demanda, CPU por defecto vía
  `docling[rapidocr]`, GPU opcional vía extra `ocr-gpu`).

### Caché y deduplicación
- `cache/CacheManager` (REQ-006): SQLite + WAL, clasifica new/modified/unchanged.
- `dedup/DeduplicationManager` (REQ-005): duplicados exactos + conflictos de versión; `resolve()`
  soporta que el llamante elija el documento canónico por grupo (`user_choice`) — la web lo usa para
  dar control interactivo antes de mover nada.

### Proyectos y autenticación
- `projects/ProjectRegistry` (REQ-008): cada proyecto agrupa su propia `Conversión/`, `cache.db` y
  `duplicados/` bajo una ubicación elegida por el usuario. Escopado por tenant.
- `auth/AuthStore`: autenticación multi-usuario y multi-tenant. Sesión por cookie
  (`HttpOnly`+`SameSite=Strict`), **no** bearer token compartido (diseño descartado explícitamente,
  ver `DECISIONS_LOG.md`). Contraseñas con `hashlib.scrypt` + salt. Logout selectivo.

### CLI (`python -m doc_organize ...`, no `doclink`)
- `project create` / `project list`
- `scan --paths ... [--project ...] [--use-ocr] [--use-gpu]` (ya no deduplica — ver `deduplicate`)
- `deduplicate --paths ... [--project ...] [--duplicates-dir ...]` (acción aparte, a petición del usuario)
- `web [--host ...] [--port ...]`
- `tenant create` / `user create` (contraseña vía `getpass`, nunca como argumento)

### Interfaz web (extra `[web]`, opcional — el núcleo nunca depende de FastAPI)
- Project Selector, Dashboard, Login — autenticación de sesión.
- Folder Selector + **WebSocket** de progreso (no SSE — decisión revertida, ver
  `DECISIONS_LOG.md`), `scan/ScanCommand.run_streaming()` compartido con el CLI.
- Cache Viewer (solo lectura), Duplicates Resolver (re-escanea en vivo, nunca confía en rutas de
  archivo del cliente al resolver), Export ZIP (`Conversión/` + `cache_export.json` +
  `DEDUP_REPORT.json`, streaming vía fichero temporal).
- **No existe** una página "Settings" — se evaluó y se descartó explícitamente por no tener
  requisito real detrás (los ajustes de OCR/GPU ya son casillas por-escaneo).

---

## Arquitectura (3 niveles reales)

```
src/doc_organize/
├── core/            # Nivel 1 — modelos Pydantic, excepciones, constantes
├── utils/           # Nivel 1 — hash_file, safe_path_join, logging
├── validators/       # Nivel 2 — FolderValidator, ProjectValidator
├── scanner/           # Nivel 2 — DocumentScanner
├── converter/          # Nivel 2 — DocumentConverter, OCRScheduler
├── dedup/                # Nivel 2 — DeduplicationManager
├── cache/                 # Nivel 2 — CacheManager (SQLite+WAL)
├── projects/                # Nivel 2 — ProjectRegistry
├── auth/                      # Nivel 2 — AuthStore (SQLite+WAL)
├── scan/                        # Nivel 3 — ScanCommand (orquestación compartida CLI/web)
├── web/                           # Nivel 3 — FastAPI, extra [web]
└── main.py                         # Nivel 3 — CLI
```

Detalle completo: `.ai/architecture.md` (diagrama) y `docs/api/index.md` (referencia técnica
generada desde los docstrings).

---

## Stack tecnológico real

| Componente | Rol |
|---|---|
| **Docling** (`docling[rapidocr]`) | Extracción de documentos + OCR en CPU, dependencia obligatoria |
| **Pydantic v2** | Modelos y validación |
| **aiosqlite** | Backend de `CacheManager` y `AuthStore` |
| **aiofiles** | I/O async en `hash_file()` |
| **FastAPI + Uvicorn + Jinja2** | Interfaz web (extra `[web]`, no obligatorio) |
| **torch/torchvision/opencv-python/easyocr** | OCR GPU (extra `ocr-gpu`, opcional) |
| **hashlib.scrypt + secrets** (stdlib) | Autenticación multi-usuario — sin dependencia nueva |
| **mkdocs + mkdocs-material + mkdocstrings** | Documentación (extra `docs`) |

---

## Requisitos funcionales — estado real

| REQ | Descripción | Estado |
|---|---|---|
| REQ-001 | Selección + validación de carpetas | ✅ Implementado |
| REQ-002 | Escaneo recursivo | ✅ Implementado |
| REQ-003 | Conversión Markdown + JSON | ✅ Implementado |
| REQ-004 | Detección y reprocesado OCR | ✅ Implementado |
| REQ-005 | Deduplicación | ✅ Implementado (auto vía CLI/scan; interactivo vía web) |
| REQ-006 | Caché incremental | ✅ Implementado |
| REQ-007 | Interfaz web | ✅ Implementado (Project Selector con buscador+paginación, Dashboard con Carpetas guardadas, Escanear+WS con pestañas Escanear/Caché, Duplicados con pestañas Buscar duplicados/Histórico, Export ZIP) |
| REQ-008 | Gestión de proyectos | ✅ Implementado (multi-tenant) |

Fuente de verdad detallada (incluye historial de revisiones y AUDIT_PLAN de cada pieza):
`.github/prompts/doclink_extractor_plan.md`.

## Pendiente (Fase E, no bloqueante)

Ver `§13`/`§15` del PLAN: rate-limiting en `/login`, tokens de API personales, roles por tenant,
pruebas en navegador real, confirmación en verde de la matriz de CI ampliada a Python 3.10-3.14,
tests de integración adicionales, documentación ampliada.

---

## Referencias

- Especificación completa (fuente de verdad): `.github/prompts/doclink_extractor_plan.md`
- Documentación publicada: `docs/index.md`, `docs/guides/`, `docs/functional/`, `docs/api/`
- Registro de decisiones: `.ai/DECISIONS_LOG.md`
- Docling: https://github.com/docling-project/docling

---

**Documento regenerado**: 2026-08-28 (sustituye contenido fabricado de una sesión de Copilot previa)
**Clasificación**: contexto persistente IA — leer antes de planificar
