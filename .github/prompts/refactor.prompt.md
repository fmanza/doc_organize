# Prompt: refactor (Python library)

## Devuelve en este orden
1. PLAN
2. AUDIT_PLAN
3. IMPLEMENT por rutas o módulos
4. AUDIT_CODE
5. VERSION

## Reglas
- No introducir cambios funcionales.
- Priorizar separación de responsabilidades, eliminación de duplicación y legibilidad.
- Mantener la API pública salvo justificación explícita.
- Antes de aplicar compatibilidad hacia atrás, confirmar explícitamente si se mantiene enfoque "solo OO" o se habilitan funciones wrapper, y si se autoriza romper contratos públicos/snapshots.
- Incluir validación con `mypy src`, `ruff check src tests` y tests de documentación; corregir cualquier rotura restante antes de cerrar el refactor.

## Revisar
- módulos
- clases
- contratos públicos
- tipado
- dependencias
- queries y metadatos
- separación de responsabilidades
- estrategia de pruebas o cobertura preservada
