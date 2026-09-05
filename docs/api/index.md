# Arquitectura

`doc_organize` se organiza en tres capas, de fundacional a orquestación (ver
`.github/instructions/architecture.instructions.md` en el repositorio para la
convención completa):

- **Nivel 1 — Fundacional** (`core/`, `utils/`): sin dependencias del resto del
  paquete. Modelos, excepciones, constantes, hashing, validación de rutas.
- **Nivel 2 — Servicios independientes** (`validators/`, `scanner/`, `converter/`,
  `dedup/`, `cache/`, `projects/`, `auth/`): cada uno resuelve una responsabilidad
  del dominio sin depender de los otros módulos de su mismo nivel. Solo dependen
  de Nivel 1.
- **Nivel 3 — Orquestación** (`scan/`, `web/`, `main.py`): coordinan los servicios
  de Nivel 2 sin cambiar sus contratos. `scan/` es compartido por el CLI y la web
  a propósito — ninguno de los dos "posee" la orquestación de escaneo.

```mermaid
graph TB
    subgraph L3["Nivel 3 — Orquestación"]
        CLI["main.py (CLI)"]
        ScanCmd["scan/ScanCommand"]
        Web["web/ (FastAPI, extra [web])"]
    end

    subgraph L2["Nivel 2 — Servicios independientes"]
        Validators["validators/"]
        Scanner["scanner/DocumentScanner"]
        Converter["converter/DocumentConverter + OCRScheduler"]
        Dedup["dedup/DeduplicationManager"]
        Cache["cache/CacheManager"]
        Projects["projects/ProjectRegistry"]
        Auth["auth/AuthStore"]
    end

    subgraph L1["Nivel 1 — Fundacional"]
        Core["core/ (modelos, excepciones, constantes)"]
        Utils["utils/ (hash_file, safe_path_join, logging)"]
    end

    CLI --> ScanCmd
    Web --> ScanCmd
    CLI --> Projects
    Web --> Projects
    Web --> Auth
    CLI --> Auth

    ScanCmd --> Validators
    ScanCmd --> Scanner
    ScanCmd --> Converter
    ScanCmd --> Dedup
    ScanCmd --> Cache

    Validators --> Core
    Scanner --> Utils
    Scanner --> Core
    Converter --> Core
    Dedup --> Utils
    Dedup --> Core
    Cache --> Utils
    Cache --> Core
    Projects --> Utils
    Projects --> Core
    Auth --> Core
```

## Autenticación web (host no-loopback)

Sesión por cookie (`HttpOnly`, `SameSite=Strict`), no bearer token compartido:
`POST /login` valida usuario+contraseña+tenant contra `AuthStore` y fija la
cookie; `AuthMiddleware` la exige en toda ruta salvo `/login`/`/logout`. Las
conexiones WebSocket (`web/routes/scan.py`) no pasan por el middleware HTTP
(Starlette no lo intercepta para el scope `"websocket"`) y autentican la sesión
explícitamente en el propio handler.

## Roles y gestión de usuarios

Cada tenant nuevo (`AuthStore.create_tenant`) crea automáticamente, en una única
transacción, un rol `admin` (`is_admin=True`, ve todos los proyectos del tenant)
y un usuario `admin`/`admin` marcado con `must_change_password=True`. Mientras
esa marca esté activa y el host no sea loopback, `AuthMiddleware` bloquea toda
ruta salvo `/change-password` y `/logout`.

Un rol no-admin solo ve los proyectos listados explícitamente en
`Role.project_names`; `AuthStore.can_access_project()` es la única fuente de
verdad para esa comprobación, usada tanto por `require_project_access`
(`web/dependencies.py`, aplicada por firma en cada ruta `{name}`-scoped) como
por el handler WebSocket de escaneo. Gestión de roles/usuarios: `/api/roles` y
`/api/users` (`web/routes/admin.py`), protegidas por `require_admin` a nivel de
router — ningún endpoint nuevo puede olvidarse de exigirlo.

`Role.allowed_scan_roots` es un control distinto de `project_names`: no rige el
acceso a proyectos ya existentes, sino qué rutas del sistema de archivos puede
explorar/escanear un rol para crear un proyecto nuevo (`GET /api/fs/browse` y el
WebSocket de escaneo aplican la misma restricción vía
`get_allowed_scan_roots()`). Un rol `is_admin` nunca tiene lista propia — bypasa
la restricción por completo.

Las páginas HTML de administración están separadas: `GET /admin/roles`
(`admin_roles.html.j2`) y `GET /admin/users` (`admin_users.html.j2`), cada una
con su propia entrada de menú agrupada bajo "Admin" en el sidebar
(`base.html.j2`). En `/admin/roles`, las raíces de escaneo permitidas se
construyen como una lista (botones "Guardar carpeta" y "Buscar…" — este último
reutiliza `GET /api/fs/browse` — más "Eliminar" por entrada) en vez de un campo
de texto libre; el array resultante se envía tal cual en
`POST /api/roles`/`PATCH /api/roles/{id}` (`allowed_scan_roots: list[str]`, sin
cambios de contrato).

`POST /api/users` acepta `must_change_password: bool = False`: si se marca,
el usuario debe cambiar su contraseña en su primer login (`AuthMiddleware`),
igual que el usuario `admin` de bootstrap o tras un reseteo de contraseña vía
`PATCH /api/users/{id}`.

## Referencia

Generada desde los docstrings del código (Google-style).

::: doc_organize.core.models
::: doc_organize.core.exceptions
::: doc_organize.scanner.document_scanner
::: doc_organize.converter.converter
::: doc_organize.converter.ocr_scheduler
::: doc_organize.dedup.deduplication
::: doc_organize.cache.cache_manager
::: doc_organize.projects.project_registry
::: doc_organize.auth.auth_store
::: doc_organize.scan.scan_command
::: doc_organize.web.app
::: doc_organize.web.auth
