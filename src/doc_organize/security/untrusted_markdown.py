"""
Markdown de terceros sin nada activo (2.0.0, F3, D6 a): `neutralize_untrusted_markdown`.

El sitio sin conexión se abre desde el disco (`file://`) o con `start_server.py`, sin la CSP `sandbox` con la que la web
sirve el sitio. Zensical (Python-Markdown) deja pasar tal cual el HTML incrustado en los `.md`, y los `.md` salen de
documentos de terceros: un `<script>` podría leer el índice de búsqueda (todo el corpus) y enviarlo fuera. Por eso, antes
de construir el sitio sin conexión, se neutraliza la **copia** de las páginas:

- El HTML fuera del código (bloques ```` ``` ````/`~~~` y `código en línea`) se escapa (`<script>` → `&lt;script&gt;`):
  se ve como texto. Los comentarios `<!-- … -->` completos se conservan (docling emite `<!-- image -->`; no ejecutan).
- Los enlaces e imágenes con esquema `javascript:`, `vbscript:` o `data:` (salvo `data:image/` en imágenes) quedan
  como su texto. Se comprueba el esquema tras decodificar entidades y quitar espacios y controles
  (`java&#9;script:`), como hace el navegador.
- Las imágenes remotas (`http(s)://`, `//`) pasan a ser un enlace («Imagen externa: …»): abrir la página no avisa a un
  tercero (píxel de seguimiento). Las imágenes por referencia (`![alt][ref]`) pasan a enlace por la misma razón.
- Las listas de atributos (`{: onclick=… }`, extensión `attr_list`, activa en Zensical) con manejadores `on*`, `href`,
  `src`, `style` o similares se escapan.

Es idempotente: neutralizar dos veces da lo mismo que una.

Example:
    >>> result = neutralize_untrusted_markdown('Hola <script>alert(1)</script> <!-- image --> [x](javascript:alert(1))')
    >>> print(result.text)
    Hola &lt;script>alert(1)&lt;/script> <!-- image --> x
    >>> result.counts == {"html": 2, "unsafe_links": 1}
    True
"""

from __future__ import annotations

import html
import re

from collections import Counter
from dataclasses import dataclass, field

#: Inicio de una etiqueta HTML, de cierre, de declaración o de instrucción (`<a`, `</a`, `<!DOCTYPE`, `<?xml`).
_TAG_START = re.compile(r"<(?=[A-Za-z/!?])")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"(`+)(?:.+?)(?<!`)\1(?!`)")
#: Enlace o imagen en línea: `[texto](url "título")` / `![alt](url)`.
_INLINE_LINK = re.compile(
    r"(?P<bang>!?)\[(?P<label>[^\]\n]*)\]\(\s*(?P<url><[^>\n]*>|[^\s()]+(?:\([^\s()]*\)[^\s()]*)*)(?P<title>\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^)\n]*\)))?\s*\)"
)
#: Imagen por referencia: `![alt][ref]`, `![alt][]`.
_REFERENCE_IMAGE = re.compile(r"!\[(?P<label>[^\]\n]*)\]\[(?P<ref>[^\]\n]*)\]")
#: Definición de referencia: `[ref]: url "título"`.
_DEFINITION = re.compile(r"^(?P<lead>\s{0,3}\[[^\]\n]+\]:\s*)(?P<url><[^>\n]*>|\S+)(?P<rest>.*)$")
_ATTR_LIST = re.compile(r"\{[^{}\n]*\}")
_DANGEROUS_ATTRIBUTE = re.compile(r"(?:^|[\s:{])(?:on[a-z]+|href|src|srcdoc|style|formaction|action|xlink:href|data|background)\s*=", re.IGNORECASE)
_UNSAFE_SCHEMES = ("javascript:", "vbscript:", "data:")
_REMOTE = ("http://", "https://", "//")
_INVISIBLE = re.compile(r"[\x00-\x20\x7f]+")


@dataclass(frozen=True)
class NeutralizeResult:
    """Resultado de `neutralize_untrusted_markdown`.

    Attributes:
        text (str): El Markdown sin nada activo.
        counts (dict[str, int]): Qué se neutralizó: `html` (etiquetas escapadas), `unsafe_links` (enlaces e imágenes con
            esquema peligroso), `remote_images` (imágenes remotas o por referencia pasadas a enlace) y `attributes`
            (listas de atributos con manejadores o URL).
    """

    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        """Si se neutralizó algo."""
        return bool(self.counts)


def neutralize_untrusted_markdown(text: str) -> NeutralizeResult:
    """`text` (Markdown de un documento de terceros) sin HTML activo, enlaces peligrosos ni imágenes remotas.

    Args:
        text: Markdown (p. ej. el `.md` que convirtió docling).
    """
    counts: Counter[str] = Counter()
    lines = text.split("\n")
    fence: str | None = None
    for index, line in enumerate(lines):
        opening = _FENCE.match(line)
        if fence is not None:
            if opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence) and not line.strip().strip(fence[0]):
                fence = None
            continue
        if opening:
            fence = opening.group(1)
            continue
        lines[index] = _line(line, counts)
    return NeutralizeResult(text="\n".join(lines), counts={key: value for key, value in sorted(counts.items()) if value})


def _line(line: str, counts: Counter[str]) -> str:
    definition = _DEFINITION.match(line)
    if definition is not None and not _safe_url(definition.group("url"), image=False):
        counts["unsafe_links"] += 1
        return f"{definition.group('lead')}#{definition.group('rest')}"
    parts: list[str] = []
    position = 0
    for code in _INLINE_CODE.finditer(line):  # el código en línea se queda como está: Markdown no lo interpreta
        parts.append(_text(line[position : code.start()], counts))
        parts.append(code.group(0))
        position = code.end()
    parts.append(_text(line[position:], counts))
    return "".join(parts)


def _text(segment: str, counts: Counter[str]) -> str:
    """Un trozo de texto fuera del código: comentarios intactos y el resto neutralizado."""
    parts: list[str] = []
    position = 0
    for comment in _COMMENT.finditer(segment):
        parts.append(_active(segment[position : comment.start()], counts))
        parts.append(comment.group(0))
        position = comment.end()
    parts.append(_active(segment[position:], counts))
    return "".join(parts)


def _active(segment: str, counts: Counter[str]) -> str:
    tags = len(_TAG_START.findall(segment))
    if tags:
        counts["html"] += tags
        segment = _TAG_START.sub("&lt;", segment)
    segment = _INLINE_LINK.sub(lambda match: _link(match, counts), segment)

    def reference_image(match: re.Match[str]) -> str:
        counts["remote_images"] += 1
        return f"[{match.group('label') or 'Imagen'}][{match.group('ref')}]"

    segment = _REFERENCE_IMAGE.sub(reference_image, segment)

    def attributes(match: re.Match[str]) -> str:
        if not _DANGEROUS_ATTRIBUTE.search(match.group(0)):
            return match.group(0)
        counts["attributes"] += 1
        return "&#123;" + match.group(0)[1:]

    return _ATTR_LIST.sub(attributes, segment)


def _link(match: re.Match[str], counts: Counter[str]) -> str:
    image, label, url = bool(match.group("bang")), match.group("label"), match.group("url")
    if not _safe_url(url, image=image):
        counts["unsafe_links"] += 1
        return label
    if image and _remote(url):
        counts["remote_images"] += 1
        return f"[Imagen externa: {label or 'sin texto'}]({url})"
    return match.group(0)


def _normalized(url: str) -> str:
    """La URL como la interpreta el navegador para decidir su esquema: sin `<>`, entidades decodificadas, sin espacios ni
    caracteres de control, en minúsculas."""
    decoded = _INVISIBLE.sub("", html.unescape(url)).lower()
    return decoded.removeprefix("<").removesuffix(">")


def _safe_url(url: str, *, image: bool) -> bool:
    normalized = _normalized(url)
    if image and normalized.startswith("data:image/"):
        return True
    return not normalized.startswith(_UNSAFE_SCHEMES)


def _remote(url: str) -> bool:
    return _normalized(url).startswith(_REMOTE)


__all__ = ["NeutralizeResult", "neutralize_untrusted_markdown"]
