# audit_code

Auditoría técnica de código. Emite veredicto final con evidencias concretas.

## Cuándo usar
- Revisar código antes de mergear
- Auditoría independiente de módulo/archivo
- Verificar contratos sync/async, seguridad, tipado

## Inputs requeridos (OBLIGATORIO completar TODOS)

- [ ] **Archivos a revisar**: Rutas completas o globs (ej. `src/doc_organize/dedup/`)
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
Archivos: src/doc_organize/dedup/

Contexto: Auditoría post-refactor para detectar regresiones

Foco: bugs, edge cases, tipado, tests
```

## Ejemplo de salida esperada (AUDIT_CODE)

```markdown
## AUDIT_CODE

**Hallazgos**:

### Bugs potenciales
- `hash_resolver.py:156`: Missing check en resultado de `hashlib.sha256()` (puede ser None si el stream falla)
- `duplicate_finder.py:89`: Loop sobre lista de candidatos con None puede fallar

### Edge cases
- Carpeta vacía sin documentos → `DuplicateResolver.find_groups()` crashea
- Documento con hash duplicado pero tamaño distinto → no hay validación

### Tipado
- `hash_resolver.py:45`: Variable `result` typed as `Any`
- `duplicate_finder.py:120`: Missing type hint en parámetro `candidates`

### Tests
- Falta test para carpeta vacía sin documentos

**Veredicto**: APROBADO CON CONDICIONES
- Condiciones: Fijar Any en hash_resolver.py + test para carpeta vacía
```
