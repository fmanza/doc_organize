"""Tests de `create_templates()` (revisión de seguridad, 2026-09-01)."""

from pathlib import Path

from doc_organize.web.templating import create_templates


def test_create_templates_forces_autoescape_on(tmp_path: Path) -> None:
    templates = create_templates(tmp_path)

    assert templates.env.autoescape is True


def test_create_templates_autoescape_survives_html_j2_naming(tmp_path: Path) -> None:
    # select_autoescape() por defecto solo mira la ultima extension del nombre de
    # plantilla ("j2" en "*.html.j2") y no la reconoce -- confirma que el fix no
    # depende de jinja2.select_autoescape() adivinar bien esa convencion.
    template_path = tmp_path / "sample.html.j2"
    template_path.write_text("{{ value }}", encoding="utf-8")
    templates = create_templates(tmp_path)

    rendered = templates.get_template("sample.html.j2").render(value="<script>alert(1)</script>")

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered


def test_create_templates_registers_date_format_filters(tmp_path: Path) -> None:
    template_path = tmp_path / "sample.html.j2"
    template_path.write_text("{{ value | format_datetime }} / {{ seconds | format_duration }}", encoding="utf-8")
    templates = create_templates(tmp_path)

    rendered = templates.get_template("sample.html.j2").render(value="2026-08-01T10:00:00+00:00", seconds=65.4)

    # Agosto (horario de verano en Europe/Madrid, valor por defecto): UTC+2.
    assert rendered == "01/08/2026 12:00:00 / 1m 5s"
