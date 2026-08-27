# security_review

Auditoría de seguridad independiente. Hallazgos verificables, ordenados por severidad.

## Revisar
- validación de inputs
- SQL injection y parametrización
- manejo de credenciales y secretos
- fuga de información en logs/errores
- superficies de ataque por configuración o documentación generada
- contratos sync/async y manejo de recursos

## Devuelve en este orden

### PLAN
- alcance de la revisión
- archivos y módulos analizados

### AUDIT_PLAN
- hipótesis de riesgo priorizadas

### AUDIT_CODE
- hallazgos por severidad (crítico / alto / medio / bajo)
- evidencia concreta (archivo, línea)
- remediación accionable por hallazgo
- supuestos y datos faltantes etiquetados

### VERSION
- commit message (si hay cambios; formato: `security: <descripción>`)
- checklist de validación post-remediación

## Ejemplo de entrada

```
Áreas: src/doc_organize/doc/, src/doc_organize/analysis/

Revisar: Fuga de secretos, SQL injection, exposición de datos sensibles
```

## Ejemplo de salida esperada (AUDIT_CODE)

```markdown
## AUDIT_CODE - Hallazgos por severidad

### 🔴 Crítico (bloquea publicación)
- `html_generator.py:203`: SQL query con interpolación directa (SQL injection)
  - Remediación: Usar parámetros

### 🟠 Alto
- `render.py:145`: Logs incluyen valores de tabla (PII potencial)
  - Remediación: Sanitizar logs

### 🟡 Medio
- Documentación generada expone nombres de credentials en ejemplos
  - Remediación: Usar placeholders

**Veredicto**: RECHAZADO hasta fijar 🔴 Crítico
```
