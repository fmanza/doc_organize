# Instrucciones para GitHub Copilot Chat — doc_organize

## ⚠️ Contexto previo obligatorio

## ⚠️ Contexto previo obligatorio

Lee **primero** estos ficheros en este orden:

1. **`.github/SHARED_INSTRUCTIONS.md`** — Fuente canónica: arquitectura de doc_organize (TIMELOG), SOLID,
   calidad, comandos de desarrollo, documentación, flujo de trabajo, Conventional Commits.
2. **Este fichero** — Especialización para Copilot Chat en VS Code/GitHub únicamente.

---

## Agentes disponibles en Copilot Chat

Usa estos agentes cuando solicites trabajo estructurado. Cada agente implementa una fase
del flujo canónico `PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION`.

| Agente | Fase | Propósito |
|---|---|---|
| **Workflow Director** | Clasificación | Clasificar solicitud (feature, hotfix, refactor, security_review, tech_debt, maturity_assessment, version_closure) |
| **Plan Architect** | PLAN + AUDIT_PLAN | Preparar plan, contrastar con código real, detectar riesgos y expansion de alcance |
| **Feature Implementer** | IMPLEMENT | Ejecutar cambios con alcance aprobado, aplicar patches acotados |
| **Hotfix Responder** | RCA + FIX + AUDIT_CODE + VERSION | RCA mínimo, fix acotado (P1/P2 sin refactorizar) |
| **Code Auditor** | AUDIT_CODE | Revisar bugs, edge cases, contratos, cobertura, arquitectura |
| **Security Reviewer** | security_review | Auditoría de seguridad independiente (auth, secretos, validación) |
| **Documentation Reviewer** | audit (modo lectura) | Revisar docs, ejemplos, coherencia, gaps (sin editar) |
| **Documentation Generator** | IMPLEMENT (modo escritura) | Generar docs funcional/técnica con Mermaid en `docs/` |
| **Config Reviewer** | AUDIT_CODE (configuración IA) | Revisar y consolidar instrucciones IA, eliminar duplicación |
| **Explore** | lectura | Exploración rápida del repo, responder preguntas (sin editar) |
| **Maturity Assessment** | evaluación | Evaluar madurez del repositorio (estructura, tests, contratos, readiness) |
| **Version Closer** | VERSION | Resumir cambios, evidencias, pendientes, compatibilidad, rollback, directrices para futuras IAs |

Ver [`.github/AGENTS.md`](./.github/AGENTS.md) para registro completo.

---

## Flujo recomendado en Copilot Chat

Para cambios no triviales, usa el flujo estructurado con agentes:

```text
→ Workflow Director (clasificar)
→ Plan Architect (preparar PLAN + AUDIT_PLAN)
→ Feature Implementer (ejecutar IMPLEMENT)
→ Code Auditor (verificar AUDIT_CODE)
→ Version Closer (cerrar VERSION)
```

**Solicitud de ejemplo para nueva feature**:

```markdown
Trabaja sobre doc_organize. Usa agentes si es necesario.

Objetivo: [describe el cambio]
Alcance: [rutas o módulos: timelog/, common/, etc.]
Restricciones: [compatibilidad, no refactor, docs, etc.]

Primero revisa .github/SHARED_INSTRUCTIONS.md.
Luego planifica, implementa, audita y cierra versión.
```

---

## Reglas específicas para Copilot Chat

### Uso de `#file:` y selección

- Si usas `#file:` o selecciones de código, contrástalo con el árbol real del repositorio
- No asumir rutas basadas en títulos de ficheros; verifica con `file_search` si es necesario

### Contradicciones y prioridades

- Si una instrucción IA contradice `pyproject.toml` o el código real,
  **prioriza el código real** y explícita el supuesto en tu respuesta
- Cuando referencias `doc_organize` (proyecto histórico), valida que los módulos
  existan en el árbol actual

### Validación de referencias heredadas

No propongas módulos, archivos o estructuras que no existan:
- ❌ `servicios/`, `metadata/`, `bulk/` — no están en src/
- ❌ `SyncDatabaseManager`, `introspección SQL` — no están en el código actual
- ✅ Usa `grep_search` para validar antes de referenciar

### Sincronización de instrucciones IA

Si cambias reglas comunes, actualiza **en este orden**:

1. **`.github/SHARED_INSTRUCTIONS.md`** (fuente canónica) — cambios globales
2. **`.github/copilot-instructions.md`** (este fichero) — especialización Copilot, si aplica
3. **`CLAUDE.md`** — especialización Claude Code, si aplica
4. **`.github/AGENTS.md`** — actualizar si cambian agentes

**Validación**: Antes de cerrar PR de instrucciones IA, verifica que ambos ficheros
(copilot-instructions.md y CLAUDE.md) sean consistentes en estructura y que no haya
duplicación de contenido shared.

---

## Cuándo usar agentes vs. Claude Code vs. Copilot Chat directo

| Escenario | Recomendación | Razón |
|---|---|---|
| Cambio pequeño (1-2 archivos, acotado) | Copilot Chat directo (sin agentes) | Rápido y eficiente |
| Nueva feature compleja (5+ archivos, PLAN required) | Plan Architect → Feature Implementer | Flujo estructurado, verificación de riesgos |
| Bug P1/P2 que requiere RCA | Hotfix Responder | Especialización en hotfix, fix mínimo |
| Auditoría de código existente | Code Auditor | Independencia, verificación exhaustiva |
| Pregunta rápida sobre arquitectura | Explore | Lectura rápida, sin cambios |
| Documentación nueva o actualización | Documentation Generator | Escritura de docs con Mermaid |
| Revisión de docs para gaps | Documentation Reviewer | Auditoría sin escritura |
| Cambios en instrucciones IA | Config Reviewer | Especialización en DRY y gobernanza |

---
### Cambios en Instrucciones IA

Cuando modifiques instrucciones, revisa y sincroniza **al menos**:
- `.github/SHARED_INSTRUCTIONS.md` (fuente canónica)
- `.github/copilot-instructions.md` (este fichero, si cambia flujo Copilot)
- `CLAUDE.md` (si cambia flujo común o slash commands)
- `.github/AGENTS.md` (si cambia responsabilidades de agentes)

Usa `grep_search` para verificar que no quedan referencias heredadas en ficheros.

---

## Generación de Documentación

Sigue el **flujo estándar de 7 fases** definido en [`DOCUMENTATION_STANDARD.md` §5](DOCUMENTATION_STANDARD.md#5-roles-de-agentes-y-flujo-de-trabajo)
y la estructura de `DOCUMENTATION_STANDARD.md` §3 (funcional) y §3.2 (técnica).

Para un módulo o el proyecto completo:

```text
# Módulo individual — funcional
Lee src/doc_organize/[modulo].py y genera la documentación funcional
usando .github/prompts/functional_doc.prompt.md.
Guarda en docs/functional/[nombre].md y actualiza mkdocs.yml.

# Módulo individual — técnica
Lee src/doc_organize/[modulo].py y genera la documentación técnica
usando .github/prompts/technical_doc.prompt.md.
Guarda en docs/api/[nombre].md y actualiza mkdocs.yml.

# Proyecto completo (fases 3-4 del flujo estándar)
@Documentation Generator
Genera la documentación completa del proyecto: todos los módulos en src/doc_organize/.
Tipo: funcional + técnica para cada módulo. Actualiza mkdocs.yml al finalizar.
```

Regla crítica: no inventar. Lee el código fuente antes de generar cualquier sección.
Criterio de completitud: `mkdocs build --strict` sin errores + todos los módulos de `src/` documentados.

## 📐 Arquetipos Formales de Documentación

Toda documentación en doc_organize sigue **6 arquetipos formales** definidos en [`.github/DOCUMENTATION_STANDARD.md`](.github/DOCUMENTATION_STANDARD.md#3-propuesta-de-cambios):

| Arquetipo | Propósito | Ubicación | Prompt | Secciones |
|---|---|---|---|---|
| **1. Funcional** | ¿Qué hace y por qué? | `docs/functional/` | `functional_doc.prompt.md` | 1. Descripción · 2. Reglas · 3. Casos de Uso · 4. Criterios* · 5. Glosario |
| **2. Técnica/API** | ¿Cómo funciona internamente? | `docs/api/` | `technical_doc.prompt.md` | 1. Arquitectura · 2. Contratos · 3. Componentes · 4. Dependencias · 5. Ejemplos Relacionados ↔ |
| **3. Guía de Usuario** | ¿Cómo se usa/instala? | `docs/` raíz | `guide_doc.prompt.md` | 1. Objetivo · 2. Requisitos · 3. Pasos · 4. Verificación · 5. Variantes |
| **4. Ejemplos de Código** | ¿Cómo se implementa? | `docs/examples/` | `example_doc.prompt.md` | 1. Contexto · 2. Código (`--8<--`) · 3. Explicación · 4. Ejecución · 5. Referencias ↔ |
| **5. Decisión Arquitectónica** | ¿Por qué se decidió así? | `docs/adr/` | `architecture_doc.prompt.md` | Contexto → Decisión → Consecuencias → Alternativas → Estado |
| **6. Navegación Principal** *(variante)* | Intro + instalación + visión | `docs/index.md`, `INSTALLATION.md` | `landing_doc.prompt.md` | Variante A/B/C según tipo |

**Características clave**:
- ✅ Secciones fijas: estructura inmutable (nunca omitir, escribir "No aplica" si vacío)
- ✅ Enlaces bidireccionales: Arquetipo 2 (§5) ↔ Arquetipo 4 (§5) obligatorios
- ✅ Multi-lenguaje: Arquetipo 2 soporta pseudocódigo en Python, Java, TypeScript, Go, etc.
- ✅ Navegación: 7 secciones top-level exactas en `mkdocs.yml`

**Notas especiales**:
- Criterios de Aceptación (Arq.1 §4): Pendiente QA — placeholder hasta validación
- Documentación informativo-libre: Roadmaps/planes de release usan `<!-- arquetipo: informativo-libre -->` y quedan exentos

## Documentación con Copilot Chat

Usa **Documentation Generator** como **único punto de entrada** para crear o actualizar documentación,
tanto de un módulo concreto como del proyecto completo.
No uses un único prompt masivo: divide siempre el trabajo por fases.

### Flujo por fases

```
Fase 1 — Inventariar: src/, README, docs/, docs/examples/, mkdocs.yml
Fase 2 — Mapeo funcional (Senior Product Owner): objetivo, precondiciones, flujo Mermaid, reglas
Fase 3 — Documentación técnica: responsabilidad, Mermaid, API pública, contratos, errores
Fase 4 — Ejemplos verificables: código real, resultado determinista, sin credenciales
Fase 5 — Sincronizar mkdocs.yml: añadir/mover/retirar entradas de navegación
Fase 6 — Revisión final: Markdown, enlaces relativos, sintaxis Mermaid, mkdocs build --strict
```

**Solicitud para módulo único**:

```markdown
@Documentation Generator

Genera documentación funcional y técnica para [ruta_del_módulo].
Aplica functional_doc.prompt.md y technical_doc.prompt.md.
Guarda en docs/functional/[nombre].md y docs/api/[nombre].md.
MkDocs renderiza automáticamente al añadir la entrada a `mkdocs.yml`; no requiere más configuración.
No inventes capacidades; marca como pendiente lo no verificable.
```

**Solicitud para proyecto completo**:

```markdown
@Documentation Generator

Revisa el proyecto completo y actualiza la documentación pública en 6 fases:
1. Inventariar módulos reales en src/doc_organize/ y clasificarlos.
2. Mapeo funcional con functional_doc.prompt.md por módulo sin doc o desactualizado.
3. Documentación técnica con technical_doc.prompt.md y Mermaid apropiado.
4. Ejemplos verificables en docs/examples/ para módulos sin ejemplo reproducible.
5. MkDocs renderiza automáticamente tras añadir la entrada a `mkdocs.yml` (no requiere más sync).
6. Revisión final: Markdown, enlaces y Mermaid; recomendar `mkdocs build --strict`.

No inventes módulos ni capacidades; marca como pendiente lo no verificable.
No uses APIs externas por el momento.
```

**Para auditar documentación sin editar**, usa **Documentation Reviewer**:

```markdown
@Documentation Reviewer

Revisa docs/, docs/examples/, README y mkdocs.yml para detectar gaps.
Usa .github/prompts/documentation_review.prompt.md como criterio.
Entrega hallazgos con severidad (Nivel 1/2/3) sin editar archivos.
```

---

## Bootstrap de configuración IA a otro proyecto

Para **trasladar este sistema de instrucciones IA** (Claude / Gemini / Copilot / Cursor / Codex) a otro
proyecto, incluso de **otro lenguaje y arquitectura**, usa el prompt
[`bootstrap_ai_config.prompt.md`](prompts/bootstrap_ai_config.prompt.md) y audita el resultado con
**Config Reviewer**.

**Método y dirección — modelo PULL**: invoca **desde el proyecto destino**, apuntando a este repo
como plantilla de solo lectura (el destino debe estar en contexto para adaptar lenguaje, arquitectura
y comandos). El lenguaje/arquitectura del destino es un **parámetro**.

```markdown
# Abre el PROYECTO DESTINO en VS Code y escribe:
Lee y aplica .github/prompts/bootstrap_ai_config.prompt.md
Origen (solo lectura): <ruta del repo origen>
Destino: <raíz de este proyecto>
Lenguaje/arquitectura destino: <p.ej. TypeScript + NestJS>
Plataformas IA activas: Claude Code, Gemini, Copilot, Cursor, Codex
Fase: PLAN y AUDIT_PLAN únicamente.
```

Capas: **A** copiar verbatim · **B** copiar + reescribir dominio · **C** regenerar analizando el
destino · **D** excluir (sesiones, changelog, caches). Detalle completo en el propio prompt.

---

## Integración con Claude Code

Esta especialización es **compatible con Claude Code**:

- **Cambios aprobados en Claude Code** se pueden auditar con **Code Auditor** (Copilot)
- **Documentación generada en Claude Code** se revisa con **Documentation Reviewer** (Copilot)
- **Configuración IA** se sincroniza via **Config Reviewer**

**Flujo bidireccional recomendado**:
1. Claude Code: `/new-feature` → PLAN + AUDIT_PLAN + IMPLEMENT + AUDIT_CODE
2. Copilot Chat: Code Auditor con cambios de Claude Code → verificación adicional
3. Copilot Chat: Version Closer → cierre final y changelog

### Validación de Markdown — Checklist obligatorio

Ver `.github/SHARED_INSTRUCTIONS.md` § "Validación de Markdown en documentación" para directrices completas.

**Puntos críticos**:
- ✅ Listas: usar `- item` o `1. item`, NUNCA dos espacios al final de línea
  - ❌ `✅ Item 1  ` → Renderiza con `<br />` (horizontal)
  - ✅ `- ✅ Item 1` → Renderiza como `<ul><li>` (vertical)
- ✅ Enlaces a archivos estáticos: usar rutas relativas, NO placeholders
  - ❌ `[archivo.zip](#)`
  - ✅ `[archivo.zip](../doc_organize.zip)` (desde `site/downloads/index.html` → apunta a `site/doc_organize.zip`)
- ✅ Validar: `python -m mkdocs build --strict` sin errores
- ✅ Inspeccionar HTML: Revisar que `<ul><li>` se usan para listas, NUNCA `<p><br /></p>`

---

## 📦 Descarga de Documentación Offline

Util_bbdd proporciona **documentación en ZIP offline** con búsqueda integrada, SHA256 checksums y auto-publicación en GitHub Releases.

### Funcionalidades

✅ **Página de descargas**: https://fmanza.github.io/doc_organize/downloads/
✅ **ZIP comprimido**: ~2.5 MB (150+ archivos HTML)
✅ **SHA256 Checksum**: Validación de integridad del archivo
✅ **Auto-publicar**: GitHub Release automático en cada push a `main`/`develop`
✅ **Búsqueda offline**: `search_index.json` incluido en ZIP

### Generar localmente

```bash
mkdocs build --strict
python scripts/build_docs_zip.py

# Validar checksums
sha256sum -c dist/*.sha256
```

### En GitHub Actions

El workflow `.github/workflows/docs-zip-release.yml` se ejecuta automáticamente:
1. En cada `push` a `main`/`develop` (si hay cambios en `docs/`)
2. Manualmente desde Actions UI

**Resultado**: Release con tag `docs-vX.X.X` + ZIP + checksums adjuntos

### Para otros proyectos (Bootstrap)

El sistema de descarga ZIP es **reutilizable** via bootstrap. Ver:
- `.github/prompts/bootstrap_ai_config.prompt.md` — Sección "📦 Descarga de Documentación Offline"
- Incluye matriz de equivalencias para Python, Node.js, Go, Java

---

## Checklist de sincronización

Cuando actualices **`.github/SHARED_INSTRUCTIONS.md`**, verifica:

- [ ] Ambos ficheros (copilot-instructions.md y CLAUDE.md) contienen referencias a secciones shared actualizadas
- [ ] No hay duplicación de contenido entre SHARED_INSTRUCTIONS.md y especializaciones
- [ ] Rutas de archivos son relativas y portables (`./.github/...`, no `file://...`)
- [ ] Tabla de gobernanza en SHARED_INSTRUCTIONS.md refleja responsabilidad de cada fichero
- [ ] Timestamps de actualización están sincronizados

---

*Actualizado: 2026-06-05*
