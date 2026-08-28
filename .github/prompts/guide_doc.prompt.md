# Prompt: guide_doc — Guía de usuario o configuración (Arquetipo 3)

Genera o actualiza guías de instalación, configuración y uso para **doc_organize** usando solo
información verificable del código, README, `docs/` y configuración del proyecto.

## Instrucción al modelo

```
Actúa como technical writer especializado en documentación de usuario para librerías Python.

Analiza el área de documentación proporcionada y el contexto real del repositorio.
No asumas pasos, comandos ni comportamientos que no aparezcan en el código real,
`pyproject.toml`, README o `docs/`.

Genera una guía en Markdown siguiendo el Arquetipo 3 con estas secciones en este orden exacto:

# [Guía de X / Tutorial de Y]

## 1. Objetivo
Qué conseguirás al seguir esta guía (1 párrafo).
Distingue si es orientada a tarea ("instalar X") o aprendizaje ("entender cómo funciona X").

## 2. Requisitos Previos
Lista de herramientas, accesos o estado inicial requerido antes de comenzar.
Incluye: versiones mínimas, permisos necesarios, dependencias previas.

## 3. Pasos
Procedimiento secuencial numerado con bloques de código para cada paso.
Usa bloques ```bash para comandos de terminal.
Cada paso debe ser atómico y verificable.

## 4. Verificación
Comando exacto para comprobar que la instalación o configuración fue exitosa.
Incluye el output esperado para que el usuario pueda comparar con su resultado real.
Si no hay verificación automatizable: describe el comportamiento visual esperado.

## 5. Variantes y Solución de Problemas
Tabla con columnas: | Escenario/Error | Causa probable | Solución |
Incluye: alternativas al flujo principal, configuraciones opcionales y errores conocidos.
Si no hay casos: "*No aplica para este módulo.*"

---

Restricciones:
- Si una sección queda vacía, escribe "*No aplica para este módulo.*" — nunca omitas la sección
- USA verbos imperativos: "instala", "ejecuta", "verifica" (no "puede instalarse", "se recomienda")
- NO inventes pasos, comandos, outputs ni errores
- Los comandos deben ser ejecutables con el código actual de la rama principal
- NO uses la directiva --8<-- para incluir código; embebe el código directamente en los bloques fenced
- Si falta información, añade subsección "### Pendiente de verificación" con preguntas concretas
- Responde SOLO con el Markdown, sin texto introductorio ni cierre
```

## Cómo usar este prompt

### Modo guía única — Claude Code

```
Lee [ruta_del_área_o_módulo] y genera la guía de usuario usando el
prompt en .github/prompts/guide_doc.prompt.md.
Actualiza docs/[nombre-guia].md si existe, o crea la página si no hay equivalente.
Actualiza mkdocs.yml si se crea o mueve una página.
No inventes pasos ni comandos; si falta información, márcala como pendiente.
```

### Modo guía única — Copilot Chat

```
#file:.github/prompts/guide_doc.prompt.md
#file:[ruta_del_módulo_o_área]

Genera la guía de usuario del área indicada siguiendo las instrucciones del prompt.
```

## Arquetipos de guías en este proyecto

> **Nota**: `docs/INSTALLATION.md` ya **no** se rige por este arquetipo; pasó al Arquetipo 6
> (`landing_doc.prompt.md`, Variante B). Para instalación usa ese prompt, no este.

| Archivo | Tipo de guía |
|---|---|
| `docs/guides/installation.md` | Instalación y extras opcionales (`[web]`) |
| `docs/guides/quick_start.md` | Inicio rápido: escaneo, conversión y caché |
| `docs/guides/troubleshooting.md` | Solución de problemas |
| `docs/functional/index.md` | Referencia funcional (scanner, converter, cache, dedup, auth, web) |
| `docs/api/index.md` | Referencia de API (mkdocstrings) |
| Guías de herramientas IA | Configuración y uso de asistentes IA |

## Output esperado

Markdown con título H1 y las 5 secciones del Arquetipo 3 numeradas (`## 1.`–`## 5.`).
`## 4. Verificación` debe incluir siempre al menos un comando ejecutable.
`## 5. Variantes y Solución de Problemas` con tabla o `*No aplica para este módulo.*`.
