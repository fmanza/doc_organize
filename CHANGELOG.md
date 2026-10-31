# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).
Este proyecto sigue [SemVer](https://semver.org/lang/es/) desde v0.2.0 (sin
releases publicados antes de esa versión).

## [Unreleased]

## [0.9.3] - 2026-10-31

Primera versión publicada en GitHub Releases con wheel y sdist, para que doc_organize_web pueda fijarla por URL y
hash. Recoge todo lo integrado en `develop` desde la 0.9.0.

> **Nota de versión**: por SemVer estricto, las novedades de `Added` pedirían una MINOR. Se publica como PATCH porque
> la 0.10.0 está reservada para la API pública de la separación librería/web (tareas L-1…L-6 del plan de
> doc_organize_web). El tag `v0.9.2` (2026-09-17) marcó un estado intermedio sin subir la versión del paquete, que
> seguía en 0.9.0; esta versión alinea `pyproject.toml`, `__version__` y el tag.

### Added

- `dedup/deduplication.py`: tercera pasada opcional de deduplicación por similitud aproximada de
  nombre (`find_duplicates(fuzzy_threshold=0-100)`), usando `rapidfuzz.process.cdist` con
  `fuzz.WRatio` sobre nombres normalizados (sin extensión, separadores unificados vía
  `rapidfuzz.utils.default_process`) y agrupación por componentes conexas sin exigir
  transitividad estricta. Los grupos resultantes (`DuplicateReason.FUZZY_NAME_MATCH`) nunca se
  auto-resuelven: quedan excluidos de "Buscar duplicados" y solo se resuelven desde el
  formulario interactivo de "Revisar Duplicados" (activación explícita por grupo).
- `web/routes/duplicates.py`, `web/templates/duplicates_resolver.html.j2`: control de umbral de
  similitud (`fuzzy_threshold`) y activación por grupo (`fuzzy_group_toggles`) en la pantalla de
  Duplicados.
- `context/taxonomy_templates_builtin/sgi-integrado.md`: plantilla de taxonomía «sgi-integrado» (7 dominios + 9
  tipos de material).
- `utils/office_detector.py`: detección de LibreOffice (mismo patrón que `av_detector.py`/`gpu_detector.py`);
  `web/templates/_status_banner_macros.html.j2` unifica los banners de GPU, audio/vídeo y LibreOffice en Escaneo.
- `web/`: edición de rol y restablecimiento de contraseña en los paneles de usuarios y tenants; edición de nombre,
  admin y proyectos de un rol; enlace «Proyectos» en el bloque Admin.
- `auth/migrations.py`: migraciones de esquema SQLite centralizadas (protocolo `SchemaMigration`);
  documentación del modelo de hilos (`web/STATE.md`, ADR-004) y pruebas de estrés concurrente de `ProjectRegistry` (estado `v0.9.2`).

### Changed

- `auth/`: `AuthStore` se descompone en `TenantStore`, `RoleStore`, `UserStore` y `SessionStore` (misma API pública
  como fachada); se elimina código de migración muerto.
- `ai/_http_client_base.py`: base HTTP compartida por los 5 clientes de IA, sin cambios de comportamiento.
- `web/routes/taxonomy_templates.py`: la administración de plantillas de taxonomía se separa de las rutas de contexto.
- `scan/scan_command.py`: la excepción capturada al reenviar fallos de OCR por la cola se acota a
  `(OSError, ValueError, RuntimeError, TypeError)`.
- `__version__` pasa de `"0.1.0"` a la versión real del paquete.
- CI: `ruff` fijado a `<0.16` (la 0.16 activa por defecto reglas DTZ/RUF/SIM y el CI estaba en rojo desde
  septiembre con 11 avisos nuevos, pendientes de revisar), `pandas` sin stubs ignorado por mypy y `cryptography`
  añadido al extra `dev` (lo importa `auth/secrets_cipher.py`; solo estaba en `web`).
- CI: la matriz de tests deja de incluir Python 3.11 (3.12, 3.13 y 3.14).

### Fixed

- `src/doc_organize/main.py` (`_run_web`): `uvicorn.run(..., ws_ping_timeout=None)` evita que
  uvicorn cierre el WebSocket de escaneo/deduplicación por un pong tardío durante OCR largo
  (el hilo de `asyncio.to_thread` compite por el GIL con el event loop), que antes se veía
  como "Cliente desconectado durante el escaneo" en pleno progreso.
- `dedup/deduplication.py`: la similitud de nombres usa `fuzz.WRatio` sobre nombres normalizados (mejor precisión
  con sufijos de copia/versión).
- `converter/converter.py`: la conversión de `.xls` sin LibreOffice se corta con un mensaje claro en lugar de agotar
  reintentos; el error de conversión muestra la causa raíz encadenada por Docling (hasta 2 niveles).
- `web/`: el alta de usuario exige elegir rol de forma explícita (antes se preseleccionaba `admin`); el bloque Admin se
  muestra en modo local sin autenticación; desplegable de plantilla de taxonomía a todo el ancho.
- `auth/migrations.py`: `datetime.utcnow()` (obsoleto) sustituido por `datetime.now(UTC)` en las migraciones 004/005.
- `scanner/document_scanner.py`: un fichero que desaparece durante el escaneo ya no aborta el recorrido cuando
  `Path.is_symlink()` propaga el error de `lstat()` (Linux); se omite como el resto de casos TOCTOU.
- `projects/project_registry.py`: el doctest de `move_project_root` compara rutas resueltas (fallaba en Windows con
  nombres cortos de `tempfile`).

## [0.9.0] - 2026-09-11

### Added

- `src/doc_organize/context/taxonomy_manifest.py` (nuevo): `load_taxonomy_manifest()` lee
  `<project.root_path>/taxonomy_manifest.md` (front matter YAML, cuerpo Markdown libre para
  lectura humana) y lo valida como `TaxonomyManifest` (`core/models.py`, nuevo, junto con
  `TaxonomyCatalogEntry`) — catálogo cerrado de dominios + tipos de material de origen. Cada
  entrada puede llevar `keywords` opcionales que suman a la puntuación de ese candidato,
  además de las palabras derivadas de su propio `slug`.
- `src/doc_organize/context/domain_classifier.py`: nueva clase `MaterialTypeClassifier`
  (segundo eje de clasificación, solo por reglas) y función `score_catalog()` (extraída de
  `DomainClassifier._best_from_catalog` para reutilizar la misma puntuación en ambos ejes,
  sin cambiar su comportamiento), con soporte para `extra_keywords` por slug
  (`TaxonomyCatalogEntry.keywords`). `DomainClassifier` gana el método público `score_domain()`.
- `src/doc_organize/context/context_builder.py`: `ContextBuilder.build()` acepta
  `taxonomy_manifest: TaxonomyManifest | None` — con manifiesto, clasifica cada documento en
  2 ejes (dominio + tipo de material); un documento con los tres artefactos completos siempre
  se reorganiza, con el slug placeholder `sin-clasificar` en el eje que no alcance el umbral,
  en vez de excluirse (`unclassified_documents` sigue reservado a artefactos incompletos). Sin
  manifiesto, comportamiento idéntico al de antes de esta sesión. La Sub-fase B (IA) en modo
  manifiesto se añade en esta misma sesión (ver bullet siguiente) — ya no queda diferida.
- `src/doc_organize/ai/taxonomy_classification_client.py` (nuevo): `TaxonomyClassificationClient`
  — Sub-fase B para manifiesto de taxonomía, resuelve dominio + tipo de material en **una sola
  llamada combinada** al LiteLLM Proxy (en vez de dos llamadas independientes). Mismo patrón que
  `DomainClassificationClient`: `httpx.AsyncClient` con `transport` inyectable, config propia
  (`LiteLLMTaxonomyClassificationConfig`, nuevo en `core/models.py`, env vars propias
  `DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_BASE_URL`/`_VIRTUAL_KEY`/`_MODEL` — no comparte
  credenciales con la config de 1 eje, ISP) y excepciones propias
  (`TaxonomyClassificationError`/`AuthError`/`ConnectionError`, nuevas en `core/exceptions.py`).
  El valor devuelto en cada eje se valida siempre contra su propio catálogo candidato, nunca
  inventa un dominio o tipo de material fuera de lista.
  `ContextBuilder.build()` gana el parámetro `taxonomy_classification_client`; en modo
  manifiesto, con `ai_classification_enabled=True` y un cliente dado,
  `_classify_with_manifest_ai()` reintenta por IA cada documento que las reglas dejaron con el
  placeholder `sin-clasificar` en el eje de dominio y/o en el de tipo de material — la sugerencia
  de la IA solo se aplica al eje que seguía en placeholder; un eje ya resuelto por reglas con
  confianza nunca se sobreescribe, aunque la IA sugiera algo distinto para ese eje en la misma
  respuesta. `DomainDocument.classified_by` pasa a `"ai"` si la IA cambió efectivamente algún eje,
  se queda en `"rules"` si no cambió nada (un único campo string sigue bastando).
- `src/doc_organize/context/reorganizer.py`/`mkdocs_generator.py`: la carpeta de tipo
  (`<dominio>/<tipo>/<stem>/` y el nav de `mkdocs.yml`) usa `DomainDocument.material_type`
  cuando está definido, o la extensión como hasta ahora.
- `src/doc_organize/web/routes/context.py`: `POST /api/projects/{name}/context` (REST y
  WebSocket) carga `taxonomy_manifest.md` automáticamente si existe; lo combina con
  `candidate_domains` en la misma petición devuelve `400` explícito. `ai_classification_enabled`
  ahora también tiene efecto en modo manifiesto: `_optional_ai_client()` construye
  `TaxonomyClassificationClient` (2 ejes) en vez de `DomainClassificationClient` (1 eje) cuando
  hay `taxonomy_manifest` — env vars de clasificación de 2 ejes sin definir se traduce en `400`
  explícito, igual criterio que ya existía para las de 1 eje. La página "Contexto"
  (`GET /projects/{name}/context`) consulta la config del proxy correspondiente al modo
  (manifiesto o no) para decidir si el checkbox de IA aparece habilitado.
- `src/doc_organize/web/templates/context.html.j2`: la página "Contexto" expone el modo
  manifiesto de taxonomía — aviso "Modo manifiesto de taxonomía activo" cuando
  `Context.taxonomy_manifest_used`, y cada fila de dominio se despliega para ver el tipo de
  material de cada documento (`DomainDocument.material_type_name`, o el slug derivado si el
  documento cayó en el placeholder `sin-clasificar`). Sin cambios en `web/routes/context.py`
  ni en el contrato REST/WebSocket — la plantilla ya recibía el `Context` completo.

- `src/doc_organize/context/taxonomy_template_registry.py` (nuevo): `TaxonomyTemplateRegistry` —
  biblioteca de plantillas de manifiesto de taxonomía reutilizables **entre proyectos**
  (`~/.doc_organize/taxonomy_templates/` por defecto, o ruta alternativa vía
  `doc_organize web --templates-path`), con fallback a plantillas empaquetadas de solo lectura
  (`sgi-iso27001`, `calidad`). Seleccionable por nombre al construir el contexto de un proyecto
  (`taxonomy_template_name`, selector en la página "Contexto"); el `taxonomy_manifest.md` local de
  un proyecto, si existe, sigue ganando siempre sobre cualquier plantilla.
- `src/doc_organize/ai/taxonomy_manifest_draft_client.py` (nuevo): `TaxonomyManifestDraftClient` +
  `POST /api/projects/{name}/context/taxonomy-manifest-draft` — a partir de una muestra de
  documentos ya convertidos (muestreo round-robin determinista por carpeta,
  `taxonomy_manifest_sampler.select_document_sample()`), pide a un LiteLLM Proxy que proponga un
  catálogo de dominios + tipos de material. Distinto de la Sub-fase B de clasificación (que elige
  DENTRO de un catálogo ya cerrado): aquí la IA propone el catálogo mismo. Endpoint de solo
  lectura — nunca persiste nada; el usuario revisa/edita el borrador antes de guardarlo.
- `src/doc_organize/auth/instance_secrets_store.py` (nuevo) + `web/routes/ai_settings.py`: panel
  `/admin/configuracion-ia` — ver/editar desde la web las 5 familias de credenciales de IA que
  antes solo eran configurables editando `.env` a mano. Cifradas en reposo con
  [Fernet](https://cryptography.io/en/latest/fernet/) (`DOC_ORGANIZE_SECRETS_KEY`, extra `[web]`);
  un secreto ya guardado nunca se reexpone (`GET` solo devuelve `masked_hint`, últimos 4
  caracteres). Precedencia store → `.env` → sin configurar. `PUT
  /api/projects/{name}/context/taxonomy-manifest` (nuevo) persiste por fin el borrador que
  "Proponer con IA" generaba pero nadie podía guardar hasta ahora. `/admin/plantillas-taxonomia`
  gana CRUD completo (crear/editar/borrar) sobre `TaxonomyTemplateRegistry`.

### Changed

- `src/doc_organize/core/exceptions.py`: `ProjectNotFoundError`/`ProjectAlreadyExistsError`
  construyen ahora su propio mensaje en `__init__(name: str)` a partir del nombre, en vez de que
  cada llamador repitiera el mismo f-string (cluster de literales duplicados, regla S1192) —
  cualquier código que las instanciara pasando un mensaje ya formateado debe pasar solo `name`.
- **Rediseño Tenant/Role/User** (breaking change en la API pública de `AuthStore`, ver
  `.ai/DECISIONS_LOG.md` Revisión 16 y `.ai/sessions/2026-09-11-tenant-role-user-redesign/`):
  `AuthStore` aprovisiona de fábrica, sin CLI previa, un tenant `"default"` + usuario `admin` al
  primer arranque (`must_change_password=True`, `is_instance_admin=True`); esa cuenta no puede
  completar `POST /login` en modo no-loopback mientras conserve la contraseña de fábrica.
  `create_tenant()` ya no aprovisiona ningún rol/usuario para tenants adicionales. `Role` deja de
  estar ligado a un tenant (`name` único **globalmente**): `create_role/get_role/update_role/
  delete_role/list_roles/can_access_project` pierden el parámetro `tenant_id`.
  `RoleNotFoundError`/`RoleAlreadyExistsError` pierden el parámetro `tenant_id` en su constructor.
  El acceso de escaneo de un rol no-admin pasa a ser implícito (`project.root_path` de cada
  proyecto en `project_names`); `GET /api/fs/browse` gana el parámetro opcional `project`. Nuevo
  `User.is_blocked` (bloquear invalida todas sus sesiones activas en la misma transacción) e
  `User.is_instance_admin` (nivel de instancia, independiente del `is_admin` de un rol; gestiona
  cualquier tenant desde la nueva pantalla `/admin/tenants` y es el único que puede tocar
  configuración de IA/plantillas de taxonomía, que pasan de `require_admin` a
  `require_instance_admin`). Nuevo subcomando CLI `user set-instance-admin`.

### Removed

- `src/doc_organize/core/models.py`: `Role.tenant_id` y `Role.allowed_scan_roots` (ver "Changed"
  arriba) — el acceso de escaneo de un rol restringido ya no se declara explícitamente, es
  implícito a la carpeta de sus proyectos permitidos.

### Fixed

- `src/doc_organize/context/context_builder.py`/`mkdocs_generator.py`: el `name`/`description`
  declarados por dominio y tipo de material en `taxonomy_manifest.md` ahora se reflejan en la
  tabla "Contexto", `context.json` y el nav de `mkdocs.yml` — antes se ignoraban y siempre se
  mostraba el slug derivado (p. ej. "Rrhh" en vez de "Recursos Humanos"), pese a que `name` es
  un campo obligatorio del manifiesto.
- `src/doc_organize/auth/auth_store.py`: las guardas de "último admin del tenant"
  (`delete_user`/`update_user`/`set_user_blocked`) bloqueaban también vaciar un tenant por
  completo eliminando/bloqueando/degradando a su único usuario restante, dejando `delete_tenant()`
  (que exige cero usuarios) inalcanzable para ese tenant. Ahora solo bloquean si dejarían a OTROS
  usuarios del tenant sin ningún admin.

## [0.8.0] - 2026-09-10

### Fixed

- `src/doc_organize/converter/converter.py`: dos fallos reales de conversión sin diagnóstico útil.
  Un `.docx`/`.html` cuyo `output_dir` vivía fuera del árbol escaneado terminaba con
  `[Errno 2] No such file or directory` al extraer imágenes (la ruta de salida arrastraba la
  jerarquía absoluta completa del disco de origen en vez de una relativa a la carpeta escaneada) y
  una excepción sin mensaje dejaba el documento en `ERROR` sin ninguna pista visible.
  `resolve_output_paths()` calcula ahora la ruta relativa a `scan_roots` (las carpetas indicadas al
  escanear), y `convert_document()` usa un mensaje de respaldo cuando `str(exc)` está vacío.
- `src/doc_organize/converter/converter.py`: dos causas adicionales del mismo tipo de fallo,
  encontradas al reprocesar los ficheros reales que motivaron el fix anterior. Un `MemoryError` (sin
  mensaje propio, por diseño de Python) al convertir un HTML muy grande (~60 MB, informe OWASP ZAP)
  seguía sin dar ninguna pista útil — ahora se reporta el tamaño del documento en el mensaje. Un
  fichero cuyo nombre termina en espacio antes de la extensión (p. ej. `"Anti SPAM correo Virtual
  Desk .docx"`) generaba una carpeta `img/<stem>/` sin ese espacio final (Windows lo normaliza al
  crearla, como último componente de la ruta) pero luego se referenciaba con el espacio al escribir
  una imagen dentro (ya como componente intermedio, sin normalizar), produciendo
  `[Errno 2] No such file or directory` — `resolve_output_paths()` ahora sanea con `rstrip(" .")`
  cada segmento de la ruta mirroreada (carpetas intermedias y nombre final).
- `src/doc_organize/web/templates/base.html.j2`: la tabla de la pestaña "Historial de ejecuciones"
  (Escanear) mostraba scroll horizontal — el contenedor `<main>` compartido por toda la app
  (`max-w-[720px]`) era más estrecho que las 7 columnas de la tabla. Ampliado a `max-w-[920px]`.
- `pyproject.toml`: el extra `ocr-gpu` instalaba `torch`/`torchvision`/`opencv-python` pero no
  `easyocr` en sí, el paquete que Docling realmente carga para el motor OCR acelerado por GPU —
  `pip install .[ocr-gpu]` seguido de `--use-ocr --use-gpu` fallaba con
  `EasyOCR is not installed`. Añadido `easyocr>=1.7` al extra (`docs/guides/installation.md` y
  `.ai/product.md` actualizados para reflejarlo).
- `src/doc_organize/web/templates/_shared_scripts.html.j2`: el explorador de carpetas del servidor
  ("Buscar…") no protegía contra respuestas de red desordenadas (navegar rápido por subcarpetas
  podía dejar la vista con datos de una carpeta distinta a la mostrada) ni contra doble clic en
  "Usar esta carpeta" durante una petición en curso. Añadido token de generación de petición y
  deshabilitado temporal del botón mientras se resuelve `onSelect`.
- `src/doc_organize/context/{domain_classifier,context_builder,reorganizer}.py`: `images_dir` de
  `ConversionResult` se perdía al construir `DomainDocument` y `Reorganizer._copy_document` nunca
  copiaba la carpeta `img/<stem>/` al destino reorganizado, así que MkDocs servía las imágenes de
  los documentos como rotas. Corregido en dos pasadas: propagar `images_dir` por `DomainDocument`/
  `Reorganizer`, y `web/routes/context.py::_gather_converted_documents` (que reconstruye
  `ConversionResult` desde `cache.db` recalculando `markdown_path`/`json_path`) recalculando también
  `images_dir` — no se persiste en `cache.db` ni en `document.json`, así que el primer fix por sí
  solo operaba sobre un `ConversionResult` que ya nacía sin él.

### Added

- `src/doc_organize/web/routes/downloads.py`: nuevo `GET /downloads/projects/{name}/export-preview`
  (`_compute_export_preview()`) — nº de ficheros y tamaño total en bytes que incluiría `export.zip`,
  sin generarlo; espeja las mismas tres fuentes que `_build_export_zip()` (`Conversión/`,
  `cache_export.json`, `DEDUP_REPORT.json`).
- `src/doc_organize/web/templates/_nav_macros.html.j2`: "Descargar export" muestra ahora esa
  estimación de tamaño/nº de archivos junto al botón (cargada vía `fetch` al `export-preview`) y,
  si el navegador soporta la File System Access API (`showDirectoryPicker`, Chrome/Edge en contexto
  seguro), permite elegir la carpeta de destino y escribe el ZIP ahí; en el resto de navegadores
  cae al comportamiento estándar (carpeta de descargas configurada del navegador).
- `src/doc_organize/core/models.py`: nuevos `ScanEventType.OCR_STARTED`/`OCR_FILE_STARTED`.
- `src/doc_organize/converter/ocr_scheduler.py`: `OCRScheduler.process_with_ocr()` gana un
  parámetro opcional `progress_callback` (no rompe compatibilidad — `None` por defecto), invocado
  justo antes de reconvertir cada documento con su índice/total.
- `src/doc_organize/scan/scan_command.py`: la segunda pasada de OCR informa ahora progreso en vivo
  en vez de todo de golpe al terminar el batch completo. Nuevo `_stream_ocr_batch()` lanza
  `OCRScheduler.process_with_ocr()` en una tarea paralela y retransmite `OCR_FILE_STARTED` por una
  cola según avanza cada documento; `_process_ocr()` emite `OCR_STARTED` (con el total de
  candidatos) antes de arrancar el batch.
- `src/doc_organize/web/templates/folder_selector.html.j2`: la pestaña "Escanear" muestra ahora una
  segunda barra de progreso (`#scan-ocr-progress`) dedicada a los ficheros en curso de OCR, análoga
  a la barra de conversión general ya existente — visible solo cuando hay candidatos a OCR en esta
  ejecución.
- `src/doc_organize/web/routes/admin.py`: la gestión de roles y usuarios pasa de una única página
  combinada (`GET /admin/users`) a dos páginas independientes — `GET /admin/roles` (nueva) y
  `GET /admin/users` — cada una con su propia entrada de menú, agrupadas bajo un apartado "Admin" en
  el sidebar (`base.html.j2`).
- `src/doc_organize/web/routes/admin.py`: `POST /api/users` acepta ahora
  `must_change_password: bool = False`; expuesto como checkbox "Debe cambiar contraseña" en
  `admin_users.html.j2` (antes solo alcanzable programáticamente, sin UI).
- `src/doc_organize/web/templates/admin_roles.html.j2`: "Raíces de escaneo permitidas" pasa de un
  `<textarea>` de texto libre a una lista gestionada con "Guardar carpeta" (ruta manual) y
  "Buscar…" (explorador de carpetas del servidor, reutilizando `GET /api/fs/browse`), con botón
  "Eliminar" por entrada.
- `src/doc_organize/ai/` (extra `ai`, nuevo — fase 2): monitorización de uso/coste de IA
  multi-fuente, sin funcionalidad de inferencia/proxying. `LiteLLMUsageClient.get_usage()` consulta
  el spend de una virtual key de un LiteLLM Proxy externo (`GET /key/info`);
  `GitHubCopilotUsageClient.get_usage()` consulta el consumo de "premium requests" de un plan
  Copilot Pro individual vía la API oficial de Billing Usage de GitHub
  (`GET /users/{username}/settings/billing/premium_request/usage`, sin tocar el endpoint interno de
  completions de Copilot). Ambos devuelven `UsageSnapshot`/`UsageLineItem`
  (`src/doc_organize/core/models.py`) y cumplen el protocolo estructural `UsageSource`
  (`src/doc_organize/ai/usage_source.py`) sin herencia compartida. Nuevas excepciones
  `UsageSourceError`/`UsageSourceAuthError`/`UsageSourceConnectionError`
  (`src/doc_organize/core/exceptions.py`).
- `src/doc_organize/context/` (paquete nuevo, extra `context`): organización documental por
  dominios. `ContextBuilder.build()` clasifica los documentos ya convertidos de un proyecto en dos
  sub-fases — `DomainClassifier` (Sub-fase A, reglas sobre `chunks`/`title` del `.json` de
  conversión, catálogo predefinido o descubrimiento por carpeta) y, opt-in vía
  `ai_classification_enabled`, un fallback por IA (Sub-fase B, `DomainClassificationClient` en
  `src/doc_organize/ai/`) que solo elige entre el catálogo ya confirmado por la Sub-fase A —
  ninguna de las dos inventa un dominio nuevo. `Reorganizer.reorganize()` copia original + `.md` +
  `.json` de cada documento clasificado a `<output_folder_name>/<dominio>/<tipo>/<stem>/` (nunca
  mueve, limpia copias huérfanas de dominios/documentos ya no vigentes en cada reconstrucción, y
  valida todos los artefactos antes de tocar disco para no destruir una reconstrucción anterior si
  falla a mitad). `MkDocsGenerator.generate()` escribe `mkdocs.yml` + `index.md` usando
  `organizado/` como `docs_dir` directamente. `ContextRegistry` persiste `context.json` +
  `domains/<slug>/{DOMAIN.md,index.json}` (mismo patrón que `ProjectRegistry`), preservando el
  texto editado a mano en `DOMAIN.md` entre reconstrucciones.
- `src/doc_organize/ai/domain_classification_client.py`: `DomainClassificationClient` (Sub-fase B)
  + `litellm_classification_config_from_env()` — habla `chat/completions` de un LiteLLM Proxy
  (config propia `LiteLLMClassificationConfig`, no comparte credenciales con `LiteLLMUsageConfig`);
  el dominio devuelto siempre se valida contra el catálogo antes de propagarlo. Nuevas excepciones
  `DomainClassificationError`/`AuthError`/`ConnectionError`.
- `src/doc_organize/web/routes/context.py`: `GET /projects/{name}/context` (página),
  `POST`/`GET /api/projects/{name}/context` (construir/ver) — rechaza con `409` si hay otra
  operación en curso para el proyecto, con `400` si se activa la IA sin
  `DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL`/`_VIRTUAL_KEY` configuradas.
- `deploy/litellm/{docker-compose.yml,config.yaml.example,.env.example}` + guía
  [`docs/guides/litellm_proxy_setup.md`](docs/guides/litellm_proxy_setup.md): despliegue local del
  LiteLLM Proxy que requiere la Sub-fase B (proxy + Postgres, virtual key dedicada).
- `src/doc_organize/context/mkdocs_generator.py`: construir el contexto ejecuta ahora `mkdocs build`
  a disco (si `mkdocs` está instalado) en vez de dejar solo `mkdocs.yml` sin construir.
  `output_folder_name` es elegible en la primera construcción de un proyecto (validado contra path
  traversal y contra nombres ya reservados por otros subsistemas) y queda fijo hasta que se elimina
  el contexto por completo — nuevo `DELETE /api/projects/{name}/context`, con confirmación explícita
  en la UI — así se puede elegir otra carpeta sin dejar copias huérfanas. La página de Contexto avisa
  si LiteLLM Proxy está configurado antes de que el usuario intente activar la Sub-fase B.
- `src/doc_organize/web/routes/context.py`: nuevo `GET /projects/{name}/context/site[...]` para
  visualizar el sitio MkDocs ya construido de cualquier proyecto, independiente del flujo de
  build/reconstruir contexto, con el mismo control de acceso por tenant/rol que el resto de la app
  (`require_project_access`). Nunca se dispara automáticamente tras un build — el usuario lo abre
  desde el enlace "ver documentación generada", visible solo cuando `mkdocs_site_built` es `True`.
- `src/doc_organize/web/templates/context.html.j2`: "Reconstruir/Construir contexto" y "Eliminar
  contexto" muestran ahora el mismo semáforo de 3 luces que Escanear/Duplicados
  (Inicio/Ejecución/Finalización, rojo en error), con progreso real vía dos WebSocket nuevos
  (`/context/build`, `/context/delete`) que retransmiten cada paso de
  `ContextBuilder`/`Reorganizer`/`MkDocsGenerator` — incluida una barra numérica X/Y para la
  clasificación por IA y la copia de documentos. El checkbox de "Clasificación asistida por IA" se
  deshabilita (y se fuerza desmarcado) cuando LiteLLM Proxy no está configurado, incluso si un build
  anterior lo había dejado activo.

### Changed

- `src/doc_organize/web/templates/dashboard.html.j2`, `admin_roles.html.j2`, `admin_users.html.j2`,
  `project_selector.html.j2`: el helper `postJson`/`apiError` y el panel "explorador de carpetas
  del servidor" (antes duplicados inline en cada plantilla, incluyendo una implementación
  independiente en `project_selector.html.j2` con `createFolderBrowser()`) se extraen a
  `_shared_scripts.html.j2` (JS, `initFolderBrowser(idPrefix, onSelect)`) y
  `_folder_browser_macros.html.j2` (macros Jinja, `class_override` opcional para preservar las
  clases Tailwind propias de "Mover"/"ubicación al crear proyecto"); sin cambio de comportamiento
  observable — incluida la diferencia real de cerrar o no el panel tras seleccionar (resuelta con
  un segundo argumento `close()` que cada página invoca o ignora según su flujo).
- `src/doc_organize/web/dependencies.py`: la autenticación y el lock de los WebSocket de proyecto
  (antes duplicados entre `scan.py` y `context.py`, con textos ya divergentes entre sí) se
  centralizan aquí, reutilizados por los WS de escaneo, deduplicación y, ahora, construir/eliminar
  contexto.
- `src/doc_organize/web/templates/_semaforo_macros.html.j2` (nuevo): el HTML/JS del semáforo de 3
  luces (antes triplicado entre `folder_selector.html.j2`, `duplicates_resolver.html.j2` y
  `context.html.j2`) se extrae a esta macro común; sin cambio de comportamiento observable
  (verificado en navegador real con Playwright en las 3 páginas).

## [0.7.0] - 2026-09-03

### Added

- `src/doc_organize/core/models.py`: `ScanRunReport` gana `discovery_duration_seconds`/
  `total_conversion_seconds` (ambos opcionales — `None` en históricos previos a estos campos,
  para no romper la carga de líneas ya escritas en `SCAN_HISTORY.jsonl`). Nuevo `DedupEventType`
  (`started`/`duplicates_found`/`group_started`/`group_resolved`/`completed`) y `DedupEvent`,
  mismo patrón que `ScanEventType`/`ScanEvent`, emitidos por `ScanCommand.deduplicate_streaming()`.
- `src/doc_organize/scan/scan_command.py`: el payload de `FILE_CONVERTED`/`OCR_PROCESSED` gana
  `duration_seconds` (ya calculado por `ConversionResult`, antes descartado); el de `SCANNED` gana
  `discovery_duration_seconds` (ya calculado por `DocumentScanner.scan_folders()`, antes descartado).
  `ScanSummary` acumula ambos (`total_conversion_seconds`, `discovery_duration_seconds`) y los
  refleja en `render()` (CLI) y en el evento `COMPLETED`.
- `src/doc_organize/dedup/deduplication.py`: `DeduplicationManager` gana `move_group()` (mueve los
  descartados de un único grupo) y `finalize_report()` (persiste `DEDUP_REPORT.json`/
  `DEDUP_HISTORY.jsonl`), ambos públicos — `resolve_duplicates()` pasa a componerlos.
- `src/doc_organize/web/routes/scan.py`: nuevo WebSocket `WS /api/projects/{name}/scan/deduplicate`,
  retransmitiendo cada `DedupEvent` en vivo (progreso por grupo de duplicados detectado/movido) —
  mismo patrón que el WebSocket de escaneo.
- `src/doc_organize/web/templates/duplicates_resolver.html.j2`: la pestaña "Buscar duplicados"
  muestra ahora una barra de progreso en vivo por grupo ("Moviendo grupo X/Y…") y la duración de la
  ejecución, en vez de un semáforo que solo simulaba "en ejecución" sobre una única llamada bloqueante.
- `src/doc_organize/web/templates/folder_selector.html.j2`: la pantalla "Escanear" muestra ahora la
  duración de descubrimiento de ficheros y de conversión acumulada, tanto en la última ejecución
  (en vivo y tras recargar) como en cada fila del histórico de ejecuciones.
- `src/doc_organize/core/constants.py`: `DEDUP_REPORT_JSON_NAME` (`DEDUP_REPORT.json`),
  `DEDUP_HISTORY_JSONL_NAME` (`DEDUP_HISTORY.jsonl`) — nombres de fichero de deduplicación
  centralizados, mismo patrón que `SCAN_HISTORY_JSONL_NAME`/`SCAN_ERRORS_HISTORY_JSONL_NAME`.

### Changed

- `src/doc_organize/web/routes/scan.py`: `_authorize_scan_websocket` renombrado a
  `_authorize_project_websocket` — ahora compartido por los WebSocket de escaneo y de deduplicación.
- `src/doc_organize/dedup/deduplication.py`, `src/doc_organize/web/routes/downloads.py`,
  `src/doc_organize/web/routes/duplicates.py`, `src/doc_organize/main.py`: los literales
  `"DEDUP_REPORT.json"`/`"DEDUP_HISTORY.jsonl"`/`"duplicados"` pasan a usar las constantes
  centralizadas de `core/constants.py` (sin cambio de valor ni de comportamiento).

### Removed

- `src/doc_organize/scan/scan_command.py`: `ScanCommand.deduplicate()` eliminado — sustituido por
  `deduplicate_streaming()` (async generator con progreso, ver "Added"). Sin variante síncrona de
  resumen final: los llamadores que solo necesitan el resumen (CLI) consumen el generador y se
  quedan con su evento `COMPLETED`.
- `src/doc_organize/web/routes/scan.py`: `POST /api/projects/{name}/scan/deduplicate` eliminado —
  sustituido por el WebSocket `WS /api/projects/{name}/scan/deduplicate` (ver "Added").

## [0.6.0] - 2026-09-03

### Added

- `src/doc_organize/core/models.py`: `DeduplicationReport` gana `started_at`/`duration_seconds`
  (ambos opcionales — `None` en históricos previos a este campo, para no romper la carga de líneas ya
  escritas en `DEDUP_HISTORY.jsonl`).
- `src/doc_organize/dedup/deduplication.py`: `DeduplicationManager.resolve_duplicates()` acepta un
  nuevo parámetro opcional `started_at: datetime | None = None` — cuando se pasa, calcula
  `duration_seconds` cubriendo desde ahí hasta que termina la resolución.
- `src/doc_organize/scan/scan_command.py`: `DeduplicationSummary` gana `duration_seconds`;
  `ScanCommand.deduplicate()` captura `started_at` antes de re-escanear/detectar duplicados, para que
  la duración cubra la operación completa de "Buscar duplicados" (mismo criterio que
  `duration_seconds` en `ScanSummary`/`ScanRunReport` para "Escanear").
- `src/doc_organize/web/routes/scan.py`: `DeduplicateFoldersResponse` gana `duration_seconds`.
- `src/doc_organize/web/routes/duplicates.py`: el formulario interactivo de resolución
  (`POST /api/projects/{name}/duplicates/resolve`) también captura y persiste `started_at`/
  `duration_seconds`, mismo criterio que la acción masiva "Buscar duplicados".
- `src/doc_organize/web/templates/duplicates_resolver.html.j2`: la pantalla "Duplicados" muestra ahora
  la duración de la última ejecución de "Buscar duplicados" (banner) y de cada ejecución del histórico,
  reutilizando el filtro Jinja `format_duration` ya existente.
- `src/doc_organize/core/models.py`: nuevo `ScanEventType.FILE_STARTED`, emitido por
  `ScanCommand._convert_documents()` justo antes de convertir cada documento, con
  `{"path", "index", "total"}` (`total` = ficheros a convertir en esta ejecución).
- `src/doc_organize/scan/scan_command.py`: el payload del evento `SCANNED` gana `to_process` (total
  real de ficheros que se van a convertir, distinto de `scanned`/`new + modified`: también incluye
  reintentos de ficheros en `ERROR` sin cambios).
- `src/doc_organize/web/templates/folder_selector.html.j2`: la pantalla "Escanear" muestra ahora una
  barra de progreso en vivo con "Procesando X/Y: nombre_de_fichero" mientras el escaneo corre, y un
  mensaje final ("Completado: N fichero(s) procesado(s)." o "Sin ficheros nuevos que convertir."); el
  registro JSON detallado de eventos pasa a un `<details>` colapsado ("Resultado del escaneo") en vez
  de ser el elemento principal de la pantalla.

## [0.5.0] - 2026-09-03

### Added

- `src/doc_organize/utils/date_format.py`: nuevo módulo `format_datetime(value, pattern=None, tz_name=None)` /
  `format_duration(seconds)`, registrados como filtros Jinja (`web/templating.py`) — centraliza cómo se
  muestran al usuario los timestamps ISO 8601 UTC que genera el resto del proyecto. Parametrizable vía las
  variables de entorno `DOC_ORGANIZE_DATE_FORMAT` / `DOC_ORGANIZE_TIMEZONE` (mismo patrón que
  `utils/logging.py`); por defecto, formato español (`dd/mm/aaaa HH:MM:SS`) y zona horaria de España
  (`Europe/Madrid`, con cambio automático de horario de verano/invierno).
- `src/doc_organize/core/models.py`: nuevo modelo `ScanRunReport` (`scan_run_id`, `started_at`,
  `finished_at`, `duration_seconds`, `total_scanned`, `completed`) — histórico de duración de ejecuciones
  de escaneo.
- `src/doc_organize/scan/scan_history_store.py`: nuevo store JSONL append-only
  (`append_scan_run(history_path, report)` / `list_scan_runs(history_path)`), exportado desde
  `doc_organize.scan`. Mismo patrón que `SCAN_ERRORS_HISTORY.jsonl`/`DEDUP_HISTORY.jsonl`, pero registra
  **toda** ejecución (completada o no), no solo las que producen error.
- `src/doc_organize/core/constants.py`: `SCAN_HISTORY_FOLDER_NAME` (`historial_escaneo`),
  `SCAN_HISTORY_JSONL_NAME` (`SCAN_HISTORY.jsonl`).
- `src/doc_organize/scan/scan_command.py`: `ScanCommand.run()`/`run_streaming()` aceptan un nuevo
  parámetro opcional `history_log_path: Path | None = None`; `ScanSummary` incluye `duration_seconds`
  (también en el resumen impreso por el CLI, línea "Tiempo de ejecución: …"). Cada ejecución —completada
  o interrumpida por una excepción— se registra en el histórico con `completed=True`/`False`.
- `src/doc_organize/web/routes/scan.py` / `web/templates/folder_selector.html.j2`: la pantalla "Escanear"
  muestra ahora la duración de la última ejecución, y una nueva pestaña "Historial de ejecuciones" lista
  cada ejecución registrada (inicio, fin, duración, documentos escaneados, si terminó o se interrumpió).
- `pyproject.toml`: nueva dependencia `tzdata` (requerida por `zoneinfo` para resolver zonas horarias
  IANA como `Europe/Madrid` en Windows).
- `scripts/build_docs_zip.py`: nuevo script para empaquetar la documentación compilada como ZIP
  con checksums SHA256 para distribución offline. Genera:
  - `dist/doc_organize-docs-{version}.zip` (sitio MkDocs completo comprimido)
  - `dist/doc_organize-docs-{version}.zip.sha256` (checksum individual)
  - `dist/CHECKSUMS.txt` (histórico de todas las builds)
- `.github/workflows/docs-zip-release.yml`: nueva automatización que en cada push a `main`/`develop`
  que afecte `docs/`, `mkdocs.yml` o `pyproject.toml`:
  1. Construye documentación con `mkdocs build --strict`
  2. Genera ZIP con `scripts/build_docs_zip.py`
  3. Crea GitHub Release con tag `docs-v{version}` y adjunta ZIP + checksums
  4. Publica en [Releases](https://github.com/fmanza/doc_organize/releases)

**Features (documentación offline):**
- ✅ Descarga offline de documentación completa con búsqueda
- ✅ Verificación de integridad por SHA256 (portable, compatible con `sha256sum -c`)
- ✅ Histórico de builds en `CHECKSUMS.txt` para auditoría
- ✅ GitHub Artifacts (retención 30 días) para CI/CD
- ✅ Error handling + validaciones (cross-platform, Python 3.11+)

**Uso:**
```bash
# Manual (local)
python scripts/build_docs_zip.py
python scripts/build_docs_zip.py --no-build  # rezip site/ existente

# Automático (CI/CD)
# En cada push que toque docs/ → GitHub Release automático
```

### Changed

- `web/templates/dashboard.html.j2`, `project_selector.html.j2`, `duplicates_resolver.html.j2`,
  `scan_errors.html.j2`: los timestamps ISO 8601 UTC que antes se mostraban crudos ahora pasan por el
  filtro `format_datetime` (formato español/España por defecto, configurable — ver `date_format.py`
  arriba).

### Fixed

- `format_datetime()` degrada a mostrar el valor original (en vez de lanzar una excepción y tumbar la
  página) ante un timestamp no parseable o una zona horaria mal configurada — mismo criterio de
  tolerancia a datos corruptos que ya aplican `load_error_history`/`_load_dedup_history`.
- La persistencia del histórico de duración de ejecuciones se realiza ahora **antes** de emitir el evento
  `COMPLETED` (no después, en un `finally`): evita una carrera intermitente con la desconexión del cliente
  WebSocket, que cierra la conexión en cuanto recibe ese evento.
- Un fallo de E/S al escribir el histórico de tiempos de escaneo o el histórico de errores de escaneo
  (permiso denegado, disco lleno…) ya no aborta un escaneo que por lo demás terminó con éxito — ambas
  escrituras son ahora best-effort (se loguea un warning en vez de propagar la excepción).

---

## [0.4.0] - 2026-08-31

⚠️ **Rompe contratos públicos** (ver "Removed"/"Changed"): firma de `ScanCommand`, flags del CLI
`scan`, payload del WebSocket de escaneo y el enum `ScanEventType`. Sin release publicado de
`doc_organize` hasta la fecha — no se ofrece guía de migración formal, solo el detalle de cada
cambio abajo.

### Added

- `src/doc_organize/scan/scan_command.py`: nuevo método `ScanCommand.deduplicate(paths,
  duplicates_dir, folders_json) -> DeduplicationSummary` — busca y mueve duplicados de forma
  independiente al escaneo, a petición explícita del usuario. Nuevo dataclass
  `DeduplicationSummary` (`groups_found`, `moved`, `warnings`), exportado desde `doc_organize.scan`.
- `src/doc_organize/main.py`: nuevo subcomando CLI `deduplicate --paths ... [--project ...]
  [--duplicates-dir ...]`, con su propia resolución de rutas (`_resolve_dedup_paths`) — no exige
  `--output-dir`/`--cache-file` como `scan`, porque no convierte ni cachea nada.
- `src/doc_organize/web/routes/scan.py`: nuevo `POST /api/projects/{name}/scan/deduplicate` —
  equivalente web del subcomando CLI, sobre todas las carpetas guardadas del proyecto.
- `src/doc_organize/dedup/deduplication.py`: `DeduplicationManager.resolve_duplicates()` añade
  además una línea a `duplicados/DEDUP_HISTORY.jsonl` (JSON Lines, append-only) por cada ejecución
  — histórico incremental y consultable, a diferencia de `DEDUP_REPORT.json` (que solo refleja la
  última). Se registra toda ejecución, incluso sin duplicados encontrados.
- `src/doc_organize/web/templates/folder_selector.html.j2`: botón "Buscar duplicados" (menú
  Escaneo) — "Escanear" nace deshabilitado y solo se habilita tras una ejecución exitosa de
  "Buscar duplicados" en la misma visita a la página (gate de cliente, sin persistencia entre
  visitas; no sustituye ningún control de seguridad existente).
- `src/doc_organize/web/routes/duplicates.py` / `duplicates_resolver.html.j2`: sección "Histórico
  de deduplicaciones" — lista todas las ejecuciones registradas en `DEDUP_HISTORY.jsonl`, cada una
  con su propio detalle de archivos (conservado/movido), en un bloque colapsable
  (`<details>`/`<summary>` nativo, sin JavaScript de terceros). El buscador y el contador de la
  página cubren los grupos de todas las ejecuciones, no solo la más reciente.
- `src/doc_organize/core/constants.py`: `SCAN_FOLDERS_JSON_NAME` — nombre centralizado del fichero
  `folders.json`, usado por `main.py`, `web/routes/scan.py` y `web/routes/duplicates.py`.

### Changed

- `src/doc_organize/web/routes/scan.py`: el WebSocket `/api/projects/{name}/scan` ya no acepta
  `paths` del cliente — resuelve siempre todas las carpetas guardadas del proyecto
  (`ScannedFoldersStore`) del lado servidor. `mark_used()` ahora marca solo las rutas ya validadas
  por `FolderValidator`, no las carpetas guardadas sin validar (evita marcar como usada — y por
  tanto no eliminable — una carpeta que ya no existe en disco).
- `src/doc_organize/web/routes/duplicates.py`: la sección "Duplicados ya resueltos" desaparece
  como bloque independiente — su contenido pasa a ser, simplemente, el detalle de la ejecución más
  reciente dentro de "Histórico de deduplicaciones". "Última deduplicación" se deriva ahora de
  `DEDUP_HISTORY.jsonl` (primera entrada) en vez de leer `DEDUP_REPORT.json` aparte — elimina una
  posible inconsistencia entre ambas lecturas si un fallo interrumpe la escritura entre los dos
  ficheros. `DEDUP_REPORT.json` se sigue escribiendo en disco sin cambios (contrato externo).
- `src/doc_organize/web/templates/duplicates_resolver.html.j2`: al resolver un conflicto desde el
  formulario interactivo, la página se refresca (antes solo mostraba un texto de resultado sin
  actualizar el estado de pendientes/histórico).
- Lecturas de fichero en `web/routes/duplicates.py` (histórico, último reporte, re-escaneo de
  duplicados pendientes) pasan a ejecutarse en un hilo aparte (`asyncio.to_thread`) para no
  bloquear el bucle de eventos — relevante porque `DEDUP_HISTORY.jsonl` crece sin límite durante la
  vida del proyecto.

### Removed

- `src/doc_organize/scan/scan_command.py`: `ScanCommand.run()`/`run_streaming()` pierden los
  parámetros `deduplicate: bool` y `duplicates_dir: Path` — la deduplicación ya no forma parte del
  pipeline de escaneo (ver `deduplicate()` en "Added").
- `src/doc_organize/main.py`: `scan` pierde los flags `--deduplicate` y `--duplicates-dir`.
- `src/doc_organize/core/models.py`: `ScanEventType.DEDUPLICATED` eliminado del enum — el escaneo
  ya no emite ningún evento de deduplicación (`deduplicate()` no emite `ScanEvent`, devuelve un
  `DeduplicationSummary` de una sola vez).

## [0.3.0] - 2026-08-31

### Added

- `src/doc_organize/web/routes/duplicates.py` /
  `src/doc_organize/web/templates/duplicates_resolver.html.j2`: la página
  "Revisar Duplicados" ahora incluye un buscador de filtrado instantáneo en
  cliente (por nombre de archivo o carpeta, sin round-trip al servidor), muestra
  la carpeta contenedora y el tamaño legible (`1.5 MB`) de cada documento en una
  tabla en vez de una lista de radios en texto plano, añade una sección de
  solo lectura "Duplicados ya resueltos" con el detalle de los grupos que un
  escaneo previo con "Deduplicar" activado ya movió automáticamente (lee
  `duplicados/DEDUP_REPORT.json`), y un contador que se actualiza a
  "X de Y grupo(s)." mientras el filtro está activo (suma pendientes + ya
  resueltos). Sin cambios en los modelos Pydantic ni en las rutas JSON
  existentes (`GET`/`POST /api/projects/{name}/duplicates...`).
- `src/doc_organize/web/routes/cache.py` /
  `src/doc_organize/web/templates/cache_viewer.html.j2`: misma mejora de
  visualización aplicada a la página "Caché" — buscador de filtrado instantáneo
  en cliente (por nombre de archivo o carpeta) y columnas Archivo/Carpeta
  separadas en vez de la ruta completa en una sola celda; el contador de
  entradas se actualiza a "X de Y entradas." mientras el filtro está activo. Sin
  cambios en `CacheEntryResponse`/`CacheListResponse` ni en las rutas JSON.

### Fixed

- `src/doc_organize/web/routes/duplicates.py`: la página "Revisar Duplicados"
  ya no muestra el mensaje ambiguo "No se detectaron duplicados" cuando un
  escaneo previo con "Deduplicar" activado ya había resuelto y movido los
  duplicados fuera de las carpetas escaneadas — un re-escaneo en vivo no podía
  encontrarlos y el mensaje contradecía lo que el propio escaneo acababa de
  informar. Ahora se explica el porqué y se lista su detalle (ver Added).
- `src/doc_organize/web/routes/duplicates.py`: un `duplicados/DEDUP_REPORT.json`
  truncado o corrupto (p. ej. por un proceso interrumpido a mitad de escritura)
  ya no produce un error 500 permanente en la página — se ignora y se degrada
  al mismo comportamiento que si el fichero no existiera.

## [0.2.0] - 2026-08-29

### Added

- `Role.allowed_scan_roots` (revisión de seguridad, revisión 9 roles y gestión de
  usuarios): un rol no-admin ahora solo puede escanear las raíces del sistema de
  archivos que un admin le haya asignado explícitamente vía `/api/roles` o
  `/admin/users`. Sin raíces configuradas, no puede escanear ninguna carpeta
  externa. Los roles `is_admin` no se ven afectados (siguen sin restricción).
  - `src/doc_organize/core/models.py`: campo `Role.allowed_scan_roots`.
  - `src/doc_organize/auth/auth_store.py`: tabla `role_scan_roots`,
    `AuthStore.create_role()`/`update_role()`/`get_role()`/`list_roles()`.
  - `src/doc_organize/web/routes/admin.py`: `CreateRoleRequest`/`UpdateRoleRequest`/
    `RoleResponse` incluyen `allowed_scan_roots`.
  - `src/doc_organize/web/templates/admin_users.html`: formulario de raíces de
    escaneo permitidas.
- `LoginRateLimiter` (`src/doc_organize/web/auth.py`): bloquea `POST /login`
  durante 60s tras 5 fallos consecutivos para el mismo (tenant_id, username) —
  mitiga la fuerza bruta sobre el usuario `admin`/`admin` de bootstrap.
  Constantes `LOGIN_MAX_ATTEMPTS`/`LOGIN_LOCKOUT_SECONDS` en
  `src/doc_organize/core/constants.py`.

### Fixed

- `src/doc_organize/web/routes/scan.py`: el WebSocket
  `/api/projects/{name}/scan` rechaza (`close 1008`) cualquier ruta fuera de las
  `allowed_scan_roots` del rol de la sesión — antes, un rol restringido a
  `project_names` concretos podía igualmente escanear cualquier ruta legible por
  el proceso servidor (incluyendo proyectos de otros tenants), evadiendo por
  completo esa restricción.
- `src/doc_organize/web/routes/auth.py`: la cookie de sesión
  (`doc_organize_session`) se marca `Secure` cuando la petición de `/login` llega
  por HTTPS — antes nunca se marcaba, permitiendo que viajara en claro sobre HTTP
  en un despliegue no-loopback sin TLS en el propio proceso.

## [0.1.0] - Fase 1

Base inicial: CLI + interfaz web multi-tenant (scan, dedup, caché, auth por
sesión), sin este archivo de changelog (añadido en 0.2.0).
