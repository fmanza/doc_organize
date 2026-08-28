# Prompt: bootstrap_ai_config — Trasladar la configuración IA multiplataforma a otro proyecto

## Objetivo

Replicar el sistema de instrucciones IA de este repositorio (origen) en un **proyecto destino**,
que puede usar **otro lenguaje y otra arquitectura**, separando lo reutilizable de lo que debe
regenerarse analizando el código real del destino. Cubre las cinco plataformas en uso:
**Claude Code, Gemini Code Assist, GitHub Copilot Chat, Cursor y Codex (OpenAI)**.

Este prompt es **agnóstico de lenguaje**: el lenguaje y la arquitectura del destino son **parámetros
de entrada** que confirma quien lo invoca, no constantes embebidas.

> **Nota sobre Codex**: Codex (OpenAI) **no usa un fichero de instrucciones propio**; lee
> `CLAUDE.md`, `.github/SHARED_INSTRUCTIONS.md` y `.github/AGENTS.md`, con su guía de uso en
> `docs/codex_guide.md`. Al hacer bootstrap, replica esa guía adaptada al destino.

---

## Método y dirección de la llamada (OBLIGATORIO leer antes de empezar)

**Modelo PULL — se invoca desde el proyecto DESTINO**, apuntando al origen como plantilla de solo lectura.

**Por qué desde el destino y no desde el origen:** la adaptación (capas B y C, ver abajo) exige tener el
**código real del nuevo proyecto en contexto** para reescribir arquitectura, lenguaje, comandos y
estrategia de tests. Si se lanza desde el origen, la IA no "ve" el destino y acabaría arrastrando
supuestos del repositorio origen (lenguaje, motores, generador de docs, jerarquía de errores).

**Invocación concreta** (una vez copiado este prompt al destino, o leído desde la ruta del origen):

```text
# Abres el PROYECTO DESTINO en VS Code / Claude Code / Cursor y escribes:

Lee y aplica .github/prompts/bootstrap_ai_config.prompt.md
Origen (solo lectura): <ruta absoluta del repo origen, p.ej. c:\Desarrollo\python\libs\doc_organize>
Destino: <raíz de este proyecto>
Lenguaje/arquitectura destino: <p.ej. TypeScript + NestJS hexagonal, Go + Clean Architecture, Java + Spring>
Plataformas IA activas: <Claude Code, Gemini, Copilot, Cursor, Codex — marca las que apliquen>
Generador de documentación destino: <p.ej. Docusaurus, Typedoc, MkDocs, ninguno>
Fase: PLAN y AUDIT_PLAN únicamente.   # o "completa" para llegar hasta VERSION
```

**Dirección de los ficheros** (origen → destino, misma estructura de carpetas):

| Origen | Destino | Modo |
|---|---|---|
| `.github/agents/` | `.github/agents/` | verbatim (revisar comandos embebidos) |
| `.github/prompts/` | `.github/prompts/` | verbatim (revisar comandos embebidos) |
| `.claude/commands/` + `COMMAND_TEMPLATE.md` + `settings.json.example` | `.claude/` | verbatim (adaptar hooks) |
| `.ai/sessions/TEMPLATE/` | `.ai/sessions/TEMPLATE/` | verbatim |
| `.github/SHARED_INSTRUCTIONS.md` | idem | copiar + reescribir dominio |
| `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md`, `.github/AGENTS.md`, `.cursorrules` | idem | copiar + reescribir dominio |
| `docs/codex_guide.md` (guía de uso de Codex) | idem | copiar + reescribir dominio |
| `scripts/build_docs_zip.py` + `.github/workflows/docs-release.yml` | idem | copiar + adaptar builder/secrets/prefijo ZIP |
| `.ai/{product,architecture,runtime,glossary,standards}.md` | idem | **regenerar desde cero** |

---

## Devuelve en este orden

1. ANÁLISIS (clasificación por capas A/B/C/D + matriz de equivalencias)
2. PLAN
3. AUDIT_PLAN
4. IMPLEMENT
5. AUDIT_CODE
6. VERSION

---

## Contexto a completar (OBLIGATORIO antes de emitir PLAN)

- [ ] **Ruta del origen** (solo lectura):
- [ ] **Ruta del destino**:
- [ ] **Lenguaje y framework del destino**:
- [ ] **Arquitectura del destino** (capas, módulos, patrón: hexagonal, MVC, Clean, etc.):
- [ ] **Plataformas IA activas** (Claude / Gemini / Copilot / Cursor / Codex):
- [ ] **Herramientas de calidad del destino** (linter, formateador, type-checker, test runner):
- [ ] **Generador de documentación del destino** (o "ninguno"):
- [ ] **Gestor de paquetes / comando de build**:

**⚠️ VALIDACIÓN**: si falta cualquiera de estos campos, **DETENTE y aclara antes de continuar**.
No emitas PLAN hasta tenerlos todos.

---

## Clasificación por capas (núcleo del trabajo)

Clasifica **cada** activo IA del origen en una de estas cuatro capas:

| Capa | Carácter | Acción |
|---|---|---|
| **A — Metodología** | Agnóstico de lenguaje: ciclo `PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION`, agentes, prompts, plantilla de sesión | **Copiar verbatim**, revisando comandos embebidos |
| **B — Especialización** | Mezcla método reutilizable + dominio (entry points por plataforma, instrucciones compartidas) | **Copiar y reescribir** las secciones de dominio |
| **C — Contexto de dominio** | 100 % específico del origen (módulos reales, capacidades, lenguaje, motores) | **Regenerar desde cero** analizando el destino |
| **D — No copiar** | Historial/estado del origen: sesiones pasadas, changelog, caches, notas de migración | **Excluir** |

### Capa A — Copiar verbatim (revisar comandos embebidos)

- `.github/agents/*.agent.md`
- `.github/prompts/*.prompt.md` (incluido este)
- `.claude/commands/*.md`, `.claude/COMMAND_TEMPLATE.md`, `.claude/settings.json.example`
- `.ai/sessions/TEMPLATE/`

> ⚠️ **No es verbatim puro**: estos ficheros contienen comandos embebidos del origen
> (p.ej. `python -m pytest`, `mkdocs build`, rutas `src/<paquete>/...`). Revisa y sustituye
> por los equivalentes del destino usando la matriz de equivalencias del ANÁLISIS.

### Capa B — Copiar y reescribir dominio

- `.github/SHARED_INSTRUCTIONS.md` (canónico: rol, arquitectura, comandos, tests, docs)
- `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md`, `.cursorrules`
- `.github/AGENTS.md`, `.github/instructions/sync.instructions.md`
- `.github/DOCUMENTATION_STANDARD.md` (solo si el destino publica documentación)
- **PROMPTS DE ARQUETIPOS DOCUMENTALES** (si el destino publica documentación):
  - `.github/prompts/functional_doc.prompt.md` (Arquetipo 1: Documentación Funcional)
  - `.github/prompts/technical_doc.prompt.md` (Arquetipo 2: Documentación Técnica/API)
  - `.github/prompts/guide_doc.prompt.md` (Arquetipo 3: Guías de Usuario)
  - `.github/prompts/example_doc.prompt.md` (Arquetipo 4: Ejemplos de Código)
  - `.github/prompts/architecture_doc.prompt.md` (Arquetipo 5: Decisiones Arquitectónicas/ADR)
  - `.github/prompts/landing_doc.prompt.md` (Arquetipo 6: Páginas Navegación Principal)
- **NUEVO**: `docs/downloads.md` (página de descarga offline si destino publica documentación)
- **NUEVO**: `scripts/build_docs_zip.py` + `.github/workflows/docs-zip-release.yml` (si destino
  publica documentación con generador estático): adaptar builder por defecto (`--builder`),
  secrets del workflow, prefijo ZIP, SHA256 y generación de checksums
- **NUEVO**: `.github/prompts/onboarding_dev.prompt.md` (Arquetipo 7 — Onboarding Desarrolladores):
  copiar + actualizar el bloque "Especialización de dominio" con stack, herramientas, infraestructura
  y rutas del destino; las 11 secciones del núcleo son idénticas en todos los proyectos

### Capa C — Regenerar desde cero (NO copiar contenido del origen)

- `.ai/product.md`, `.ai/architecture.md`, `.ai/runtime.md`, `.ai/glossary.md`, `.ai/standards.md`
- `.github/instructions/<lenguaje>.instructions.md` (reglas por tipo de archivo del destino)
- `.github/INTEGRATION_MAP.md`

> Regla absoluta: **no inventes módulos, capacidades ni APIs**. Lee el árbol real del destino
> (`src/`, `app/`, `cmd/`, `pkg/`, lo que aplique) y describe solo lo que existe. Marca como
> pendiente lo no verificable.

### Capa D — Excluir explícitamente

- `.ai/sessions/<fechas>/` (todo lo que no sea `TEMPLATE/`)
- `CHANGELOG.md`, `COMPATIBILITY.md`, notas de migración específicas del origen
- `.coverage`, `coverage.xml`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `site/`, `build/`, `dist/`
- `.claude/settings.local.json` (configuración local, git-ignored)

---

## Contexto obligatorio vs. opcional en el destino

### Mínimo OBLIGATORIO (sin esto el sistema no funciona)

1. `.github/SHARED_INSTRUCTIONS.md` — canónico, **reescrito** para el dominio del destino.
2. Un punto de entrada **por cada plataforma activa**: `CLAUDE.md`, `GEMINI.md`,
   `.github/copilot-instructions.md`, `.cursorrules` y `docs/codex_guide.md` (Codex).
3. `.ai/architecture.md` + `.ai/product.md` — contexto que los agentes leen antes de planificar.
4. Núcleo de método: prompts/commands `new_feature`, `hotfix`, `refactor`, `audit_code`,
   `version_closure` + agentes `plan-architect`, `code-auditor`, `version-closer`.
5. `.ai/sessions/TEMPLATE/` — sin plantilla, la fase VERSION no tiene dónde escribir.

### OPCIONAL (añadir según necesidad)

- Agentes de documentación (`documentation-generator`, `documentation-reviewer`) → solo si destino publica docs.
- `security-review`, `tech-debt`, `maturity-assessment` → recomendables, no críticos al arrancar.
- `EDGE_CASES.md`, `TESTING_GUIDE.md` → copiar como plantilla vacía; se pueblan con el tiempo.
- `INTEGRATION_MAP.md` → si el destino es una librería con docs públicas.

---

## Mapeo por plataforma (entry points a regenerar)

| Plataforma | Fichero entry point | Especificidad a reescribir |
|---|---|---|
| Claude Code | `CLAUDE.md` | slash commands, hooks `.claude/settings.json`, ejecución local, arquetipos doc |
| Gemini | `GEMINI.md` | estándares de código del lenguaje destino, comandos rápidos, arquetipos doc |
| Copilot Chat | `.github/copilot-instructions.md` | agentes VS Code, `#file:`, validación de rutas, arquetipos doc |
| Cursor | `.cursorrules` | estándar de documentación/ejemplos y reglas de estilo del destino |
| Codex (OpenAI) | `docs/codex_guide.md` | guía de uso; lee `CLAUDE.md` + `SHARED_INSTRUCTIONS.md` + `AGENTS.md` (sin fichero propio) |

Todos referencian a `.github/SHARED_INSTRUCTIONS.md` como **fuente canónica**.
**Regla de oro**: edita primero `SHARED_INSTRUCTIONS.md`; los entry points solo añaden especialización.

---

## 📐 Sección Especial: Arquetipos Documentales (Capa B)

**Aplica solo si** el destino publica documentación pública con un generador estático
(MkDocs, Docusaurus, Hugo, Sphinx, etc.).

### Estructura de arquetipos (5 tipos + 1 variante)

El estándar de documentación incluye **6 arquetipos formales** que garantizan consistencia y
búsqueda automática por IA. Cada uno responde una pregunta de usuario distinta:

| Arq. | Nombre | Propósito | Ubicación | Prompt |
|---|---|---|---|---|
| **1** | Funcional | ¿Qué hace y por qué? | `docs/functional/` | `functional_doc.prompt.md` |
| **2** | Técnica/API | ¿Cómo funciona internamente? | `docs/api/` | `technical_doc.prompt.md` |
| **3** | Guía de Usuario | ¿Cómo se usa/instala? | `docs/` raíz | `guide_doc.prompt.md` |
| **4** | Ejemplos de Código | ¿Cómo se implementa? | `docs/examples/` | `example_doc.prompt.md` |
| **5** | Decisión Arquitectónica (ADR) | ¿Por qué se decidió así? | `docs/adr/` | `architecture_doc.prompt.md` |
| **6** | Navegación Principal *(variante)* | Intro + instalación + visión | `docs/index.md`, `INSTALLATION.md`, `ARCHITECTURE.md` | `landing_doc.prompt.md` |

### Adaptación de arquetipos al destino

Cada prompt de arquetipo (`functional_doc.prompt.md`, etc.) contiene:
- Estructura fija de secciones (numeradas, inmutables)
- Ejemplos de Mermaid específicos del patrón
- Reglas de validación (p.ej., "no inventar módulos")
- Directivas de inclusión de código (`--8<--` para snippets)

**En el destino, adaptar**:
1. **Lenguaje de ejemplo en diagramas**: sustituir `Python` → lenguaje destino
2. **Rutas de módulos**: reemplazar `src/doc_organize/` → estructura real del destino
3. **Herramientas de documentación**: si destino usa Docusaurus en lugar de MkDocs,
   adaptar referencias a `mkdocs.yml` → `docusaurus.config.js`, plugins, etc.
4. **Comandos de construcción**: actualizar en instrucciones IA si destino usa otra herramienta

**Regla de no-invención**: Los prompts generados deben describir **solo módulos y capacidades
reales** del destino. Marcar como "Pendiente" cualquier sección que no se pueda verificar.

### Enlace bidireccional (Capa B)

Los arquetipos 2 (Técnica) y 4 (Ejemplos) **están obligados a enlazarse entre sí**:
- Arquetipo 2 §5 → lista ejemplos relacionados de Arquetipo 4
- Arquetipo 4 §5 → lista documentación técnica de Arquetipo 2

Este enlace facilita navegación y retroalimentación de IA (agentes pueden validar coherencia).

---

## 📦 Sección Especial: Descarga de Documentación Offline (Capa B)

**Aplica solo si** el destino publica documentación pública con un generador estático
(MkDocs, Docusaurus, Hugo, Sphinx, etc.) **y necesita ZIP offline distribuible**.

### Archivos a copiar/adaptar

1. **`docs/downloads.md`** — Página de descargas
   - Copiar verbatim, adaptar URLs y rutas del proyecto destino
   - Reemplazar: `doc_organize` → nombre del proyecto destino
   - Reemplazar: `https://fmanza.github.io/doc_organize/` → URL raíz del destino

2. **`scripts/build_docs_zip.py`** — Script de generación
   - **Copiar y adaptar**:
     - Línea 23: `PYPROJECT = ROOT / "pyproject.toml"` → archivo de versión del destino
       - Python: `pyproject.toml`
       - Node.js: `package.json`
       - Go: `go.mod` (extraer versión del tag o var)
       - Java: `pom.xml`
     - Comando build: `mkdocs build --strict` (Python) → equivalente del destino
       (Node.js: `docusaurus build` / `npm run build:docs`; Go: `hugo` / `make docs`)
     > **Nota**: `scripts/build_docs_zip.py` no existe todavía en este repo origen (herencia de un
     > experimento de migración a "Zensical" nunca completado, ver `.ai/DECISIONS_LOG.md`) — no
     > copiar como si fuera un script funcional; escribirlo desde cero en el destino si esa
     > funcionalidad de ZIP de release hace falta.

3. **`.github/workflows/docs-zip-release.yml`** — Workflow CI/CD (actualmente roto en el origen,
   ver nota arriba — adaptar con cautela, no asumir que funciona)
   - **Copiar y adaptar**:
     - Setup Python/Node/Go según lenguaje destino
     - Comando build: `mkdocs build --strict` → equivalente del destino
     - Script: `python scripts/build_docs_zip.py` → equivalente del destino (escribir desde cero)
     - Secrets: mantener `GITHUB_TOKEN` (nativo en GH Actions)

### Características clave (comunes a todos los destinos)

✅ **SHA256 Checksum**: `scripts/build_docs_zip.py` genera:
   - `{project}-docs-{version}.zip.sha256` (para validación offline)
   - `dist/CHECKSUMS.txt` (histórico de hashes)

✅ **Auto-publicar**: `.github/workflows/docs-zip-release.yml`
   - Trigger: push a `main`/`develop` + cambios en `docs/`
   - Release automática: tag `docs-vX.X.X` con artifacts adjuntos
   - Body con instrucciones y SHA256

✅ **Página de descargas**: `docs/downloads.md`
   - Tabla de versiones disponibles
   - Instrucciones SHA256 por plataforma (Linux, Windows, Mac)
   - FAQ, changelog, links

### Matriz de equivalencias (Capa A → Capa B)

| Componente | Python + MkDocs | Node.js + Docusaurus | Go + Hugo |
|---|---|---|---|
| Versión desde | `pyproject.toml` | `package.json` | `git describe` o var |
| Builder | `mkdocs` | `docusaurus` | `hugo` |
| Build cmd | `mkdocs build --strict` | `docusaurus build` | `hugo` |
| Output dir | `site/` | `build/` | `public/` |
| ZIP script | `python scripts/build_docs_zip.py` | `node scripts/build-docs-zip.js` | `./scripts/build-docs-zip.sh` |
| CI language | Python 3.12 | Node.js 20 | Go 1.22 |

---

Copia únicamente `.claude/settings.json.example` y adapta los comandos a las herramientas del destino.
No copies `settings.json` del origen (apunta a herramientas Python). Sustituye según la matriz:

| Rol | Origen (Python) | Destino (ejemplo TS/Node) |
|---|---|---|
| Formateo | `ruff format` | `prettier --write` |
| Linting | `ruff check` | `eslint` |
| Type-check | `mypy` | `tsc --noEmit` |
| Tests | `pytest` | `jest` / `vitest` |

(Genera la fila correcta para el lenguaje real del destino en el ANÁLISIS.)

---

## Auditoría posterior (AUDIT_CODE)

Tras IMPLEMENT, ejecuta una auditoría de configuración (reutiliza el agente `config-reviewer` /
prompt `config_review`). Verifica:

- **DRY**: sin duplicación entre `SHARED_INSTRUCTIONS.md` y los entry points.
- **Rutas relativas y portables** (`./.github/...`, no rutas absolutas del origen).
- **Cero referencias huérfanas**: busca términos del origen que no apliquen al destino
  (nombre del repo origen, lenguaje origen, generador de docs origen, nombres de módulos origen).
- **Comandos coherentes**: todos los comandos embebidos corresponden a herramientas del destino.
- **Autosuficiencia**: cada entry point es usable sin leer los demás (salvo el canónico).

---

## Formato de salida esperado

### ANÁLISIS
- Tabla de clasificación por capas (A/B/C/D) de cada activo del origen
- Matriz de equivalencias de comandos (origen → destino)
- Inventario del árbol real del destino (módulos verificados, no inventados)

### PLAN
- Objetivo y alcance in/out
- Lista de ficheros a copiar verbatim, a adaptar y a regenerar (con rutas destino)
- Orden de ejecución y dependencias

### AUDIT_PLAN
- Riesgos funcionales (contaminación de dominio, sesiones heredadas)
- Riesgos técnicos (hooks rotos, comandos embebidos, direccionalidad)
- Riesgos de seguridad (no copiar `settings.local.json`)
- Simplificaciones posibles (arranque mínimo viable)
- **Veredicto:** `GO | GO_CONDICIONAL | NO_GO`

### IMPLEMENT
- Por capa: A (copias) → B (copias reescritas) → C (regenerados)
- Contenido completo de cada fichero reescrito o regenerado

### AUDIT_CODE
- Resultado de las verificaciones de la auditoría posterior
- Referencias huérfanas detectadas y corregidas
- Veredicto: `APROBADO | APROBADO CON CONDICIONES | RECHAZADO`

### VERSION
- Commit message (Conventional Commits, p.ej. `chore: bootstrap configuración IA multiplataforma`)
- Resumen de qué se copió, qué se adaptó y qué se regeneró
- Rollback: pasos para revertir (eliminar carpetas/ficheros añadidos)
