---
applyTo: "src/**/render/**/*.py"
---
# Renderizado de documentación

> **TL;DR** — Salida determinista (orden alfabético estable). Funciones de render puras: reciben el modelo IR, devuelven contenido sin efectos secundarios. Librería específica por formato (openpyxl, python-docx, Jinja2). Sin servicios externos ni dependencias pesadas. Tests de snapshot o asserts sobre fragmentos clave.

- La salida debe ser determinista: ordena alfabéticamente schemas/tablas/columnas.
- Formato Markdown con secciones consistentes: Resumen, Tablas, Columnas, PK, FK, Índices, Vistas.
- Incluye enlaces internos o anchors cuando el formato destino los soporte de forma estable y predecible.
- Para Excel, genera un formato propio y usa una librería específica (p.ej. openpyxl).
- Para Word, genera un formato propio y usa una librería específica (p.ej. python-docx).
- Para HTML, genera un formato propio y usa una librería específica (p.ej. Jinja2).
- Evita dependencias pesadas; prioriza soluciones ligeras y sin servicios externos.
- Mantén funciones de renderizado puras, recibiendo el modelo de metadatos y devolviendo el resultado sin efectos secundarios.
- Documenta claramente qué información se incluye en la documentación generada y cómo se estructura.
- Proporciona tests de integración que validen la salida generada contra un modelo de metadatos conocido.
- Si la generación de documentación no puede incluir cierta información (p.ej. comentarios de columnas en SQLite), documenta esta limitación y sugiere alternativas (p.ej. input manual o modelo intermedio).

## Patrones recomendados para render
- `Template Method`: define pipeline común de render y sobreescribe solo pasos específicos por formato.
- `Builder`: construye el documento por secciones para evitar funciones monolíticas.
- `Strategy`: encapsula variaciones por salida (Markdown, HTML, Word, Excel) sin `if/elif` dispersos.
- `Facade`: expone una API simple de alto nivel para el flujo completo de documentación.
