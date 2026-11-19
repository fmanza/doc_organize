"""`neutralize_untrusted_markdown` (M9, F3, D6 a): nada activo de terceros en el sitio sin conexión."""

import pytest

from doc_organize.security.untrusted_markdown import neutralize_untrusted_markdown


@pytest.mark.parametrize(
    ("markdown", "expected", "counts"),
    [
        ("<script>alert(1)</script>", "&lt;script>alert(1)&lt;/script>", {"html": 2}),
        ('<img src="x" onerror="alert(1)">', '&lt;img src="x" onerror="alert(1)">', {"html": 1}),
        ('<iframe src="https://e.example"></iframe>', '&lt;iframe src="https://e.example">&lt;/iframe>', {"html": 2}),
        ("<form action=x><input></form> <style>p{}</style> <object></object> <embed>", None, {"html": 8}),
        ("<!DOCTYPE html><?xml x?>", "&lt;!DOCTYPE html>&lt;?xml x?>", {"html": 2}),
        ("[pulsa](javascript:alert(1))", "pulsa", {"unsafe_links": 1}),
        ("[a](JaVa&#9;Script:alert(1)) [b](vbscript:x) [c](data:text/html,x)", "a b c", {"unsafe_links": 3}),
        ("[d]( <javascript:alert(1)> )", "d", {"html": 1, "unsafe_links": 1}),
        ("![espía](https://tracker.example/p.png)", "[Imagen externa: espía](https://tracker.example/p.png)", {"remote_images": 1}),
        ("![](//tracker.example/p.png)", "[Imagen externa: sin texto](//tracker.example/p.png)", {"remote_images": 1}),
        ("![x][logo]\n\n[logo]: https://e.example/l.png", "[x][logo]\n\n[logo]: https://e.example/l.png", {"remote_images": 1}),
        ('[ref]: javascript:alert(1) "t"', '[ref]: # "t"', {"unsafe_links": 1}),
        (
            '[x](a.md){onclick="alert(1)"} {: .nota } {: style="x" }',
            '[x](a.md)&#123;onclick="alert(1)"} {: .nota } &#123;: style="x" }',
            {"attributes": 2},
        ),
    ],
)
def test_active_content_is_neutralized(markdown: str, expected: str | None, counts: dict[str, int]) -> None:
    result = neutralize_untrusted_markdown(markdown)

    if expected is not None:
        assert result.text == expected
    assert "<" not in result.text.replace("<!--", "")
    assert result.counts == counts and result.changed


@pytest.mark.parametrize(
    "markdown",
    [
        "# Título\n\nTexto con **negrita**, [enlace](otra.md), [web](https://e.example) y ![figura](img/f.png).",
        "<!-- image -->\n\nTexto <!-- comentario --> más texto.",
        "![incrustada](data:image/png;base64,iVBORw0KGgo=)",
        "Código `<script>alert(1)</script>` en línea y ``doble `<b>` ``.",
        "```html\n<script>alert(1)</script>\n```\n\n~~~~\n<iframe>\n~~~~",
        "{: .nota } y $a < b$",
    ],
)
def test_safe_markdown_is_left_alone(markdown: str) -> None:
    result = neutralize_untrusted_markdown(markdown)

    assert result.text == markdown and not result.changed


def test_code_fences_only_close_with_the_same_fence() -> None:
    markdown = "````\n```\n<script>dentro</script>\n````\n<script>fuera</script>"

    result = neutralize_untrusted_markdown(markdown)

    assert "<script>dentro</script>" in result.text and "&lt;script>fuera&lt;/script>" in result.text


def test_unterminated_comment_is_escaped() -> None:
    assert neutralize_untrusted_markdown("<!-- sin cerrar <script>").text == "&lt;!-- sin cerrar &lt;script>"


def test_idempotent() -> None:
    markdown = (
        "<script>x</script> <!-- image --> [a](javascript:x) ![b](https://e.example/b.png) ![c][r] {onclick=x}\n\n[r]: vbscript:x\n\n```\n<b>\n```"
    )
    once = neutralize_untrusted_markdown(markdown)

    twice = neutralize_untrusted_markdown(once.text)

    assert twice.text == once.text and not twice.changed
    assert once.counts == {"attributes": 1, "html": 2, "remote_images": 2, "unsafe_links": 2}
