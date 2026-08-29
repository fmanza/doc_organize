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
    "DEFAULT_ADMIN_PASSWORD",
    "DEFAULT_ADMIN_ROLE_NAME",
    "DEFAULT_ADMIN_USERNAME",
    "DEFAULT_AUTH_DB_NAME",
    "DEFAULT_CACHE_DB_NAME",
    "IGNORED_NAMES",
    "LOGIN_LOCKOUT_SECONDS",
    "LOGIN_MAX_ATTEMPTS",
    "PROJECT_NAME_FORBIDDEN_CHARS",
    "PROJECT_NAME_MAX_LENGTH",
    "PROJECT_NAME_RESERVED_PATTERN",
    "ROLE_NAME_MAX_LENGTH",
    "ROLE_NAME_PATTERN",
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
