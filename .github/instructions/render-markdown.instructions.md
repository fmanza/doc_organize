---
applyTo: "src/**/render/**/*.py"
---
# Render Markdown — No aplica a doc_organize

Este fichero describía el formato Markdown para documentar tablas de base de datos (`Columnas →
Clave primaria → FK → Índices`), heredado de un proyecto de introspección de bases de datos.
`doc_organize` no genera Markdown de esquemas: genera Markdown de **contenido de documentos**
(PDF/DOCX/XLSX/PPTX/imagen), y esa conversión la realiza Docling internamente — ver
`src/doc_organize/converter/converter.py::_write_outputs()`.

Ver `render.instructions.md` para la nota completa.
