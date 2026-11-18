"""Spike de M0 para F3 (sitio sin conexión, plan único 2.0.0): ¿qué da Zensical con el plugin `offline`?

Construye en una carpeta temporal un sitio sintético y responde a:

1. ¿`offline` funciona desde `zensical.toml`? ¿Qué cambia (`use_directory_urls`, índice de búsqueda)?
2. ¿Quedan referencias a terceros (unpkg.com: shim `iframe-worker`, Mermaid)? ¿Se evitan con un shim local?
3. ¿Se puede inyectar una CSP en `<meta>` con `theme.custom_dir` (bloque `extrahead`)?
4. ¿Dos builds seguidos dan el mismo `site/` (reproducibilidad del ZIP)?
5. ¿Cuánto pesa el índice de búsqueda con N páginas?
6. ¿El HTML incrustado (`<script>`, `onerror`) llega tal cual? (confirma la necesidad de D6 a).

Uso: python spike_zensical_offline.py [--pages 2600] [--words 400] [--shim <ruta a iframe-worker/shim.js>]
Sin red. Escribe un informe en la salida estándar (se copia a SPIKE.md).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

from pathlib import Path

HOSTILE = """# Página hostil

<script>alert("xss")</script>

<img src="x" onerror="alert(1)">

[enlace](javascript:alert(1))

![remota](https://example.com/pixel.png)

```mermaid
graph TD; A-->B
```
"""

CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; connect-src 'none'; img-src 'self' data:; frame-src 'none'; form-action 'none'"


def _write_site(root: Path, pages: int, words: int, shim: Path | None) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True)
    (docs / "index.md").write_text("# Inicio\n\nSitio de prueba.\n", encoding="utf-8")
    (docs / "hostil.md").write_text(HOSTILE, encoding="utf-8")
    nav = ['{ "Inicio" = "index.md" }', '{ "Hostil" = "hostil.md" }']
    body = " ".join(f"palabra{i % 997}" for i in range(words))
    for index in range(pages):
        (docs / "dominio").mkdir(exist_ok=True)
        (docs / "dominio" / f"doc{index}.md").write_text(f"# Documento {index}\n\n{body}\n", encoding="utf-8")
    if pages:
        nav.append('{ "Dominio" = [' + ", ".join(f'"dominio/doc{i}.md"' for i in range(pages)) + "] }")

    overrides = root / "overrides"
    overrides.mkdir()
    (overrides / "main.html").write_text(
        '{% extends "base.html" %}\n{% block extrahead %}'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
        "{% endblock %}\n",
        encoding="utf-8",
    )
    polyfills = ""
    if shim is not None:
        target = docs / "assets" / "vendor" / "iframe-worker"
        target.mkdir(parents=True)
        shutil.copy(shim, target / "shim.js")
        polyfills = '\n[project.extra]\npolyfills = ["assets/vendor/iframe-worker/shim.js"]\n'
    (root / "zensical.toml").write_text(
        "[project]\n"
        'site_name = "Spike"\n'
        'docs_dir = "docs"\n'
        'site_dir = "site"\n'
        f"nav = [{', '.join(nav)}]\n"
        "[project.theme]\n"
        'language = "es"\n'
        "font = false\n"
        'custom_dir = "overrides"\n'
        "[project.plugins.offline]\n"
        f"{polyfills}",
        encoding="utf-8",
    )


def _build(root: Path) -> float:
    start = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-m", "zensical", "build", "--clean"], cwd=root, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"zensical build falló:\n{result.stdout}\n{result.stderr}")
    return time.perf_counter() - start


def _digest(site: Path) -> str:
    sha = hashlib.sha256()
    for path in sorted(p for p in site.rglob("*") if p.is_file()):
        sha.update(path.relative_to(site).as_posix().encode())
        sha.update(path.read_bytes())
    return sha.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=2600)
    parser.add_argument("--words", type=int, default=400)
    parser.add_argument("--shim", type=Path, default=None)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_site(root, args.pages, args.words, args.shim)
        first = _build(root)
        site = root / "site"
        digest1 = _digest(site)
        second = _build(root)
        digest2 = _digest(site)

        html = {p: p.read_text(encoding="utf-8", errors="replace") for p in site.rglob("*.html")}
        hostile = next(text for path, text in html.items() if path.name == "hostil.html")
        third_party = sorted(
            {m for text in html.values() for m in re.findall(r"https?://(?:unpkg\.com|cdn\.[\w.]+)[^\"' >]*", text)}
        )
        search = sorted(p for p in site.rglob("*") if p.is_file() and "search" in p.as_posix().lower())
        total = sum(p.stat().st_size for p in site.rglob("*") if p.is_file())

        print(f"pages={args.pages} words={args.words} shim_local={args.shim is not None}")
        print(f"build_s first={first:.1f} second={second:.1f}")
        print(f"reproducible={digest1 == digest2}")
        print(f"site_mb={total / 1e6:.1f}")
        for path in search:
            print(f"search_file {path.relative_to(site).as_posix()} {path.stat().st_size / 1e6:.2f} MB")
        print(f"html_links_to_folders={sum(len(re.findall(r'href=\"(?!https?:)[^\"]*/\"', t)) for t in html.values())}")
        print(f"csp_meta_present={'Content-Security-Policy' in hostile}")
        print(f"third_party_refs={third_party}")
        print(f"hostile_script_tag_raw={'<script>alert(' in hostile}")
        print(f"hostile_onerror_raw={'onerror=' in hostile}")
        print(f"hostile_javascript_href={'href="javascript:' in hostile}")
        print(f"remote_img={'https://example.com/pixel.png' in hostile}")


if __name__ == "__main__":
    main()
