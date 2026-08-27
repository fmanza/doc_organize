---
applyTo: "src/**/render/**/*.py"
---
# Render Markdown

> **TL;DR** — Cada tabla con secciones en orden fijo: Columnas → Clave primaria → FK → Índices. Orden alfabético estable. Anchors solo si el renderer destino los soporta de forma predecible. Mermaid permitido solo para diagramas de relaciones. Tests sobre fragmentos clave del Markdown generado.

## Estructura obligatoria por tabla
Cada tabla debe documentarse con este orden:

## Tabla `<schema>.<table>`
### Columnas
| Columna | Tipo | Nullable | Descripción |
|--------|------|----------|-------------|

### Clave primaria
- `(col1, col2)`

### Claves foráneas
- `<col>` -> `<schema>.<table>(<col>)`

### Índices
- `<index_name>` (`col1`, `col2`)

## Reglas
- No mezclar secciones.
- Si una sección no aplica, omitirla.
- No usar emojis ni adornos visuales.
- No incluir información no obtenible por introspección (p.ej. comentarios de columnas en SQLite).
- Mantener formato consistente entre tablas.
- Para tablas sin esquema, usar solo el nombre de la tabla en el título.
- Para columnas sin tipo específico, usar "desconocido" o similar.
- Para columnas sin información de nullabilidad, asumir "desconocido" o similar.
- Para claves foráneas sin información de columna referenciada, usar "desconocido" o similar.
- Para índices sin nombre, usar "índice_desconocido" o similar.
- Para índices sin columnas, usar "sin_columnas" o similar.
- Para tablas sin claves primarias, omitir la sección de Clave primaria.
- Para tablas sin claves foráneas, omitir la sección de Claves foráneas.
- Para tablas sin índices, omitir la sección de Índices.
- Para tablas sin vistas, omitir la sección de Vistas.
- Para vistas, documentar solo el nombre de la vista y su definición SQL (si es posible).
- Mantener el mismo orden de columnas en la tabla de Columnas para todas las tablas documentadas.
- Si una tabla tiene muchas columnas, puedes añadir una tabla de resumen antes del detalle completo, sin omitir la información introspectada disponible.
- Para columnas con tipos de datos complejos o específicos de un motor, puedes añadir una descripción adicional en la columna de Descripción si deriva de metadatos reales o reglas documentadas.
- Si una tabla tiene muchas claves foráneas o índices, puedes usar listas numeradas para mejorar la legibilidad.
- Si el caso lo justifica, puedes incluir un diagrama Mermaid `erDiagram` u otro bloque Markdown compatible, siempre generado a partir de metadatos reales.

## Diseño recomendado
- Usa `Builder` para ensamblar bloques Markdown por sección.
- Usa `Template Method` para mantener un orden fijo y personalizar solo detalles de salida.
- Mantén funciones deterministas y sin efectos secundarios para facilitar snapshot tests.
