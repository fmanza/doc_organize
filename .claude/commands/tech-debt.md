# tech_debt

Inventario de deuda técnica. No mezclar con nuevas features en el mismo PLAN.

## Inputs requeridos (OBLIGATORIO completar TODOS)

- [ ] **Módulo/paquete objetivo**: Ruta específica (ej. `src/doc_organize/metadata/`)
- [ ] **Deuda conocida o síntomas**: Describe qué viste (ej. "hay `Any` sueltos", "duplicación sync/async")
- [ ] **Scope**: ¿Solo análisis (PLAN+AUDIT_CODE) o también IMPLEMENT?
- [ ] **Política de compatibilidad**: ¿Se autoriza romper contratos públicos?

**⚠️ VALIDACIÓN**: Si falta alguno, **DETENTE y aclara como supuesto explícito** antes de continuar.

## Devuelve en este orden

### PLAN
- módulo objetivo
- síntomas o deuda conocida
- scope (análisis / análisis + implement)
- riesgos de regresión al abordarla

### AUDIT_PLAN
- riesgos funcionales
- riesgos técnicos
- riesgos de seguridad
- dependencias entre ítems de deuda

### AUDIT_CODE
- deuda detectada por módulo (`archivo:línea` cuando aplique)
- impacto real (tipado, mantenibilidad, tests, rendimiento, seguridad)
- prioridad clasificada:
  - `quick_win` — < 1h, sin riesgo de regresión, PR de 1 commit
  - `fase_media` — cambio acotado, test requerido, posible breaking change
  - `deuda_estructural` — refactor amplio, decisión de arquitectura (requiere PLAN+AUDIT_PLAN aprobados)
- quick wins listos para implementar (con estrategia de prueba mínima)
- plan por fases con orden de dependencias
- riesgos si no se aborda
- **Veredicto:** `LIMPIO | DEUDA_MENOR | DEUDA_SIGNIFICATIVA | CRÍTICO`

### VERSION
- solo si IMPLEMENT fue autorizado en el scope
- commit message (formato: `refactor: <descripción>`)
- pruebas sugeridas
