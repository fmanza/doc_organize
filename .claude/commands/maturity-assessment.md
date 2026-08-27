# maturity_assessment

Evaluación de madurez del repositorio. Separar bloqueantes de mejoras recomendadas.

## Inputs requeridos (RECOMENDADO completar)

- [ ] **Objetivo**: Por qué evalúas (publicación estable, readiness, etc.)
- [ ] **Áreas de foco**: Módulos clave (doc/, metadata/, analysis/) o repo completo

**Nota**: Son recomendados pero no bloqueantes. Si faltan, emitiremos supuestos.

## Evaluar

- estructura del proyecto y coherencia con arquitectura de 3 niveles
- consistencia de APIs públicas (managers sync/async, contratos, tipos)
- tipado (mypy strict) y docstrings en código público
- seguridad y gestión de recursos (credenciales, SQL dinámico, async leak)
- tests (cobertura, determinismo, ausencia de dependencias externas)
- documentación generada y ejemplos
- readiness para publicación y mantenimiento a largo plazo

## Devuelve en este orden

### PLAN
- objetivo de la evaluación
- áreas analizadas
- fuentes de contexto consultadas

### AUDIT_PLAN
- dimensiones de riesgo priorizadas
- hipótesis de bloqueantes

### AUDIT_CODE
- hallazgos por dimensión con evidencia concreta (`archivo:línea`)
- clasificación: **bloqueante** / **mejora recomendada** / **informativo**
- **Veredicto:** `PRODUCTION_READY | NEAR_READY | BLOCKED`
  - `PRODUCTION_READY`: sin bloqueantes conocidos
  - `NEAR_READY`: bloqueantes menores o mejoras acotadas
  - `BLOCKED`: bloqueantes que impiden publicación o uso fiable

### VERSION
- commit message si hay cambios derivados del assessment
- checklist de acciones previas a publicación
