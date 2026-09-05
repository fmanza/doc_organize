# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-05
- **Tipo**: `hotfix` (PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION), dos
  rondas sobre el mismo área de código
- **Rama**: `develop`
- **Estado**: EN CURSO (ronda 1 ya commiteada; ronda 2 implementada, tests,
  lint, mypy y `mkdocs build --strict` en verde, commit pendiente)

## Objetivo
El usuario reportó dos conversiones reales terminadas en error durante un
escaneo: (1) un `.html` (informe OWASP ZAP) marcado `ERROR` sin ningún mensaje
visible; (2) un `.docx` con imágenes embebidas fallando con
`[Errno 2] No such file or directory` en una ruta claramente duplicada/mal
construida. Pidió el flujo `PLAN → AUDIT_PLAN` antes de implementar (ronda 1).
Tras commitear la ronda 1 y volver a escanear los mismos ficheros reales, los
dos siguieron fallando pero con causas **distintas y más precisas** (los
síntomas originales ya estaban resueltos): `MemoryError` sin pista en el HTML
(60 MB) y un `[Errno 2]` por un espacio final en el nombre del `.docx`. El
usuario pidió de nuevo `PLAN → AUDIT_PLAN → IMPLEMENT` para esta ronda 2.

## Cambios Ejecutados

### ✅ 1. RONDA 1 — PLAN + AUDIT_PLAN — Diagnóstico de causa raíz
**Descripción**: investigación (agente Explore + lectura directa) localizó
ambas causas en `src/doc_organize/converter/converter.py`:
- **Bug 1**: el único `except Exception as exc` de `convert_document()`
  (captura genérica deliberada, no relanza para no abortar el batch) hace
  `error=str(exc)` sin fallback — si la excepción no lleva mensaje
  (`str(exc) == ""`), el documento queda `ERROR` con `error_message=""`
  propagado sin corrección por `_build_entry`/`_collect_error_entries`
  (`scan_command.py`) hasta la UI/export.
- **Bug 2**: `resolve_output_paths()` usaba
  `Path(full_path).resolve().parts[1:]` (solo quita la unidad `C:\`) y
  reconstruía la ruta absoluta de origen ENTERA bajo `output_dir` — si
  `output_dir` vive en otra rama del árbol de ficheros que la carpeta
  escaneada, el resultado duplica/anida la jerarquía completa.
**Status**: ✅ el usuario confirmó explícitamente el diseño a aplicar (ver
punto 2) antes de implementar.

### ✅ 2. RONDA 1 — Decisión de diseño confirmada por el usuario (AskUserQuestion)
Tres opciones planteadas para el esquema de rutas de salida: (a) relativa a
un root de escaneo, (b) aplanar todo a `output_dir/<stem>`, (c) hash corto de
la ruta absoluta + stem. El usuario eligió **(a) — relativa a un root de
escaneo**.
**Status**: ✅ decisión tomada, usada como base de IMPLEMENT.

### ✅ 3. RONDA 1 — IMPLEMENT — Bug 1: mensaje de error nunca vacío
**Archivo(s)**: `src/doc_organize/converter/converter.py`.
**Descripción**: `error_message = str(exc) or f"{type(exc).__name__} sin
mensaje de error"` en vez de `str(exc)` a secas; `self.logger.warning(...,
exc_info=True)` para traceback completo en el log JSON.
**Status**: ✅ implementado y verificado.

### ✅ 4. RONDA 1 — IMPLEMENT — Bug 2: rutas de salida relativas a `scan_roots`
**Archivo(s)**: `src/doc_organize/converter/converter.py`,
`src/doc_organize/converter/ocr_scheduler.py`,
`src/doc_organize/scan/scan_command.py`, `docs/api/converter.md`.
**Descripción**: `resolve_output_paths(full_path, output_dir, scan_roots=())`
gana un tercer parámetro opcional (`Sequence[str]`, retrocompatible). Si
`full_path` cuelga de alguna de `scan_roots`, calcula la ruta relativa a la
raíz más específica que coincide y la replica bajo `output_dir`; si ninguna
coincide, se aplana a `output_dir/<stem>`. Propagado por toda la cadena real
de producción: `ScanCommand.run_streaming` → `_delete_orphaned_outputs` /
`_convert_documents` → `DocumentConverter.convert_document` /
`_write_outputs`, y `_process_ocr` → `OCRScheduler.process_with_ocr` →
`convert_document`.
**Status**: ✅ implementado y verificado (3 tests nuevos/actualizados).

### ✅ 5. RONDA 1 — AUDIT_CODE
**Descripción**: sin regresiones — 489 passed, `ruff`/`mypy`/`mkdocs build`
limpios. `scan_roots` opcional en los 5 puntos donde se añadió.
**Status**: ✅ **commiteado** como `65d9b10` (`fix: no duplicar la ruta
absoluta de origen al convertir documentos, e incluir siempre un mensaje de
error`), por el usuario directamente (fuera de esta sesión de Claude Code).

### ✅ 6. RONDA 2 — Verificación en caliente con los ficheros reales
**Descripción**: tras la ronda 1, el usuario reescaneó los mismos dos
ficheros reales. Confirmó que ambos síntomas originales desaparecieron (la
ruta del `.docx` ya no arrastra `DOC_ORGANIZE_04`; el HTML ya muestra un tipo
de excepción en vez de nada), pero ambos documentos **siguen fallando por
otra causa**, más profunda:
- **HTML (informe ZAP)**: `MemoryError` — confirmado que el fichero real pesa
  **63.386.397 bytes (~60,4 MB)**, un HTML gigantesco que agota memoria al
  construir el árbol DOM (bs4/lxml, vía Docling).
- **.docx (Anti SPAM correo Virtual Desk)**: `[Errno 2]` en
  `...\img\Anti SPAM correo Virtual Desk \image_...png` — el nombre de
  origen termina en espacio antes de `.docx`. Se confirmó por descarte que
  NO es un problema de longitud de ruta (197 caracteres, muy por debajo de
  `MAX_PATH`=260): es que Windows normaliza (quita) espacios/puntos finales
  de un componente de ruta SOLO cuando es el ÚLTIMO de la llamada a la API.
  Al crear `img/<stem>/` (stem = último componente en ese momento) el
  espacio desaparece del directorio real; al escribir luego una imagen
  dentro (`stem` pasa a ser un componente INTERMEDIO) no se normaliza, y
  Windows busca un directorio con el espacio que nunca existió.
**Status**: ✅ diagnóstico confirmado con evidencia real (tamaño exacto del
fichero, longitud exacta de la ruta), no solo hipótesis.

### ✅ 7. RONDA 2 — PLAN + AUDIT_PLAN + decisión del usuario
**Descripción**: se plantearon opciones para cada bug (ver conversación):
Bug 1 — (A) solo mensaje específico para `MemoryError`, (B) A + guardia
previa por tamaño, (C) aislar en subproceso, (D) preprocesar HTML de ZAP.
Bug 2 — (A) sanear solo el `stem` final, (B) sanear cada segmento de la
jerarquía mirroreada (carpetas intermedias + stem). AUDIT_PLAN señaló, para
ambos: riesgo de colisión por nombres que solo difieren en espacio/punto
final tras el saneo (mismo tipo de riesgo ya aceptado con el namespacing por
stem existente); para Bug 1, riesgo de que el mensaje sugiera con demasiada
certeza "el documento es la causa" cuando podría ser presión de memoria del
sistema en ese instante.
**Status**: ✅ el usuario eligió explícitamente **Bug 1 → opción A** (solo
mensaje específico, sin guardia de tamaño) y **Bug 2 → opción B** (sanear
toda la jerarquía).

### ✅ 8. RONDA 2 — IMPLEMENT
**Archivo(s)**: `src/doc_organize/converter/converter.py`,
`tests/unit/test_converter.py`, `docs/api/converter.md`, `CHANGELOG.md`.
**Descripción**:
- Bug 1: en el `except Exception as exc`, si `isinstance(exc, MemoryError)`,
  el mensaje pasa a ser `f"Memoria insuficiente durante la conversión
  (documento de {size_mb:.1f} MB)"` (usando `source_doc.size_bytes`, ya
  disponible) en vez del fallback genérico — deliberadamente redactado como
  correlación ("durante la conversión"), no como causa cierta.
- Bug 2: en `resolve_output_paths`, `stem = stem.rstrip(" .")` y
  `dir_parts = [part.rstrip(" .") for part in relative_parts[:-1]]` — se
  sanea cada segmento de la ruta mirroreada, no solo el nombre final.
- Se actualizó `docs/api/converter.md` ("Notas Internas") y `CHANGELOG.md`
  (`[Unreleased] > Fixed`, incluyendo también la entrada que faltaba de la
  ronda 1, nunca añadida al changelog pese a estar ya commiteada).
**Status**: ✅ implementado, con 3 tests nuevos:
`test_convert_document_memory_error_reports_size_in_message` (usa el tamaño
real del informe ZAP, 63.386.397 bytes, y verifica "60.4 MB" en el mensaje),
`test_resolve_output_paths_strips_trailing_space_from_stem` (reproduce el
nombre real del `.docx`), `test_resolve_output_paths_strips_trailing_space_
from_intermediate_folder` (mismo saneo en una carpeta intermedia, no solo en
el fichero final).

### ✅ 9. RONDA 2 — AUDIT_CODE
**Descripción**: sin regresiones — 492 passed (489 previos + 3 nuevos),
`ruff check`/`mypy src` limpios, `mkdocs build --strict` sin warnings tras
documentar ambos fixes.
**Status**: ✅ 492 passed, 21 deselected (slow), 0 fallos.

---

## Impacto

### Código
- **Archivos modificados (ronda 2, sin commitear)**:
  `src/doc_organize/converter/converter.py`, `tests/unit/test_converter.py`,
  `docs/api/converter.md`, `CHANGELOG.md`.
- **Archivos modificados (ronda 1, ya commiteados en `65d9b10`)**:
  `src/doc_organize/converter/converter.py`,
  `src/doc_organize/converter/ocr_scheduler.py`,
  `src/doc_organize/scan/scan_command.py`, `tests/unit/test_converter.py`,
  `docs/api/converter.md`.
- **Cambios funcionales**: sí — `ConversionResult.error` para un `MemoryError`
  ahora incluye el tamaño del documento en MB en vez del fallback genérico;
  `resolve_output_paths()` sanea espacios/puntos finales de cada segmento de
  ruta mirroreado (no solo el esquema relativo-a-root de la ronda 1).

### Compatibilidad
- **BREAKING**: ninguno.
- **NO BREAKING**: cambio de comportamiento (no de firma) — un documento con
  nombre terminado en espacio/punto ahora genera una salida con ese carácter
  ya recortado; antes generaba una ruta que fallaba al escribir imágenes. Sin
  migración de caché (mismo razonamiento que la ronda 1).

---

## Verificación
```
# Ronda 1 (ya commiteada)
python -m pytest -m "not slow" -q        → 489 passed, 21 deselected

# Ronda 2 (esta sesión)
python -m ruff check src tests                              → All checks passed!
python -m mypy src                                           → Success: no issues found in 53 source files
python -m pytest tests/unit/test_converter.py -m "not slow" -q  → 12 passed
python -m pytest -m "not slow" -q                             → 492 passed, 21 deselected
mkdocs build --strict                                         → sin warnings ni links rotos
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Colisión por `rstrip(" .")`: dos nombres (fichero o carpeta) que solo difieren en espacios/puntos finales producen la misma salida tras el saneo — una reconversión de uno podría borrar las imágenes del otro (`shutil.rmtree` antes de escribir) | Caso extremo, poco probable en nombres reales; mismo tipo de riesgo ya aceptado con el namespacing por stem existente (dos ficheros `a.pdf`/`a.docx` ya colisionan igual) | Aceptado por el usuario en AUDIT_PLAN de ronda 2, no mitigado |
| Segmento que queda vacío tras `rstrip(" .")` (nombre de origen compuesto solo por espacios/puntos) produce una salida `output_dir/.md` (fichero oculto en Windows) | Caso exótico, no probado; no crashea | Aceptado, no mitigado |
| Mensaje de `MemoryError` da a entender que el tamaño del documento es la causa, pero también podría deberse a presión de memoria del sistema en ese instante sobre un documento pequeño | Redactado como correlación ("durante la conversión"), no como causa cierta; el usuario aceptó explícitamente no añadir guardia previa por tamaño (opción B descartada) | Aceptado por decisión explícita del usuario |
| `_delete_orphaned_outputs` recalcula la ruta antigua con los `scan_roots` ACTUALES — si las carpetas escaneadas cambiaron entre la conversión original y el "forzar rescan", la ruta recalculada podría no coincidir con la escrita originalmente | Edge case inherente al esquema relativo-a-root elegido en ronda 1; no se detectó forma de evitarlo sin persistir el root usado en cada conversión | No mitigado, aceptado por alcance (heredado de ronda 1) |
| El fichero real que dispara el bug del `.docx` no pudo verificarse directamente en disco durante esta sesión (ruta con tilde no resuelta desde las herramientas usadas) — el fix se validó con tests que reproducen el nombre exacto reportado, no con una reconversión real del fichero original | Pendiente que el usuario reescanee el proyecto real tras el commit de esta ronda para confirmar en caliente | No mitigado, ver Siguientes Pasos |

---

## Siguientes Pasos (Recomendado)
1. Confirmar el mensaje de commit de la ronda 2 (más abajo) y crear el
   commit — pendiente de confirmación explícita del usuario.
2. Reescanear/forzar rescan de los dos proyectos reales (ZAP e informe con
   `.docx`) tras el commit, para confirmar en caliente: el HTML debería
   seguir fallando pero con un mensaje que incluya "60.4 MB"; el `.docx`
   debería convertir con éxito (o, si sigue fallando, indicaría una tercera
   causa distinta a investigar).
3. `git push` a `origin/develop` — no evaluado en esta sesión, pendiente de
   petición explícita.

---

## Directrices para Futuras IAs

- **[`DocumentConverter.resolve_output_paths()` calcula rutas relativas a
  `scan_roots`, nunca a la raíz absoluta del disco]**: recibe
  `scan_roots: Sequence[str] = ()`. Si ninguna raíz coincide, aplana a
  `output_dir/<stem>` — NUNCA reconstruir `Path(full_path).resolve().
  parts[1:]` bajo `output_dir` directamente (bug real, ronda 1).
- **[`resolve_output_paths()` sanea cada segmento con `rstrip(" .")`]**: un
  nombre de origen (fichero o carpeta) que termina en espacio o punto rompe
  la escritura posterior porque Windows normaliza (quita) esos caracteres
  SOLO en el último componente de cada llamada de API — al crear el
  directorio (donde el nombre problemático ES el último componente) se
  normaliza, pero al escribir un fichero dentro (donde pasa a ser un
  componente INTERMEDIO) no se normaliza, y busca un nombre que nunca
  existió en disco (`[Errno 2] No such file or directory`, bug real: `.docx`
  con nombre terminado en espacio, ronda 2, sesión 2026-09-05). Si se añade
  cualquier otro punto que derive nombres de carpeta/fichero a partir del
  nombre de origen, aplicar el mismo saneo ahí también.
- **[Cualquier punto que reconvierta un documento ya convertido debe recibir
  el MISMO `scan_roots` que la primera pasada]**: `OCRScheduler.
  process_with_ocr()` y `ScanCommand._delete_orphaned_outputs()` dependen de
  calcular la misma ruta que `_convert_documents()` calculó originalmente.
- **[`ConversionResult.error` nunca debe ser `""`, y `MemoryError` tiene su
  propio mensaje]**: el `except Exception` de `convert_document()` usa
  `str(exc) or f"{type(exc).__name__} sin mensaje de error"` como fallback
  genérico, PERO `MemoryError` (que nunca lleva mensaje propio, por diseño de
  Python) tiene una rama previa dedicada que reporta `source_doc.size_bytes`
  en MB — redactado como correlación, no como causa cierta (un `MemoryError`
  en un documento pequeño también es posible por presión de memoria del
  sistema). Cualquier otro tipo de excepción "sin mensaje por diseño" que
  aparezca en el futuro (raras en la práctica) es candidata al mismo patrón:
  una rama `isinstance` específica antes del fallback genérico.
- **[Un documento HTML de decenas de MB (informes de herramientas de
  escaneo de seguridad tipo OWASP ZAP) puede agotar memoria en el backend
  HTML de Docling]**: no hay guardia previa por tamaño (descartada
  explícitamente por el usuario en esta sesión, ronda 2) — si en el futuro
  se decide añadir una, el punto de inserción es al principio del `try` de
  `convert_document()`, antes de llamar a `docling_converter.convert()`,
  usando `source_doc.size_bytes` contra un umbral en `core/constants.py`.
- **[`_JsonFormatter` (`utils/logging.py`) ya serializa `exc_info` si el
  record lo lleva]**: no hace falta ningún cambio de logging para que
  `exc_info=True` en `logger.warning()`/`logger.error()` deje el traceback
  completo en el log JSON.
- **[El `CHANGELOG.md` del proyecto (`[Unreleased]`) no se actualiza solo]**:
  el commit `65d9b10` (ronda 1) no tocó `CHANGELOG.md` pese a ser un fix
  visible — se añadió retroactivamente en esta sesión (ronda 2), junto a la
  entrada de la propia ronda 2. Recordar añadir la entrada de changelog en
  el mismo commit del fix, no solo describirla en la conversación.

---

## Veredicto

### 🟡 GO_CONDICIONAL

**Criterios**:
- ✅ Ronda 1: PLAN/AUDIT_PLAN/IMPLEMENT/AUDIT_CODE completos, commiteada
  (`65d9b10`) y verificada en caliente por el usuario con los ficheros reales
- ✅ Ronda 2: PLAN/AUDIT_PLAN ejecutados sobre las causas reales encontradas
  al reescanear (`MemoryError` de 60,4 MB; espacio final en nombre de
  `.docx`), decisión de alcance confirmada explícitamente por el usuario
  para cada bug
- ✅ Ronda 2: IMPLEMENT completo, con 3 tests de regresión nuevos que
  reproducen los valores reales del bug (tamaño exacto del HTML, nombre
  exacto del `.docx`)
- ✅ Ronda 2: AUDIT_CODE — 492 passed, `ruff`/`mypy`/`mkdocs build --strict`
  en verde; `docs/api/converter.md` y `CHANGELOG.md` actualizados (incluida
  la entrada de changelog que faltaba de la ronda 1)
- ⬜ Commit de la ronda 2: mensaje redactado, pendiente de confirmación
  explícita del usuario para crearlo
- ⬜ Verificación en caliente de la ronda 2 con los ficheros reales: pendiente
  (a diferencia de la ronda 1, aún no reescaneada por el usuario)
- ⬜ Push a `origin/develop`: no solicitado en esta sesión

**Evidencia**:
- Branch: `develop`
- Commits: `65d9b10` (ronda 1, ya en el historial); ronda 2 aún en working
  tree, sin commitear
- Tests: 492 passed, 21 deselected (`python -m pytest -m "not slow" -q`)

**Sesión cerrada**: pendiente (commit de la ronda 2 no creado aún)
