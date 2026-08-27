# 📚 Especificación de Estandarización de Documentación

Objetivo: Unificar la estructura de documentación técnica, funcional y general en **doc_organize**
y definir un flujo de trabajo repetible para otros proyectos con IA.

---

## 1. Objetivo

Estandarizar instrucciones de documentación para asegurar:
- **Claridad de usuario**: Documentación funcional orientada a "qué puedo hacer"
- **Claridad de desarrollador**: Documentación técnica orientada a "cómo funciona internamente"
- **Mantenibilidad**: Estructura agnóstica al lenguaje, fácil de auditar y actualizar
- **Automatización**: Generación de docs con agentes, validación con CI/CD
- **Versionamiento**: Sincronización CHANGELOG.md y COMPATIBILITY.md con releases

---

## 2. Estado Actual

### 2.1 Estructura MkDocs
- **Site**: `mkdocs.yml` (v1.5+, Material theme) / `zensical.toml` (alternativo, compatible)
- **Webs de referencia oficial** (consultar con `--verify-tools` para validar versiones y plugins):
  - MkDocs: `https://www.mkdocs.org/about/release-notes/`
  - Material for MkDocs: `https://squidfunk.github.io/mkdocs-material/plugins/`
  - Zensical: `https://zensical.org/`
- **Secciones existentes**:
  - ✅ Guías (DUPLICATE_PROJECT_GUIDE, NEXT_STEPS, README_DUPLICADOR, ARCHITECTURE_VISUAL)
  - ✅ Funcional (`docs/functional/`) — 8 módulos
  - ✅ Ejemplos (`docs/examples/`) — 10+ ejemplos de uso
  - ✅ API/Referencias (`docs/api/`) — 8 módulos técnicos
  - ✅ Compatibilidad y Changelog

### 2.2 Archivos Generados
- Funcional: 8 archivos en `docs/functional/`
- Técnico: 8 archivos en `docs/api/`
- Generador: mkdocstrings integrado (Python docstrings → HTML)

### 2.3 Herramientas y Agentes
| Componente | Ubicación | Estado |
|------------|-----------|--------|
| **Configuración IA** | `CLAUDE.md`, `copilot-instructions.md` | ✅ Existente |
| **Agent: config-reviewer** | `.github/agents/config-reviewer.agent.md` | ✅ Existente |
| **Agent: documentation-generator** | `.github/agents/documentation-generator.agent.md` | ✅ Existente — soporta `--verify-tools` |
| **Agent: documentation-reviewer** | `.github/agents/documentation-reviewer.agent.md` | ✅ Existente |
| **Prompt: config_review** | `.github/prompts/config_review.prompt.md` | ✅ Existente |
| **Prompt: functional_doc** | `.github/prompts/functional_doc.prompt.md` | ✅ Existente |
| **Prompt: technical_doc** | `.github/prompts/technical_doc.prompt.md` | ✅ Existente |
| **Prompt: landing_doc** | `.github/prompts/landing_doc.prompt.md` | ✅ Existente |
| **Prompt: documentation_review** | `.github/prompts/documentation_review.prompt.md` | ✅ Existente |

### 2.4 Gaps Actuales
- ✅ Referencia OneDrive → reemplazada por referencias internas al repositorio (§4)
- ✅ Estructura funcional y técnica → mapeada explícitamente en §4.2
- ✅ Roles de agentes → documentados en orden de ejecución en §5
- ⚠️ Seguridad y Rendimiento → cubiertos como opcionales en §3.2 y §4.3; excluidos del nav por defecto

---

## 3. Propuesta de Cambios

### 3.1 Arquetipo 1 — Documentación Funcional (`docs/functional/`)

**Propósito**: Responder "¿Qué hace y por qué?"

**Audiencia**: Product Owner, QA, responsables de negocio.

**Ubicación**: `docs/functional/[módulo].md`

**Estructura obligatoria** (secciones numeradas, en este orden):

```
# [Título del Módulo/Funcionalidad]

## 1. Descripción General
Contexto de negocio y objetivo (2-3 párrafos, sin jerga técnica).

## 2. Reglas de Negocio
Tabla: | Regla | Descripción | Impacto si se viola |

## 3. Casos de Uso
### Flujo principal
Diagrama Mermaid sequenceDiagram (actor → módulo → salida).
### Flujos alternativos y de error
Variantes y casos de error verificables. Si no hay, "No aplica para este módulo."

## 4. Criterios de Aceptación      ← PENDIENTE QA (placeholder hasta validación)
Estructura prevista: Tabla | ID | Criterio | Verificable con |
Redacción: "Dado X, cuando Y, entonces Z."

## 5. Glosario y Términos
Tabla: | Término | Definición |
Si no hay términos específicos: "No aplica para este módulo."
```

**Regla de sección vacía**: Si un subapartado queda vacío, escribe `*No aplica para este módulo.*` — nunca omitas la sección.

**Diagramas recomendados**: `sequenceDiagram` (flujo principal), `flowchart TD` (decisiones).

---

### 3.2 Arquetipo 2 — Documentación Técnica (`docs/api/`)

**Propósito**: Responder "¿Cómo está construido?"

**Audiencia**: desarrolladores, ingenieros de datos, DBAs.

**Ubicación**: `docs/api/[módulo].md`

**Nota**: Los archivos generados automáticamente por `mkdocstrings` (`bulk.md`, `comparator.md`, `managers.md`, `reporters.md`, `exceptions.md`, `index.md`) están excluidos de este arquetipo.

**Estructura obligatoria** (secciones numeradas, en este orden):

```
# [Nombre del Componente/Módulo]

[Párrafo introductorio de una frase: responsabilidad exacta del módulo.]

## 1. Arquitectura y Diseño
Diagrama Mermaid (flowchart TD, classDiagram, sequenceDiagram o architecture-beta).
Máximo 12 nodos. Ver criterios de selección en docs.instructions.md.

## 2. Modelo de Datos / Contratos
### API pública
Tabla: | Función/Clase | Firma simplificada | Descripción | Retorna |
### Contrato de entrada
Tabla: | Parámetro | Tipo | Descripción | Restricciones |
### Contrato de salida
Tipos, estructura y casos especiales.
### Errores y casos especiales
Excepciones propias del módulo y entradas inválidas.

## 3. Componentes y Clases
Responsabilidad de cada clase exportada.
Para módulos con una sola clase: "No aplica para este módulo."

## 4. Dependencias y Requisitos
Tabla: | Dependencia | Propósito | Requerida | Comportamiento sin ella |

## 5. Ejemplos Relacionados      ← OBLIGATORIO (enlace bidireccional con Arquetipo 4 §5)
Lista de enlaces a docs/examples/ con descripción de lo que ilustra cada uno.
Si no existe ningún ejemplo del módulo: "Pendiente — crear ejemplo en docs/examples/[nombre].md"
```

**Regla de sección vacía**: Si un subapartado queda vacío, escribe `*No aplica para este módulo.*`.

**Diagramas recomendados**: Ver tabla en `docs.instructions.md` y en `technical_doc.prompt.md`.

---

### 3.3 Arquetipo 3 — Guías de Usuario o Configuración (`docs/guides/`)

**Propósito**: Responder "¿Cómo se usa/instala/opera?"

**Audiencia**: usuarios finales, operadores y desarrolladores que necesitan una guía how-to.

**Ubicación**: `docs/guides/[nombre_guia].md` (siempre en `guides/`, nombre en minúsculas con guiones bajos)

**Estructura obligatoria** (secciones numeradas, en este orden):

```
# [Guía de X / Tutorial de Y]

## 1. Objetivo
Qué conseguirás al seguir esta guía (1 párrafo). Distingue how-to ("instalar X") vs tutorial ("entender X").

## 2. Requisitos Previos
Lista: herramientas, versiones, accesos o estado inicial requerido.

## 3. Pasos
Procedimiento secuencial numerado con bloques de código. Cada paso atómico y verificable.

## 4. Verificación
Comando + output esperado para confirmar éxito.

## 5. Variantes y Solución de Problemas
Tabla: | Escenario/Error | Causa probable | Solución |
Incluye alternativas al flujo principal y configuraciones opcionales.
Si no hay casos conocidos: "No aplica para este módulo."
```

**Excepciones aceptadas**: `docs/index.md` y `docs/legacy-versions.md` están exentos de arquetipo (páginas especiales).

---

### 3.4 Arquetipo 4 — Guías de Ejemplos de Código (`docs/examples/`)

**Propósito**: Responder "¿Cómo se implementa?"

**Audiencia**: desarrolladores que quieren implementar un patrón concreto.

**Ubicación**: `docs/examples/[nombre].md`

**Estructura obligatoria** (secciones numeradas, en este orden):

```
# Ejemplo: [Nombre del Patrón/Funcionalidad]

## 1. Contexto del Ejemplo
Qué problema concreto resuelve este código (1-2 párrafos).

## 2. Implementación de Referencia
Exclusivamente: --8<-- "examples/[ruta].py"

## 3. Explicación del Código
Puntos críticos: concurrencia, rendimiento, contratos.
Para ejemplos triviales: "No aplica para este módulo."

## 4. Ejecución y Pruebas
Comando exacto + output esperado si determinista.

## 5. Referencias Relacionadas      ← OBLIGATORIO (enlace bidireccional con Arquetipo 2 §5)
- Documentación funcional: [enlace a docs/functional/...]
- Referencia técnica: [enlace a docs/api/...]
- Ejemplos relacionados: [otros ejemplos del mismo área si existen]
```

**Regla de snippet**: En `## 2.` usar siempre `--8<--`. Si el `.py` no existe, crearlo antes de referenciar.

---

### 3.5 Arquetipo 5 — Decisión Arquitectónica / ADR (`docs/adr/`)

**Propósito**: Responder "¿Por qué se decidió así?"

**Audiencia**: arquitectos de software, tech leads, responsables de plataforma.

**Ubicación**: `docs/adr/ADR-[NNN]-[nombre-kebab-case].md`

**Prompt**: `.github/prompts/architecture_doc.prompt.md`.

**Secciones obligatorias**: Contexto y Problema → Decisión → Consecuencias → Alternativas Consideradas → Estado y Revisión.

Documenta **una decisión concreta con trade-offs**, no la visión global del sistema (esa es la Variante C del Arquetipo 6). Los documentos de planificación (roadmap, release plans) se marcan con `<!-- arquetipo: informativo-libre -->` y quedan exentos.

---

### 3.6 Arquetipo 6 — Páginas de Navegación Principal (`docs/` raíz)

**Propósito**: Responder "¿Qué es, cómo lo instalo y cómo está organizado?" en las páginas de entrada.

**Audiencia**: cualquier visitante que llega a la documentación por primera vez.

**Ubicación**: `docs/index.md` (Inicio), `docs/installation.md` (Instalación), `docs/architecture.md` (Arquitectura).

**Prompt**: `.github/prompts/landing_doc.prompt.md` (tres variantes A/B/C, 5 secciones cada una).

Estas páginas entran directamente en `nav:` (nivel raíz), no bajo `functional/`, `api/`, `examples/` ni `adr/`:

- **Variante A — Inicio**: Identidad y Propósito → Capacidades → Quick Start → Mapa de la Documentación → Compatibilidad y Soporte.
- **Variante B — Instalación**: Requisitos → Instalación del Paquete → Drivers por Motor → Verificación → Solución de Problemas.
- **Variante C — Arquitectura** (modelo **arc42-lite + C4**): Visión General y Objetivos de Calidad (C4 nivel 1) → Mapa de Módulos / Building Blocks (C4 nivel 3) → Flujo en Ejecución (Runtime) → Conceptos Transversales y Estándares No Funcionales (checklist NFR) → Decisiones, Extensión y Límites (enlace a `docs/adr/`).

**Distinción con otros arquetipos**:
- El Arquetipo 5 (`architecture_doc`) documenta **un ADR concreto** (decisión con trade-offs, formato MADR-lite); la Variante C es la **vista panorámica del sistema** (arc42-lite + C4) y enlaza al log de ADR. Ambas conviven bajo la sección "Arquitectura" del nav y forman un modelo único: panorámica + decisiones.
- El Arquetipo 3 (`guide_doc`) cubre guías genéricas (async, drivers, troubleshooting); la Variante B es específica de instalación del paquete y drivers.

**Excepción**: `docs/index.md` y `docs/legacy-versions.md` seguían exentos en v1; con este arquetipo `index.md` pasa a regirse por la Variante A. `legacy-versions.md` permanece exento.

---

### 3.7 Arquetipo 7 — Guía de Incorporación para Desarrolladores (`docs/ONBOARDING_DEV.md`)

**Propósito**: Responder "¿Cómo me incorporo al proyecto y pongo en marcha mi entorno?"

**Audiencia**: desarrolladores que se incorporan al proyecto por primera vez.

**Ubicación**: `docs/guides/onboarding_dev.md` (todos los proyectos — mismo convenio que el resto de guías)

**Prompt**: `.github/prompts/onboarding_dev.prompt.md`

**Secciones obligatorias** (11, en este orden):

```
## 1. Prerequisitos del Entorno      — tabla: Herramienta | Versión mínima | Verificar con | Notas
## 2. Obtener el Código              — clone, rama de trabajo, submódulos/dependencias privadas
## 3. Configurar el Entorno          — venv/IDE, credenciales, registros privados, ficheros de config
## 4. Primera Compilación/Instalación — comando principal + tabla de errores frecuentes
## 5. Infraestructura Local           — BD, contenedores, servicios; "*No aplica*" si librería stateless
## 6. Ejecutar la Aplicación          — puertos, URLs, credenciales; "*No aplica*" si librería
## 7. Mapa del Código                 — árbol simplificado, responsabilidad por módulo/paquete, regla de capas
## 8. Convenciones y Herramientas     — lint, format, tipos, tests — verificar contra SHARED_INSTRUCTIONS.md
## 9. Flujo de Trabajo Git            — ramas, Conventional Commits, PR/MR
## 10. Verificación del Entorno       — tabla: Verificación | Comando | Output esperado
## 11. Recursos y Referencias         — .ai/*.md, docs/ relevantes, normativa, contacto
```

**Regla de sección vacía**: §5 y §6 **siempre** están presentes. Si el proyecto no requiere infraestructura o no tiene servidor, escribir `*No aplica para este proyecto.*` con explicación breve. Nunca omitir la sección.

**Distinción con Arquetipo 3** (Guías de Usuario):
- Arquetipo 3 documenta **cómo usar o configurar una funcionalidad** (guía how-to para usuarios finales).
- Arquetipo 7 documenta **cómo unirse al equipo de desarrollo** (entorno, código, convenciones, workflow).

**Cuándo actualizar**: en cada release mayor, tras cambios de stack o infraestructura, o cuando un nuevo desarrollador detecte que la guía está desactualizada.

---

### 3.8 Arquetipo 8 — Trazabilidad Normativa (`docs/normativa/`) — **Condicional**

**Propósito**: Responder "¿Qué obligaciones legales o reglamentarias están cubiertas por este sistema?"

**Condición de activación**: SOLO si el proyecto hace referencia explícita a leyes, decretos,
directivas, normas UNE o cualquier normativa de obligado cumplimiento. Verificar en `.ai/product.md`
o `README.md`. Si no hay normativa de referencia → **este arquetipo no aplica** y la carpeta
`docs/normativa/` no se crea.

> **Este proyecto (doc_organize)**: librería Python de operaciones de base de datos sin normativa de
> referencia explícita. El arquetipo no aplica actualmente. Si en el futuro se incorpora
> normativa (ej. RGPD, LOPD-GDD para datos procesados, normas de accesibilidad), aplicar entonces.

**Audiencia**: auditores de cumplimiento, técnicos de normativa, responsables de proyecto.

**Ubicación**: `docs/normativa/<abbrev_norma>_traceability.md`  
**Naming**: nombre en minúsculas con guión bajo (ej. `ley39_rd174_traceability.md`, `rgpd_traceability.md`)

**Estructura obligatoria** (secciones en este orden):

```
# Trazabilidad Normativa — <Nombre de las normas>

(versión del sistema analizado + fecha de revisión)

## Propósito

## 1. <Norma A> — <Nombre corto>
  ### 1.1 <Grupo de artículos>
  Tabla: | Artículo | Obligación | Módulo/servicio | Doc de referencia | Cobertura |
  ### ...

## 2. <Norma B> — ...

## N. Resumen de gaps por severidad
  ### Nivel 1 — Crítico (riesgo de incumplimiento o auditoría bloqueada)
  Tabla: | ID | Gap | Norma | Módulo afectado | Acción recomendada |
  ### Nivel 2 — Importante (gap documental, dificulta mantenimiento)
  ### Nivel 3 — Mejora

## N+1. Normativa complementaria referenciada
Tabla: | Norma | Objeto | Cobertura en el sistema |

## N+2. Próximas acciones priorizadas
```

**Leyenda de cobertura**:

| Símbolo | Significado |
|---------|-------------|
| ✅ | Cubierto — implementado y documentado |
| ⚠️ | Parcial — implementado pero con gap documental o funcional conocido |
| ❌ | Gap — no implementado o sin documentación verificable |
| 🔍 | A verificar — evidencia insuficiente para determinar cobertura |

**Sección MkDocs** (solo si el arquetipo aplica):

```yaml
- Normativa:                                                     # Entre "Funcional" y "Arquitectura"
    - Trazabilidad <Nombre norma>: normativa/<codigo>_traceability.md
```

**Cuándo crear**: al comenzar el proyecto si la normativa es conocida desde el inicio, o en la
primera auditoría de cumplimiento formal.

**Cuándo actualizar**:
- Cuando cambia la normativa de referencia (modificación legal, nuevo artículo)
- Cuando se implementa un módulo que cubre un gap documentado
- En cada revisión de versión mayor que afecte lógica de negocio regulada

**Restricciones estrictas**:
- No inventar contenido normativo sin verificar contra el texto oficial
- Marcar como 🔍 cualquier artículo sin evidencia suficiente en código o documentación
- No documentar como ✅ ningún artículo sin módulo del sistema identificado
- No copiar texto legal verbatim; describir la obligación en términos del sistema

**Prompt de generación**: `.github/prompts/normative_traceability.prompt.md`

---

### 3.9 Estándar de la Sección Guías (`docs/guides/`)

Esta sección define el contrato mínimo y las reglas de nomenclatura para **todos los proyectos**.

#### Convenio de nombres

| Regla | Correcto | Incorrecto |
|---|---|---|
| Nombre en minúsculas | `connection_guide.md` | `CONNECTION_GUIDE.md` |
| Palabras con guión bajo | `async_guide.md` | `async-guide.md`, `asyncGuide.md` |
| Ubicación siempre en `guides/` | `docs/guides/troubleshooting.md` | `docs/TROUBLESHOOTING.md` |
| Sin subcarpetas dentro de `guides/` | `guides/deployment_guide.md` | `guides/ops/deployment.md` |

#### Conjunto mínimo obligatorio

| Fichero | Arquetipo | Contenido | Mandatorio |
|---|---|---|---|
| `guides/onboarding_dev.md` | 7 | Incorporación: entorno, código, convenciones, verificación | ✅ Siempre |
| `guides/troubleshooting.md` | 3 | Problemas frecuentes por categoría + solución verificable | ✅ Siempre |

#### Guías adicionales según tipo de proyecto

| Tipo de proyecto | Guías recomendadas |
|---|---|
| Librería Python (doc_organize) | `connection_guide.md`, `async_guide.md`, `exceptions.md`, `migration_guide.md`, + guías de drivers y herramientas IA |
| Aplicación con servidor (dpss) | `despliegue_docker.md` o `deployment_guide.md` |
| Cualquier proyecto con herramientas IA | Subsección "Herramientas IA" en Guías: claude_code_guide.md, codex_guide.md, etc. |

#### Estructura de la sección en `mkdocs.yml`

```yaml
- Guías:
    - Incorporación para Desarrolladores: guides/onboarding_dev.md   # Siempre primero
    - [Grupos operativos según el proyecto]:                           # Conexión, Despliegue, etc.
        - [Guía específica]: guides/[nombre_guia].md
    - Errores y Diagnóstico:
        - Troubleshooting: guides/troubleshooting.md                  # Siempre en esta subsección
    - Herramientas IA:                                                 # Si el proyecto usa herramientas IA
        - [Nombre herramienta]: guides/[tool]_guide.md
```

#### Cuándo actualizar

- Al incorporar el primer desarrollador externo → generar `onboarding_dev.md` si no existe.
- Tras cambios de stack, build tool o infraestructura → actualizar `onboarding_dev.md`.
- Cuando se reporta un error no documentado → añadir a `troubleshooting.md`.
- Cuando se añade una herramienta IA nueva → añadir su guía en Herramientas IA.

---

## 4. Configuración Recomendada mkdocs.yml

La siguiente configuración es la **referencia estándar** para todos los proyectos.
Adapta los valores de `site_*`, `extra.version` y `nav` a cada proyecto; el resto es la base común.

### 4.1 Configuración Completa (Referencia)

```yaml
# ── Metadatos del sitio ──────────────────────────────────────────────────────
site_name: [Nombre del Proyecto]
site_description: [Descripción breve del proyecto]
site_author: [Autor / Equipo]
site_url: https://[usuario].github.io/[repo]

# ── Tema ─────────────────────────────────────────────────────────────────────
theme:
  name: material
  language: es
  features:
    # Navegación
    - navigation.tabs           # Pestañas principales en la barra superior
    - navigation.sections       # Agrupa entradas en secciones colapsables
    - navigation.top            # Botón "volver arriba"
    - toc.follow                # TOC sigue el scroll
    # Búsqueda
    - search.suggest
    - search.highlight
    # Código
    - content.code.copy         # Botón copiar en bloques de código
    - content.code.annotate     # Anotaciones en código
    - content.tabs.link         # Tabs de código sincronizadas

# ── Plugins ──────────────────────────────────────────────────────────────────
plugins:
  - search:
      lang: es

  # Opcional: muestra fecha de última modificación
  - git-revision-date-localized:  # pip install mkdocs-git-revision-date-localized
      type: date

  # Obligatorio si el proyecto es Python (docstrings → HTML)
  - mkdocstrings:               # pip install mkdocstrings[python]
      handlers:
        python:
          paths: [src]
          options:
            show_source: true
            show_root_heading: true

# ── Extensiones Markdown ─────────────────────────────────────────────────────
markdown_extensions:
  - admonition                  # Bloques de nota, warning, tip, etc.
  - tables
  - toc:
      permalink: true           # Anclas en encabezados

  # Resaltado de código
  - pymdownx.highlight:
      use_pygments: true
      anchor_linenums: true
  - pymdownx.inlinehilite

  # Bloques de código con Mermaid
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format

  - pymdownx.snippets           # Incluir fragmentos de otros archivos
  - pymdownx.emoji:             # Emojis :material-check:
      emoji_index: !!python/name:pymdownx.emoji.twemoji
      emoji_generator: !!python/name:pymdownx.emoji.to_svg

# ── Extras ───────────────────────────────────────────────────────────────────
extra:
  version:
    provider: mike              # pip install mike (versionado multi-versión)
  # Publicar versión: mike deploy [X.Y.Z] latest --update-aliases
  social:                       # Opcional
    - icon: fontawesome/brands/github
      link: https://github.com/[usuario]/[repo]

# ── Navegación (Obligatoria) ─────────────────────────────────────────────────
nav:
  - Inicio: index.md

  - Guías:
      - Inicio Rápido: [guia-rapida].md
      - Próximos Pasos: NEXT_STEPS.md
      - Arquitectura Visual: ARCHITECTURE_VISUAL.md

  - Funcional:
      - Contratos Base: functional/base.md
      - [Módulo 1]: functional/[modulo1].md
      - [Módulo 2]: functional/[modulo2].md

  - Ejemplos:
      - Inicio: examples/README.md
      - API y CLI:
          - [Ejemplo 1]: examples/[ejemplo1].md
      - Herramientas de IA:
          - [Guía IA]: examples/[guia-ia].md

  - API & Referencias:
      - Técnica:
          - Contratos Base: api/base.md
          - [Módulo 1]: api/[modulo1].md
      - Compatibilidad: COMPATIBILITY.md
      - Changelog: CHANGELOG.md
      - Troubleshooting: TROUBLESHOOTING.md
```

---

### 4.2 Navegación de doc_organize (Implementación Actual)

Mapeo concreto del proyecto sobre la estructura anterior.
La fuente canónica de la navegación es siempre `mkdocs.yml`; este bloque refleja
los grupos principales como referencia rápida:

```yaml
nav:
  - Inicio: index.md
  - Instalación: INSTALLATION.md

  - Documentación Funcional:
      - Managers:
          - Gestión de Conexiones (Sync): functional/managers-sync.md
          - Ciclo de vida de sesión sincrónica: functional/managers-sync-session-lifecycle.md
          - Gestión de Conexiones (Async): functional/managers-async.md
      - Metadatos e Introspección:
          - Extracción de Metadatos: functional/metadata-extraction.md
          - Selección de Driver: functional/drivers-selection.md
      - Operaciones de Datos:
          - Operaciones Bulk (CRUD): functional/bulk-operations.md
          - Auditoría de Operaciones Bulk: functional/bulk-audit.md
      - Queries y Validación:
          - Registro de Queries: functional/query-registry.md
          - Ejecución de Consultas: functional/query-execution.md
          - Patrón de Validadores: functional/validators-pattern.md
      - Comparación de Esquemas:
          - Comparador de Esquemas: functional/schema-comparison.md
      - Migración de Esquemas:
          - Migración Oracle (origen): functional/migrate-oracle-mariadb.md
          - Migración MariaDB (origen): functional/migrate-mariadb-source.md
          - Migración SQL Server (origen): functional/migrate-sqlserver-source.md
          - Migración PostgreSQL (origen): functional/migrate-postgresql-source.md
      - Análisis de Relaciones:
          - Visualización de Grafos: functional/graph-analysis.md
      - Documentación de BD:
          - Generación de Documentación: functional/database-documentation.md

  - Referencia Técnica:
      - Managers: api/managers-sync.md  # y otros bajo api/managers-*.md
      - Metadatos: api/metadata-manager.md
      - Conexiones: api/connection-factory.md
      - Bulk: api/bulk-crud.md
      - Queries: api/query-system.md
      - Migración: api/migrate-oracle-mariadb.md  # y otros bajo api/migrate-*.md
      - Análisis: api/analysis.md
      - Documentación BD: api/database-documentation.md
      - Excepciones: api/exceptions.md

  - Ejemplos:                              # subsecciones por área, igual que Referencia Técnica
      - Metadatos e Introspección:
          - Conectar e Introspeccionar: examples/example-connect-introspect.md
      - Operaciones Bulk:
          - Bulk Insert desde CSV: examples/bulk_insert_csv.md
      - Comparación de Esquemas:
          - Comparación de Esquemas: examples/schema_comparison.md
      - Migración de Esquemas:
          - Migración Oracle (origen): examples/migrate-oracle-mariadb.md
          - Migración MariaDB (origen): examples/migrate-mariadb-source.md
      # ... resto de ejemplos agrupados por área en mkdocs.yml

  - Guías:                                 # subsecciones temáticas (how-tos transversales)
      - Incorporación para Desarrolladores: guides/onboarding_dev.md
      - Conexión y Drivers:
          - Programación Asíncrona: guides/async_guide.md
          - Drivers PostgreSQL: guides/postgresql_driver_guide.md
      - Errores y Diagnóstico:
          - Excepciones: guides/exceptions.md
          - Troubleshooting: guides/troubleshooting.md
      - Herramientas IA:
          - Guía completa (VS Code): guides/doc_generation_vscode_guide.md
      # ... resto de guías agrupadas por tema en mkdocs.yml
```

---

### 4.3 Secciones Opcionales (Agregar según necesidad)

| Sección | Ubicación | Cuándo agregar |
|---------|-----------|----------------|
| **Seguridad** | `docs/security/` | Proyectos con auth, datos sensibles o auditoría |
| **Tutoriales** | `docs/tutorials/` | Curvas de aprendizaje complejas |
| **FAQ** | `docs/faq.md` | Preguntas frecuentes por módulo |
| **Glosario** | `docs/glossary.md` | Dominio específico con muchos términos |
| **Web Interface** | `docs/web-interface.md` | Si el proyecto tiene UI web |
| **Arquitectura Web API** | `docs/architecture/web-api.md` | Si existe `src/**/web/` con FastAPI/Flask/etc. |
| **Microservicios** | `docs/architecture/microservices.md` | Si el proyecto expone o consume múltiples servicios |
| **Docker / Contenedores** | `docs/architecture/docker.md` | Si existe `Dockerfile` o `docker-compose.yml` en el repo |
| **Contributing** | `docs/contributing.md` | Proyectos open source |
| **Normativa** | `docs/normativa/` | **Solo** si el proyecto referencia leyes, decretos o normativas de obligado cumplimiento (Arquetipo 8) |

---

## 5. Roles de Agentes y Flujo de Trabajo

### Flujo Recomendado para Documentación

| Fase | Agente | Tarea | Entrada | Salida |
|------|--------|-------|---------|--------|
| **1. Planificación** | `Plan Architect` | Validar estructura actual vs propuesta | `mkdocs.yml` + código fuente | `PLAN` + `AUDIT_PLAN` |
| **2. Validación IA** | `config-reviewer` | Revisar coherencia en `CLAUDE.md`, `copilot-instructions.md` | Archivos IA | Findings + recomendaciones |
| **3. Exploración** | `Explore` | Mapear módulos existentes vs faltantes | `src/`, `docs/` | Matriz de cobertura |
| **4. Generación** | `documentation-generator` | Crear/actualizar docs funcional + técnica | Código fuente + prompts | Archivos en `docs/` + `mkdocs.yml` |
| **5. Auditoría** | `documentation-reviewer` | Validar completitud, ejemplos, coherencia | Docs generadas | Findings + mejoras |
| **6. Verificación de config** (opt-in `--verify-tools`) | `documentation-generator` | Fetch webs oficiales — validar plugins y versiones en `mkdocs.yml` / `zensical.toml` | Config + webs MkDocs/Zensical/PyPI | Discrepancias por severidad |
| **6b. Verificación de build** (opt-in `--verify-build`) | `documentation-generator` | Build + inspección HTML generado — alias bug, snippets, Mermaid, nav | `site/` (Modo A) o `localhost:8000` (Modo B `--serve`) | Hallazgos por página + acciones recomendadas |
| **7. Cierre** | `Version Closer` | Sincronizar `CHANGELOG.md` + `COMPATIBILITY.md` | Cambios completados | Release notes |

### Cuándo Usar Cada Agente

| Agente | Cuándo | Comando | Scope |
|--------|--------|---------|-------|
| `documentation-generator` | Generar docs por primera vez o actualizar módulo completo | `/new-feature "generar doc [módulo]"` | `src/` → `docs/` |
| `documentation-reviewer` | Auditar docs existentes (calidad, ejemplos, claridad) | `/audit-code` | `docs/functional/`, `docs/api/` |
| `config-reviewer` | Sincronizar instrucciones IA entre archivos de configuración | `/config-review` | `CLAUDE.md`, `copilot-instructions.md` |
| `Plan Architect` | Cambio estructural en `mkdocs.yml` o nuevo módulo importante | `/new-feature` o `/refactor` | `mkdocs.yml` |

---

## 6. Restricciones y Decisiones

### Restricciones Generales

- ✅ **MkDocs v1.5+** — No usar versiones antiguas, usar Material theme
- ✅ **Diagramas Mermaid** — Agnóstico a Graphviz, integrado en mkdocs
- ✅ **Lenguaje agnóstico** — Ejemplos Python en carpetas separadas si hay múltiples lenguajes
- ✅ **NO inventar código** — Todos los ejemplos deben validarse contra `src/`
- ✅ **Encoding UTF-8** — Todos los archivos markdown
- ❌ **NO guardar en OneDrive o Google Drive** — Usar referencias internas al repositorio

### Decisiones Críticas

1. **Separación Funcional ↔ Técnica**: Cada módulo tiene 2 documentos separados, no mezcladas
   - Funcional: `docs/functional/[módulo].md` (usuario final)
   - Técnica: `docs/api/[módulo].md` (desarrollador)

2. **Ubicaciones Fijas** (No cambiar sin consenso):
   - Funcional: `docs/functional/[módulo].md`
   - Técnica: `docs/api/[módulo].md`
   - Ejemplos: `docs/examples/[caso].md` (ficheros **planos en disco**, sin subcarpetas por tipo).
     En `nav:` **se agrupan en subsecciones por área funcional**, igual que `Referencia Técnica`
     y `Documentación Funcional` (ver `docs.instructions.md` → "Agrupación en subsecciones por área").
   - Guías: `docs/guides/[nombre].md` (ficheros en carpeta `guides/`, **nombre siempre en minúsculas con guiones bajos**).
     En `nav:` **se agrupan en subsecciones temáticas** (Incorporación, Conexión y Drivers, Errores y Diagnóstico,
     Rendimiento, Migración de Versión, Herramientas IA…), no por módulo.

3. **Actualización de mkdocs.yml**: Automatizada con `mkdocstrings` + agente `documentation-generator`

4. **Build CI/CD**: `mkdocs build` validado en cada PR, detecta links rotos

5. **Versionamiento**: Sincronizar CHANGELOG.md + COMPATIBILITY.md según `.github/instructions/sync.instructions.md`

---

## 7. Cómo Proceder

Los pasos corresponden 1:1 con las fases de §5.

### Paso 1: Planificar (20 min)
```text
@Plan Architect
Validar estructura docs/ vs mkdocs.yml real. Entregar PLAN + AUDIT_PLAN.
```

### Paso 2: Validar Configuración IA (30 min)
```text
@config-reviewer
Revisar coherencia propuesta vs código real en src/.
Validar que estructura propuesta es implementable.
```

### Paso 3: Explorar Módulos (15 min)
```text
@Explore
Mapear módulos en src/ vs docs/. Identificar faltantes. Solo lectura.
```

### Paso 4: Generar/Actualizar Documentación (1-2 h)
```text
@documentation-generator
Generar docs para módulo específico O proyecto completo.
Actualiza mkdocs.yml automáticamente.
```

### Paso 5: Auditar Documentación (30 min)
```text
@documentation-reviewer
Validar ejemplos contra código real.
Verificar coherencia, completitud, claridad.
Reportar mejoras.
```

### Paso 6: Integración y Build (15 min)
```text
@Code Auditor
Ejecutar mkdocs build. Verificar links. Reportar errores de build.
```

### Paso 7: Sincronizar Versión (20 min)
```text
@Version Closer
Actualizar CHANGELOG.md, COMPATIBILITY.md.
Generar release notes.
```

### Criterio de Completitud

La estandarización se considera **completa** cuando:

- [ ] `mkdocs build --strict` finaliza sin errores ni warnings de links rotos
- [ ] Todos los módulos en `src/` tienen doc funcional (`docs/functional/`) y técnica (`docs/api/`)
- [ ] Todos los archivos referenciados en `docs/examples/` existen en disco
- [ ] `CHANGELOG.md` y `COMPATIBILITY.md` reflejan la versión actual de `pyproject.toml`
- [ ] Las instrucciones IA (`CLAUDE.md`, `copilot-instructions.md`) son coherentes con el código real
- [ ] Todos los documentos en `nav:` (excepto `legacy-versions.md`) tienen exactamente las secciones numeradas de su arquetipo asignado (`index.md`, `INSTALLATION.md` y `ARCHITECTURE.md` se rigen por el Arquetipo 6)
- [ ] Las secciones vacías contienen `*No aplica para este módulo.*` en lugar de estar omitidas
- [ ] Los prompts `.github/prompts/guide_doc.prompt.md` y `example_doc.prompt.md` existen y son coherentes con Arquetipos 3 y 4

---

## 📎 Referencias Internas

- [`.github/SHARED_INSTRUCTIONS.md`](.github/SHARED_INSTRUCTIONS.md) — Fuente canónica de arquitectura
- [`CLAUDE.md`](CLAUDE.md) — Instrucciones para Claude Code
- [`.github/copilot-instructions.md`](.github/copilot-instructions.md) — Instrucciones para Copilot Chat
- [`.github/instructions/docs.instructions.md`](.github/instructions/docs.instructions.md) — Guía de estilo para documentación
- [`pyproject.toml`](pyproject.toml) — Versión actual del proyecto
- [`.ai/product.md`](.ai/product.md) — Contexto de producto
- [`mkdocs.yml`](mkdocs.yml) — Configuración actual de MkDocs
- [`.github/instructions/sync.instructions.md`](.github/instructions/sync.instructions.md) — Sincronización de versiones
