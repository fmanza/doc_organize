# Compatibilidad

Tabla de compatibilidad por versión de `doc_organize`. Generada a partir del historial real de
`pyproject.toml` (`git log --follow -- pyproject.toml`), no de la memoria/documentación —
`doc_organize` no tiene releases publicados en PyPI ni GitHub Releases todavía (ver
`CHANGELOG.md`): todas las versiones listadas son estados internos del repositorio, no paquetes
instalables desde fuera.

> **Nota (2026-10-31)**: desde la 0.9.3 hay wheel y sdist publicados en GitHub Releases; las versiones
> anteriores siguen siendo estados internos del repositorio.

> **Nota de corrección (2026-09-10)**: esta tabla llevaba desde 0.4.0 sin una fila nueva pese a que
> `pyproject.toml` ya iba por 0.7.0 — 3 versiones de diferencia. Las filas 0.5.0/0.6.0/0.7.0 se han
> reconstruido ahora verificando `git show <commit-de-bump>:pyproject.toml` de cada una (mismas
> cotas que 0.4.0 en los tres casos, sin cambios) al cerrar la 0.8.0.

| Versión | Python | Dependencias clave | Estado |
|---|---|---|---|
| 0.9.3 | `>=3.11` | Mismas cotas que 0.9.0 (sin cambios en `pyproject.toml` salvo la versión); primera versión con wheel en GitHub Releases | ✅ Activa |
| 0.9.0 | `>=3.11` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0`, nueva `cryptography>=41.0` (cifrado Fernet de credenciales de IA); `[ai]`: `httpx>=0.24`; `[context]`: `pyyaml>=6.0` | ❌ EOL |
| 0.8.0 | `>=3.11` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0`; nuevos extras `[ai]`: `httpx>=0.24`, `[context]`: `pyyaml>=6.0` | ❌ EOL |
| 0.7.0 | `>=3.11` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0` | ❌ EOL |
| 0.6.0 | `>=3.11` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0` | ❌ EOL |
| 0.5.0 | `>=3.11` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0` | ❌ EOL |
| 0.4.0 | `>=3.11` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0` | ❌ EOL |
| 0.3.0 | `>=3.11` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0` | ❌ EOL |
| 0.2.0 | `>=3.10` → `>=3.11`¹ | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0` | ❌ EOL |
| 0.1.0 | `>=3.10` | `docling[rapidocr]>=2.0.0`, `pydantic>=2.0`, `aiosqlite>=0.19`, extra `[web]`: `fastapi>=0.100`, `jinja2>=3.1.0` | ❌ EOL |

¹ El suelo mínimo subió de `>=3.10` a `>=3.11` **dentro** de la propia 0.2.0 (commit `83504cc`,
2026-08-29, antes de que `pyproject.toml` avanzara a 0.3.0) — ver
`.ai/sessions/2026-08-29-python-3-11/TRACEABILITY.md`. La columna refleja el estado final de esa
versión tal como quedó commiteado (`>=3.11`), no su estado inicial.

Las dependencias clave (`docling`, `pydantic`, `aiosqlite`) no han cambiado de cota mínima en
ninguna versión hasta la fecha — la columna se repite igual en la mayoría de filas porque es un
hecho verificado (`git show <commit>:pyproject.toml`), no una omisión. La 0.8.0 fue la primera en
sumar cotas nuevas, vía dos extras opcionales (`ai`, `context`) que no afectan a la instalación
base. La 0.9.0 añade `cryptography>=41.0` al extra `[web]` (cifrado en reposo de credenciales de
IA guardadas desde `/admin/configuracion-ia`) — sigue sin afectar a la instalación base
(`pip install doc_organize` sin extras).

## Cómo mantener esta tabla

Al cerrar una versión (fase VERSION, ver `.github/instructions/sync.instructions.md`):
1. Añadir una fila nueva arriba con la versión que se cierra, marcada `✅ Activa`.
2. Cambiar la fila que era `✅ Activa` a `❌ EOL` (este proyecto no publica releases externos que
   pudieran seguir en uso durante una transición — no hay estado `⚠️ Legacy` real hasta que eso
   cambie).
3. Verificar Python/dependencias clave contra el `pyproject.toml` real de ese commit, no copiar la
   fila anterior sin comprobar — si algo cambió, esta tabla debe reflejarlo exactamente.
