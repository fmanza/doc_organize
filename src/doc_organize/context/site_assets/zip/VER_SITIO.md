# Cómo ver este sitio

Este ZIP contiene la documentación organizada del proyecto **$project** como un sitio web que funciona sin conexión y
sin instalar nada.

1. Descomprime el ZIP en una carpeta.
2. Abre `sitio/index.html` con doble clic (Edge, Chrome o Firefox).

Si el buscador no funciona al abrirlo así (algunos navegadores lo limitan en ficheros locales), usa el servidor local
incluido; necesita Python 3.10 o posterior:

| Sistema | Cómo |
|---|---|
| Windows | Doble clic en `start_server.py`, o en una terminal: `py start_server.py` |
| macOS | En Terminal, en la carpeta: `python3 start_server.py` |
| Linux | En una terminal, en la carpeta: `python3 start_server.py` |

Se abre el navegador en `http://127.0.0.1:<puerto>/`. El servidor solo escucha en este equipo; Ctrl+C lo para.

## Huella

El SHA-256 del ZIP lo da quien lo entrega: compáralo para saber que no ha cambiado
(Windows: `certutil -hashfile <zip> SHA256`; macOS y Linux: `shasum -a 256 <zip>`).

## Contenido de terceros

El texto del sitio sale de documentos de terceros. Antes de generarlo se ha **neutralizado**: el HTML incrustado se
muestra como texto, los enlaces `javascript:` no funcionan y las imágenes remotas son enlaces que no se cargan solos. El
sitio no pide nada a internet. Aun así, trátalo como el resto de la documentación del proyecto: puede contener
información confidencial.
