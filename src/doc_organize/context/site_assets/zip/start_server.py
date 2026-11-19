"""Abre el sitio de este ZIP en el navegador con un servidor local (solo este equipo).

Uso: `python start_server.py` (Python 3.10 o posterior, sin instalar nada). Sirve la carpeta `sitio/` en
`http://127.0.0.1:<puerto libre>/` y abre el navegador. Ctrl+C para pararlo.

El servidor solo escucha en 127.0.0.1: nadie más en la red puede verlo. También se puede abrir `sitio/index.html` con
doble clic, sin servidor; el servidor solo hace falta si el navegador no deja buscar desde `file://`.
"""

import functools
import http.server
import socketserver
import sys
import threading
import webbrowser

from pathlib import Path

SITE = Path(__file__).resolve().parent / "sitio"


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


def main() -> int:
    if not (SITE / "index.html").is_file():
        print(f"No se encuentra el sitio en {SITE}", file=sys.stderr)
        return 1
    handler = functools.partial(_Handler, directory=str(SITE))
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler) as server:
        url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
        print(f"Sitio en {url} (Ctrl+C para parar)")
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
