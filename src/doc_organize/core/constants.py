"""
Constantes compartidas de doc_organize (REQ-002, REQ-005).
"""

import re

#: Extensiones de documento soportadas por el escaner (REQ-002), sin el punto.
#: Ampliado (sesion "soporte de formatos docling") con el subconjunto de formatos
#: adicionales que Docling convierte de forma nativa sin ambiguedad de extension:
#: html/htm/xhtml, csv, odt/ods/odp (OpenOffice), adoc/asciidoc/asc, epub, eml, txt.
#: Quedan fuera deliberadamente `xml` (Docling lo reparte entre xml_jats/xml_xbrl/
#: xml_uspto sin distincion por extension), los formatos nicho sin caso de uso
#: identificado (latex, boxnote, dclx, mets_gbs, json_docling) y audio/video, que
#: siguen siendo opt-in via `include_audio_video` (ver `AV_SUPPORTED_EXTENSIONS`)
#: por requerir el extra `av` (Whisper + ffmpeg) para convertirse.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        "pdf",
        "docx",
        "doc",
        "xlsx",
        "xls",
        "pptx",
        "ppt",
        "png",
        "jpg",
        "jpeg",
        "tiff",
        "bmp",
        "html",
        "htm",
        "xhtml",
        "csv",
        "odt",
        "ods",
        "odp",
        "adoc",
        "asciidoc",
        "asc",
        "epub",
        "eml",
        "txt",
    }
)

#: Extensiones de audio/video, opt-in via `include_audio_video` (REQ-002, sesion
#: "soporte de formatos docling"): requieren el extra `av` (Whisper + binario
#: `ffmpeg` del sistema, ver `doc_organize.utils.av_detector`) para convertirse —
#: no se activan por defecto para no fallar conversiones por dependencias
#: ausentes en un escaneo normal.
AV_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        "wav",
        "mp3",
        "m4a",
        "aac",
        "ogg",
        "flac",
        "mp4",
        "avi",
        "mov",
        "mkv",
        "webm",
    }
)

#: Nombres de archivo/carpeta ignorados durante el escaneo (REQ-002).
#: Decision explicita: no se parsea `.gitignore` del repositorio escaneado.
IGNORED_NAMES: frozenset[str] = frozenset({".git", "__pycache__", ".DS_Store"})

#: Sufijo de version en el nombre de archivo (REQ-005, AUDIT_PLAN revision 4):
#: "documento_v1.pdf", "documento-final.pdf", "documento draft.pdf", etc.
#: El grupo "base" es el nombre sin el sufijo de version.
VERSION_SUFFIX_PATTERN = re.compile(
    r"^(?P<base>.+?)[_\-\s]?(v\d+|final|draft)$",
    re.IGNORECASE,
)

#: Nombre por defecto de la base de datos de cache (REQ-006).
DEFAULT_CACHE_DB_NAME = "cache.db"

#: Numero maximo de reintentos automaticos (en escaneos normales, sin "forzar
#: rescan") para un fichero sin cambios cuya conversion sigue en ERROR. Evita
#: que un fichero permanentemente irrecuperable (p.ej. cifrado) se reprocese
#: en cada escaneo para siempre: al alcanzar el limite, vuelve a requerir
#: "forzar rescan completo" (ver `ScanCommand._collect_stale_error_paths`).
MAX_AUTO_ERROR_RETRIES = 3

#: Nombre del fichero que registra la última tanda de rutas escaneadas/deduplicadas
#: por proyecto (escrito por `ScanCommand._resolve_scan_paths`, releído por
#: `web/routes/duplicates.py` para re-escanear sin pedir las carpetas de nuevo).
SCAN_FOLDERS_JSON_NAME = "folders.json"

#: Carpeta donde `DocumentConverter` escribe el `.md`/`.json` de cada documento
#: convertido, dentro de la raíz del proyecto (`main.py`, `web/routes/scan.py`,
#: `web/routes/downloads.py`, y `web/routes/context.py::_gather_converted_documents`
#: para reconstruir `ConversionResult` a partir de `cache.db`). Antes repetida como
#: literal en cada uno de esos ficheros, sin nada que garantizara que no divergieran
#: (AUDIT_CODE, sesión 2026-09-10 — el nombre también forma parte del denylist de
#: `web/routes/context.py::_RESERVED_OUTPUT_FOLDER_NAMES`, para que `output_folder_name`
#: no pueda coincidir con ella).
CONVERSION_FOLDER_NAME = "Conversión"

#: Carpeta donde `DeduplicationManager.resolve_duplicates`/`finalize_report` mueve
#: los documentos descartados de cada proyecto, y donde escribe
#: `DEDUP_REPORT_JSON_NAME`/`DEDUP_HISTORY_JSONL_NAME` (releídos por
#: `web/routes/duplicates.py` y `web/routes/downloads.py`).
DUPLICATES_FOLDER_NAME = "duplicados"

#: Fichero con el resultado de la última deduplicación (solo el último run) y
#: fichero del histórico acumulado (una línea JSON por ejecución, nunca se
#: sobrescribe), ambos dentro de `DUPLICATES_FOLDER_NAME`. Escritos por
#: `DeduplicationManager.finalize_report`.
DEDUP_REPORT_JSON_NAME = "DEDUP_REPORT.json"
DEDUP_HISTORY_JSONL_NAME = "DEDUP_HISTORY.jsonl"

#: Carpeta y fichero del histórico de errores de escaneo, dentro de la raíz del
#: proyecto (gestión de errores de escaneo agrupados por ejecución): una línea JSON
#: (`ScanErrorReport`) por ejecución de `ScanCommand.run_streaming()` que produjo
#: al menos un error, añadida por `ScanCommand._persist_error_report` y releída por
#: `web/routes/scan_errors.py`. Constantes (no una única `Path` ya compuesta) para
#: que cada llamador pueda construir la ruta absoluta con su propia raíz de proyecto.
SCAN_ERRORS_FOLDER_NAME = "errores_escaneo"
SCAN_ERRORS_HISTORY_JSONL_NAME = "SCAN_ERRORS_HISTORY.jsonl"

#: Carpeta y fichero del histórico de duración de ejecuciones de escaneo, dentro de
#: la raíz del proyecto: una línea JSON (`ScanRunReport`) por cada llamada a
#: `ScanCommand.run_streaming()` (completada o no), añadida por
#: `scan.scan_history_store.append_scan_run` y releída por `web/routes/scan.py`.
#: A diferencia de `SCAN_ERRORS_HISTORY_JSONL_NAME`, se registra toda ejecución,
#: no solo las que producen error.
SCAN_HISTORY_FOLDER_NAME = "historial_escaneo"
SCAN_HISTORY_JSONL_NAME = "SCAN_HISTORY.jsonl"

#: Contexto de organización documental en la raíz del proyecto (L-8b, G28): `context.json` + `domains/<slug>/`
#: (`ContextRegistry`), manifiesto de taxonomía local (`load_taxonomy_manifest`) y sitio de contexto (`SiteGenerator`:
#: `zensical.toml`, `site/` y la caché `.cache/` que Zensical crea junto a su configuración). `mkdocs.yml` es la
#: configuración de antes de 0.13.0: se borra al regenerar o eliminar el sitio.
CONTEXT_FILE_NAME = "context.json"
DOMAINS_FOLDER_NAME = "domains"
TAXONOMY_MANIFEST_FILE_NAME = "taxonomy_manifest.md"
SITE_FOLDER_NAME = "site"
SITE_CONFIG_FILE_NAME = "zensical.toml"
SITE_CACHE_FOLDER_NAME = ".cache"
LEGACY_MKDOCS_CONFIG_NAME = "mkdocs.yml"

#: Longitud maxima de un nombre de proyecto (REQ-008), tras strip().
PROJECT_NAME_MAX_LENGTH = 100

#: Caracteres prohibidos en un nombre de proyecto (REQ-008): invalidos en Windows
#: (`< > : " / \ | ? *`) mas caracteres de control (0x00-0x1F). Se aplica el
#: subconjunto seguro de Windows universalmente (Windows/macOS/Linux) por ser el
#: mas restrictivo de los tres, garantizando portabilidad.
PROJECT_NAME_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: Nombres de dispositivo reservados en Windows (case-insensitive), con o sin
#: extension (p.ej. "CON", "con.txt", "COM1.bak").
PROJECT_NAME_RESERVED_PATTERN = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)",
    re.IGNORECASE,
)

__all__ = [
    "AV_SUPPORTED_EXTENSIONS",
    "CONTEXT_FILE_NAME",
    "CONVERSION_FOLDER_NAME",
    "DEDUP_HISTORY_JSONL_NAME",
    "DEDUP_REPORT_JSON_NAME",
    "DEFAULT_CACHE_DB_NAME",
    "DOMAINS_FOLDER_NAME",
    "DUPLICATES_FOLDER_NAME",
    "IGNORED_NAMES",
    "LEGACY_MKDOCS_CONFIG_NAME",
    "MAX_AUTO_ERROR_RETRIES",
    "PROJECT_NAME_FORBIDDEN_CHARS",
    "PROJECT_NAME_MAX_LENGTH",
    "PROJECT_NAME_RESERVED_PATTERN",
    "SCAN_ERRORS_FOLDER_NAME",
    "SCAN_ERRORS_HISTORY_JSONL_NAME",
    "SCAN_FOLDERS_JSON_NAME",
    "SCAN_HISTORY_FOLDER_NAME",
    "SCAN_HISTORY_JSONL_NAME",
    "SITE_CACHE_FOLDER_NAME",
    "SITE_CONFIG_FILE_NAME",
    "SITE_FOLDER_NAME",
    "SUPPORTED_EXTENSIONS",
    "TAXONOMY_MANIFEST_FILE_NAME",
    "VERSION_SUFFIX_PATTERN",
]
