---
applyTo: "src/**/render/**/*.py"
---
# Renderizado de documentación — No aplica a doc_organize

Este fichero describía un módulo de renderizado propio de esquemas de base de datos a
Markdown/Excel/Word/HTML (`Tablas, Columnas, PK, FK, Índices, Vistas`), heredado de un proyecto de
introspección de bases de datos. `doc_organize` no tiene ni necesita un módulo `render/`: la
conversión a Markdown la realiza Docling internamente
(`docling_result.document.export_to_markdown()`, ver `src/doc_organize/converter/converter.py`).

Si en el futuro `doc_organize` necesitara post-procesar o generar salida adicional a partir del
Markdown/JSON ya producido por Docling (p.ej. un reporte HTML propio para la web, REQ-007), ese
código debería documentarse aquí con reglas específicas a `doc_organize`, no reutilizando las
reglas de esquemas de base de datos de la versión anterior de este fichero.
