# 📦 Product Context — doc_organize

## Descripción Ejecutiva

**doc_organize** escanea carpetas de documentos heterogéneos (PDF, Word, Excel, PowerPoint,
imágenes), los convierte a Markdown + JSON con [Docling](https://github.com/docling-project/docling),
detecta y resuelve duplicados, y mantiene un caché incremental (SHA-256) para no reconvertir lo que
no ha cambiado. Se usa desde la línea de comandos, o desde una interfaz web opcional con
autenticación multi-usuario y multi-tenant.

**Propósito primario**: normalizar repositorios heterogéneos de documentos en Markdown versionado,
sin perder la estructura de carpetas original ni duplicar trabajo entre ejecuciones.

**Versión**: Fase 1 completa (A–D2c) + organización documental (Fase 2) + rediseño Tenant/Role/User |
**Estado**: IMPLEMENT — ver `§13` del PLAN | **Python**: ≥3.11

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
  Rediseño Tenant/Role/User (2026-09-11, ver `DECISIONS_LOG.md` Revisión 16): un tenant `"default"`
  y su usuario `admin` se aprovisionan **de fábrica** al primer arranque, sin CLI previa (esa
  cuenta no puede completar el login en modo no-loopback mientras conserve la contraseña de
  fábrica). `Role` ya no está ligado a un tenant (`name` único globalmente, asignable a usuarios
  de tenants distintos); su acceso de escaneo es implícito (carpeta de cada proyecto permitido, ya
  no una lista `allowed_scan_roots`). `User.is_instance_admin`, independiente del `is_admin` de su
  rol, gestiona cualquier tenant desde la pantalla "Tenants y usuarios".

### Organización documental e IA (Fase 2, `context/` + `ai/`)
- `context/ContextBuilder`: clasifica los documentos ya convertidos de un proyecto en **dominios**
  (Sub-fase A por reglas, Sub-fase B opcional por IA) y, con un `taxonomy_manifest.md`, en un
  segundo eje de **tipo de material de origen**. `Reorganizer` copia cada documento (original +
  `.md` + `.json`) a una carpeta reorganizada; `MkDocsGenerator` genera un sitio MkDocs navegable
  del resultado, servido en la propia app web.
- `ai/`: clientes IA (`DomainClassificationClient`, `TaxonomyClassificationClient`,
  `TaxonomyManifestDraftClient` contra un LiteLLM Proxy; `LiteLLMUsageClient`/
  `GitHubCopilotUsageClient` para monitorización de uso/coste) — todos con config resuelta desde
  variables `DOC_ORGANIZE_*` o desde el panel `/admin/configuracion-ia`
  (`auth/instance_secrets_store.py`, credenciales cifradas en reposo con Fernet).
- Biblioteca de plantillas de taxonomía (`context/taxonomy_template_registry.py`), reutilizables
  entre proyectos desde `/admin/plantillas-taxonomia`.

### CLI (`python -m doc_organize ...`, no `doclink`)
- `project create` / `project list`
- `scan --paths ... [--project ...] [--use-ocr] [--use-gpu]` (ya no deduplica — ver `deduplicate`)
- `deduplicate --paths ... [--project ...] [--duplicates-dir ...]` (acción aparte, a petición del usuario)
- `web [--host ...] [--port ...]` — ya no exige aprovisionar nada antes: el tenant `default` y su
  usuario `admin` se crean de fábrica al primer arranque (ver "Proyectos y autenticación").
- `tenant create` / `user create` (contraseña vía `getpass`, nunca como argumento) — sigue
  disponible para tenants adicionales al `default`, que no reciben aprovisionamiento automático.
- `user set-instance-admin <username> --tenant <id> [--revoke]` — escape hatch para conceder/retirar
  `is_instance_admin` sin pasar por la UI (p. ej. tras migrar una instalación multi-tenant antigua).

### Interfaz web (extra `[web]`, opcional — el núcleo nunca depende de FastAPI)
- Project Selector, Dashboard, Login — autenticación de sesión.
- Folder Selector + **WebSocket** de progreso (no SSE — decisión revertida, ver
  `DECISIONS_LOG.md`), `scan/ScanCommand.run_streaming()` compartido con el CLI.
- Cache Viewer (solo lectura), Duplicates Resolver (re-escanea en vivo, nunca confía en rutas de
  archivo del cliente al resolver), Export ZIP (`Conversión/` + `cache_export.json` +
  `DEDUP_REPORT.json`, streaming vía fichero temporal).
- Panel `/admin/*` (5 páginas): Roles, Usuarios (propio tenant), Tenants y usuarios (pantalla
  cruzada, solo `is_instance_admin`), Configuración de IA (credenciales cifradas en reposo,
  solo `is_instance_admin`), Plantillas de taxonomía (solo `is_instance_admin` para
  crear/editar/borrar). No hay una página "Settings" genérica de app — los ajustes de OCR/GPU
  siguen siendo casillas por-escaneo; lo que sí existe ahora es configuración de instancia
  (credenciales IA) editable desde la web, ver `docs/functional/admin.md`.

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
├── ai/                          # Nivel 2 — clientes IA (LiteLLM Proxy, GitHub Copilot Pro)
├── context/                      # Nivel 2 — ContextBuilder/Registry/Reorganizer/MkDocsGenerator
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
| **mkdocs + mkdocs-material + mkdocstrings** | Documentación (extra `docs`); también genera el sitio de organización documental por proyecto |
| **httpx** (extra `[ai]`) | Clientes IA (`ai/`): LiteLLM Proxy, GitHub Copilot Pro, con `transport` inyectable en tests |
| **pyyaml** (extra `[context]`) | Front matter YAML de `taxonomy_manifest.md` y plantillas compartidas |
| **cryptography (Fernet)**, extra `[web]` | Cifrado en reposo de credenciales de IA guardadas desde `/admin/configuracion-ia` (`auth/secrets_cipher.py`); import perezoso dentro de `auth/`, para que `AuthStore`/CLI (`tenant create`/`user create`) sigan usables sin `[web]` instalado |

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

Ver `§13`/`§15` del PLAN: tokens de API personales, pruebas en navegador real (sin Playwright
instalado, ver `.ai/sessions/2026-09-05-admin-roles-usuarios/TRACEABILITY.md`), confirmación en
verde de la matriz de CI ampliada a Python 3.10-3.14, tests de integración adicionales,
documentación ampliada. Rate-limiting en `/login` y roles (ahora globales, no por tenant) ya están
implementados — retirados de esta lista tras la revisión de 2026-09-11 (ver `DECISIONS_LOG.md`).
Pendiente de una pasada de sincronización `CHANGELOG.md`/`COMPATIBILITY.md`/`pyproject.toml` tras
el rediseño Tenant/Role/User y las features de IA/taxonomía de esta misma franja de commits (ver
`sync.instructions.md`).

---

## Referencias

- Especificación completa (fuente de verdad): `.github/prompts/doclink_extractor_plan.md`
- Documentación publicada: `docs/index.md`, `docs/guides/`, `docs/functional/`, `docs/api/`
- Registro de decisiones: `.ai/DECISIONS_LOG.md`
- Docling: https://github.com/docling-project/docling

---

**Documento regenerado**: 2026-08-28 (sustituye contenido fabricado de una sesión de Copilot previa)
**Última revisión de contenido**: 2026-09-11 (secciones de auth/IA/organización documental
actualizadas tras quedar desactualizadas varias sesiones — ver maturity-assessment de esa fecha)
**Clasificación**: contexto persistente IA — leer antes de planificar
