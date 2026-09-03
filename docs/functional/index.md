# Funcionalidad por módulo

Organizados por capa, de fundacional a orquestación — ver
[Arquitectura](../api/index.md) para el diagrama y la explicación de las capas.

## Nivel 1 — Fundacional

### `core/`

Modelos Pydantic compartidos (`DocumentMetadata`, `Project`, `Tenant`, `User`,
`Session`, `CacheEntry`, `ScanEvent`, etc.), excepciones (`DocOrganizeError` y sus
subclases) y constantes (extensiones soportadas, límites de nombre, parámetros de
hashing de contraseña). No depende de ningún otro módulo del paquete.

### `utils/`

`hash_utils.hash_file()` — única fuente de verdad para SHA-256 (async, lectura por
bloques). `path_utils.safe_path_join()` — construcción de rutas segura contra path
traversal, usada en cualquier sitio que combine una ruta base con un segmento
elegido por el usuario. `logging.get_logger()` — logging estructurado en JSON.

## Nivel 2 — Servicios independientes

### `validators/`

`FolderValidator` (REQ-001): valida un conjunto de carpetas de entrada (sin
redundancia entre ellas). `ProjectValidator` (REQ-008): valida y normaliza (NFC)
nombres de proyecto — caracteres prohibidos, nombres reservados de Windows,
longitud.

### `scanner/`

`DocumentScanner` (REQ-002): recorre carpetas recursivamente, descubre documentos
de extensión soportada y calcula su hash SHA-256 de forma concurrente. No sigue
symlinks (se tratan como nodo opaco).

### `converter/`

`DocumentConverter` (REQ-003): convierte un documento a Markdown + JSON con
Docling, replicando la estructura de carpetas de origen bajo el directorio de
salida. `OCRScheduler` (REQ-004): detecta si un documento necesita OCR (sin capa
de texto nativa — `confidence.parse_score` es `NaN`) y lo reprocesa bajo demanda,
en CPU (RapidOCR) o GPU (EasyOCR, extra `ocr-gpu`).

### `dedup/`

`DeduplicationManager` (REQ-005): detecta duplicados exactos (mismo hash) y
conflictos de versión (mismo nombre base, hash distinto), y mueve los documentos
descartados a una carpeta separada preservando su estructura, con una auditoría
(`DEDUP_REPORT.json`). Soporta que el llamante elija qué documento conservar por
grupo (`DuplicateGroup.user_choice`) — la interfaz web lo usa para dar control al
usuario antes de mover nada.

### `cache/`

`CacheManager` (REQ-006): caché transaccional de hashes en SQLite (modo WAL),
permite lecturas concurrentes durante escrituras. Clasifica cada documento como
nuevo, modificado o sin cambios frente a la última pasada.

### `projects/`

`ProjectRegistry` (REQ-008): crea, lista y abre proyectos — cada uno con su propia
carpeta de conversión, caché y duplicados bajo una ubicación elegida por el
usuario. Registro en `~/.doc_organize/projects.json`, escritura atómica. Los
proyectos están escopados por tenant (ver `auth/`); el tenant implícito
`"default"` cubre el uso por CLI y por sesiones web sin autenticar.

### `auth/`

`AuthStore`: autenticación multi-usuario y multi-tenant. Tenants, usuarios y
sesiones en SQLite (modo WAL); contraseñas con `hashlib.scrypt` (parámetros
recomendados por OWASP) + salt aleatorio por usuario; tokens de sesión opacos.
Logout selectivo: cerrar una sesión no afecta a las demás del mismo usuario.

## Nivel 3 — Orquestación

### `scan/`

`ScanCommand`: orquesta dos acciones independientes usando los servicios de
Nivel 2, sin cambiar ninguno de sus contratos. Usada tanto por el CLI
(`main.py`) como por la interfaz web (`web/routes/scan.py`) — no pertenece a
ninguno de los dos.

- `run()`/`run_streaming()`: escaneo + diff de caché + conversión + OCR
  opcional. `run()` devuelve solo el resumen final (uso del CLI);
  `run_streaming()` emite progreso incremental por evento (usado por el
  WebSocket de la web). Ya no deduplica.
- `deduplicate_streaming()`: busca y mueve duplicados, a petición explícita del
  usuario (botón "Buscar duplicados" de la página Duplicados en la web,
  subcomando `deduplicate` en el CLI), emitiendo progreso por grupo (mismo
  criterio que `run_streaming()`: un WebSocket dedicado en la web,
  `WS /api/projects/{name}/scan/deduplicate`).

### `web/` (extra `[web]`)

Interfaz web opcional sobre FastAPI — nunca se importa desde el núcleo, así que
una instalación solo-CLI no arrastra sus dependencias. Autenticación por sesión
(cookie `HttpOnly`+`SameSite=Strict`) en host no-loopback; páginas: selector de
proyectos, dashboard, login, selector de carpetas con progreso por WebSocket,
visor de caché, resolución de duplicados; descarga de un export ZIP por proyecto.

### `main.py` (CLI)

Punto de entrada (`python -m doc_organize ...`): subcomandos `project`, `scan`,
`web`, `tenant`, `user`. Importa `web/` de forma perezosa (solo si se invoca
`web`), para que el resto del CLI funcione sin el extra `[web]` instalado.
