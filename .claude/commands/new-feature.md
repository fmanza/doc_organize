# new_feature

Nueva funcionalidad para la librería. Política: **prohibido refactorizar**.

## Cuándo usar
- Añades comportamiento nuevo que no existía
- Extiendes API pública con parámetros, métodos o clases nuevas
- Necesitas ciclo completo: PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION

## Inputs requeridos (OBLIGATORIO completar TODOS)

- [ ] **Objetivo**: Descripción breve de qué se implementa (1-2 líneas)
- [ ] **Módulo(s) o clase(s)**: Rutas completas (ej. `src/doc_organize/doc/render_markdown.py`)
- [ ] **API pública esperada**: Qué cambia en la firma (parámetros, tipos, métodos)
- [ ] **Contrato de entrada**: Qué espera recibir (prerequisitos, tipos)
- [ ] **Contrato de salida**: Qué garantiza producir (output, invariantes)
- [ ] **Reglas de negocio**: Restricciones funcionales (no inventar metadata, determinismo)
- [ ] **Restricciones técnicas**: Límites (sin dependencias nuevas, sync/async, etc.)
- [ ] **Motores o formatos afectados**: DB motors o formatos (Markdown, HTML, etc.)
- [ ] **¿Hay archivos relevantes existentes?**: sí/no + referencias si aplica

**⚠️ VALIDACIÓN**: Si falta alguno de estos campos, **DETENTE y aclara antes de continuar**. No emitas PLAN hasta que todos estén completos.

## Devuelve en este orden

### PLAN
- objetivo
- rutas afectadas
- componentes implicados
- tipos necesarios
- riesgos

### AUDIT_PLAN
- riesgos funcionales
- riesgos técnicos (incluir impacto en LSP/ISP: contratos sync/async y tamaño de interfaces)
- riesgos de seguridad
- simplificaciones posibles
- **Veredicto:** GO / NO_GO / GO_CONDICIONAL (con condiciones si aplica)

### IMPLEMENT (por capas: Level 1 → 2 → 3)
- cambios por archivo
- código
- explicación breve

### AUDIT_CODE
- bugs potenciales
- edge cases
- performance
- seguridad
- tipado
- deuda técnica

### VERSION
- commit message (formato: `feat: <descripción>`)
- changelog por módulo afectado
- impacto en API pública (cambios de firma, parámetros, tipos)
- rollback (pasos para revertir)
- pruebas sugeridas

## Ejemplo de entrada

```
Objetivo: Exportar Markdown con diagramas Mermaid opcionales

Módulo(s): src/doc_organize/doc/render_markdown.py, tests/test_render_markdown.py

API esperada: parámetro `enable_mermaid: bool = False` en render_markdown()

Contrato entrada: Schema ya introspectado + tablas normalizadas

Contrato salida: Markdown válido, portable, determinista (orden estable)

Reglas negocio: no inventar metadatos; solo Mermaid si hay datos reales

Restricciones: sin dependencias nuevas (Mermaid es nativo)

Motores: Markdown (agnóstico de BD)

Archivos relevantes: sí - render_markdown.py y templates/
```

## Ejemplo de salida esperada (PLAN)

```markdown
## PLAN

**Objetivo**: Exportación Markdown con Mermaid opcional

**Rutas afectadas**:
- src/doc_organize/doc/render_markdown.py
- tests/test_render_markdown.py
- docs/

**Componentes implicados**:
- `MarkdownRenderer` clase
- Método `render_markdown(schema, enable_mermaid=False)`
- Template `mermaid_diagram.j2`

**Tipos necesarios**: `MermaidDiagram` dataclass

**Riesgos**:
- Funcional: Markdown malformado si Mermaid falla
- Técnico: Performance si schema es muy grande (> 50 tablas)
- Seguridad: SQL injection no aplica (datos ya normalizados)
```
- pruebas sugeridas
