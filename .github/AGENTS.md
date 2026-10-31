# Agentes Disponibles

Registro de agentes especializados en `.github/agents/` para orquestación del flujo de trabajo PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION.

## Invocación

**En Claude Code**:
```
/new-feature
/hotfix
/refactor
/security-review
/audit-code
/tech-debt
/maturity-assessment
/version-closure
```

**En Copilot Chat**: Usa `runSubagent` o invoca directamente con nombre del agente.

---

## Agentes por flujo

### 1. **Workflow Director** (`workflow-director.agent.md`)
- **Propósito**: Clasificar solicitudes, validar contexto mínimo, elegir fase siguiente
- **Entrada**: Descripción de tarea por usuario
- **Salida**: Clasificación (new_feature | hotfix | refactor | security_review | tech_debt | maturity_assessment | version_closure)
- **Herramientas**: read, search
- **Invocable**: No (interno)

### 2. **Plan Architect** (`plan-architect.agent.md`)
- **Propósito**: Preparar PLAN y AUDIT_PLAN, contrastar con código real, detectar riesgos
- **Entrada**: Solicitud con contexto (objetivo, módulos, API, restricciones)
- **Salida**: PLAN (rutas, componentes, tipos, riesgos) + AUDIT_PLAN (veredicto)
- **Herramientas**: read, search
- **Invocable**: Sí (fases new_feature, refactor)

### 3. **Feature Implementer** (`feature-implementer.agent.md`)
- **Propósito**: Ejecutar IMPLEMENT con alcance aprobado, aplicar cambios, validar tests
- **Entrada**: AUDIT_PLAN aprobado + descripción de tarea
- **Salida**: IMPLEMENT (cambios por archivo) + auditoría local
- **Herramientas**: read, write, exec (run_task, run_in_terminal)
- **Invocable**: Sí (después de AUDIT_PLAN aprobado)

### 4. **Hotfix Responder** (`hotfix-responder.agent.md`)
- **Propósito**: RCA, fix mínimo, verificación; incidencias P1/P2 sin refactorizar
- **Entrada**: Descripción de bug con impacto
- **Salida**: PLAN + FIX + AUDIT_CODE + VERSION
- **Herramientas**: read, write, exec
- **Política**: Solo fix acotado, prohibido refactorizar u optimizar

### 5. **Code Auditor** (`code-auditor.agent.md`)
- **Propósito**: AUDIT_CODE de implementaciones, revisar bugs, edge cases, contratos
- **Entrada**: Rutas modificadas o cambios propuestos
- **Salida**: Scope, Findings, Compatibility, Coverage, Verdict
- **Herramientas**: read, search
- **Invocable**: Sí (fase AUDIT_CODE)

### 6. **Documentation Reviewer** (`documentation-reviewer.agent.md`)
- **Propósito**: Revisar y auditar documentación completa, ejemplos, gaps, coherencia
- **Entrada**: Alcance (README | ejemplos | APIs | guías | todas)
- **Salida**: Scope, Findings por categoría, Critical gaps, Priority improvements, Recomendaciones
- **Herramientas**: read, search
- **Invocable**: Sí (auditoría independiente)
- **Criterios**: Nivel 1 (crítico), Nivel 2 (alto), Nivel 3 (recomendado)
- **Prompt Copilot Chat**: `.github/prompts/documentation_review.prompt.md`
- **Slash command**: No disponible en `.claude/commands/` — invocar mediante lenguaje natural en Claude Code

### 6b. **Documentation Generator** (`documentation-generator.agent.md`) ⭐ **NUEVO**
- **Propósito**: GENERAR documentación funcional y técnica con diagramas Mermaid para módulos de doc_organize
- **Entrada**: Módulo Python objetivo, tipo (`functional` | `technical` | `both`), directorio destino
- **Salida**: Archivos `.md` en `docs/` + entrada sugerida para `zensical.toml`
- **Herramientas**: read, write, search
- **Invocable**: Sí (generación activa, escribe archivos)
- **Diferencia con Reviewer**: Reviewer audita, Generator crea contenido nuevo
- **Prompts base**: `.github/prompts/functional_doc.prompt.md` + `.github/prompts/technical_doc.prompt.md`
- **Workflow CI/CD**: `.github/workflows/doc_agents.yml` (Anthropic / OpenAI)

### 7. **Config Reviewer** (`config-reviewer.agent.md`) ⭐ **NUEVO**
- **Propósito**: Revisar y consolidar ficheros de configuración IA, eliminando duplicación entre plataformas
- **Entrada**: Ficheros a revisar (copilot-instructions.md, CLAUDE.md, etc.) + estrategia preferida
- **Salida**: ANÁLISIS (categorización shared/copilot-only/claude-only), PLAN, AUDIT_PLAN, IMPLEMENT, AUDIT_CODE, VERSION
- **Herramientas**: read, search
- **Invocable**: Sí (auditoría de configuración)
- **Criterios**: DRY (sin duplicación), funcionalidad autosuficiente, coherencia de flujos
- **Prompt Copilot Chat**: `.github/prompts/config_review.prompt.md`
- **Slash command**: No disponible en `.claude/commands/` — invocar mediante `/config-review` (próx. sesión) o lenguaje natural

### 8. **Security Reviewer** (`security-reviewer.agent.md`)
- **Propósito**: Auditoría de seguridad independiente sobre auth, validación, secretos, logging
- **Entrada**: Rutas o áreas de seguridad crítica
- **Salida**: Executive summary, Scope, Findings, Evidence, Remediation, Residual risk, Verdict
- **Herramientas**: read, search
- **Invocable**: Sí (auditoría independiente)

### 9. **Maturity Assessment** (`maturity-assessment.agent.md`)
- **Propósito**: Evaluar madurez del repositorio completo (estructura, contratos, tests, readiness)
- **Entrada**: Área a evaluar o evaluación completa
- **Salida**: Executive summary, Findings by area, Blockers, Recommendations, Maturity verdict
- **Herramientas**: read, search
- **Invocable**: Sí (auditoría estratégica)

### 10. **Version Closer** (`version-closer.agent.md`)
- **Propósito**: Cierre de versión, resumir cambios, evidence, impacto, validar sincronización y handoff
- **Entrada**: Sesión completada
- **Salida**: Release notes, Commit messages, Changelog, Rollback strategy, Testing suggestions
- **Validación requerida**: Revisar `.github/instructions/sync.instructions.md`
  - CHANGELOG.md ↔ docs/CHANGELOG.md sincronizados
  - .ai/COMPATIBILITY.md ↔ docs/COMPATIBILITY.md sincronizados
  - `zensical build --strict` pasa sin errores
- **Herramientas**: read, search
- **Invocable**: Sí (final de sesión)

### 11. **Explore** (`explore.agent.md`)
- **Propósito**: Exploración rápida del repositorio, Q&A sin modificaciones
- **Entrada**: Pregunta sobre código, estructura, patrón
- **Salida**: Context, Findings, ubicación de archivos
- **Herramientas**: read, search
- **Invocable**: Sí (Q&A)

---

## Matriz de relaciones

| Fase | Agente | Output | Next |
|------|--------|--------|------|
| CLASIFICACIÓN | Workflow Director | Tipo de tarea | PLAN |
| PLAN | Plan Architect | PLAN + AUDIT_PLAN | IMPLEMENT (si GO) o RETORNO |
| IMPLEMENT | Feature Implementer | Cambios por archivo | AUDIT_CODE |
| AUDIT_CODE | Code Auditor | Hallazgos, Severidad | CORRECCIÓN (si issues) o VERSION |
| VERSION | Version Closer | Release notes, Changelog | FIN |
| HOTFIX DIRECTO | Hotfix Responder | PLAN + FIX + AUDIT + VERSION | FIN |
| AUDITORÍA INDEPENDIENTE | Security/Documentation/Config/Maturity Reviewer | Executive summary + Findings | BACKLOG / NEXT ITERATION |

---

## Ejemplo: Invocar Documentation Reviewer

### En Claude Code
```
Necesito revisar toda la documentación de doc_organize para identificar gaps, ejemplos faltantes y mejorar coherencia.

Usa Documentation Reviewer para:
1. Mapear estado actual de docs (README, guías, ejemplos, docstrings)
2. Identificar ejemplos faltantes por módulo
3. Detectar gaps críticos vs recomendados
4. Proporcionar backlog de mejoras con prioridades
```

### En Copilot Chat
```
/runSubagent Documentation Reviewer

Input: Necesito una auditoría completa de documentación de doc_organize incluyendo ejemplos faltantes, gaps en guías técnicas y coherencia general.
```

### Output esperado
```
## Executive summary
[Resumen de hallazgos principales]

## Scope reviewed
- Archivos de documentación analizados (README.md, docs/*, docs/examples/*, .ai/*)
- Cobertura de ejemplos por módulo
- Documentación de APIs públicas

## Critical gaps (Nivel 1)
[Bloqueantes que impiden onboarding o uso seguro]

## High priority improvements (Nivel 2)
[Dificultades de usabilidad o claridad]

## Recommended enhancements (Nivel 3)
[Mejoras de experiencia]

## Examples inventory & coverage
[Ejemplos existentes + Ejemplos faltantes]

## Documentation readiness verdict
PRODUCTION_READY | NEAR_READY | BLOCKED
```

---

## Registro de herramientas restricciones

| Agente | read | write | search | exec | web_fetch |
|--------|------|-------|--------|------|-----------|
| Plan Architect | ✅ | ❌ | ✅ | ❌ | ❌ |
| Feature Implementer | ✅ | ✅ | ❌ | ✅ | ❌ |
| Hotfix Responder | ✅ | ✅ | ❌ | ✅ | ❌ |
| Code Auditor | ✅ | ❌ | ✅ | ❌ | ❌ |
| Documentation Reviewer | ✅ | ❌ | ✅ | ❌ | ❌ |
| Documentation Generator | ✅ | ✅ | ✅ | ❌ | ❌ |
| Config Reviewer | ✅ | ❌ | ✅ | ❌ | ❌ |
| Security Reviewer | ✅ | ❌ | ✅ | ❌ | ❌ |
| Maturity Assessment | ✅ | ❌ | ✅ | ❌ | ❌ |
| Version Closer | ✅ | ❌ | ✅ | ❌ | ❌ |
| Explore | ✅ | ❌ | ✅ | ❌ | ❌ |
| Workflow Director | ✅ | ❌ | ✅ | ❌ | ❌ |

---

## Bootstrap a otro proyecto (cross-project)

Para **trasladar este sistema de instrucciones IA a otro proyecto** (incluso de otro lenguaje y
arquitectura) usa el prompt `bootstrap_ai_config` y, como auditor del resultado, el agente
**Config Reviewer**.

- **Prompt**: [`.github/prompts/bootstrap_ai_config.prompt.md`](prompts/bootstrap_ai_config.prompt.md)
- **Auditor**: `config-reviewer.agent.md` (DRY + referencias huérfanas)
- **Método y dirección**: modelo **PULL** — se invoca **desde el proyecto destino**, apuntando a
  este repo como plantilla de solo lectura. El lenguaje/arquitectura del destino es un **parámetro**.
- **Capas**: A (copiar verbatim) · B (copiar + reescribir dominio) · C (regenerar) · D (excluir).

Ver el detalle completo de rutas, contexto obligatorio/opcional y mapeo por plataforma
(Claude / Gemini / Copilot / Cursor / Codex) en el propio prompt.

---

## Configuración

Personalizaciones por contexto:
- **Prompts**: `.github/prompts/*.prompt.md` — instrucciones por slash command (17 prompts; 8 equivalentes a `.claude/commands/` + 6 arquetipos de documentación `functional_doc`/`technical_doc`/`guide_doc`/`example_doc`/`architecture_doc`/`landing_doc` + `documentation_review` + `config_review` + `bootstrap_ai_config`)
- **Instrucciones**: `.github/instructions/*.instructions.md` — reglas por tipo de archivo
- **Hooks**: `.claude/settings.json` — comandos pre/post tool (lint, format, type-check)
- **Workflow IA**: `.github/workflows/doc_agents.yml` — generación automática vía Anthropic/OpenAI
- **Script**: `.github/scripts/generate_docs.py` — invocado por `doc_agents.yml`

Modificar un agente: editar su archivo `.agent.md` en `.github/agents/`.

---

## Nota: Asimetría slash commands ↔ agentes

Los **slash commands** de Claude Code (`.claude/commands/`) cubren 8 flujos (new-feature, hotfix, refactor, audit-code, security-review, tech-debt, maturity-assessment, version-closure).

Los **agentes** (`.github/agents/`) son 12: incluyen los 8 anteriores más `documentation-reviewer`, `documentation-generator`, `config-reviewer`, `explore` y `workflow-director` (este último interno, no invocable). Los de documentación y `config-reviewer` no tienen slash command pero son invocables por lenguaje natural (Claude Code) o mediante sus prompts correspondientes (Copilot Chat).

Ver gobernanza completa en [`.github/INTEGRATION_MAP.md`](INTEGRATION_MAP.md).
