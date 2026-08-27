# audit_code

Auditoría técnica de código. Emite veredicto final con evidencias concretas.

## Cuándo usar
- Revisar código antes de mergear
- Auditoría independiente de módulo/archivo
- Verificar contratos sync/async, seguridad, tipado

## Inputs requeridos (OBLIGATORIO completar TODOS)

- [ ] **Archivos a revisar**: Rutas completas o globs (ej. `src/doc_organize/metadata/`)
- [ ] **Contexto**: Qué cambió recientemente o por qué se audita
- [ ] **Foco**: Bugs, seguridad, tipado, tests, o todo lo anterior

**⚠️ VALIDACIÓN**: Si no especificas archivos, DETENTE.

## Revisar en todo
- bugs y edge cases detectados
- contratos públicos sync/async (si aplica)
- seguridad (SQL injection, credenciales, inputs)
- compatibilidad y migraciones
- tests faltantes o insuficientes
- tipado (Any sueltos, missing annotations)

## Devuelve en este orden

### PLAN
- alcance
- archivos analizados

### AUDIT_PLAN
- riesgos funcionales
- riesgos técnicos
- riesgos de seguridad

### AUDIT_CODE
- bugs potenciales (archivo:línea)
- edge cases
- performance
- seguridad
- tipado
- deuda técnica
- **Veredicto:** APROBADO / APROBADO CON CONDICIONES / RECHAZADO

### VERSION
- commit message (si hay cambios derivados; formato: `fix: <descripción>` o `refactor: <descripción>`)
- pruebas sugeridas (casos no cubiertos detectados)

## Ejemplo de entrada

```
Archivos: src/doc_organize/metadata/

Contexto: Auditoría post-refactor para detectar regresiones

Foco: bugs, edge cases, tipado, tests
```

## Ejemplo de salida esperada (AUDIT_CODE)

```markdown
## AUDIT_CODE

**Hallazgos**:

### Bugs potenciales
- `mariadb.py:156`: Missing check en cursor.execute() result (puede ser None)
- `fetcher.py:89`: Loop sobre tabla con None puede fallar

### Edge cases
- Tabla vacía sin columnas → `SchemaFetcher.build_columns()` crashea
- FK a tabla no existente → no hay validación

### Tipado
- `fetcher.py:45`: Variable `result` typed as `Any`
- `builder.py:120`: Missing type hint en parámetro `metadata`

### Tests
- Falta test para tabla vacía con 0 columnas

**Veredicto**: APROBADO CON CONDICIONES
- Condiciones: Fijar Any en fetcher.py + test para tabla vacía
```
