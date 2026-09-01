"""
Factoria compartida de `Jinja2Templates` (revisión de seguridad, 2026-09-01).

`Jinja2Templates(directory=...)` usa por defecto `autoescape=jinja2.select_autoescape()`,
que solo activa el autoescape para nombres de plantilla que terminan en
`.html`/`.htm`/`.xml`. Todas las plantillas de esta app se llaman `*.html.j2` (la
extensión real es `.j2`), así que ese autoescape por defecto queda desactivado — un
valor de cualquier campo derivado de datos externos (nombre de fichero real, ruta de
carpeta, etc.) se renderiza sin escapar y abre la puerta a XSS. Cada módulo de rutas
creaba su propia instancia de `Jinja2Templates` y tenía que acordarse de este override
por separado; `create_templates()` centraliza el fix para que una ruta nueva no pueda
repetir el olvido.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates


def create_templates(directory: str | Path) -> Jinja2Templates:
    """Crea un `Jinja2Templates` con el autoescape forzado a `True`.

    Args:
        directory (str | Path): Carpeta de plantillas (típicamente `web/templates/`).

    Returns:
        Jinja2Templates: Instancia lista para `TemplateResponse()`, con autoescape
            activo independientemente del nombre de fichero de la plantilla.

    Example:
        >>> templates = create_templates(Path(__file__).parent / "templates")
        >>> templates.env.autoescape
        True
    """
    templates = Jinja2Templates(directory=str(directory))
    templates.env.autoescape = True
    return templates


__all__ = ["create_templates"]
