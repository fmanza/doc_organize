---
applyTo: "src/**/scanner/**/*.py,src/**/converter/**/*.py"
---
# Extracción de documentos (scanner/converter)

> **TL;DR** — API agnóstica de formato de documento; diferencias entre PDF/DOCX/XLSX/PPTX/imagen
> quedan encapsuladas dentro de Docling, no reimplementadas en `doc_organize`. Devolver siempre los
> modelos estables de `core/models.py` (`DocumentMetadata`, `ConversionResult`), nunca objetos
> internos de Docling. Nunca inventar metadatos: si Docling no expone un dato, dejarlo `None` o
> marcarlo explícitamente como no disponible, no rellenarlo con un valor supuesto.

- `DocumentScanner` (escaneo, REQ-002) y `DocumentConverter` (conversión, REQ-003) son agnósticos
  del formato concreto de cada documento — las diferencias entre PDF/DOCX/XLSX/PPTX/imagen las
  resuelve Docling internamente; `doc_organize` no debe reimplementar parsers por formato.
- Devuelve siempre un modelo estable de `core/models.py` (`DocumentMetadata`, `ConversionResult`),
  nunca el objeto `docling_result`/`docling_result.document` crudo — encapsula el acceso a Docling
  dentro de `converter/converter.py` (ver `_needs_ocr()`, `_write_outputs()` como ejemplo de esa frontera).
- Si falta un dato (p.ej. autor o fecha de creación que Docling no extrajo), no lo inventes:
  déjalo `None`/omítelo en el JSON de metadata, tal como hace `DocumentConverter._write_outputs()`.
- Prioriza funciones puras para clasificar/transformar metadata (p.ej.
  `DeduplicationManager._extract_base_name`), dejando la escritura a disco a un paso explícito y
  aparte (`_write_outputs`, `save_entries`).
- Documenta claramente qué metadatos se extraen y qué limitaciones existen (p.ej. `ocr_required`
  se basa en `confidence.parse_score` siendo `NaN` — ver `doclink_extractor_plan.md` §2.4 para el
  spike que confirmó esta señal).
- Los tests de escaneo/conversión corren contra documentos de fixture reales (ver
  `tests/conftest.py::native_pdf`/`scanned_pdf`), no contra mocks de Docling — coherente con la
  política general de no mockear el motor de conversión real.
