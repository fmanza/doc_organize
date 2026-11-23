"""Nombre de la carpeta reorganizada del contexto (L-8b): qué nombres puede usar `Context.output_folder_name`.

En `core/` (Nivel 1) porque lo valida el propio modelo `Context` al cargarse; `projects/layout.py` lo reexporta, que es
donde lo publica la API (`doc_organize.validate_output_folder_name`, `RESERVED_OUTPUT_FOLDER_NAMES`).
"""

import re
import unicodedata

from doc_organize.core.constants import (
    CONTEXT_FILE_NAME,
    CONTEXT_HISTORY_FOLDER_NAME,
    CONVERSION_FOLDER_NAME,
    DEFAULT_CACHE_DB_NAME,
    DOMAINS_FOLDER_NAME,
    DUPLICATES_FOLDER_NAME,
    LEGACY_MKDOCS_CONFIG_NAME,
    SCAN_ERRORS_FOLDER_NAME,
    SCAN_FOLDERS_JSON_NAME,
    SCAN_HISTORY_FOLDER_NAME,
    SITE_CACHE_FOLDER_NAME,
    SITE_CONFIG_FILE_NAME,
    SITE_FOLDER_NAME,
    TAXONOMY_MANIFEST_FILE_NAME,
    UNCLASSIFIED_FILE_NAME,
)
from doc_organize.core.exceptions import InvalidPathError

#: Nombre del registro de carpetas guardadas (antes privado en ``scanned_folders_store``).
SCANNED_FOLDERS_JSON_NAME = "scanned_folders.json"

#: Nombres de la raíz del proyecto que no puede usar ``Context.output_folder_name`` (se comparan sin distinguir
#: mayúsculas): la carpeta reorganizada se borra entera al reconstruir o eliminar el contexto, así que coincidir con
#: una carpeta o un fichero de otro subsistema lo pisaría (L-8b, G28).
RESERVED_OUTPUT_FOLDER_NAMES: frozenset[str] = frozenset(
    {
        CONVERSION_FOLDER_NAME,
        DUPLICATES_FOLDER_NAME,
        SCAN_ERRORS_FOLDER_NAME,
        SCAN_HISTORY_FOLDER_NAME,
        CONTEXT_HISTORY_FOLDER_NAME,
        DOMAINS_FOLDER_NAME,
        SITE_FOLDER_NAME,
        SITE_CACHE_FOLDER_NAME,
        CONTEXT_FILE_NAME,
        UNCLASSIFIED_FILE_NAME,
        SITE_CONFIG_FILE_NAME,
        LEGACY_MKDOCS_CONFIG_NAME,
        TAXONOMY_MANIFEST_FILE_NAME,
        DEFAULT_CACHE_DB_NAME,
        SCAN_FOLDERS_JSON_NAME,
        SCANNED_FOLDERS_JSON_NAME,
    }
)

#: Nombre simple de carpeta: letras, dígitos, ``_``, ``.``, ``-`` y espacios (sin separadores de ruta).
_OUTPUT_FOLDER_NAME_PATTERN = re.compile(r"^[\w.\- ]+$")


def folder_key(name: str) -> str:
    """Clave de comparación: sin puntos ni espacios finales (Windows los quita), en NFC y sin mayúsculas."""
    return unicodedata.normalize("NFC", name.rstrip(" .")).casefold()


_RESERVED_KEYS = frozenset(folder_key(reserved) for reserved in RESERVED_OUTPUT_FOLDER_NAMES)


def validate_output_folder_name(name: str) -> str:
    """Valida ``name`` como carpeta reorganizada del contexto y lo devuelve sin espacios a los lados.

    Tiene que ser un nombre simple (sin separadores de ruta, ni ``.``/``..``) y no puede coincidir, sin distinguir
    mayúsculas, con ``RESERVED_OUTPUT_FOLDER_NAMES`` (tampoco con puntos o espacios finales, que Windows quita, ni en
    otra forma Unicode).

    Raises:
        InvalidPathError: Si el nombre está vacío, no es simple o está reservado.

    Example:
        >>> validate_output_folder_name(" organizado ")
        'organizado'
        >>> validate_output_folder_name("Site")
        Traceback (most recent call last):
            ...
        doc_organize.core.exceptions.InvalidPathError: 'Site' es un nombre de carpeta reservado por el proyecto — elige otro.
    """
    candidate = name.strip()
    key = folder_key(candidate)
    if not key or not _OUTPUT_FOLDER_NAME_PATTERN.fullmatch(candidate):
        raise InvalidPathError(f"Nombre de carpeta de salida inválido: '{name}'.")
    if key in _RESERVED_KEYS:
        raise InvalidPathError(f"'{name}' es un nombre de carpeta reservado por el proyecto — elige otro.")
    return candidate


__all__ = ["RESERVED_OUTPUT_FOLDER_NAMES", "SCANNED_FOLDERS_JSON_NAME", "folder_key", "validate_output_folder_name"]
