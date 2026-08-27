# Prompt: technical_doc — Documentación técnica con Mermaid

Genera o actualiza diagramas Mermaid.js y documentación técnica para módulos de **doc_organize**,
basándote solo en código, configuración y documentación existente verificable.

## Instrucción al modelo

```
Actúa como arquitecto de software senior especializado en Python, procesamiento de documentos y documentación técnica.

⚠️ PROYECTO: doc_organize v0.1.0 Alpha (extracción/conversión de documentos, no bases de datos)
⚠️ GUARDRAIL: No inventar módulos no implementados. Si módulo está [TODO vX.X], marcar como tal.

Analiza el módulo [NOMBRE_MÓDULO] de doc_organize y la documentación existente relacionada.
No asumas dependencias, motores, APIs ni capacidades que no aparezcan en el código real,
`pyproject.toml`, README, `docs/` o `mkdocs.yml`.

Módulos IMPLEMENTADOS en v0.1.0: core/, utils/, __init__.py (todos parcialmente vacíos)
Módulos PLANEADOS (TODO): scanner/, converter/, cache/, dedup/, workflow/, web/

Genera documentación técnica en Markdown siguiendo el Arquetipo 2 con estas secciones en este orden exacto:

# [Nombre del Componente/Módulo]

[Una frase que describa la responsabilidad exacta del módulo en el sistema.]

## 1. Arquitectura y Diseño
Elige el tipo de diagrama más apropiado:
- `sequenceDiagram` → si el módulo procesa requests/responses o tiene flujo I/O
- `flowchart TD` → si el módulo tiene lógica de decisión o pipeline de transformación
- `classDiagram` → si el módulo expone jerarquía de clases relevante para el consumidor

Criterios del diagrama:
- Omite: credenciales, puertos, variables internas, rutas de ficheros de implementación
- Incluye: actores externos, operaciones de negocio, flujo de datos, puntos de decisión
- Máximo 12 nodos para legibilidad sin zoom
- Usa etiquetas en español para actores y acciones
- Si no hay suficiente información para un diagrama correcto, declara la limitación y no inventes flujo

Si el módulo contiene Web API, servidor web, base de datos o contenedores, añade inmediatamente
después del diagrama principal un párrafo de infraestructura y un diagrama `architecture-beta`.
Ver restricciones de sintaxis en docs.instructions.md.

## 2. API Reference

### Autodoc
Incluir la directiva de generación automática según el lenguaje del proyecto:
  Python:     ::: doc_organize.[modulo].[Clase]
  Java:       ::: com.ejemplo.[paquete].[Clase]
  TypeScript: ::: [Modulo].[Clase]
Solo exportados en __all__, public o export. No implementación interna.

### API pública
Tabla con columnas: | Función/Clase | Firma simplificada | Descripción | Retorna |
Solo las funciones/clases exportadas en __all__ o __init__.py.

### Contratos
Tabla entrada: | Parámetro | Tipo | Descripción | Restricciones |
Contrato de salida: tipos, estructura y casos especiales de cada función principal.
Errores y casos especiales: qué ocurre con entradas inválidas o conexión fallida.

## 3. Componentes y Clases
Responsabilidad de cada clase o función principal exportada (una línea por componente).
Si el módulo tiene una sola clase o función: "*No aplica para este módulo.*"

## 4. Dependencias y Requisitos
Tabla con columnas: | Dependencia | Propósito | Requerida | Comportamiento sin ella |
Incluye dependencias externas (librerías) e internas (módulos del mismo paquete).
Si no hay dependencias externas: indicar explícitamente.

## 5. Ejemplos Relacionados
Lista de enlaces a docs/examples/ con descripción de lo que ilustra cada uno.
Busca en docs/examples/ los ficheros que referencian este módulo.
Si no existe ninguno:
  "Pendiente — crear ejemplo en docs/examples/[nombre-modulo].md"
Formato:
- [Ejemplo: Nombre del patrón](../examples/[nombre].md) — descripción de 1 línea

---

Restricciones:
- Si una sección queda vacía, escribe "*No aplica para este módulo.*" — nunca omitas la sección
- SOLO incluye lo exportado públicamente, no implementación interna
- El diagrama debe ser Mermaid válido en bloque fenced `mermaid`
- No inventes firmas, excepciones, tipos, dependencias ni efectos secundarios
- Si falta información, añade subsección "### Pendiente de verificación" con puntos concretos
- NO uses la directiva --8<-- para incluir código; embebe el código directamente en los bloques fenced
- Responde SOLO con el Markdown
```
## Criterios de selección de diagrama por tipo de módulo

| Tipo de módulo | Diagrama recomendado | Motivo |
|---|---|---|
| Módulo con excepciones y data classes base | `classDiagram` | Jerarquía de tipos exportados |
| Pipeline de validación y filtrado de archivos | `flowchart TD` | Lógica de decisión encadenada |
| Generación de múltiples tipos de archivo | `flowchart TD` | Selección y pipeline de transformación |
| Motor de personalización con sustituciones | `flowchart TD` | Pipeline: leer → aplicar → escribir |
| Orquestador con múltiples fases | `sequenceDiagram` | Flujo completo con actores y salidas |
| Módulo con Web API / base de datos / Docker | `architecture-beta` | Topología de infraestructura física |

## Cómo usar este prompt

### Modo módulo único — Claude Code

```
Lee el archivo [ruta_del_módulo] y genera documentación técnica con diagrama Mermaid
usando el prompt en .github/prompts/technical_doc.prompt.md.
Guarda el resultado en docs/api/[nombre_módulo].md y actualiza mkdocs.yml.
```

Ejemplo concreto:

```
Lee src/doc_organize/timelog/project_loader.py y genera documentación técnica
usando .github/prompts/technical_doc.prompt.md.
Tipo de diagrama: sequenceDiagram.
Guarda en docs/api/project-manager.md y añade la entrada en mkdocs.yml bajo "Técnica:".
```

### Modo módulo único — Copilot Chat

```
#file:.github/prompts/technical_doc.prompt.md
#file:[ruta_del_módulo]

Genera la documentación técnica con diagrama Mermaid del módulo indicado.
```

### Modo proyecto completo (iterativo por módulo)

No uses un único prompt masivo. Recorre el proyecto en fases:

```
Fase 1 — Inventariar módulos públicos desde src/doc_organize/.
  Lista funciones/clases exportadas en __init__.py o __all__; agrúpalas por área funcional.

Fase 2 — Para cada módulo (o área), aplica technical_doc.prompt.md:
  "Lee [ruta] y genera docs/api/[nombre].md con responsabilidad, diagrama Mermaid,
   API pública, contratos de entrada/salida, errores y ejemplo técnico mínimo.
   Elige el tipo de diagrama según el patrón del módulo (ver tabla más abajo).
   Marca como pendiente lo no verificable."

Fase 3 — Actualizar mkdocs.yml:
  Añade o actualiza entradas en la sección docs/api/ del nav.

Fase 4 — Revisión cruzada:
  Contrasta con docs/functional/ y docs/examples/ para detectar inconsistencias de contratos.
```

## Tipos de diagrama recomendados

| Patrón real del módulo | Diagrama recomendado | Motivo |
|---|---|---|
| Flujo entre usuario, CLI, servicio externo y salida | `sequenceDiagram` | Muestra interacción y orden temporal |
| Pipeline de transformación o decisiones | `flowchart TD` | Muestra ramas, validaciones y resultado |
| Jerarquía pública de clases | `classDiagram` | Muestra contratos orientados a objetos |

## Prompt dedicado para infografías Mermaid

Usa este prompt cuando necesites solo el diagrama, sin la documentación técnica completa:

```
Basándote únicamente en la lógica verificable del módulo [Nombre], genera exclusivamente
el código Mermaid.js para un diagrama de secuencia que ilustre la interacción entre el
usuario, el componente principal y sus salidas.
Omite: credenciales, puertos, variables internas, rutas de implementación, nombres de bases de datos.
Incluye: actores externos, operaciones de negocio, puntos de decisión, flujo de datos.
Máximo 12 nodos. Etiquetas en español.
Si el flujo no puede inferirse con seguridad, declara qué información falta en lugar de inventar.
```

## Exclusiones actuales

- No incluir ejemplos de generación mediante APIs externas por el momento.
- No usar un único prompt masivo para todo el proyecto; iterar módulo a módulo o por área.

## Output esperado

Markdown con título H1, párrafo introductorio de una frase y las 5 secciones del Arquetipo 2
numeradas (`## 1.`–`## 5.`), incluyendo un bloque `mermaid` válido en `## 1.`, directiva
autodoc y tablas de contratos en `## 2.`, y al menos un enlace a ejemplo en `## 5.` o el
placeholder de "Pendiente". Secciones vacías con `*No aplica para este módulo.*`.
Todo el contenido derivado del código real: sin inventar parámetros, retornos ni comportamientos.
