"""Exportación de un proyecto (L-7, hueco G8 de doc_organize_web): ZIP en *streaming* con vista previa exacta, Excel
de la caché y Excel de errores de escaneo; y el paquete del contexto para IA (2.0.0, F7).

Sin web ni registro de proyectos: rutas explícitas (`ProjectLayout` o rutas sueltas) y entradas de una o varias
cachés. Las escrituras son síncronas, con `on_progress`/`cancel_token` como `ScanCommand.run_streaming`; el Excel
necesita el extra `export` (`openpyxl`), que se importa al escribir.

Example:
    >>> import asyncio, io, tempfile
    >>> from pathlib import Path
    >>> from doc_organize.projects import ProjectLayout
    >>> layout = ProjectLayout(Path(tempfile.mkdtemp()))
    >>> entries = asyncio.run(load_cache_entries([layout.cache_db]))
    >>> preview_project_zip(entries, layout=layout) == write_project_zip(io.BytesIO(), entries, layout=layout)
    True
"""

from doc_organize.export.ai_bundle import BUNDLE_DOCUMENTS_FOLDER, AiBundleStats, render_llms_txt, write_ai_context_bundle
from doc_organize.export.sources import load_cache_entries, load_context_history, load_scan_error_history
from doc_organize.export.xlsx_export import write_cache_xlsx, write_context_documents_xlsx, write_context_history_xlsx, write_scan_errors_xlsx
from doc_organize.export.zip_export import CACHE_SNAPSHOT_NAME, ExportStats, preview_project_zip, write_project_zip

__all__ = [
    "BUNDLE_DOCUMENTS_FOLDER",
    "CACHE_SNAPSHOT_NAME",
    "AiBundleStats",
    "ExportStats",
    "load_cache_entries",
    "load_context_history",
    "load_scan_error_history",
    "preview_project_zip",
    "render_llms_txt",
    "write_ai_context_bundle",
    "write_cache_xlsx",
    "write_context_documents_xlsx",
    "write_context_history_xlsx",
    "write_project_zip",
    "write_scan_errors_xlsx",
]
