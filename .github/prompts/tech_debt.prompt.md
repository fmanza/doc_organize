# Prompt: tech_debt (Python library)

## Inputs requeridos
Antes de ejecutar, confirma que dispones de:
- **Módulo/paquete objetivo** (p.ej. `src/doc_organize/converter/`)
- **Deuda conocida o síntomas** (p.ej. "hay `Any` sueltos", "duplicación sync/async")
- **Versión actual** y rama activa
- **Restricciones de scope**: ¿solo análisis (PLAN+AUDIT_CODE) o también IMPLEMENT?
- **Política de compatibilidad**: ¿se autoriza romper contratos públicos?

Si falta alguno, decláralos como supuesto explícito antes de continuar.

## Devuelve en este orden
1. PLAN
2. AUDIT_PLAN
3. AUDIT_CODE
4. VERSION (solo si IMPLEMENT fue autorizado)

## Salida — AUDIT_CODE de deuda técnica
- deuda detectada por módulo (archivo concreto + línea si aplica)
- impacto real (tipado, mantenibilidad, tests, rendimiento, seguridad)
- prioridad clasificada:
  - `quick_win` — < 1h, sin riesgo de regresión
  - `fase_media` — cambio acotado, test requerido, posible breaking change
  - `deuda_estructural` — refactor amplio, decisión de arquitectura
- quick wins listos para implementar (con estrategia de prueba mínima)
- plan por fases con orden de dependencias
- riesgos si no se aborda

## Criterios de prioridad
| Nivel            | Criterio de entrada                                         | Criterio de salida              |
|------------------|-------------------------------------------------------------|---------------------------------|
| `quick_win`      | Fix aislado, sin cambio de contrato público, test trivial    | PR de 1 commit, sin migration   |
| `fase_media`     | Cambio visible en API interna, test de integración requerido | Review explícito antes de merge |
| `deuda_estructural` | Afecta arquitectura, múltiples módulos o compatibilidad | PLAN+AUDIT_PLAN aprobados primero |

## Reglas
- Emitir veredicto final: `LIMPIO | DEUDA_MENOR | DEUDA_SIGNIFICATIVA | CRÍTICO`.
- Señalar evidencias concretas (archivo, función, línea).
- Diferenciar hallazgos confirmados de hipótesis.
- No mezclar deuda técnica con nuevas features en el mismo PLAN.
- Si la deuda implica un patrón arquitectónico, referenciar el patrón correcto (SOLID, GoF).
