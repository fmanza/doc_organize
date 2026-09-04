# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-05
- **Tipo**: `hotfix` (PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION)
- **Rama**: `develop`
- **Estado**: EN CURSO (implementación, tests, lint, mypy y `mkdocs build` en
  verde; commit pendiente de confirmación explícita del usuario)

## Objetivo
El usuario reportó dos conversiones reales terminadas en error durante un
escaneo: (1) un `.html` (informe OWASP ZAP) marcado `ERROR` sin ningún mensaje
visible; (2) un `.docx` con imágenes embebidas fallando con
`[Errno 2] No such file or directory` en una ruta claramente duplicada/mal
construida. Pidió explícitamente el flujo `PLAN y AUDIT_PLAN` antes de
implementar, y tras revisar el diagnóstico autorizó `IMPLEMENT`.

## Cambios Ejecutados

### ✅ 1. PLAN + AUDIT_PLAN — Diagnóstico de causa raíz
**Descripción**: investigación (agente Explore + lectura directa) localizó
ambas causas en `src/doc_organize/converter/converter.py`:
- **Bug 1**: el único `except Exception as exc` de `convert_document()`
  (captura genérica deliberada, no relanza para no abortar el batch) hace
  `error=str(exc)` sin fallback — si la excepción no lleva mensaje
  (`str(exc) == ""`, plausible en fallos internos de bs4/lxml al parsear HTML
  grande/patológico como un informe ZAP), el documento queda `ERROR` con
  `error_message=""` propagado sin corrección por `_build_entry`/
  `_collect_error_entries` (`scan_command.py`) hasta la UI/export.
- **Bug 2**: `resolve_output_paths()` usaba
  `Path(full_path).resolve().parts[1:]` (solo quita la unidad `C:\`) y
  reconstruía la ruta absoluta de origen ENTERA bajo `output_dir` — si
  `output_dir` vive en otra rama del árbol de ficheros que la carpeta
  escaneada, el resultado duplica/anida la jerarquía completa, reproduciendo
  byte a byte la ruta del error real (`<output_dir>\Desarrollo\documentation\
  DOC_ORGANIZE_04\...\img\...\image_...png`).
AUDIT_PLAN identificó el riesgo funcional principal: cambiar el esquema de
`resolve_output_paths` afecta también a `ScanCommand._delete_orphaned_outputs`
y a la reconversión OCR (`OCRScheduler.process_with_ocr`), que deben usar el
mismo esquema para no desalinear rutas entre pasadas.
**Status**: ✅ el usuario confirmó explícitamente el diseño a aplicar (ver
punto 2) antes de implementar.

### ✅ 2. Decisión de diseño confirmada por el usuario (AskUserQuestion)
Tres opciones planteadas para el esquema de rutas de salida: (a) relativa a
un root de escaneo, (b) aplanar todo a `output_dir/<stem>`, (c) hash corto de
la ruta absoluta + stem. El usuario eligió **(a) — relativa a un root de
escaneo**, preservando la jerarquía real de lo escaneado sin arrastrar la
ruta absoluta completa del disco.
**Status**: ✅ decisión tomada, usada como base de IMPLEMENT.

### ✅ 3. IMPLEMENT — Bug 1: mensaje de error nunca vacío
**Archivo(s)**: `src/doc_organize/converter/converter.py`.
**Descripción**: en el `except Exception as exc` de `convert_document()`,
`error_message = str(exc) or f"{type(exc).__name__} sin mensaje de error"` en
vez de `str(exc)` a secas; además `self.logger.warning(..., exc_info=True)`
para que el traceback completo quede en el log JSON (`_JsonFormatter` ya
soportaba `exc_info`) aunque el mensaje de usuario tenga que recurrir al
fallback.
**Status**: ✅ implementado y verificado con test nuevo
(`test_convert_document_error_without_message_gets_fallback_text`, fuerza una
`Exception()` sin argumentos monkeypencheando `_needs_ocr`).

### ✅ 4. IMPLEMENT — Bug 2: rutas de salida relativas a `scan_roots`
**Archivo(s)**: `src/doc_organize/converter/converter.py`,
`src/doc_organize/converter/ocr_scheduler.py`,
`src/doc_organize/scan/scan_command.py`, `docs/api/converter.md`.
**Descripción**: `resolve_output_paths(full_path, output_dir, scan_roots=())`
gana un tercer parámetro opcional (`Sequence[str]`, retrocompatible). Si
`full_path` cuelga de alguna de `scan_roots`, calcula la ruta relativa a la
raíz MÁS ESPECÍFICA que coincide (mayor profundidad, por si hay roots
anidados) y la replica bajo `output_dir`; si ninguna coincide (o no se pasa
ninguna), se aplana a `output_dir/<stem>` — nunca reconstruye la ruta
absoluta completa del disco de origen, que era la causa del bug. Se
propagó `scan_roots` (con el valor de `clean_paths`, las carpetas que el
usuario indicó al escanear) por toda la cadena real de producción:
`ScanCommand.run_streaming` → `_delete_orphaned_outputs` /
`_convert_documents` → `DocumentConverter.convert_document` /
`_write_outputs`, y `_process_ocr` → `OCRScheduler.process_with_ocr` →
`convert_document` (necesario para que la segunda pasada de OCR calcule la
MISMA ruta que la primera para un mismo documento).
**Status**: ✅ implementado y verificado con 3 tests nuevos/actualizados en
`test_converter.py`: mirroring relativo a un root explícito, no-duplicación
del árbol absoluto cuando `output_dir` vive en otra rama (reproduce el bug
real reportado), y aplanado cuando ninguna raíz coincide.

### ✅ 5. AUDIT_CODE
**Descripción**: sin regresiones — suite completa no-slow en verde (489
passed) antes y después del cambio; `ruff check`, `mypy src` y
`mkdocs build` limpios. Se confirmó que `scan_roots` es opcional en los 5
puntos donde se añadió (`resolve_output_paths`, `convert_document`,
`_write_outputs`, `process_with_ocr`, `_delete_orphaned_outputs`), así que
ningún llamador/test preexistente que no lo pasa se rompe — cambia semántica
solo donde `ScanCommand` lo provee explícitamente. Se actualizó
`docs/api/converter.md` (firma de `convert_document`/`process_with_ocr`,
tabla de parámetros, nota en "Notas Internas") por ser cambio de API pública
(CLAUDE.md lo exige).
**Status**: ✅ 489 passed, 21 deselected (slow), 0 fallos.

---

## Impacto

### Código
- **Archivos modificados**: `src/doc_organize/converter/converter.py`,
  `src/doc_organize/converter/ocr_scheduler.py`,
  `src/doc_organize/scan/scan_command.py`, `tests/unit/test_converter.py`,
  `docs/api/converter.md`.
- **Cambios funcionales**: sí — `ConversionResult.error` nunca queda vacío
  (fallback de texto + traceback en log); las rutas de salida de conversión
  ya no duplican la ruta absoluta de origen cuando `output_dir` vive fuera de
  la carpeta escaneada.

### Compatibilidad
- **BREAKING**: ninguno declarado — `scan_roots` es `Sequence[str] = ()` en
  todos los puntos donde se añadió.
- **NO BREAKING**: el esquema de rutas de salida SÍ cambia de comportamiento
  por defecto (sin `scan_roots`, antes replicaba la ruta absoluta completa,
  ahora aplana a `output_dir/<stem>`) — no rompe ninguna firma, pero un
  `.md`/`.json` ya generado con el esquema anterior queda huérfano hasta el
  próximo "forzar rescan" (`force=True`, ya limpia huérfanos vía
  `_delete_orphaned_outputs`). No hay migración de caché: `cache.db` no
  almacena rutas de salida, solo el `full_path` de origen.

---

## Verificación
```
python -m ruff check src tests           → All checks passed!
python -m mypy src                       → Success: no issues found in 53 source files
python -m pytest tests/unit/test_converter.py -m "not slow" -q      → 9 passed
python -m pytest tests/unit/test_scan_command.py tests/unit/test_main.py \
  tests/unit/test_ocr_scheduler.py -m "not slow" -q                 → 44 passed
python -m pytest -m "not slow" -q        → 489 passed, 21 deselected
mkdocs build                             → sin warnings ni links rotos
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Con `scan_roots` vacío (llamador que no lo pasa, p.ej. uso directo de `DocumentConverter`/tests fuera de `ScanCommand`), la salida se aplana a `output_dir/<stem>` — dos documentos de distinto origen con el mismo stem podrían colisionar si ambos se convierten sin indicar `scan_roots` | En producción, `ScanCommand` siempre pasa `clean_paths`; solo afecta a uso directo de la librería sin pasar por `ScanCommand` | Aceptado, documentado en `docs/api/converter.md` |
| `_delete_orphaned_outputs` recalcula la ruta antigua con los `scan_roots` ACTUALES (`clean_paths` de la ejecución en curso) — si las carpetas escaneadas cambiaron entre la conversión original y el "forzar rescan", la ruta recalculada podría no coincidir con la que realmente se escribió, dejando el `.md`/`.json` antiguo huérfano sin borrar | Edge case inherente al esquema relativo-a-root elegido por el usuario; no se detectó forma de evitarlo sin persistir el root usado en cada conversión (fuera de alcance del hotfix) | No mitigado, aceptado por alcance |
| No se verificó con un repro exacto (fichero real) cuál de las dos hipótesis (longitud de ruta > `MAX_PATH` de Windows, o discrepancia por el espacio final del nombre `"...Virtual Desk "`) disparaba el `[Errno 2]` original — el fix ataca la causa estructural (duplicación de jerarquía), no la manifestación exacta | El fix elimina la ruta larga/duplicada de raíz, por lo que ambas hipótesis quedan cubiertas sin necesidad de diagnosticarlas por separado | Aceptado, no bloqueante |

---

## Siguientes Pasos (Recomendado)
1. Confirmar el mensaje de commit (ya redactado en la sesión) y crear el
   commit — pendiente de confirmación explícita del usuario en este momento.
2. Si el usuario quiere reprocesar los dos ficheros reales que motivaron el
   reporte (informe ZAP y el `.docx` de Anti SPAM), relanzar un escaneo/forzar
   rescan sobre esos proyectos tras el commit, para confirmar en caliente que
   ambos ya no fallan.
3. `git push` a `origin/develop` — no evaluado en esta sesión, pendiente de
   petición explícita.

---

## Directrices para Futuras IAs

- **[`DocumentConverter.resolve_output_paths()` calcula rutas relativas a
  `scan_roots`, nunca a la raíz absoluta del disco]**: recibe
  `scan_roots: Sequence[str] = ()` (las carpetas indicadas por el usuario al
  escanear, `ScanCommand.run_streaming`'s `clean_paths`). Si ninguna raíz
  coincide con el documento, aplana la salida a `output_dir/<stem>` — NUNCA
  reconstruir `Path(full_path).resolve().parts[1:]` bajo `output_dir`
  directamente, eso fue exactamente el bug real (ruta duplicada,
  `[Errno 2] No such file or directory` al extraer imágenes de un `.docx`,
  sesión 2026-09-05).
- **[Cualquier punto que reconvierta un documento ya convertido debe recibir
  el MISMO `scan_roots` que la primera pasada]**: `OCRScheduler.
  process_with_ocr()` (segunda pasada de OCR) y `ScanCommand.
  _delete_orphaned_outputs()` (limpieza en "forzar rescan") dependen de
  calcular la misma ruta que `_convert_documents()` calculó originalmente —
  si se añade un tercer punto de reconversión en el futuro, propagar
  `clean_paths` ahí también, no reintroducir un cálculo de ruta
  independiente.
- **[`ConversionResult.error` nunca debe ser `""`]**: el `except Exception`
  de `convert_document()` usa `str(exc) or f"{type(exc).__name__} sin mensaje
  de error"` como mensaje de usuario, y `exc_info=True` en el `logger.
  warning()` para que el traceback completo quede en el log aunque el
  mensaje de usuario tenga que recurrir al fallback. Cualquier otro punto que
  capture una excepción amplia y la convierta en un mensaje visible al
  usuario debería seguir el mismo patrón (nunca asumir que `str(exc)` es
  suficiente).
- **[`_JsonFormatter` (`utils/logging.py`) ya serializa `exc_info` si el
  record lo lleva]**: no hace falta ningún cambio de logging para que
  `exc_info=True` en una llamada `logger.warning()`/`logger.error()` deje el
  traceback completo en el log JSON — solo hay que pasarlo en la llamada.

---

## Veredicto

### 🟡 GO_CONDICIONAL

**Criterios**:
- ✅ PLAN/AUDIT_PLAN ejecutados, causa raíz de ambos bugs confirmada con
  lectura directa del código (no solo hipótesis del agente de exploración)
- ✅ Decisión de diseño (esquema de rutas) confirmada explícitamente por el
  usuario antes de implementar
- ✅ IMPLEMENT completo para ambos bugs, con tests de regresión nuevos que
  reproducen el escenario real reportado
- ✅ AUDIT_CODE: suite completa (489 passed), `ruff`, `mypy`, `mkdocs build`
  en verde; cambio de API pública documentado en `docs/api/converter.md`
- ⬜ Commit: mensaje redactado y presentado al usuario, pendiente de
  confirmación explícita para crearlo
- ⬜ Push a `origin/develop`: no solicitado en esta sesión

**Evidencia**:
- Branch: `develop`
- Commits: ninguno todavía (cambios en working tree)
- Tests: 489 passed, 21 deselected (`python -m pytest -m "not slow" -q`)

**Sesión cerrada**: pendiente (commit no creado aún)
