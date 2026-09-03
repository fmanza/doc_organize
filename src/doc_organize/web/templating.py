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

También registra aquí el filtro `highlight`, común a todas las páginas con
buscador server-side (pestaña Caché de Escanear, Proyectos): antes cada módulo
de rutas que lo necesitaba lo redefinía por su cuenta. Igual criterio para
`format_datetime`/`format_duration` (revisión de formato de fecha/hora): antes
cada plantilla mostraba el timestamp ISO 8601 UTC crudo (`{{ x.created_at }}`)
directamente; ahora pasa por `doc_organize.utils.date_format`, que centraliza
la zona horaria y el patrón de visualización (por defecto, español/España).
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from doc_organize.utils.date_format import format_datetime, format_duration


def _highlight(text: str, query: str | None) -> Markup:
    """Envuelve en `<mark>` la subcadena de `text` que coincide (insensible a
    mayúsculas) con `query`. `text` viene de un dato controlado por quien busca
    (nombre de archivo, ruta de carpeta, nombre de proyecto...) — cada fragmento
    se escapa individualmente con `markupsafe.escape()` antes de recomponer el
    HTML, para no reabrir un XSS vía un valor malicioso."""
    if not query:
        return escape(text)
    lowered_text = text.lower()
    lowered_query = query.lower()
    start = lowered_text.find(lowered_query)
    if start == -1:
        return escape(text)
    end = start + len(query)
    return Markup("{}<mark>{}</mark>{}").format(text[:start], text[start:end], text[end:])


def create_templates(directory: str | Path) -> Jinja2Templates:
    """Crea un `Jinja2Templates` con el autoescape forzado a `True` y el filtro
    `highlight` disponible.

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
    templates.env.filters["highlight"] = _highlight
    templates.env.filters["format_datetime"] = format_datetime
    templates.env.filters["format_duration"] = format_duration
    return templates


__all__ = ["create_templates"]
