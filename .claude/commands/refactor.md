# refactor

Refactor sin cambios funcionales. API pública estable salvo justificación explícita.

## Cuándo usar
- Mejoras estructura/legibilidad sin cambiar comportamiento
- Aplicar SRP, reducir duplicación, mejorar nombres
- Ciclo completo pero con énfasis en regresión: PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION

## Inputs requeridos (OBLIGATORIO completar TODOS)

- [ ] **Objetivo**: Qué mejoras (SRP, duplicación, nombres, etc.)
- [ ] **Módulo(s) afectados**: Rutas específicas
- [ ] **Restricción API pública**: ¿La API pública cambiar? (NO, a menos que justificado)
- [ ] **Tests existentes**: ¿Hay cobertura? (necesaria para validar regresión)

**⚠️ VALIDACIÓN**: Si hay cambio de API sin justificación, DETENTE y aclara.

## Reglas
- No introducir cambios funcionales.
- Mantener API pública; confirmar explícitamente antes de romper contratos.
- Validar con `mypy src`, `ruff check src tests` y tests antes de cerrar.

## Devuelve en este orden

### PLAN
- objetivo
- rutas afectadas
- componentes implicados
- riesgos de regresión

### AUDIT_PLAN
- riesgos funcionales
- riesgos técnicos
- riesgos de seguridad (p.ej. cambios en flujo de parametrización SQL o manejo de recursos)
- simplificaciones posibles

### IMPLEMENT (por rutas o módulos)
- cambios por archivo
- código
- explicación breve

### AUDIT_CODE
- regresiones potenciales
- contratos públicos sync/async
- cobertura preservada
- tipado

### VERSION
- commit message (formato: `refactor: <descripción>`)
- changelog (qué módulos mejoraron y cómo)
- impacto en API pública (DEBE SER CERO si no hay justificación)
- rollback (pasos para revertir)
- validación ejecutada: `mypy src` + `ruff check src tests` + `pytest` (todos pasan)

## Ejemplo de entrada

```
Objetivo: Separar construcción de payload de leyenda y renderizado HTML sin cambiar comportamiento

Módulos: src/doc_organize/doc/html_generator.py

Restricción API: NO cambia. Mismo input/output.

Tests: Sí, existen snapshots en tests/test_html_generator.py
```

## Ejemplo de salida esperada (PLAN)

```markdown
## PLAN - Refactor

**Objetivo**: Extraer método `_build_legend_payload()` para legibilidad

**Módulo**: src/doc_organize/doc/html_generator.py (1 archivo)

**Cambios**:
- Extraer líneas 150-200 a método privado `_build_legend_payload()`
- Actualizar 2 call sites

**API pública**: SIN CAMBIOS (método es privado)

**Regresión risk**: BAJO (método pure, no state)
```
