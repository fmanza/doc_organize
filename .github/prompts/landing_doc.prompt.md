# Prompt: landing_doc — Páginas de Navegación Principal (Arquetipo 6)

Genera o actualiza las **páginas de navegación principal** de **doc_organize** —
**Inicio**, **Instalación** y **Arquitectura**— usando solo información verificable del código,
`pyproject.toml`, README, `zensical.toml`, `.github/SHARED_INSTRUCTIONS.md` y `docs/`.

Estas páginas son de nivel superior (entran directamente en `nav`, no bajo `functional/`, `api/`,
`examples/` ni `adr/`). Cada una tiene su propia plantilla de 5 secciones; **elige la plantilla según
la página solicitada** y respétala en el orden exacto.

---

## Instrucción al modelo

```
Actúa como technical writer y arquitecto de software especializado en las páginas de entrada
de la documentación de una librería Python.

Analiza el contexto real del repositorio. No asumas capacidades, módulos, comandos, motores
ni outputs que no aparezcan en el código real, pyproject.toml, README, zensical.toml o docs/.

Identifica cuál de las tres páginas debes generar y aplica SU plantilla:

═══════════════════════════════════════════════════════════════════════════════
 VARIANTE A — INICIO  (docs/index.md)
═══════════════════════════════════════════════════════════════════════════════

# [Nombre del Proyecto]

[Una frase de propósito: qué es y para quién, sin jerga de marketing.]

**Version:** [X.Y.Z de pyproject.toml] | **Status:** [classifier real] | **Python:** [requires-python]

## 1. Identidad y Propósito
Qué problema resuelve la librería (1-2 párrafos). Audiencia objetivo.
La versión, estado y Python mínimo deben coincidir con pyproject.toml (no inventes).

## 2. Capacidades Principales
Lista de capacidades reales (✅) verificadas contra la API pública de src/__init__.py.
Incluye la matriz de soporte por motor (sync/async) solo con los motores realmente soportados.

## 3. Quick Start
Instalación mínima (un comando) + el ejemplo ejecutable más corto posible.
El código debe importar solo símbolos exportados en doc_organize.__all__.
Usa SQLite en memoria si necesitas un ejemplo sin servidor externo.

## 4. Mapa de la Documentación
Tabla: | Sección | Para qué sirve | Enlace |
Una fila por cada grupo del nav (Instalación, Funcional, Técnica, Ejemplos, Guías, Arquitectura).
Usa enlaces relativos a páginas que existan en docs/.

## 5. Compatibilidad y Soporte
Matriz por motor (Conexión sync/async, driver) + enlaces a Compatibilidad/Changelog si existen.
Nota explícita de los motores SIN async, si los hay.

═══════════════════════════════════════════════════════════════════════════════
 VARIANTE B — INSTALACIÓN  (docs/INSTALLATION.md)
═══════════════════════════════════════════════════════════════════════════════

# Guía de Instalación — [Nombre del Proyecto]

## 1. Requisitos Previos
Python mínimo (de requires-python), pip actualizado, accesos de red, dependencia interna
(p. ej. `util @ git+...`) si la hay. Solo requisitos verificables en pyproject.toml.

## 2. Instalación del Paquete
Comando pip básico + extras opcionales REALES de [project.optional-dependencies].
Tabla: | Extra | Comando | Para qué |
No inventes extras: usa exactamente los nombres declarados en pyproject.toml.

## 3. Drivers por Motor
Los drivers de BD se instalan por separado. Tabla:
| Motor | Driver sync | Driver async | Comando de instalación |
Solo motores realmente soportados por la librería.

## 4. Verificación
Snippet ejecutable (preferentemente SQLite en memoria) + output esperado exacto en comentario.
Debe usar solo API pública. Incluye además una variante de verificación para un motor con servidor.

## 5. Solución de Problemas
Tabla: | Error / Síntoma | Causa probable | Solución |
Errores reales de drivers/conexión/pool. Si no hay casos: "*No aplica para este módulo.*"

═══════════════════════════════════════════════════════════════════════════════
 VARIANTE C — ARQUITECTURA  (docs/ARCHITECTURE.md)
═══════════════════════════════════════════════════════════════════════════════

# Arquitectura del Sistema — [Nombre del Proyecto]

[Una frase: estilo arquitectónico y propósito global. Es la VISTA PANORÁMICA del sistema
(modelo arc42-lite + C4), NO un ADR individual: las decisiones puntuales viven en docs/adr/.]

> Las 5 secciones mapean un subconjunto de arc42: §1≈arc42 1+3 (objetivos+contexto, C4 nivel 1),
> §2≈arc42 5 (building blocks, C4 nivel 3), §3≈arc42 6 (runtime), §4≈arc42 8+10 (transversal+calidad),
> §5≈arc42 9+11 (decisiones+riesgos).

## 1. Visión General y Objetivos de Calidad
Estilo arquitectónico (capas / niveles), principios rectores y frontera de la librería
(qué hace y qué deja fuera). Basado en .github/SHARED_INSTRUCTIONS.md, no en suposiciones.
Incluye:
- Tabla de **objetivos de calidad** (máx. 3-5): | Objetivo de calidad | Por qué importa |
- **Diagrama de contexto (C4 nivel 1)** en Mermaid (`flowchart`, máx. 12 nodos): quién consume
  la librería y contra qué sistemas externos opera (motores de BD, dependencias). C4Context nativo
  de Mermaid es opcional (experimental); preferir `flowchart` por estabilidad de render.

## 2. Mapa de Módulos (Building Blocks)
Vista estática equivalente a C4 nivel 3 (Component). Árbol real de src/[paquete]/ (refleja las
carpetas que existen) +
Tabla: | Módulo | Responsabilidad |
Una fila por módulo de primer nivel verificable en src/.

## 3. Flujo en Ejecución (Runtime)
Diagrama Mermaid (`flowchart TD` o `sequenceDiagram`, máx. 12 nodos) que muestre cómo fluye
una operación típica entre capas (p. ej. manager → factory → connection → executor → results).
Solo componentes que existan en src/.

## 4. Conceptos Transversales y Estándares No Funcionales
Dos bloques:
- **Conceptos transversales**: principios de diseño aplicados (SOLID operativo, logging, formato)
  y reglas de acceso transversales (p. ej. único punto autorizado para SQL de introspección).
- **Checklist no funcional** (tabla): | Dimensión | Requisito | Cómo se cumple |
  Dimensiones mínimas: Seguridad, Observabilidad, Rendimiento, Compatibilidad, Robustez/Errores, Tipado/Calidad.
  Cada fila debe anclarse a un mecanismo REAL del código (no aspiraciones). Usa `- [x]`/`- [ ]`
  para marcar lo ya cubierto vs pendiente.

## 5. Decisiones, Extensión y Límites
Tres bloques:
- **Decisiones arquitectónicas**: enlace al log de ADR (`docs/adr/`); citar los ADR cuando una
  regla transversal tenga decisión formal asociada.
- **Riesgos y deuda técnica** conocidos (verificables), o "*No aplica para este módulo.*".
- **Extensión y límites**: cómo extender de forma soportada (añadir motor, reporter, validador)
  y qué NO hacer (anti-patrones).

───────────────────────────────────────────────────────────────────────────────

Restricciones (todas las variantes):
- Si una sección queda vacía, escribe "*No aplica para este módulo.*" — nunca omitas la sección
- La versión, estado, Python, extras, motores y símbolos deben coincidir EXACTAMENTE con
  pyproject.toml y src/__init__.py — no inventes ni arrastres valores obsoletos
- Todo bloque de código Python debe usar solo símbolos exportados en `__all__`
- NO uses la directiva --8<-- aquí; embebe el código directamente en bloques fenced
- Enlaces siempre relativos y a páginas que existan en docs/
- Diagramas en Mermaid (no Graphviz); máximo 12 nodos
- Si falta información, añade subsección "### Pendiente de verificación" con preguntas concretas
- Responde SOLO con el Markdown de la página, sin texto introductorio ni cierre
```

---

## Cómo usar este prompt

### Modo página única — Claude Code

```
Genera/actualiza la página [Inicio | Instalación | Arquitectura] usando el
prompt en .github/prompts/landing_doc.prompt.md (Variante A/B/C correspondiente).
Verifica versión, extras y motores contra pyproject.toml y src/__init__.py.
Actualiza zensical.toml si la página es nueva o cambia de ubicación.
No inventes capacidades; marca como pendiente lo no verificable.
```

### Modo página única — Copilot Chat

```
#file:.github/prompts/landing_doc.prompt.md
#file:pyproject.toml
#file:zensical.toml

Genera la página [Inicio | Instalación | Arquitectura] aplicando la variante correspondiente.
```

---

## Páginas cubiertas por este arquetipo

| Página | Archivo | Variante | Entrada en `nav` |
|---|---|---|---|
| Inicio | `docs/index.md` | A | `Inicio` (raíz) |
| Instalación | `docs/INSTALLATION.md` | B | `Instalación` (raíz) |
| Arquitectura | `docs/ARCHITECTURE.md` | C | `Arquitectura` (raíz, junto a los ADR) |

**Diferencia con el Arquetipo 5 (`architecture_doc`)**: el Arquetipo 5 documenta **una decisión
arquitectónica concreta (ADR)**. Esta Variante C documenta la **visión global del sistema** (mapa de
módulos, capas, flujo). Ambas conviven bajo la sección "Arquitectura" del nav.

**Diferencia con el Arquetipo 3 (`guide_doc`)**: `guide_doc` cubre guías de configuración/uso genéricas
(async, drivers, troubleshooting). La Variante B es específica de **instalación del paquete y drivers**.

## Output esperado

Markdown con título H1 y las **5 secciones numeradas** (`## 1.`–`## 5.`) de la variante elegida.
Inicio y Arquitectura deben incluir al menos un enlace al resto de la documentación;
Instalación y la Variante A deben incluir al menos un bloque de código ejecutable verificable.
