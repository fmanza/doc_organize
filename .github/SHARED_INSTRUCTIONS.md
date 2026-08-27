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
- Documentación de librerías Python con MkDocs Material

---

## Proyecto: doc_organize (v0.1.0 Alpha)

`doc_organize` es una librería Python (en fase Alpha temprana) para:
- **Escaneo**: identificar y catalogar documentos en carpetas (PDF, DOCX, XLSX, PPTX)
- **Conversión**: transformar documentos a Markdown/JSON preservando estructura (párrafos, títulos, listas, tablas)
- **Deduplicación**: eliminar archivos duplicados por hash SHA256
- **Caché transaccional**: almacenamiento eficiente con respaldo a BD local
- **Organización en pipelines**: composición modular de operaciones (scan → convert → dedup → cache)

**Versión canónica**: consultar `pyproject.toml` antes de cerrar releases.
**Python**: `>=3.10` según `pyproject.toml`.

### Capacidades principales (v0.1.0 MVP)

- **Scanner**: escaneo recursivo de carpetas con identificación de tipos de archivo
- **Converter**: conversión de formatos documento → Markdown/JSON (con Docling backend)
- **Metadata**: extracción de metadatos (nombre, tamaño, hash, tipo, marcas de tiempo)
- **Deduplicator**: identificación y eliminación de documentos duplicados por hash
- **Cache**: almacenamiento eficiente con transaccionalidad
- **Workflow orchestration**: pipeline composable de operaciones batch

---

## Arquitectura real (v0.1.0)

### Módulos implementados

```text
src/doc_organize/
  __init__.py           # API pública (en desarrollo)
  core/
    __init__.py         # Tipos base, excepciones (VACÍO — TODO v0.1.0)
  utils/
    __init__.py         # Utilidades comunes (VACÍO — TODO v0.1.0)
```

### Módulos planeados (v0.1.0+)

```text
src/doc_organize/
  scanner/              # DocumentScanner: escaneo recursivo, identificación tipos [TODO v0.1.0]
  converter/            # DocumentConverter: formato → Markdown/JSON con Docling [TODO v0.1.0]
  cache/                # CacheManager: almacenamiento eficiente con transacciones [TODO v0.1.0]
  dedup/                # DeduplicatorService: hash SHA256, identificación duplicados [TODO v0.1.0]
  workflow/             # PipelineOrchestrator: composición de operaciones batch [TODO v0.2.0]
  web/                  # FastAPI webapp con UI para gestión [TODO v0.2.0]
```

### Responsabilidades por módulo (v0.1.0+)

| Módulo | Responsabilidad | Estado |
|---|---|---|
| `core/` | Tipos base: `Document`, `DocumentMetadata`, `Conversion`, excepciones | TODO v0.1.0 |
| `utils/` | Logging, config, helpers comunes (`safe_path_join`, `validate_format`) | TODO v0.1.0 |
| `scanner/` | Escaneo recursivo, identificación de tipo de archivo, catalogación | TODO v0.1.0 |
| `converter/` | Conversión de formato (PDF, DOCX, XLSX, PPTX → Markdown/JSON) vía Docling | TODO v0.1.0 |
| `cache/` | Almacenamiento eficiente con transacciones locales (SQLite) | TODO v0.1.0 |
| `dedup/` | Deduplicación por hash SHA256, identificación de duplicados | TODO v0.1.0 |
| `workflow/` | Orquestación de pipelines batch, composición de operaciones | TODO v0.2.0 |
| `web/` | Web UI con FastAPI para gestión de documentos | TODO v0.2.0 |

### API pública recomendada (v0.1.0 MVP)

```python
from doc_organize.scanner import DocumentScanner
from doc_organize.converter import DocumentConverter
from doc_organize.cache import CacheManager
from doc_organize.dedup import DeduplicatorService

# Ejemplo: escanear documentos
scanner = DocumentScanner("/path/to/documents")
docs = scanner.scan()  # → [Document, ...]

# Ejemplo: convertir a Markdown
converter = DocumentConverter()
for doc in docs:
    markdown = converter.convert(doc, output_format="markdown")
    print(markdown)

# Ejemplo: deduplicar
dedup = DeduplicatorService()
unique_docs = dedup.deduplicate(docs)  # por SHA256 hash
```

---

## Principios de diseño

### Procesamiento de documentos (v0.1.0)
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
- **OCP**: extensión vía plugins sin modificar módulos core (futuro v0.2.0).
- **LSP**: interfaces claras entre módulos (ej. `Document` como contrato común).
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
mkdocs serve                                # documentación local
mkdocs build                                # genera sitio estático en /site
mkdocs build --strict                       # build con validación de links
```

### Estrategia de tests
- Scanner, Converter, Dedup, Cache: tests unitarios con archivos locales (fixtures en `tests/fixtures/`)
- No depender de APIs externas ni descargas reales
- Fixtures en `tests/conftest.py`: documentos mock (PDF vacío, DOCX simple, etc.)
- Tests de integración opcionales en `tests/integration/` marcados con `pytest.mark.integration`
- Cobertura target: ≥80% de líneas ejecutables en módulos core

### Documentación obligatoria

#### Cuándo es CRÍTICA (bloquea PRs)

- ✅ Nueva clase pública → docstring Google-style + ejemplo
- ✅ Cambio de API pública → actualizar guías en `docs/`
- ✅ Refactor con breaking changes → guía de migración en CHANGELOG.md
- ✅ Antes de cerrar versión → `mkdocs build --strict` sin errores ni links rotos
- ✅ Cambios en instrucciones IA → sincronizar SHARED_INSTRUCTIONS.md, copilot-instructions.md, CLAUDE.md
- ✅ Nuevo módulo → crear entrada en `docs/functional/` y `docs/api/`
- ✅ Cambio de CLI → actualizar ejemplos en README y `docs/`
- ✅ **Nueva versión (VERSION)** → revisar `.github/instructions/sync.instructions.md`
  para validar que CHANGELOG.md y COMPATIBILITY.md están sincronizados

#### Configuración de documentación — cuándo actualizar

> **Fuente única**: `mkdocs.yml`. MkDocs Material (`mkdocs serve` / `mkdocs build`) es el generador principal.

- ✅ Módulo o clase pública nueva → entrada en `mkdocs.yml` bajo `nav:`
- ✅ Página nueva, movida o eliminada en `docs/` → actualizar `mkdocs.yml`

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
- Sección `Guías:` en `mkdocs.yml`: `quick_start.md` primero; `troubleshooting.md` en subsección "Errores y Diagnóstico"

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
zensical build && python scripts/build_docs_zip.py    # Build + ZIP
python scripts/build_docs_zip.py --no-build           # ZIP sin build
sha256sum -c dist/*.sha256                             # Validar checksums
```

**Bootstrap para otros proyectos**:
- Ver `.github/prompts/bootstrap_ai_config.prompt.md`
- Sección: "📦 Descarga de Documentación Offline (Capa B)"
- Matriz de equivalencias: Python + MkDocs, Node.js + Docusaurus, Go + Hugo, Java + Sphinx
- ✅ Reorganización funcional/técnica/ejemplos → validar que `nav:` mantiene apartados separados
- ✅ Ejecutar `zensical serve` (o `mkdocs serve`) localmente antes de publicar
- ✅ Verificar que `zensical build` (o `mkdocs build`) pase sin warnings

#### Estándar de generación documental

- Usa Zensical (o MkDocs con Material for MkDocs, recíprocamente compatibles) como salida estática de referencia.
- Usa Mermaid.js para diagramas de flujo, secuencia o clases cuando aporte claridad.
- Unifica creación y actualización: busca primero documentación existente y actualízala si es el punto de entrada correcto.
- Para documentación de proyecto completo, revisa README, `docs/`, `docs/examples/`, docstrings públicos, prompts/agentes IA y `mkdocs.yml`.
- Separa claramente documentación funcional, técnica y ejemplos.
- No inventes capacidades, módulos, APIs, salidas, reglas ni dependencias. Si falta información, márcala como pendiente de verificación.
- No uses ejemplos heredados de otros repositorios: valida nombres de proyecto, rutas, clases y tests contra el árbol real antes de documentarlos.
- No uses un único prompt masivo; divide en mapeo funcional, técnica, ejemplos, Mermaid y revisión final.
- Excluye por el momento generación de documentación mediante APIs externas.

#### Estándar: Docstrings Google-style

```python
class SyncDatabaseManager:
    """Manager sincrónico para operaciones de base de datos.

    Gestiona conexión (directa o pooled), introspección de esquemas y
    ejecución de queries para los motores soportados.

    Attributes:
        db_type (str): Tipo de motor declarado en la instancia.
        conn_params (dict): Parámetros de conexión normalizados.

    Example:
        >>> manager = SyncDatabaseManager(
        ...     db_type="postgresql",
        ...     conn_params={"host": "localhost", "database": "mydb", ...}
        ... )
        >>> tables = manager.get_tables()
        >>> manager.close()
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

3. **Archivos generados por plugins**: Entender que ZIP, PDFs y otros artefactos se crean en `site/` durante `mkdocs build`
   - Plugin: `src/doc_organize/docs_build_plugin.py` → genera `site/doc_organize.zip`
   - Links desde subpáginas (ej. `site/downloads/index.html`): usar `../doc_organize.zip`

**Validación pre-commit**:
```bash
# Build con --strict (sin errores de markdown)
python -m mkdocs build --strict

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
feat: añadir soporte para exportación Parquet en bulk/

- Añade bulk_export_to_parquet() en bulk/crud.py
- Tests en tests/unit/bulk/test_export_parquet.py
- Actualiza docstring y ejemplos en docs/api/bulk.md
```

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

*Actualizado: 2026-06-05*
