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

#: Nombre por defecto de la base de datos de autenticacion (revision 8, §2.7.2).
DEFAULT_AUTH_DB_NAME = "auth.db"

#: Longitud maxima del identificador (slug) de un tenant (revision 8, §2.7.2).
TENANT_ID_MAX_LENGTH = 63

#: Longitud maxima de un nombre de usuario (revision 8, §2.7.2).
USERNAME_MAX_LENGTH = 50

#: Caracteres permitidos en un nombre de usuario: letras, numeros, punto, guion y guion bajo.
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

#: Parametros de `hashlib.scrypt` para el hashing de contrasenas (revision 8, §2.7.2).
#: n=2**17 es el minimo recomendado por OWASP (Password Storage Cheat Sheet) para scrypt
#: con r=8, p=1. `SCRYPT_MAXMEM` debe cubrir el consumo real (~128*n*r bytes = ~128 MiB
#: con estos parametros): sin especificarlo, `hashlib.scrypt` usa el limite por defecto
#: de OpenSSL (32 MiB) y lanza ValueError("Memory limit exceeded") con n=2**17.
SCRYPT_N = 2**17
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64
SCRYPT_MAXMEM = 256 * 1024 * 1024

#: Vida de una sesion de navegador desde su creacion (revision 8, §2.7.2). Fija, sin
#: renovacion deslizante: evita una escritura en auth.db en cada peticion solo para
#: refrescar `expires_at`.
SESSION_LIFETIME_HOURS = 24

#: Mitigacion de fuerza bruta en `POST /login` (revision de seguridad, revision 9):
#: tras `LOGIN_MAX_ATTEMPTS` fallos consecutivos para el mismo (tenant_id, username),
#: se bloquean nuevos intentos durante `LOGIN_LOCKOUT_SECONDS`. En memoria del
#: proceso (ver `web.auth.LoginRateLimiter`), no persistido: suficiente para frenar
#: el adivinado del admin/admin de bootstrap sin anadir infraestructura nueva.
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 60.0

#: Longitud maxima del nombre de un rol (revision 9, roles y gestion de usuarios).
ROLE_NAME_MAX_LENGTH = 50

#: Caracteres permitidos en el nombre de un rol: letras, numeros, espacios, punto,
#: guion y guion bajo (mismo criterio que USERNAME_PATTERN, mas el espacio porque
#: los nombres de rol son mas descriptivos, p.ej. "Editor de proyectos").
ROLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._\- ]+$")

#: Nombre del rol admin creado automaticamente para cada tenant nuevo (revision 9).
DEFAULT_ADMIN_ROLE_NAME = "admin"

#: Usuario admin creado automaticamente para cada tenant nuevo (revision 9). La
#: contrasena es deliberadamente conocida/publica: `User.must_change_password` se
#: fija a `True` para forzar su cambio antes de poder usar el resto de la app en
#: modo no-loopback (ver `AuthMiddleware`).
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"

__all__ = [
    "AV_SUPPORTED_EXTENSIONS",
    "CONVERSION_FOLDER_NAME",
    "DEFAULT_ADMIN_PASSWORD",
    "DEFAULT_ADMIN_ROLE_NAME",
    "DEFAULT_ADMIN_USERNAME",
    "DEFAULT_AUTH_DB_NAME",
    "DEFAULT_CACHE_DB_NAME",
    "DEDUP_HISTORY_JSONL_NAME",
    "DEDUP_REPORT_JSON_NAME",
    "DUPLICATES_FOLDER_NAME",
    "IGNORED_NAMES",
    "LOGIN_LOCKOUT_SECONDS",
    "LOGIN_MAX_ATTEMPTS",
    "MAX_AUTO_ERROR_RETRIES",
    "PROJECT_NAME_FORBIDDEN_CHARS",
    "PROJECT_NAME_MAX_LENGTH",
    "PROJECT_NAME_RESERVED_PATTERN",
    "ROLE_NAME_MAX_LENGTH",
    "ROLE_NAME_PATTERN",
    "SCAN_ERRORS_FOLDER_NAME",
    "SCAN_ERRORS_HISTORY_JSONL_NAME",
    "SCAN_FOLDERS_JSON_NAME",
    "SCAN_HISTORY_FOLDER_NAME",
    "SCAN_HISTORY_JSONL_NAME",
    "SCRYPT_DKLEN",
    "SCRYPT_MAXMEM",
    "SCRYPT_N",
    "SCRYPT_P",
    "SCRYPT_R",
    "SESSION_LIFETIME_HOURS",
    "SUPPORTED_EXTENSIONS",
    "TENANT_ID_MAX_LENGTH",
    "USERNAME_MAX_LENGTH",
    "USERNAME_PATTERN",
    "VERSION_SUFFIX_PATTERN",
]
