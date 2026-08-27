# hotfix

Corrección acotada de un bug. Política: **solo fix mínimo. Prohibido refactorizar y optimizar**.

## Cuándo usar
- Bug confirmado afecta funcionalidad crítica (P1/P2)
- Solo arreglas la causa raíz sin tocar código no relacionado
- Ciclo reducido: PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION

## Inputs requeridos (OBLIGATORIO completar TODOS)

- [ ] **Bug**: Descripción clara de qué no funciona
- [ ] **Rutas afectadas**: Dónde está el bug (archivos específicos)
- [ ] **Síntomas**: Cómo se manifiesta (logs, comportamiento incorrecto)
- [ ] **Dato faltante o supuesto**: Qué NO sabemos con seguridad

**⚠️ VALIDACIÓN**: Si no emites PLAN con diagnóstico de causa raíz claro, DETENTE.

## Devuelve en este orden

### PLAN
- objetivo
- rutas afectadas
- componentes implicados
- dato faltante o supuesto
- riesgos

### AUDIT_PLAN
- riesgos funcionales
- riesgos técnicos
- riesgos de seguridad

### IMPLEMENT
- diagnóstico de causa raíz
- implementación acotada
- test que reproduzca el fallo (si es viable)

### AUDIT_CODE
- regresiones potenciales
- edge cases
- compatibilidad

### VERSION
- commit message (formato: `fix: <descripción>`)
- changelog (1-2 líneas)
- rollback (pasos simples)

## Ejemplo de entrada

```
Bug: Renderer HTML pierde iconos offline cuando se exporta fuera del workspace

Rutas: src/doc_organize/doc/html_generator.py, src/doc_organize/doc/assets/

Síntomas: Al exportar a PDF desde ruta ajena al workspace, los iconos desaparecen. En web OK.

Supuesto: Assets deben embederse como base64 en HTML, no referenciarse como filepath.
```

## Ejemplo de salida esperada (PLAN)

```markdown
## PLAN - Diagnóstico

**Objetivo**: Fijar pérdida de iconos offline en exports

**Causa raíz**: `html_generator.py` referencia assets con filepath relativo; fuera del workspace no encuentra archivos.

**Fix mínimo**: Embeber assets como base64 en HTML, no filepaths.

**Ficheros**: 1 archivo (html_generator.py)

**Test**: Reproducir export desde /tmp/, validar que iconos aparezcan en HTML resultante
```
