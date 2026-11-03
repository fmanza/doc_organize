"""Interfaz web opcional de doc_organize (REQ-007, extra `[web]`).

Obsoleta desde 0.14.0 (L-10): congelada (solo hotfix) y se retira en 1.0.0. Usa doc_organize_web
(https://github.com/fmanza/doc_organize_web).
"""

from doc_organize._deprecations import warn_deprecated_import

warn_deprecated_import("doc_organize.web")

from doc_organize.web.app import create_app  # noqa: E402 - el aviso va antes de cargar la app

__all__ = ["create_app"]
