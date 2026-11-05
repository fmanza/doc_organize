# Instrucciones Compartidas: Copilot Chat + Claude Code + Gemini + Codex + Cursor

Configuración unificada para trabajar en `doc_organize` con asistentes de código.
Las reglas de cada plataforma solo deben añadir especialización; esta página es la
fuente común para arquitectura, calidad, pruebas y documentación.

---

## Rol esperado

Actúa como senior de ingeniería Python especializado en:
- Extracción y conversión de documentos: PDF, DOCX, XLSX, PPTX → Markdown/JSON
- Procesamiento de contenido estructurado: metadatos, deduplicación por hash, caché transaccional
- Diseño de librerías modulares con pipeline de procesamiento batch
- Programación asíncrona con `asyncio` para operaciones de IO documento (lectura, conversión)
- Testing determinista con `pytest` sin servicios externos (fixtures de documentos locales)
- Documentación de librerías Python con Zensical

---

## Proyecto: doc_organize (1.0.0, librería pura)

`doc_organize` es una librería Python con CLI para:
- **Escaneo**: identificar y catalogar documentos en carpetas (PDF, DOCX, XLSX, PPTX, imágenes; audio/vídeo con el extra `av`)
- **Conversión**: transformar documentos a Markdown + JSON con Docling, con detección y reprocesado de OCR
- **Deduplicación**: duplicados exactos (SHA-256), conflictos de versión y similitud aproximada de nombre
- **Caché incremental**: SQLite (WAL), para no reconvertir lo que no ha cambiado
- **Proyectos**: registro local (`~/.doc_organize/projects.json`) y rutas de cada proyecto (`ProjectLayout`)
- **Contexto documental**: clasificación por dominios (reglas + IA opcional vía LiteLLM Proxy), reorganización y sitio
  navegable con Zensical
- **Exportación**: ZIP en streaming y Excel de caché y de errores

**No incluye interfaz web ni autenticación** desde 1.0.0 (L-11): eso es
[doc_organize_web](https://github.com/fmanza/doc_organize_web), un proyecto aparte que usa esta librería. No añadas
servidores HTTP, plantillas, usuarios, tenants, roles ni sesiones a la librería: el test
`tests/unit/test_library_architecture.py` falla si `src/` importa FastAPI, Starlette, uvicorn, Jinja2 o
`python-multipart`, o si reaparecen `doc_organize.web` o `doc_organize.auth`. Lo que la web necesite de la librería se
pide como API nueva (parámetros, funciones sin Docling, eventos de progreso), no copiando lógica de la web aquí.

**Versión canónica**: consultar `pyproject.toml` antes de cerrar releases.
**Python**: `>=3.12` según `pyproject.toml`.
**API pública (SemVer)**: los nombres de `doc_organize.__all__`; ver `docs/api/publica.md`.

---

## Arquitectura real (1.0.0)

```text
src/doc_organize/
  __init__.py     # API pública, importada bajo demanda (PEP 562): no carga Docling hasta usarlo
  core/           # Nivel 1: modelos Pydantic, excepciones, constantes, progreso (CancelToken, ProgressEvent)
  utils/          # Nivel 1: hashing, rutas seguras, logging, detectores de GPU/AV/Office, formato de fechas
  validators/     # Nivel 2: FolderValidator, ProjectValidator
  scanner/        # Nivel 2: DocumentScanner
  converter/      # Nivel 2: DocumentConverter (adaptador de Docling), OCRScheduler
  dedup/          # Nivel 2: DeduplicationManager
  cache/          # Nivel 2: CacheManager (SQLite + WAL, también en solo lectura)
  projects/       # Nivel 2: ProjectRegistry, ProjectLayout, ScannedFoldersStore, ProjectHistoryCleaner
  ai/             # Nivel 2: clientes HTTP de IA (LiteLLM Proxy, GitHub Copilot) con su *Config explícita
  context/        # Nivel 3: ContextBuilder, ContextRegistry, Reorganizer, SiteGenerator, plantillas de taxonomía
  scan/           # Nivel 3: ScanCommand (escaneo + caché + conversión, deduplicación bajo demanda)
  export/         # Nivel 3: ZIP y Excel de un proyecto (Excel con el extra `export`)
  main.py         # Nivel 3: CLI (`project`, `scan`, `deduplicate`, `export`)
```

Las dependencias van solo hacia abajo (ver `.github/instructions/architecture.instructions.md`, regla #6). Los
consumidores (el CLI y doc_organize_web) reciben progreso por callbacks o iteradores de eventos (`ScanEvent`,
`DedupEvent`, `ContextBuildEvent`, `ProgressEvent`) y cancelan con `CancelToken`; la librería no sabe si detrás hay un
terminal, un WebSocket o SSE.

### Ejemplo de uso

```python
from doc_organize import ProjectLayout, ProjectRegistry, ScanCommand

async with ProjectRegistry() as registry:
    project = await registry.get_project("Mi Proyecto")
layout = ProjectLayout.for_project(project)
summary = await ScanCommand().run(
    paths=["/ruta/a/documentos"],
    output_dir=layout.conversion_dir,
    cache_db=layout.cache_db,
    folders_json=layout.folders_json,
)
```

---

## Principios de diseño

### Procesamiento de documentos
- Validar rutas de entrada antes de procesar; lanza `InvalidPathError` si no existe o no es legible.
- Soportar múltiples formatos: PDF, DOCX, XLSX, PPTX (vía Docling backend).
- Convertir todos los formatos a Markdown o JSON como destinos canónicos.
- Preservar estructura: párrafos, títulos, listas, tablas, metadatos (título, autor, fecha).
- Excepciones específicas por tipo de error: `DocumentError`, `ConversionError`, `CacheError`.
- Deduplicación por SHA256 hash, no por contenido (más rápido).

### Asincronía y IO
- Usar `asyncio` para operaciones de IO documento (leer, convertir, guardar caché).
- Context managers explícitos: `async with scanner:` → garantizar cierre de recursos.
- Logging de progreso en operaciones masivas.

### SOLID operativo
- **SRP**: cada módulo (`scanner/`, `converter/`, `dedup/`, `cache/`) tiene un responsabilidad única.
- **OCP**: extensión por adaptadores/Strategy (motor de OCR, formato) sin modificar módulos estables.
- **LSP**: interfaces claras entre módulos (los modelos de `core/models.py` como contrato común).
- **ISP**: métodos pequeños y focalizados; evitar clases monolíticas.
- **DIP**: dependencias inyectadas (logger, config) en lugar de estado global.

### OOP y estado
- Mantén estilo basado en clases para servicios (`DocumentScanner`, `DocumentConverter`).
- Funciones a nivel de módulo solo para utilidades: `safe_path_join()`, `hash_file()`.
- Evita estado global mutable; usa instancias de clases.
- Usa `ClassVar` para constantes de clase (`SUPPORTED_FORMATS`, `CACHE_VERSION`).

### Logging
- Las clases con lógica deben tener `self.logger: logging.Logger`.
- En servicios (scanner, converter, cache, dedup), pasa logger como parámetro si es necesario.
- En handlers de error inesperado, usa `exc_info=True`.
- Evita `print()` en la librería; solo permitido en scripts de ejemplo/CLI externos.

### Formato de cadenas
- Usa f-strings para strings con parámetros.
- Evita `.format()`, `%` formatting y concatenación para interpolación.
- Strings estáticos, docstrings y ejemplos sin parámetros están permitidos.

---

## Calidad y pruebas

### Comandos de desarrollo

```bash
python -m ruff check src tests              # lint
python -m ruff format src tests             # format
python -m mypy src                          # type-check
python -m pytest                            # tests
python -m pytest -v -x                      # verbose, stop first failure
python -m build                             # build distribution
zensical serve                              # documentación local
zensical build --strict                     # sitio estático en /site, con validación de enlaces
```

### Estrategia de tests
- Scanner, Converter, Dedup, Cache: tests unitarios con archivos locales (fixtures en `tests/fixtures/`)
- No depender de APIs externas ni descargas reales
- Fixtures en `tests/conftest.py`: documentos mock (PDF vacío, DOCX simple, etc.)
- Tests de integración opcionales en `tests/integration/` marcados con `pytest.mark.integration`
- Cobertura target: ≥80% de líneas ejecutables en módulos core
- Arquitectura: `tests/unit/test_library_architecture.py` (sin frameworks web ni `web/`/`auth/`) y
  `tests/unit/test_ai_architecture.py` deben seguir en verde; no los relajes para que pase un cambio.

### Documentación obligatoria

#### Cuándo es CRÍTICA (bloquea PRs)

- ✅ Nueva clase pública → docstring Google-style + ejemplo
- ✅ Cambio de API pública → actualizar guías en `docs/`
- ✅ Refactor con breaking changes → guía de migración en CHANGELOG.md
- ✅ Antes de cerrar versión → `zensical build --strict` sin errores ni links rotos
- ✅ Cambios en instrucciones IA → sincronizar SHARED_INSTRUCTIONS.md, copilot-instructions.md, CLAUDE.md
- ✅ Nuevo módulo → crear entrada en `docs/functional/` y `docs/api/`
- ✅ Cambio de CLI → actualizar ejemplos en README y `docs/`
- ✅ **Nueva versión (VERSION)** → revisar `.github/instructions/sync.instructions.md`
  para validar que CHANGELOG.md y COMPATIBILITY.md están sincronizados

#### Configuración de documentación — cuándo actualizar

> **Fuente única**: `zensical.toml`. Zensical (`zensical serve` / `zensical build --strict`) es el generador principal.

- ✅ Módulo o clase pública nueva → entrada en `zensical.toml` en el `nav`
- ✅ Página nueva, movida o eliminada en `docs/` → actualizar `zensical.toml`

#### Convención de nombres y estructura en `docs/`

- **Todos los ficheros `.md`** en `docs/` (y subdirectorios) usan nombre **en minúsculas con guiones bajos**: `installation.md`, `quick_start.md`, `troubleshooting.md`.
- **Estructura recomendada v0.1.0**:
  - `docs/index.md` — Landing page
  - `docs/functional/` — Documentación funcional (qué hace cada módulo)
  - `docs/api/` — Documentación técnica/API (cómo funciona internamente)
  - `docs/examples/` — Ejemplos ejecutables
  - `docs/guides/` — Guías (instalación, quick start, solución de problemas)
- **Guías** → siempre en `docs/guides/`, nunca en la raíz de `docs/`
- **Conjunto mínimo obligatorio en `guides/`**: `installation.md` + `quick_start.md` + `troubleshooting.md`
- Sección `Guías:` en `zensical.toml`: `quick_start.md` primero; `troubleshooting.md` en subsección "Errores y Diagnóstico"

### 📦 Distribución de documentación offline

**Util_bbdd** ofrece 3 características integradas para distribución documentación:

1. **Página de descargas** (`docs/downloads.md`)
   - URL pública: https://fmanza.github.io/doc_organize/downloads/
   - Tabla de versiones descargables
   - Instrucciones SHA256 por plataforma (Linux, Windows, Mac)
   - FAQ y changelog

2. **SHA256 Checksums** (`scripts/build_docs_zip.py`)
   - Genera `.sha256` file con hash del ZIP
   - Append histórico en `CHECKSUMS.txt`
   - Validación: `sha256sum -c dist/*.sha256` (Linux/Mac) o PowerShell (Windows)

3. **Auto-publish en GitHub Releases** (`.github/workflows/docs-zip-release.yml`)
   - Trigger automático: push a `main`/`develop` + cambios en `docs/`
   - Release con tag `docs-vX.X.X`
   - Artifacts: ZIP, .sha256, CHECKSUMS.txt
   - Body: versionado, fecha, instrucciones, SHA256

**Comandos locales**:
```bash
zensical build --strict && python scripts/build_docs_zip.py    # Build + ZIP
python scripts/build_docs_zip.py --no-build                  # ZIP sin build
sha256sum -c dist/*.sha256                                    # Validar checksums
```

**Bootstrap para otros proyectos**:
- Ver `.github/prompts/bootstrap_ai_config.prompt.md`
- Sección: "📦 Descarga de Documentación Offline (Capa B)"
- Matriz de equivalencias: Python + Zensical, Node.js + Docusaurus, Go + Hugo, Java + Sphinx
- ✅ Reorganización funcional/técnica/ejemplos → validar que `nav` mantiene apartados separados
- ✅ Ejecutar `zensical serve` localmente antes de publicar
- ✅ Verificar que `zensical build --strict` pase sin warnings ni links rotos

#### Estándar de generación documental

- Usa Zensical con Zensical como salida estática de referencia (`zensical build --strict`,
  ver `.github/instructions/sync.instructions.md`). No `zensical`: se evaluó como alternativa más
  rápida y se descartó — no es una dependencia instalada en este proyecto (ver `.ai/DECISIONS_LOG.md`).
- Usa Mermaid.js para diagramas de flujo, secuencia o clases cuando aporte claridad.
- Unifica creación y actualización: busca primero documentación existente y actualízala si es el punto de entrada correcto.
- Para documentación de proyecto completo, revisa README, `docs/`, `docs/examples/`, docstrings públicos, prompts/agentes IA y `zensical.toml`.
- Separa claramente documentación funcional, técnica y ejemplos.
- No inventes capacidades, módulos, APIs, salidas, reglas ni dependencias. Si falta información, márcala como pendiente de verificación.
- No uses ejemplos heredados de otros repositorios: valida nombres de proyecto, rutas, clases y tests contra el árbol real antes de documentarlos.
- No uses un único prompt masivo; divide en mapeo funcional, técnica, ejemplos, Mermaid y revisión final.
- Excluye por el momento generación de documentación mediante APIs externas.

#### Estándar: Docstrings Google-style

```python
class CacheManager:
    """Caché transaccional (SQLite + WAL) de hashes de documentos (REQ-006).

    Clasifica cada documento como nuevo, modificado o sin cambios frente a
    la última pasada, delegando siempre el hashing en `utils.hash_utils`.

    Attributes:
        db_path (Path): Ruta al archivo SQLite de caché.
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> async with CacheManager("./cache.db") as cache:
        ...     entries = await cache.load_cache()
    """
```

#### Estándar: Validación de Markdown en documentación

**Problemas comunes (registrados 2026-06-06)**:

1. **Listas renderizadas como párrafos**: Usar dos espacios al final de línea EN LUGAR DE crear lista HTML real
   - ❌ Incorrecto: `✅ **Item 1**  \n✅ **Item 2**` → Renderiza con `<br />` horizontales
   - ✅ Correcto: `- ✅ **Item 1**\n- ✅ **Item 2**` → Renderiza como `<ul><li>`

2. **Enlaces rotos a archivos estáticos generados**: Usar placeholders tipo `#` en lugar de rutas relativas
   - ❌ Incorrecto: `[archivo.zip](#)` → No descarga nada
   - ✅ Correcto: `[archivo.zip](../archivo.zip)` → Descarga desde `site/`

3. **Archivos generados por plugins**: Entender que ZIP, PDFs y otros artefactos se crean en `site/` durante `zensical build --strict`
   - Plugin: `src/doc_organize/docs_build_plugin.py` → genera `site/doc_organize.zip`
   - Links desde subpáginas (ej. `site/downloads/index.html`): usar `../doc_organize.zip`

**Validación pre-commit**:
```bash
# Build con --strict (sin errores de markdown)
python -m zensical build --strict

# Verificar visualmente que listas son verticales, no horizontales
# Revisar site/downloads/index.html: deben haber <ul><li>, no <p><br /></p>
```

### Formato de commits

Usa [Conventional Commits](https://www.conventionalcommits.org/):

```
feat:     nueva funcionalidad (dentro de scope, no refactor)
fix:      corrección de bug (hotfix, RCA → fix mínimo)
refactor: cambio sin impacto funcional
test:     solo tests, sin cambios de funcionalidad
docs:     solo documentación (README, docstrings, guías)
chore:    mantenimiento (deps, config, herramientas)
```

**Ejemplo**:
```
feat: filtros por ruta relativa en CacheManager (L-10e)

- Añade relative_to= y conversion_status= a count_entries/load_cache_page
- Tests en tests/unit/test_cache_manager.py
- Actualiza docs/api/cache.md y docs/api/publica.md
```

### Ramas y publicación

- PR a `develop` fusionado con **squash**: un commit por PR, con el título del PR en Conventional Commits. La rama se
  borra al fusionar.
- La suite (`tests.yml`) corre en cada PR y una vez en el commit resultante de `develop`; no en ramas sueltas ni en
  `main`.
- Release: el commit `release: vX.Y.Z` llega a `develop` por PR. Con su CI en verde, `main` avanza por
  **fast-forward** a ese commit y el tag se crea sobre él; `release.yml` publica wheel y sdist. Sin PR de `develop` a
  `main` ni commits de merge:

  ```bash
  git switch develop && git pull
  sha=$(git rev-parse HEAD)
  gh run list --branch develop --commit "$sha" --workflow CI   # completed / success
  git push origin "$sha:main"                                  # el ruleset lo rechaza sin CI verde
  git tag -a vX.Y.Z -m "vX.Y.Z" "$sha" && git push origin vX.Y.Z
  ```

- Rulesets: CI en verde en `main` y `develop` (6 jobs `test` y `package`, rama al día, sin force-push ni borrado) sin
  excepciones; PR obligatorio en `develop` sin excepciones y en `main` con excepción solo para administradores (el
  fast-forward).

---

## Flujo de trabajo

Para cambios no triviales:

```text
PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION
```

Para auditorías o PR reviews, prioriza hallazgos verificables:
- bug o regresión;
- contrato público roto;
- prueba faltante en comportamiento modificado;
- documentación obsoleta que pueda inducir uso incorrecto.

No mezcles feature, hotfix y refactor salvo que el usuario lo pida explícitamente.
Si detectas instrucciones heredadas de otro proyecto, corrígelas o márcalas como
deuda técnica con ruta exacta.

### Directrices para Futuras IAs — sección obligatoria en VERSION

Cuando cierres una sesión (fase VERSION o `/version-closure`), puebla la sección
`## Directrices para Futuras IAs` del `TRACEABILITY.md` de la sesión con los hechos
descubiertos que una IA futura necesitaría para no repetir análisis:

- Puntos canónicos (módulo/archivo) que centralizan una responsabilidad.
- Decisiones de diseño tomadas y su justificación breve.
- Patrones con nombre (alias P-A, re-exportadores, etc.) establecidos en la sesión.
- Lecciones aprendidas de herramientas o técnicas (p.ej. cobertura de `oldString`).

Usar formato: `**[área]**: <hecho verificable>`. El template está en
`.ai/sessions/TEMPLATE/TRACEABILITY.md`.

---

## Gobernanza de plataformas IA

| Archivo | Plataforma | Propósito |
|---|---|---|
| `.github/SHARED_INSTRUCTIONS.md` | Copilot, Claude, Gemini, Codex, Cursor | Fuente canónica: arquitectura, calidad, comandos |
| `GEMINI.md` | Gemini Code Assist | Especialización: estándares de código y comandos rápidos |
| `.github/copilot-instructions.md` | GitHub Copilot Chat | Especialización: agentes VS Code, reglas Copilot |
| `CLAUDE.md` | Claude Code | Especialización: slash commands, hooks, settings.json |
| `.github/AGENTS.md` | Copilot/Claude | Registro de agentes especializados |
| `.github/prompts/bootstrap_ai_config.prompt.md` | Todas | Trasladar esta configuración IA a otro proyecto (modelo PULL) |
| `.cursorrules` | Cursor | Especialización: estándar de documentación/ejemplos |
| `.ai/*.md` | Todas | Contexto persistente: producto, arquitectura |
| `.ai/sessions/TEMPLATE/` | Todas | Plantilla canónica de artefactos de sesión |

**Regla de oro**: Edita SHARED_INSTRUCTIONS.md primero. Luego sincroniza solo las
especializaciones afectadas (copilot-instructions.md y/o CLAUDE.md).

---

*Actualizado: 2026-08-30*
