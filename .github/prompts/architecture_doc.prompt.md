# Prompt: architecture_doc — Decisión Arquitectónica (Arquetipo 5)

Documenta una decisión arquitectónica (ADR) para **doc_organize** usando solo
información verificable del código, issues, PRs y documentación existente.

## Instrucción al modelo

```
Actúa como arquitecto de software senior especializado en documentación de decisiones
arquitectónicas (Architecture Decision Records).

Analiza el contexto proporcionado (código, issue, PR, discusión) para documentar
la decisión de forma objetiva. No asumas motivaciones ni consecuencias no verificables.

Genera un ADR en Markdown siguiendo el Arquetipo 5 con estas secciones en este orden exacto:

# ADR-[NNN]: [Título de la Decisión]

## 1. Contexto y Problema
Qué situación motivó la decisión:
- Estado del sistema antes de la decisión
- Problema o limitación identificada
- Fuerzas en conflicto (requisitos, restricciones, trade-offs)

## 2. Decisión
Qué se decidió hacer:
- Enunciado claro de la decisión tomada
- Justificación: por qué esta opción sobre las alternativas
- Fecha de la decisión y decisores si se conocen

## 3. Consecuencias
Tabla: | Tipo | Descripción |
Tipos: Ventaja | Compromiso (trade-off) | Deuda técnica | Riesgo aceptado
Ser honesto sobre los trade-offs; no omitir consecuencias negativas verificables.

## 4. Alternativas Consideradas
Tabla: | Alternativa | Pros | Contras | Motivo de rechazo |
Si no hubo alternativas documentadas: "*No aplica para este módulo.*"

## 5. Estado y Revisión
Estado actual (elegir uno):
  PROPUESTO      — en discusión, no implementado
  ACEPTADO       — aprobado e implementado
  OBSOLETO       — superado por evolución del sistema sin reemplazo formal
  REEMPLAZADO POR [ADR-NNN] — sustituido por una decisión posterior

Fecha de última revisión: YYYY-MM-DD

---

Restricciones:
- Si una sección queda vacía, escribe "*No aplica para este módulo.*" — nunca omitas la sección
- NO inventes motivaciones, fechas, decisores ni consecuencias
- NO documentes decisiones de implementación (cómo funciona algo); solo decisiones de diseño (por qué)
- Si falta información verificable, añade subsección "### Pendiente de verificación"
- Responde SOLO con el Markdown, sin texto introductorio ni cierre
```

## Cómo usar este prompt

### Modo ADR único — Claude Code

```
Documenta la decisión arquitectónica sobre [TEMA] usando el
prompt en .github/prompts/architecture_doc.prompt.md.
Guarda en docs/adr/ADR-[NNN]-[nombre-kebab-case].md.
Actualiza mkdocs.yml bajo la sección "Arquitectura".
Basa el contenido en: [PR/issue/commit/discusión de referencia]
```

### Cuándo crear un ADR

Crear un ADR cuando se toma una decisión que:
- Afecta la arquitectura pública (contratos de API, estructura de módulos)
- Elige entre múltiples enfoques con trade-offs no triviales
- Introduce o elimina una dependencia significativa
- Establece un patrón que otros módulos deben seguir

**No crear ADR** para: decisiones de implementación interna, cambios de estilo, bugfixes.

## Numeración

Los ADRs se numeran secuencialmente: ADR-001, ADR-002, ...
Consultar `docs/adr/` para el número siguiente disponible.

## Output esperado

Markdown con título `# ADR-NNN: [Título]` y las 5 secciones del Arquetipo 5 numeradas
(`## 1.`–`## 5.`). `## 5.` siempre con estado explícito y fecha.
