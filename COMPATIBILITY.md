# Compatibilidad

Tabla de compatibilidad por versión de `doc_organize`. Generada a partir del historial real de
`pyproject.toml` (`git log --follow -- pyproject.toml`), no de la memoria/documentación —
`doc_organize` no tiene releases publicados en PyPI ni GitHub Releases todavía (ver
`CHANGELOG.md`): todas las versiones listadas son estados internos del repositorio, no paquetes
instalables desde fuera.

> **Nota (2026-10-31)**: desde la 0.9.3 hay wheel y sdist publicados en GitHub Releases; las versiones
> anteriores siguen siendo estados internos del repositorio.

> **Nota de corrección (2026-09-10)**: esta tabla llevaba desde 0.4.0 sin una fila nueva pese a que
> `pyproject.toml` ya iba por 0.7.0 — 3 versiones de diferencia. Las filas 0.5.0/0.6.0/0.7.0 se han
> reconstruido ahora verificando `git show <commit-de-bump>:pyproject.toml` de cada una (mismas
> cotas que 0.4.0 en los tres casos, sin cambios) al cerrar la 0.8.0.

> **Nota de corrección (2026-11-14)**: faltaban las filas de 0.14.0 a 1.3.0 (7 versiones publicadas) y 0.13.0
> seguía marcada como activa. Se han reconstruido con `git diff <tag-anterior> <tag> -- pyproject.toml` entre
> cada par de tags publicados: las dependencias solo cambian en 0.14.0 (cota de `ruff` en `[dev]`), 1.0.0rc1 (se
> retiran el extra `[web]` y las dependencias de la web de `[dev]`) y 1.4.0 (`zensical`); el resto de cada fila
> resume el CHANGELOG. Las rc de la 1.0.0 no tienen fila propia: la 1.0.0 es idéntica a 1.0.0rc1 en `pyproject.toml`.

| Versión | Python | Dependencias clave | Estado |
|---|---|---|---|
| 1.7.1 | `>=3.12` | Mismas dependencias que 1.7.0; sin cambios de API. El `zensical.toml` generado activa `navigation.prune` (sitio de 2600 documentos: de ~1,9 GB a ~170 MB) | ✅ Activa |
| 1.7.0 | `>=3.12` | Mismas dependencias que 1.6.0; sin migración de `cache.db`. API pública ampliada (`doc_organize.security`: `redact_credentials`, `scan_credentials`, `RedactionResult`, `CredentialFinding`; `ContextBuilder(ai_redact_credentials=)`, `Context.ai_redact_credentials`/`credential_findings` y `DocumentCredentialFindings`, `SiteGenerator.generate(redact_credentials=)`/`SiteResult.credentials_redacted`, `LiteLLMTaxonomyManifestDraftConfig.redact_credentials`). Cambio de comportamiento por defecto: lo que se envía a la IA y lo que publica el sitio sale con las credenciales redactadas | ❌ EOL |
| 1.6.0 | `>=3.12` | Mismas dependencias que 1.5.0; sin migración de `cache.db`. API pública ampliada (`Context.unclassified_details` y `UnclassifiedDocument` con `unclassified.json`, `ContextBuilder(properties_concurrency=, history_policy=)`, `ContextHistoryPolicy`, `CacheOrderBy` con `mime_type`/`created_time`/`owner_name`, filtro `mime_type` y `CacheManager.list_mime_types`) | ❌ EOL |
| 1.5.0 | `>=3.12` | Dependencias de ejecución nuevas: `py3langid>=0.4` (idioma de cada documento del contexto) y `pypdfium2>=4.0` declarada (ya la instalaba Docling); mismos extras que 1.4.0. `cache.db` gana 4 columnas (migración aditiva al abrirse en escritura); API pública ampliada (metadatos de fichero, `ScanOptions.capture_owner`, autor/descripción/palabras clave/idioma y trazabilidad en `DomainDocument`, `DocumentEnrichmentClient`, historial del contexto y `write_context_history_xlsx`) | ❌ EOL |
| 1.4.0 | `>=3.12` | Mismas dependencias de ejecución que 1.3.0; los extras `[site]` y `[docs]` pasan a `zensical>=0.1.1` (límite del índice de búsqueda en posiciones de token, en el que se basa la exclusión de páginas del buscador); API pública ampliada (`SiteResult.search_excluded`, `SiteBuildError.cause`/`output_tail`) | ❌ EOL |
| 1.3.0 | `>=3.12` | Mismas dependencias que 1.2.0; exclusiones en el escaneo (`ScanOptions.exclude_paths`/`ignore_patterns`, `ScanSummary.excluded_cached`) | ❌ EOL |
| 1.2.0 | `>=3.12` | Mismas dependencias que 1.1.1; `CacheManager.load_cache_page(order_by=, descending=)` y `CacheOrderBy` | ❌ EOL |
| 1.1.1 | `>=3.12` | Mismas dependencias que 1.1.0; sin cambios de API (borrado de proyectos y salidas con ficheros de solo lectura en Windows) | ❌ EOL |
| 1.1.0 | `>=3.12` | Mismas dependencias que 1.0.1; escaneos largos, carpetas de red y duplicados desde la caché (`ScanOptions.max_documents`, `document_timeout_s`, `io_retries`…, columna `size_bytes` en `cache.db` con migración aditiva) | ❌ EOL |
| 1.0.1 | `>=3.12` | Mismas dependencias que 1.0.0; sin cambios de API (solo PDF e imágenes requieren OCR) | ❌ EOL |
| 1.0.0 | `>=3.12` | **Incompatible (MAJOR)**. Se retira el extra `[web]` (fastapi, uvicorn, jinja2, python-multipart, cryptography) y esas dependencias de `[dev]`; mismas dependencias de ejecución que 0.14.0. Sin web integrada ni `auth/` (ver doc_organize_web) | ❌ EOL |
| 0.14.0 | `>=3.12` | Mismas dependencias de ejecución que 0.13.0; `[dev]`: `ruff>=0.1.0,<0.18` (antes `<0.16`). Aditiva: límites de la Sub-fase B (`ai_max_failures`, `ai_max_documents`, reintentos en las `*Config` de `doc_organize.ai`), recuentos de IA en `Context`, `resolve_organized_paths`; la web integrada queda obsoleta (se retira en 1.0.0) | ❌ EOL |
| 0.13.0 | `>=3.12` | Mismas dependencias de ejecución que 0.12.1; el extra `[site]` pasa a `zensical>=0.0.71` (sustituye a `mkdocs`: sitio de contexto con `SiteGenerator`); API pública ampliada (rutas del contexto en `ProjectLayout`, plantillas de taxonomía como texto, `SiteBuildError`); `MkDocsGenerator` y `Context.mkdocs_*` obsoletos (se retiran en 1.0.0); la reorganización ya no sigue enlaces simbólicos | ❌ EOL |
| 0.12.1 | `>=3.12` | Mismas dependencias que 0.12.0; parámetro opcional `relative_to` en la resolución de duplicados (ruta relativa en `duplicados/`); la resolución ya no sigue enlaces simbólicos (una ruta que pase por un enlace falla) | ❌ EOL |
| 0.12.0 | `>=3.12` | Mismas dependencias que 0.11.0; API pública ampliada (rutas de salida sin Docling, caché de solo lectura con filtros, carpeta de modelos, `CacheNotFoundError`, `ModelsNotAvailableError`); `source_path` del JSON de cada documento relativo a la carpeta escaneada por defecto | ❌ EOL |
| 0.11.0 | `>=3.12` | Mismas dependencias de ejecución que 0.10.0; nuevo extra `[export]`: `openpyxl>=3.1` (Excel de `doc_organize.export`); API pública ampliada (exportación, `MissingDependencyError`) sin cambios incompatibles | ❌ EOL |
| 0.10.0 | `>=3.12` | Mismas dependencias de ejecución que 0.9.3; extra `[docs]`: `zensical>=0.0.71`, `mkdocstrings-python>=2.0` (sustituye a mkdocs); nuevo extra `[site]`: `mkdocs>=1.4` (sitio del contexto); API pública estable para doc_organize_web | ❌ EOL |
| 0.9.3 | `>=3.12` | Mismas dependencias que 0.9.0; Python mínimo sube a 3.12 (el CI ya no prueba 3.11); primera versión con wheel en GitHub Releases | ❌ EOL |
| 0.9.0 | `>=3.11` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0`, nueva `cryptography>=41.0` (cifrado Fernet de credenciales de IA); `[ai]`: `httpx>=0.24`; `[context]`: `pyyaml>=6.0` | ❌ EOL |
| 0.8.0 | `>=3.11` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0`; nuevos extras `[ai]`: `httpx>=0.24`, `[context]`: `pyyaml>=6.0` | ❌ EOL |
| 0.7.0 | `>=3.11` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0` | ❌ EOL |
| 0.6.0 | `>=3.11` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0` | ❌ EOL |
| 0.5.0 | `>=3.11` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0` | ❌ EOL |
| 0.4.0 | `>=3.11` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0` | ❌ EOL |
| 0.3.0 | `>=3.11` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0` | ❌ EOL |
| 0.2.0 | `>=3.10` → `>=3.11`¹ | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0` | ❌ EOL |
| 0.1.0 | `>=3.10` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0` | ❌ EOL |

¹ El suelo mínimo subió de `>=3.10` a `>=3.11` **dentro** de la propia 0.2.0 (commit `83504cc`,
2026-08-29, antes de que `pyproject.toml` avanzara a 0.3.0) — ver
`.ai/sessions/2026-08-29-python-3-11/TRACEABILITY.md`. La columna refleja el estado final de esa
versión tal como quedó commiteado (`>=3.11`), no su estado inicial.

Las dependencias clave (`docling`, `pydantic`, `aiosqlite`) no han cambiado de cota mínima en
ninguna versión hasta la fecha — la columna se repite igual en la mayoría de filas porque es un
hecho verificado (`git show <commit>:pyproject.toml`), no una omisión. La 0.8.0 fue la primera en
sumar cotas nuevas, vía dos extras opcionales (`ai`, `context`) que no afectan a la instalación
base. La 0.9.0 añade `cryptography>=41.0` al extra `[web]` (cifrado en reposo de credenciales de
IA guardadas desde `/admin/configuracion-ia`) — sigue sin afectar a la instalación base
(`pip install doc_organize` sin extras).

## Cómo mantener esta tabla

Al cerrar una versión (fase VERSION, ver `.github/instructions/sync.instructions.md`):
1. Añadir una fila nueva arriba con la versión que se cierra, marcada `✅ Activa`.
2. Cambiar la fila que era `✅ Activa` a `❌ EOL` (este proyecto no publica releases externos que
   pudieran seguir en uso durante una transición — no hay estado `⚠️ Legacy` real hasta que eso
   cambie).
3. Verificar Python/dependencias clave contra el `pyproject.toml` real de ese commit, no copiar la
   fila anterior sin comprobar — si algo cambió, esta tabla debe reflejarlo exactamente.
