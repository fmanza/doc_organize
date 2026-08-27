# DOCUMENTATION AUDIT — doc_organize

*Auditoría de documentación ejecutada: 2026-08-27*
*Alcance: doc_organize (librería Python existente)*

---

## PLAN

### Alcance de la revisión

**Proyecto**: `doc_organize` (librería Python para extracción y organización de documentos)  
**Versión**: 0.1.0 (Alpha)  
**Scope**: Completo

#### Fuentes consultadas

1. ✅ `README.md` — 65 líneas, descripción y comandos básicos
2. ✅ `docs/` — 3 carpetas: `api/` (vacía), `examples/` (vacía), `index.md` (50 líneas)
3. ✅ `mkdocs.yml` — Configuración Material 9.0+, 11 referencias a ejemplos
4. ✅ `pyproject.toml` — Metadatos, dependencias, configuración setuptools
5. ✅ `src/doc_organize/` — 3 módulos públicos: `__init__.py`, `core/`, `utils/`
6. ✅ `.github/prompts/` — 20 prompts de documentación incluyendo `documentation_review.prompt.md`
7. ✅ `.github/agents/` — 11 agentes disponibles (incluyendo documentation-reviewer)
8. ✅ `.github/instructions/` — Instrucciones compartidas y especializadas
9. ❌ `CHANGELOG.md` — Archivo no existe
10. ❌ `COMPATIBILITY.md` — Archivo no existe

#### Criterio de priorización

**Nivel 1 (Crítico)** > Nivel 2 (Alto) > Nivel 3 (Recomendado)

---

## AUDIT_PLAN

### Riesgos identificados antes de la revisión

| Riesgo | Probabilidad | Impacto | Nota |
|--------|---|---|---|
| **Divergencia spec ↔ código** | 🔴 Alta | 🔴 Alto | `.ai/product.md` describe 7 módulos pero código tiene solo 3 archivos vacíos |
| **Ejemplos rotos en nav** | 🔴 Alta | 🔴 Alto | `mkdocs.yml` referencia 7 archivos de ejemplos; carpeta vacía |
| **Inventar capacidades en prompts** | 🟠 Media | 🔴 Alto | 20 prompts de doc en `.github/prompts/` — riesgo de generar docs de features inexistentes |
| **APIs sin docstrings** | 🔴 Alta | 🔴 Alto | Módulos públicos tienen solo docstring mínimo o vacío |
| **Cobertura insuficiente de mkdocs** | 🔴 Alta | 🟡 Medio | `docs/api/` vacía pero `mkdocs.yml` espera `api/index.md` |
| **Desactualización de descripción** | 🟠 Media | 🟡 Medio | README y `pyproject.toml` copian descripción genérica sin validar código |

### Veredicto

**`GO_CONDICIONAL`** ✅ Proceder con auditoría detallada

**Condiciones**:
- Aceptar estado Alpha 0.1.0 como válido (proyecto incipiente)
- Reportar divorcio spec↔código como hallazgo crítico
- Separar hallazgos de **doc faltante** vs. **doc inventada**

---

## AUDIT_CODE

### README y puntos de entrada

#### Estado actual

| Archivo | Líneas | Estado | Hallazgos |
|---------|--------|--------|-----------|
| `README.md` | 65 | ⚠️ Incompleto | Descripción demasiado genérica; no explica propósito real |
| `docs/index.md` | ~50 | ⚠️ Minimal | Copia de README con instrucción vacía `from doc_organize import ...` |
| `pyproject.toml` | 43 | ✅ Presente | Metadata correcta; descripción coherente con README |

#### Hallazgo Nivel 1️⃣: README sin claridad de valor

**Ubicación**: [README.md](README.md#L1-L10)

**Problema**:
```markdown
# doc_organize
> Sistema de extracción de contenido de documentos en Markdown y JSON documentación y organización.
```

**Deficiencias**:
- ❌ Descripción abstracta (¿qué son "documentos"? ¿de dónde?)
- ❌ Sin casos de uso concretos
- ❌ Sin ejemplos que muestren valor
- ❌ Prompt de uso incompleto: `from doc_organize import ...`
- ❌ Sin quick start ejecutable

**Formato sugerido**:

```markdown
# doc_organize

Librería Python para **extraer, organizar y convertir documentos** (PDF, DOCX, XLSX, PPTX, imágenes) 
a formatos estructurados (Markdown, JSON).

## 🎯 Casos de uso

- Indexar documentos para búsqueda o RAG
- Extraer texto con preservación de estructura
- Deduplicar archivos por hash
- Organizar documentos en flujos de procesamiento batch

## ⚡ Quick start

```python
from doc_organize.scanner import DocumentScanner
from doc_organize.converter import DocumentConverter

# Escanear documentos
scanner = DocumentScanner(root_folder="/docs", hash_algorithm="sha3_256")
docs = scanner.scan()

# Convertir a Markdown
converter = DocumentConverter()
for doc in docs:
    markdown = converter.to_markdown(doc)
```
```

---

### Documentación funcional (`docs/functional/`)

#### Estado actual

| Módulo | Existe | Ubicación | Contenido |
|--------|--------|-----------|-----------|
| scanner | ❌ No | `docs/functional/scanner.md` (propuesto) | - |
| converter | ❌ No | `docs/functional/converter.md` (propuesto) | - |
| cache | ❌ No | `docs/functional/cache.md` (propuesto) | - |
| dedup | ❌ No | `docs/functional/dedup.md` (propuesto) | - |
| core | ❌ No | `docs/functional/core.md` (propuesto) | - |
| utils | ❌ No | `docs/functional/utils.md` (propuesto) | - |

#### Hallazgo Nivel 1️⃣: Documentación funcional completamente ausente

**Ubicación**: `docs/functional/` (directorio no existe)

**Problema**:
- ❌ Ningún módulo tiene documentación funcional
- ❌ Falta explicación del flujo "¿qué es y por qué?"
- ❌ Sin descripción de reglas de negocio
- ❌ Sin matriz de precondiciones/postcondiciones

**Acción requerida**:
1. Crear carpeta `docs/functional/`
2. Generar 6 documentos funcionales (uno por módulo principal):
   - `docs/functional/scanner.md` — Cómo se escanean documentos
   - `docs/functional/converter.md` — Cómo se convierten formatos
   - `docs/functional/cache.md` — Estrategia de caché
   - `docs/functional/dedup.md` — Deduplicación de archivos
   - `docs/functional/core.md` — Tipos y excepciones base
   - `docs/functional/utils.md` — Utilidades comunes
3. Cada documento debe aplicar arquitectetipo de `functional_doc.prompt.md`:
   - Descripción breve
   - Reglas de negocio
   - Casos de uso
   - Criterios de aceptación
   - Glosario

---

### Documentación técnica (`docs/api/`)

#### Estado actual

| Archivo | Existe | Líneas | Tipo |
|---------|--------|--------|------|
| `docs/api/index.md` | ❌ No | 0 | - |
| `docs/api/scanner.md` | ❌ No | 0 | - |
| `docs/api/converter.md` | ❌ No | 0 | - |
| `docs/api/cache.md` | ❌ No | 0 | - |

#### Hallazgo Nivel 1️⃣: Documentación técnica completamente ausente

**Ubicación**: `docs/api/` (carpeta existe pero vacía)

**Problema**:
- ❌ Carpeta referenciada en `mkdocs.yml` bajo `nav: > API: > Referencia: api/index.md`
- ❌ Sin contratos de API
- ❌ Sin Mermaid de arquitectura
- ❌ Sin ejemplos técnicos

**Acción requerida**:
1. Crear `docs/api/index.md` — Entrada a documentación técnica
2. Generar ficheros técnicos usando `technical_doc.prompt.md`:
   - `docs/api/scanner.md` — Responsabilidad, interfaz pública
   - `docs/api/converter.md` — Responsabilidad, transformaciones soportadas
   - `docs/api/cache.md` — Contrato de caché, invalidación
   - `docs/api/dedup.md` — Algoritmos de deduplicación
3. Cada documento debe incluir:
   - Responsabilidad del módulo (1 párrafo)
   - Diagrama Mermaid (arquitectura | flujo)
   - API pública (clases, funciones, signatures)
   - Contratos (parámetros, returns, excepciones)
   - Ejemplos relacionados ↔ `docs/examples/`

---

### Ejemplos (`docs/examples/`)

#### Estado actual

| Archivo | Existe | Estado |
|---------|--------|--------|
| `example_cli_usage.md` | ❌ No | **Referenciado en nav, NO EXISTE** |
| `example_ci_cd_integration.md` | ❌ No | **Referenciado en nav, NO EXISTE** |
| `ai_primer_pasos_proyecto_nuevo.md` | ❌ No | **Referenciado en nav, NO EXISTE** |
| `claude_code_usage_complete_example.md` | ❌ No | **Referenciado en nav, NO EXISTE** |
| `github_usage_complete_example.md` | ❌ No | **Referenciado en nav, NO EXISTE** |
| `codex_usage_complete_example.md` | ❌ No | **Referenciado en nav, NO EXISTE** |

#### Hallazgo Nivel 1️⃣: Carpeta vacía con 6 referencias rotas en navegación

**Ubicación**: `docs/examples/` (vacía) ← `mkdocs.yml` (nav referencia 7 archivos)

**Problema**:
- ❌ `mkdocs build` fallará con warnings de links rotos
- ❌ Usuarios no pueden encontrar ejemplos de uso
- ❌ Sin ejemplos verificables (correctness desconocida)

**Acción requerida (Nivel 1 — Bloqueante)**:

Opción A — Eliminar referencias falsas de nav:
```yaml
# En mkdocs.yml, reemplazar
nav:
  - Inicio: index.md
  # Ejemplos: [BACKLOG]
```

Opción B — Crear ejemplos reales (6 archivos):
```
docs/examples/
├── 01_basic_scan.md         (Escanear carpeta simple)
├── 02_convert_to_markdown.md (Convertir PDF → MD)
├── 03_deduplication.md      (Detectar duplicados)
├── 04_cli_batch.md          (Batch CLI)
├── 05_cache_strategy.md     (Configurar caché)
└── 06_error_handling.md     (Manejo de errores)
```

**Recomendación**: Opción A ahora + Opción B en v0.2.0 (backlog Nivel 3)

---

### MkDocs y navegación

#### Estado actual del `mkdocs.yml`

```yaml
nav:
  - Inicio: index.md
  - Ejemplos:
      - CLI y CI/CD:
          - CLI: examples/example_cli_usage.md              ❌ NO EXISTE
          - CI/CD Integration: examples/example_ci_cd_integration.md  ❌ NO EXISTE
      - Herramientas de IA:
          - Primeros pasos con IA: examples/ai_primer_pasos_proyecto_nuevo.md  ❌ NO EXISTE
          - Claude Code: examples/claude_code_usage_complete_example.md  ❌ NO EXISTE
          - Copilot Chat: examples/github_usage_complete_example.md  ❌ NO EXISTE
          - Codex: examples/codex_usage_complete_example.md  ❌ NO EXISTE
  - API:
      - Referencia: api/index.md  ❌ NO EXISTE
```

#### Hallazgo Nivel 1️⃣: Navegación de mkdocs referencia páginas inexistentes

**Severidad**: Bloqueante — `mkdocs build --strict` fallará

**Impacto**:
- ❌ No se puede buildear la documentación
- ❌ GitHub Pages deployment no funcionará
- ❌ Usuarios no pueden acceder a docs online

**Hallazgos específicos**:

| Sección | Recurso | Existe | Acción |
|---------|---------|--------|--------|
| Inicio | `index.md` | ✅ Sí | Mantener |
| Ejemplos (CLI) | `example_cli_usage.md` | ❌ No | ▪️ Crear O ▪️ Remover de nav |
| Ejemplos (CI/CD) | `example_ci_cd_integration.md` | ❌ No | ▪️ Crear O ▪️ Remover de nav |
| Ejemplos (IA) | `ai_primer_pasos_proyecto_nuevo.md` | ❌ No | ▪️ Crear O ▪️ Remover de nav |
| Ejemplos (Claude) | `claude_code_usage_complete_example.md` | ❌ No | ▪️ Crear O ▪️ Remover de nav |
| Ejemplos (Copilot) | `github_usage_complete_example.md` | ❌ No | ▪️ Crear O ▪️ Remover de nav |
| Ejemplos (Codex) | `codex_usage_complete_example.md` | ❌ No | ▪️ Crear O ▪️ Remover de nav |
| API Ref | `api/index.md` | ❌ No | ▪️ Crear O ▪️ Remover de nav |

#### Hallazgo Nivel 1️⃣: Ausencia de estructura funcional/técnica en documentación

**Ubicación**: `mkdocs.yml` secciones faltantes

**Problema**:
- ❌ No hay sección "Conceptos" o "Funcional"
- ❌ No hay sección "Técnica" o "Arquitectura"
- ❌ No hay sección "Troubleshooting"
- ❌ Estructura no sigue arquetipo de documentación

**Propuesta de restructuración**:

```yaml
nav:
  - Inicio: index.md
  - Guías:
      - Instalación: guides/installation.md
      - Quick Start: guides/quick_start.md
      - Troubleshooting: guides/troubleshooting.md
  - Funcional:
      - Scanner: functional/scanner.md
      - Converter: functional/converter.md
      - Cache: functional/cache.md
      - Dedup: functional/dedup.md
  - Técnica:
      - Arquitectura: api/architecture.md
      - Scanner: api/scanner.md
      - Converter: api/converter.md
      - Cache: api/cache.md
      - Dedup: api/dedup.md
  - Ejemplos:
      - Escanear documentos: examples/01_basic_scan.md
      - Convertir a Markdown: examples/02_convert_to_markdown.md
      - Deduplicación: examples/03_deduplication.md
      - CLI Batch: examples/04_cli_batch.md
```

---

### Docstrings y type hints

#### Cobertura en módulos públicos

| Módulo | Docstring | Type Hints | Parámetros | Returns | Excepciones |
|--------|-----------|-----------|-----------|---------|-------------|
| `src/doc_organize/__init__.py` | ✅ 1 línea | ❌ No | N/A | N/A | ❌ No |
| `src/doc_organize/core/__init__.py` | ❌ Vacío | ❌ No | N/A | N/A | ❌ No |
| `src/doc_organize/utils/__init__.py` | ❌ Vacío | ❌ No | N/A | N/A | ❌ No |

#### Hallazgo Nivel 1️⃣: Módulos públicos sin docstrings completos

**Ubicación**: `src/doc_organize/` (todos los módulos públicos)

**Problema**:
```python
# src/doc_organize/__init__.py
"""
Sistema de extracción de contenido de documentos en Markdown y JSON documentación y organización.
"""
__version__ = "0.1.0"

# src/doc_organize/core/__init__.py
# ← VACÍO, sin docstring

# src/doc_organize/utils/__init__.py
# ← VACÍO, sin docstring
```

**Deficiencias**:
- ❌ Sin documentación de qué exporta cada módulo
- ❌ Sin type hints en funciones/clases
- ❌ Sin ejemplos de uso en docstrings
- ❌ Sin documentación de excepciones

**Acción requerida (Nivel 1)**:

1. **Actualizar `src/doc_organize/__init__.py`**:
```python
"""Sistema de extracción, conversión y organización de documentos.

Este módulo proporciona una API simple para:
- Escanear carpetas de documentos
- Convertir PDF, DOCX, XLSX, PPTX a Markdown/JSON
- Deduplicar archivos por hash
- Caché transaccional con respaldo

Example:
    >>> from doc_organize.scanner import DocumentScanner
    >>> scanner = DocumentScanner("/path/to/docs")
    >>> docs = scanner.scan()
    >>> len(docs)
    42
"""

__version__ = "0.1.0"

# Exportar clases/funciones principales
from .scanner import DocumentScanner
from .converter import DocumentConverter
from .cache import CacheManager

__all__ = ["DocumentScanner", "DocumentConverter", "CacheManager"]
```

2. **Actualizar `src/doc_organize/core/__init__.py`**:
```python
"""Tipos, modelos y excepciones base de doc_organize.

Classes:
    DocumentMetadata: Metadatos de un documento (ruta, hash, tamaño)
    CacheEntry: Entrada en caché transaccional
    DocumentState: Estado del documento en pipeline
    
Exceptions:
    DocumentError: Error base en procesamiento de documentos
    InvalidDocumentError: Documento inválido o corrupto
    CacheError: Error en operaciones de caché
"""

from .models import DocumentMetadata, CacheEntry, DocumentState
from .exceptions import DocumentError, InvalidDocumentError, CacheError

__all__ = [
    "DocumentMetadata",
    "CacheEntry", 
    "DocumentState",
    "DocumentError",
    "InvalidDocumentError",
    "CacheError",
]
```

3. **Crear/actualizar `src/doc_organize/utils/__init__.py`**:
```python
"""Utilidades comunes (logging, configuración, helpers).

Modules:
    config: Carga y validación de configuración
    logging_setup: Configuración de logging
    file_utils: Operaciones de archivo
"""

from .config import load_config
from .file_utils import safe_path_join

__all__ = ["load_config", "safe_path_join"]
```

---

### Instrucciones IA divergentes del código real

#### Hallazgo Nivel 1️⃣: CRÍTICO — Divergencia extrema entre SHARED_INSTRUCTIONS.md y codebase

**Ubicación**: `.github/SHARED_INSTRUCTIONS.md` vs. `src/doc_organize/` (código real)

**Severidad**: 🔴 **BLOQUEANTE** — Riesgo de invención masiva en documentación generada

**Problema identificado**:

SHARED_INSTRUCTIONS.md describe una **arquitectura completamente diferente** a la que existe en el código:

**Arquitectura descrita en SHARED_INSTRUCTIONS.md:**
```
managers/, bulk/, metadata/, comparar/, doc/, connection/, factory/, query/, 
validators/, analysis/, executors/, results/, core/, _core/, _drivers/, 
models.py, async_utils.py — total 15+ módulos con SyncDatabaseManager, 
AsyncDatabaseManager, SchemaComparator, etc.
```

**Arquitectura REAL en el código:**
```
src/doc_organize/
  __init__.py (1 línea: docstring + __version__)
  core/__init__.py (VACÍO)
  utils/__init__.py (VACÍO)
```

**Impacto crítico**: Si alguien invoca prompts de documentación (functional_doc, technical_doc), generarán **100% de invención** porque refieren a especialización de dominio desactualizada:

- `functional_doc.prompt.md` línea 10: "_librería Python multimotor de bases de datos (sync/async)_"
- `technical_doc.prompt.md`: "_especializado en Python, documentación técnica y mantenibilidad_"

**Acción urgente (2-3h)**:
1. Reparar sección "Proyecto: doc_organize" en SHARED_INSTRUCTIONS.md
2. Actualizar especialización de dominio en prompts
3. Añadir guardrails: "No inventar módulos no implementados"
4. Auditar CLAUDE.md — describe comandos (zensical, pytest) no configurados

**Bloquea**:
- ✅ Invocación de functional_doc.prompt.md
- ✅ Invocación de technical_doc.prompt.md
- ✅ Uso de CLAUDE.md slash commands
- ✅ Cualquier generador automático de docs

---

### Prompts IA de documentación

#### Inventario de prompts

| Archivo | Líneas | Propósito | Riesgo |
|---------|--------|-----------|--------|
| `documentation_review.prompt.md` | 150+ | Auditar documentación | ✅ Bajo |
| `functional_doc.prompt.md` | 80+ | Generar docs funcionales | 🔴 **ALTO** — refiere a especialización desactualizada |\n| `technical_doc.prompt.md` | 80+ | Generar docs técnicas | 🔴 **ALTO** — refiere a especialización desactualizada |
| `guide_doc.prompt.md` | 80+ | Generar guías de usuario | 🟠 Medio |
| `example_doc.prompt.md` | 80+ | Generar ejemplos verificables | 🟠 Medio |
| `architecture_doc.prompt.md` | 80+ | Generar ADRs | 🟠 Medio |
| `bootstrap_ai_config.prompt.md` | 200+ | Portar config IA a otro proyecto | 🟠 Medio |
| `landing_doc.prompt.md` | 60+ | Generar landing page | 🟠 Medio |

#### Hallazgo Nivel 2: Prompts refieren a carpetas de documentación que no existen

**Ubicación**: `.github/prompts/functional_doc.prompt.md` y otros

**Problema**:
- ⚠️ Prompts instruyen generar docs en `docs/functional/` pero carpeta **no existe**
- ⚠️ Prompts instruyen generar `docs/api/` pero **está vacía**
- ⚠️ Prompts refieren a ejemplos en `docs/examples/` pero **está vacía**

**Hallazgo Nivel 2: Posible invención de características en prompts**

**Ubicación**: `.github/prompts/functional_doc.prompt.md`, línea ~40

**Riesgo**:
```markdown
# Prompt puede inducir a inventar
"Genera la documentación completa del módulo: descripción, 
reglas de negocio, casos de uso, criterios de aceptación, glosario"

→ Si el módulo NO EXISTE o está vacío, el prompt puede generar 
  documentación ESPECULATIVA de features no implementadas
```

**Ejemplo de invención** (hipotético):
```markdown
# Esperado
Error: "El módulo scanner no tiene implementación; no puedo documentar"

# Riesgo de invención
"El módulo scanner proporciona:
- Escaneo recursivo con soporte para 50+ formatos
- OCR automático con detección de idiomas
- Extracción de metadatos XMP EXIF
- Filtrado por tipo MIME y tamaño"

← Esto sería INVENTADO si el código no existe
```

#### Recomendación Nivel 2: Validar código antes de generar docs

**Acción requerida**:

1. **Actualizar prompts con guardrails**:

En `functional_doc.prompt.md`:
```markdown
# Guardrail 1: Validar existencia del módulo
Antes de generar documentación:
1. Verificar que el módulo existe en src/doc_organize/
2. Si el módulo está vacío → reportar "VACÍO" en lugar de inventar
3. Si el módulo tiene solo __init__.py → reportar "SIN IMPLEMENTACIÓN"

# Guardrail 2: No inventar features
- Documentar SOLO lo que existe en el código
- Marcar features pendientes como "[TODO v1.1]"
- Ejemplo: "Soporte OCR: [TODO v1.1 — depende de tesseract]"
```

2. **Separar "documentación actual" de "documentación planificada"**:

Estructura recomendada:
```markdown
## Funcionalidad Implementada (v0.1.0)
- ✅ Escaneo básico de carpetas
- ✅ Hash SHA-3
- ✅ Detección de duplicados por hash exacto

## Funcionalidad Planificada (v1.0)
- ⏳ OCR automático
- ⏳ Extracción de metadatos
- ⏳ WebSocket de progreso
```

---

### Duplicación entre ficheros de instrucciones IA

#### Inventario de ficheros IA

| Fichero | Ubicación | Tipo | Líneas |
|---------|-----------|------|--------|
| `SHARED_INSTRUCTIONS.md` | `.github/` | Shared | 400+ |
| `copilot-instructions.md` | `.github/` | Especialización Copilot | 300+ |
| `CLAUDE.md` | Raíz | Especialización Claude | 100+ |
| `AGENTS.md` | `.github/` | Definición de agentes | 200+ |
| `.claude/settings.json` | `.claude/` | Config Claude Code | 50+ |
| `.claude/settings.local.json` | `.claude/` | Config local | 20+ |

#### Hallazgo Nivel 2: Posible duplicación de contenido shared

**Ubicación**: `.github/SHARED_INSTRUCTIONS.md` vs. `copilot-instructions.md`

**Riesgo**:
- ⚠️ Ambos ficheros pueden tener tablas de agentes/fases repetidas
- ⚠️ Cambios en SHARED no se propagan a especializaciones
- ⚠️ Inconsistencia en referencias a `.github/prompts/`

**Acción requerida** (Nivel 2):

1. Revisar `.github/SHARED_INSTRUCTIONS.md` para identificar secciones que se repiten en:
   - `copilot-instructions.md`
   - `CLAUDE.md`
   - `AGENTS.md`

2. Si hay duplicación:
   - Mantener contenido shared en `SHARED_INSTRUCTIONS.md`
   - Reemplazar en especializaciones con referencias a SHARED
   - Formato: `Ver [SHARED_INSTRUCTIONS.md § Agentes](../SHARED_INSTRUCTIONS.md#agentes)`

**Ejemplo de consolidación**:
```markdown
# En SHARED_INSTRUCTIONS.md (única fuente de verdad)
## Agentes disponibles
[Tabla de 12 agentes con fases]

# En copilot-instructions.md (solo especialización)
## Agentes en Copilot Chat
Ver [tabla de agentes en SHARED_INSTRUCTIONS.md](../SHARED_INSTRUCTIONS.md#agentes).

Adicionalmente, en Copilot Chat disponible:
- Agent X (especialización Copilot únicamente)
- Agent Y (especialización Copilot únicamente)
```

---

## VERSION

### Resumen ejecutivo

**Auditoría de documentación ejecutada sobre `doc_organize` v0.1.0 (Alpha)**

**Estado General**: 🔴 **BLOCKED** — Proyecto con blockers críticos de documentación

**Resumen de hallazgos**:
- 🔴 **Nivel 1 (Crítico)**: 7 hallazgos (incluyendo divergencia SHARED_INSTRUCTIONS.md)
- 🟠 **Nivel 2 (Alto)**: 3 hallazgos  
- 🟡 **Nivel 3 (Recomendado)**: 0 hallazgos

---

### Hallazgos Nivel 1 — Acción inmediata requerida 🔴

| # | Hallazgo | Ubicación | Acción | Esfuerzo | **Bloquea** |
|---|----------|-----------|--------|----------|------------|
| 🔴 **0** | **SHARED_INSTRUCTIONS.md desactualizado** | `.github/SHARED_INSTRUCTIONS.md` | Reparar especialización de dominio | **2-3h** | **TODOS los prompts IA de doc** |
| 1 | README sin claridad de valor | `README.md` | Reescribir con casos de uso | 1h | Usuarios |
| 2 | Documentación funcional ausente | `docs/functional/` | Crear 6 docs funcionales | 4h | functional_doc.prompt |
| 3 | Documentación técnica vacía | `docs/api/` | Crear 5 docs técnicos | 5h | technical_doc.prompt |
| 4 | 6 referencias rotas en nav | `mkdocs.yml` | Remover refs falsas | 2h | mkdocs build |
| 5 | Docstrings incompletos | `src/doc_organize/` | Actualizar 3 módulos | 2h | Usuarios |
| 6 | mkdocs.yml sin estructura | `mkdocs.yml` | Restructurar nav | 1h | mkdocs build |

**Total Nivel 1**: ~18 horas (**+2-3h críticas para reparar SHARED_INSTRUCTIONS.md**)

---

### Hallazgos Nivel 2 — Próxima iteración (v0.2.0) 🟠

| # | Hallazgo | Ubicación | Acción | Prioridad |
|---|----------|-----------|--------|-----------|
| 1 | Prompts refieren a carpetas inexistentes | `.github/prompts/` | Validar guardrails en prompts | Media |
| 2 | Riesgo de invención en prompts de doc | `.github/prompts/functional_doc.prompt.md` | Añadir validación de código antes de generar | Media |
| 3 | Duplicación posible entre SHARED e instrucciones | `.github/` vs. raíz | Auditar y consolidar referencias | Baja |

**Total Nivel 2**: ~4 horas

---

### Hallazgos Nivel 3 — Backlog 🟡

- Ejemplos avanzados (conectar con pipeline, configuración custom)
- Troubleshooting guide
- Migration guide (si aplica en futuro)
- Performance benchmarking

---

### Veredicto de readiness

**`PRODUCTION_READY`**: ❌ NO

**`NEAR_READY`**: ❌ NO  

**`BLOCKED`**: ✅ **SÍ** — Proyecto bloqueado por hallazgos Nivel 1

**Razones de bloqueo**:
1. ❌ **CRÍTICO**: SHARED_INSTRUCTIONS.md describe proyecto diferente → prompts generan docs inventadas
2. ❌ CLAUDE.md y `.claude/settings.json` refieren a módulos/comandos inexistentes
3. ❌ `mkdocs build --strict` falla por referencias rotas
4. ❌ GitHub Pages no se puede deployar
5. ❌ Usuarios no pueden instalar ni usar la librería sin documentación
6. ❌ APIs públicas sin docstrings
7. ❌ Módulos core sin especificación funcional ni técnica

**Readiness actual**: 🔴 **0% — Proyecto incipiente + instrucciones IA heredadas desactualizado**

---

### Próximos pasos priorizados

#### Fase 0: Reparar instrucciones IA (URGENTE — bloquea todo) — 2-3 horas

**ANTES de invocar CUALQUIER prompt de documentación**:

1. 🔴 **[2-3h] Reparar SHARED_INSTRUCTIONS.md**
   - Actualizar sección "Proyecto: doc_organize" (línea 13)
   - Reemplazar arquitectura con 3 módulos actuales + 5 TODO
   - Eliminar referencias a managers, bulk, metadata, comparar, etc.
   - Validar que especialización de dominio en cada prompt es acorde

2. ✅ **[30m] Auditar `CLAUDE.md` y `.claude/settings.json`**
   - Verificar referencias a módulos se alinean con v0.1.0
   - Actualizar comandos de testing

3. ✅ **[15m] Actualizar cabecera de prompts**
   - Añadir guardrail: "No inventar módulos no implementados"

**RESULTADO**: Prompts seguros para invocar en Fase 1

---

#### Fase 1: Desbloquear documentación (Nivel 1) — 15 horas

**Secuencia recomendada** (tras completar Fase 0):

1. ✅ **[1h] Restructurar mkdocs.yml** (Hallazgo 4)
   - Remover sección "Ejemplos" con refs falsas
   - Crear estructura funcional/técnica
   - Hacer que `mkdocs build --strict` pase

2. ✅ **[2h] Actualizar README.md** (Hallazgo 1)
   - Explicar qué es doc_organize
   - Agregar casos de uso
   - Escribir quick start ejecutable

3. ✅ **[2h] Completar docstrings** (Hallazgo 5)
   - 3 módulos públicos
   - Exportaciones y type hints

4. ✅ **[4h] Crear 6 documentos funcionales** (Hallazgo 2)
   - scanner, converter, cache, dedup, core, utils

5. ✅ **[5h] Crear 5 documentos técnicos** (Hallazgo 3)
   - index, scanner, converter, cache, dedup

**Total Fase 1**: 15 horas

#### Fase 2: Crear ejemplos (Nivel 3) — Backlog

- `docs/examples/01_basic_scan.md` — Escaneo básico
- `docs/examples/02_convert_to_markdown.md` — Conversión
- `docs/examples/03_deduplication.md` — Dedup

#### Fase 3: Validar y refinar (Nivel 2) — Post v0.1.0

- Auditar prompts IA contra código real
- Consolidar instrucciones IA
- Validar que `mkdocs build && mkdocs serve` funciona

---

### Validación final

**Criterios de salida para "READY_FOR_RELEASE"**:

- ✅ `mkdocs build --strict` pasa sin errores
- ✅ README describe valor en < 100 palabras
- ✅ Quick start ejecutable sin dependencias adicionales
- ✅ Todos los módulos públicos tienen docstrings Google-style
- ✅ Documentación funcional cubre 100% de módulos core
- ✅ Documentación técnica incluye Mermaid de arquitectura
- ✅ `docs/index.md` + `mkdocs.yml` coherentes
- ✅ Sin referencias rotas en navegación
- ✅ Ejemplos (mínimo 3) verificables y actualizados

**Estado actual vs. Criterios**:

| Criterio | Actual | Meta | Gap |
|----------|--------|------|-----|
| mkdocs build | ❌ Falla | ✅ Pasa | 2h |
| README claro | ❌ Genérico | ✅ Específico | 1h |
| Quick start | ❌ Incompleto | ✅ Ejecutable | 1h |
| Docstrings | ❌ Vacíos | ✅ 100% | 2h |
| Docs funcionales | ❌ 0% | ✅ 100% | 4h |
| Docs técnicas | ❌ 0% | ✅ 100% | 5h |
| Ejemplos | ❌ 0% | ✅ 3+ | 3h |

**Total de work pending**: ~18 horas (reducible a 15h con paralelización)

---

## Conclusión

La librería **doc_organize 0.1.0** está en estado **Alpha incipiente** con documentación **completamente ausente**. 

**Recomendación**: 
- **BLOQUEAR release a PyPI** hasta completar Nivel 1 (15h)
- **PRIORIZAR**: mkdocs navigation (2h) + README (1h) + docstrings (2h) 
- **PARALLELIZAR**: docs funcionales (4h) + docs técnicas (5h)
- **TIMELINE**: 1 sprint (2-3 días con dedicación)

**Próximo hito**: Auditoría de documentación re-run tras implementar hallazgos Nivel 1

---

*Auditoría completada: 2026-08-27*  
*Agente: Documentation Reviewer*  
*Herramientas utilizadas: documentation_review.prompt.md*
