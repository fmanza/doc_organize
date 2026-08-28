# 📚 Glossary — doc_organize

> Reemplaza una versión anterior con términos de otra librería (motores de base de datos,
> `_drivers/`, `connection/`, `metadata/`) — la encarnación previa de este mismo repositorio.

## Niveles de arquitectura

- **Nivel 1 (Fundacional)**: `core/`, `utils/` — sin dependencias del resto del paquete.
- **Nivel 2 (Servicios independientes)**: `validators/`, `scanner/`, `converter/`, `dedup/`,
  `cache/`, `projects/`, `auth/` — cada uno resuelve una responsabilidad, sin depender de sus pares.
- **Nivel 3 (Orquestación)**: `scan/`, `web/`, `main.py` — coordinan Nivel 2 sin cambiar sus
  contratos.

## Entidades de dominio

- **Project**: carpeta raíz de trabajo con su propia `Conversión/`, `cache.db`, `duplicados/`.
  Pertenece a un `tenant_id` (default `"default"`).
- **Tenant**: organización/workspace que agrupa usuarios y proyectos, aislados de otros tenants.
- **User**: usuario dentro de un tenant (único por tenant, no globalmente); autenticado por
  contraseña (`scrypt`).
- **Session**: sesión de navegador activa tras `/login`; token opaco en la cookie
  `doc_organize_session`. Logout selectivo: cerrar una no invalida las demás del mismo usuario.
- **DocumentMetadata**: metadatos de un documento descubierto por el escaneo (ruta, nombre, tamaño,
  hash SHA-256).
- **CacheEntry**: entrada persistida en `cache.db` — hash, estado (new/modified/unchanged),
  estado de conversión.
- **DuplicateGroup**: grupo de documentos duplicados (exactos o conflicto de versión), con un
  documento canónico y una elección opcional del usuario (`user_choice`).
- **ScanEvent**: evento de progreso emitido por `ScanCommand.run_streaming()`
  (`started`/`scanned`/`deduplicated`/`file_converted`/`ocr_processed`/`completed`).

## Conceptos técnicos

- **`safe_path_join()`**: única forma permitida de construir una ruta a partir de un segmento
  elegido por el usuario (nombre de proyecto, destino de duplicados) — previene path traversal.
- **`hash_file()`**: única fuente de verdad de SHA-256 en todo el proyecto.
- **`ScanCommand`**: orquestación compartida de escaneo+caché+dedup+conversión+OCR, usada tanto por
  el CLI como por la web — vive en `scan/`, no en `main.py` ni en `web/`.
- **`AuthMiddleware`**: exige sesión válida en toda ruta HTTP cuando el host no es loopback. **No**
  protege conexiones WebSocket (limitación de `BaseHTTPMiddleware`, no de este proyecto).
- **`_group_key`**: clave estable (sha256 de rutas ordenadas) usada por el Duplicates Resolver para
  correlacionar un `GET` de detección con un `POST` de resolución sin persistir estado en servidor.
- **REQ-00X**: identificador de requisito funcional, definido en
  `.github/prompts/doclink_extractor_plan.md` §2.

## Siglas y convenciones del proyecto

- **`§N`**: referencia a una sección del PLAN (`.github/prompts/doclink_extractor_plan.md`).
- **Fase D-2a/b/c**: sub-fases de la interfaz web (esqueleto+auth / Folder Selector+WebSocket /
  Cache Viewer+Export+Duplicates).
- **`.ai/doc_old/`**: historial de sesiones de la encarnación anterior de este repositorio (una
  librería de motores de base de datos) — gitignored, no forma parte de este proyecto.
