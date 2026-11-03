"""
Avisos de obsolescencia de la web integrada (L-10, 0.14.0). Módulo interno: no se re-exporta.

`doc_organize.web`, `doc_organize.auth` y los subcomandos `web`, `tenant` y `user` del CLI están congelados (solo
hotfix) y se retiran en 1.0.0 (L-11): doc_organize_web los sustituye. Un único texto para el CLI y para los imports.
"""

import os
import warnings

WEB_REPLACEMENT_URL = "https://github.com/fmanza/doc_organize_web"
WEB_REMOVAL_VERSION = "1.0.0"

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
# Frames que no son del consumidor: el propio paquete (p. ej. `web` importando `auth`) y la maquinaria de import.
_SKIP_FILE_PREFIXES = (_PACKAGE_DIR, "<frozen importlib")


def web_deprecation_message(subject: str) -> str:
    """Texto común del aviso para `subject` (p. ej. ``"doc_organize.web"`` o ``"El subcomando 'web'"``)."""
    return f"{subject} está obsoleto y se retirará en doc_organize {WEB_REMOVAL_VERSION}: usa doc_organize_web ({WEB_REPLACEMENT_URL})."


def warn_deprecated_import(module_name: str) -> None:
    """`DeprecationWarning` al importar `module_name`, atribuido a la línea del consumidor que lo importa."""
    warnings.warn(web_deprecation_message(module_name), DeprecationWarning, skip_file_prefixes=_SKIP_FILE_PREFIXES)


__all__ = ["WEB_REMOVAL_VERSION", "WEB_REPLACEMENT_URL", "warn_deprecated_import", "web_deprecation_message"]
