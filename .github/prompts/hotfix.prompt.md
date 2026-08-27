# Prompt: hotfix (Python library)

## Devuelve en este orden
1. PLAN
2. AUDIT_PLAN
3. IMPLEMENT
4. AUDIT_CODE
5. VERSION

## Reglas
- No refactorizar.
- No optimizar.
- Limitarse a corregir la causa raíz del bug con el menor alcance posible.
- Incluir test que reproduzca el fallo cuando sea viable.

## PLAN
- objetivo
- rutas afectadas
- componentes implicados
- dato faltante o supuesto
- riesgos

## AUDIT_PLAN
- riesgos funcionales
- riesgos técnicos
- riesgos de seguridad
- simplificaciones posibles

## IMPLEMENT
- diagnóstico probable
- implementación acotada
- estrategia de pruebas

## AUDIT_CODE
- regresiones potenciales
- edge cases
- compatibilidad

## VERSION
- commit message
- changelog
- rollback
