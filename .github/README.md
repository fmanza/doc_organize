# Guia de .github

## Jerarquia de decision

1. `copilot-instructions.md`: politica transversal del repositorio.
2. `agents/*.agent.md`: roles especializados y limites de herramientas.
3. `instructions/*.instructions.md`: reglas por tipo de archivo o area.
4. `prompts/*.prompt.md`: flujos de trabajo concretos para tareas puntuales.
5. `ISSUE_TEMPLATE/`, `pull_request_template.md`, `workflows/`: operativa de GitHub.

Si dos documentos chocan, prevalece este orden. Cuando siga habiendo conflicto, prioriza la configuracion real del repositorio y documenta el supuesto.

## Contenido

- `copilot-instructions.md`: rol, formato esperado, politicas de ejecucion y barra de calidad.
- `agents/`: agentes custom de VS Code para routing, planificacion, implementacion, auditoria, seguridad y cierre.
- `instructions/`: reglas de documentacion, render, introspeccion, Python y tests.
- `prompts/`: plantillas para `new_feature`, `hotfix`, `refactor`, `security_review`, `audit_code`, `tech_debt`, `maturity_assessment` y `version_closure`.
- `ISSUE_TEMPLATE/`: formularios de incidencias y peticiones.
- `pull_request_template.md`: plantilla minima de PR.
- `workflows/`: automatizacion CI.
- `docs/examples/github_usage_complete_example.md`: ejemplo integral de uso de instrucciones, prompts, issues, PR, seguridad, CI y gobernanza.

## Agentes disponibles

- `Workflow Director`: clasificacion de solicitud, skill y fase.
- `Plan Architect`: PLAN y AUDIT_PLAN en solo lectura.
- `Feature Implementer`: implementacion acotada con edicion y validacion.
- `Hotfix Responder`: hotfix con RCA y fix minimo.
- `Code Auditor`: AUDIT_CODE y revision de regresiones.
- `Security Reviewer`: `security_review` en solo lectura.
- `Version Closer`: VERSION y handoff final.

## Integracion con prompts

- Los prompts de `prompts/` siguen siendo la fuente de verdad del formato de salida.
- Los agentes de `agents/` sirven para aislar responsabilidad, limitar herramientas y mejorar la delegacion dentro de VS Code.
- El patron recomendado es: `Workflow Director` -> `Plan Architect` -> `Feature Implementer` o `Hotfix Responder` -> `Code Auditor` -> `Version Closer`.

## Mapeo rapido prompt-agente

| Necesidad | Prompt habitual | Agente recomendado |
|---|---|---|
| Clasificar una peticion ambigua | opcional | `Workflow Director` |
| Planificar una feature | `new_feature` | `Plan Architect` |
| Implementar una feature aprobada | `new_feature` | `Feature Implementer` |
| Corregir un bug acotado | `hotfix` | `Hotfix Responder` |
| Ejecutar un refactor aprobado | `refactor` | `Plan Architect` -> `Feature Implementer` |
| Auditar codigo | `audit_code` | `Code Auditor` |
| Revisar seguridad | `security_review` | `Security Reviewer` |
| Inventariar deuda tecnica | `tech_debt` | `Code Auditor` |
| Evaluar madurez | `maturity_assessment` | `Code Auditor` |
| Cerrar version o sesion | `version_closure` | `Version Closer` |

## Criterios de mantenimiento

- Mantener consistencia entre instrucciones, prompts y automatizacion.
- Evitar reglas genericas que no apliquen al repositorio real.
- Si se permite una extension Markdown o una practica nueva, reflejarlo en la politica base y en la instruccion especifica afectada.
- Toda nueva plantilla debe indicar claramente orden de salida, riesgos y estrategia de pruebas.
