# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-11-14
- **Tipo**: `hotfix`
- **Rama**: `hotfix/zensical-search-limit`
- **Estado**: ✅ COMPLETADA (librería; la adaptación de doc_organize_web va en su propio repositorio)

## Objetivo
El sitio de contexto de un proyecto real (`CALIDAD_VD`, 214 páginas) no se construía desde doc_organize_web:
`zensical build` (0.0.71 y 0.1.1) fallaba entero porque un documento convertido sin títulos superaba el límite del
índice de búsqueda. Además, la web recortaba el error por el principio y se perdía la causa (la última línea).

## Cambios Ejecutados

### ✅ 1. Exclusión del buscador de las páginas que superan el límite

**Archivo(s)**: `src/doc_organize/context/site_generator.py`
**Descripción**: `generate()` (también con `build=False`) estima las entradas del índice del sitio y los tokens de la
sección más larga de cada página, y añade `search: exclude: true` a la cabecera de las que superarían
`2**(30 - ceil(log2 entradas))` posiciones (con margen ×1,1 en entradas y ×0,9 en tokens). Devuelve las páginas en
`SiteResult.search_excluded`.
**Status**: ✅

### ✅ 2. Causa legible en `SiteBuildError`

**Archivo(s)**: `src/doc_organize/core/exceptions.py`, `site_generator.py`
**Descripción**: atributos `cause` (última línea de la salida de zensical, o motivo propio) y `output_tail`; el mensaje
termina en `cause`.
**Status**: ✅

### ✅ 3. `write_text_atomic(newline=)`

**Archivo(s)**: `src/doc_organize/utils/atomic_write.py`
**Descripción**: parámetro opcional para reescribir un fichero conservando sus saltos de línea (CRLF).
**Status**: ✅

### ✅ 4. Dependencias, versión y documentación

**Archivo(s)**: `pyproject.toml` (1.4.0, `zensical>=0.1.1`), `CHANGELOG.md`, `COMPATIBILITY.md`, `docs/api/context.md`,
`docs/api/publica.md`, `docs/functional/context.md`
**Status**: ✅

---

## Impacto

### Código
- **Archivos modificados/creados**: 3 de `src/`, 1 de tests, 6 de documentación/configuración.
- **Cambios funcionales**: sí. Las páginas reorganizadas que superarían el límite reciben `search: exclude: true`;
  `str(SiteBuildError)` termina en la causa en lugar de en toda la salida.

### Compatibilidad
- **BREAKING**: ninguno en la API. Requiere `zensical>=0.1.1` (extras `[site]` y `[docs]`).
- **NO BREAKING**: `SiteResult.search_excluded` (por defecto `()`), `SiteBuildError(cause=, output_tail=)` *keyword-only*.

---

## Verificación
```
python -m ruff check src tests      # All checks passed!
python -m mypy src                  # Success: no issues found in 62 source files
python -m pytest                    # 831 passed, 7 skipped
pytest -m "slow or not slow" tests/unit/test_site_generator.py   # 45 passed (2 con zensical 0.1.1 real)
zensical build --strict             # No issues found
```
Validación manual sobre una copia de `CALIDAD_VD` con zensical 0.1.1: sin exclusión, código 1 («exceeds the search
index limit (107001 token positions; maximum 65536 for 14295 items)»); con la exclusión de la librería (2 páginas,
0,9 s de estimación), código 0 en 295 s.

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| La regla de 30 bits es empírica (no documentada por Zensical) y puede cambiar | Test real `test_real_build_succeeds_when_a_section_exceeds_the_search_index_limit` falla si cambia | Abierto |
| Estimación de tokens inexacta con HTML/código denso | Margen del 10 %; la causa del fallo ya se ve entera | Aceptado |
| `COMPATIBILITY.md` no tiene filas de 1.0.0 a 1.3.0 (ya faltaban) | Se añadió solo la de 1.4.0; reconstruir las demás desde `git show` en otra sesión | Abierto |

---

## Siguientes Pasos (Recomendado)
1. doc_organize_web: subir a `doc_organize==1.4.0` (wheel + `uv.lock`) y `zensical>=0.1.1`; mostrar `exc.cause` en
   lugar de `str(exc)[:500]`; avisar de `SiteResult.search_excluded` en el log del job.
2. Reconstruir las filas 1.0.0–1.3.0 de `COMPATIBILITY.md`.

---

## Directrices para Futuras IAs

- **[zensical/buscador]**: desde zensical 0.1.1 cada sección indexada admite `2**(30 - ceil(log2 N))` posiciones de
  token, con N = entradas del índice del sitio (página + cada título, también setext, fuera de bloques de código; el
  `#` inicial se funde con la página). Medido: 8 192 entradas → sin límite práctico; 8 193 → 65 536; 20 003 → 32 768;
  70 003 → 8 192. Por eso una página enorme aislada **no** reproduce el fallo: hace falta un sitio con más de 8 192
  entradas.
- **[zensical/buscador]**: en 0.0.71 el límite era en bytes (64 KB por campo), mucho más restrictivo; por eso el mínimo
  es `zensical>=0.1.1`.
- **[SiteGenerator]**: la exclusión se hace en `generate()` y no en `build_site()`, porque doc_organize_web llama a
  `generate(build=False)` y luego a `build_site()` por separado.
- **[SiteGenerator]**: los tokens se cuentan con el separador por defecto del buscador de Zensical
  (`zensical/config.py`, `plugins.search.separator`) tras quitar imágenes, URLs de enlaces, etiquetas HTML y `|`; en
  `CALIDAD_VD` coincide exactamente con el recuento de Zensical (107 001 y 132 189).
- **[herramientas]**: `write_text_atomic` escribe en modo texto; para reescribir un fichero ajeno sin convertir `\n`
  en `\r\n` en Windows, pasar `newline=""` y el texto leído con `read_bytes().decode()`.
- **[diagnóstico]**: ante un `SiteBuildError` recortado en la web, reproducir con el mismo intérprete que la web
  (`doc_organize_web/backend/.venv`), no con el Python del sistema: pueden tener versiones de zensical distintas.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- Causa raíz reproducida y corregida; build real de `CALIDAD_VD` en verde con zensical 0.1.1.
- Lint, tipos, tests y documentación estricta en verde.

**Evidencia**:
- Branch: `hotfix/zensical-search-limit`
- Commits: `fix: excluir del buscador las páginas que superan el límite del índice de Zensical (1.4.0)`
- Tests: 831 passed, 7 skipped; 45/45 en `test_site_generator.py` con los lentos

**Sesión cerrada**: 2026-11-14
