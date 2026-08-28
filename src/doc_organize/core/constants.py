"""
Constantes compartidas de doc_organize (REQ-002, REQ-005).
"""

import re

#: Extensiones de documento soportadas por el escaner (REQ-002), sin el punto.
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

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "IGNORED_NAMES",
    "VERSION_SUFFIX_PATTERN",
    "DEFAULT_CACHE_DB_NAME",
    "PROJECT_NAME_MAX_LENGTH",
    "PROJECT_NAME_FORBIDDEN_CHARS",
    "PROJECT_NAME_RESERVED_PATTERN",
    "DEFAULT_AUTH_DB_NAME",
    "TENANT_ID_MAX_LENGTH",
    "USERNAME_MAX_LENGTH",
    "USERNAME_PATTERN",
    "SCRYPT_N",
    "SCRYPT_R",
    "SCRYPT_P",
    "SCRYPT_DKLEN",
    "SCRYPT_MAXMEM",
    "SESSION_LIFETIME_HOURS",
]
