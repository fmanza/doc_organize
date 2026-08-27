# Prompt: security_review (Python library)

## Devuelve en este orden
1. PLAN
2. AUDIT_PLAN
3. AUDIT_CODE
4. VERSION

## Revisar
- validación de inputs
- SQL injection
- manejo de credenciales y secretos
- fuga de información en logs/errores
- superficies de ataque por configuración o documentación generada
- contratos sync/async y manejo de recursos

## Reglas
- Prioriza hallazgos verificables.
- Ordena por severidad.
- Incluye remediación accionable.
- Etiqueta claramente supuestos y datos faltantes.
