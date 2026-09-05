# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-05
- **Tipo**: `/new-feature` — nueva funcionalidad en "Escanear" (PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION, ciclo completo)
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (implementación + tests + changelog en verde)

## Objetivo
Al escanear, la pestaña "Escanear" ya mostraba una barra de progreso en vivo
de la conversión general ("Procesando X/Y: fichero"), pero el evento
`ocr_processed` de la segunda pasada de OCR solo alimentaba el log crudo y el
semáforo — no había ninguna barra dedicada, así que el usuario no sabía
cuántos ficheros de OCR quedaban ni cuál se estaba procesando. Se pidió una
segunda barra, análoga a la general, dedicada a informar del progreso de OCR
en vivo.

## Decisión de diseño (bloqueante para el AUDIT_PLAN)
`OCRScheduler.process_with_ocr()` es una única llamada `await` bloqueante que
procesa todo el batch de un tirón — a diferencia de la conversión general
(`_convert_documents`), que ya yieldea entre documento y documento porque
itera ella misma. Lograr progreso **en vivo** (no solo "ha empezado/ha
terminado") exige una pieza de concurrencia nueva (tarea paralela + cola).
Se preguntó al usuario entre esa opción y una alternativa más simple de menor
riesgo (barra indeterminada, sin desglose X/Y). Se optó por la opción con
progreso real en vivo (recomendada en el AUDIT_PLAN), asumiendo su mayor
complejidad técnica a cambio de cumplir literalmente lo pedido
("informado de lo que queda").

## Cambios Ejecutados

### ✅ 1. Nuevos tipos de evento
**Archivo(s)**: `src/doc_organize/core/models.py`.
**Descripción**: `ScanEventType.OCR_STARTED` (total de candidatos a OCR de
esta ejecución) y `OCR_FILE_STARTED` (`path`/`index`/`total` de cada
documento), análogos a `SCANNED`/`FILE_STARTED` de la conversión general.
**Status**: ✅ cubierto indirectamente por los tests de `_process_ocr`/
`_stream_ocr_batch` (abajo).

### ✅ 2. `progress_callback` opcional en `OCRScheduler.process_with_ocr()`
**Archivo(s)**: `src/doc_organize/converter/ocr_scheduler.py`.
**Descripción**: nuevo parámetro `progress_callback: Callable[[DocumentMetadata,
int, int], Awaitable[None]] | None = None` (por defecto `None` — no rompe
compatibilidad ni llamadas existentes), invocado con `(doc, index, total)`
justo antes de reconvertir cada documento. Mantiene la capa de OCR agnóstica
de `ScanEvent`/WebSocket — solo informa progreso genérico.
**Status**: ✅ `test_ocr_scheduler.py` (test real con Docling) sigue pasando
sin cambios; el propio callback se ejerce vía los tests nuevos de
`scan_command.py`.

### ✅ 3. Progreso en vivo del batch de OCR (`_stream_ocr_batch` + `_process_ocr`)
**Archivo(s)**: `src/doc_organize/scan/scan_command.py`.
**Descripción**: nuevo método `_stream_ocr_batch()` (staticmethod) que lanza
`OCRScheduler().process_with_ocr(...)` como una `asyncio.Task` paralela cuyo
`progress_callback` empuja `ScanEvent(OCR_FILE_STARTED)` a una `asyncio.Queue`
FIFO que el propio generador va drenando; la tarea empuja al final el
resultado (o la excepción, para no dejar la cola esperando para siempre si el
batch falla) como último elemento de la cola. `_process_ocr()` yieldea
`OCR_STARTED` (con el total) antes de arrancar, consume ese stream con
`contextlib.aclosing(...)` (garantiza que si el generador se cierra a mitad
de consumo — cliente WebSocket desconectado — se llame a
`_stream_ocr_batch.aclose()`, cuyo `finally` cancela la tarea en curso) y
sigue emitiendo `OCR_PROCESSED` al final, igual que antes.
**Status**: ✅ 4 tests nuevos en `test_scan_command.py`: sin candidatos → sin
eventos; secuencia completa `ocr_started`→`ocr_file_started`×N→`ocr_processed`×N
con índices/totales correctos; excepción real del scheduler se propaga (no
deja la cola colgada); cierre anticipado del generador cancela la tarea en
segundo plano (verificado interceptando `asyncio.create_task` y comprobando
`task.cancelled()`).

### ✅ 4. Segunda barra de progreso en el frontend
**Archivo(s)**: `src/doc_organize/web/templates/folder_selector.html.j2`.
**Descripción**: nuevo bloque `#scan-ocr-progress` (oculto hasta que llega
`ocr_started`), con handlers `resetOcrProgress`/`handleOcrStartedEvent`/
`handleOcrFileStartedEvent`/`handleOcrProcessedEvent`/
`handleScanCompletedOcrProgress` — mismo patrón que los ya existentes de la
barra de conversión general. `RUNNING_EVENTS` y `ws.onmessage` extendidos con
los dos eventos nuevos; `resetOcrProgress()` añadido al `submit` junto a
`resetFileProgress()`.
**Status**: ✅ verificado por inspección de código y por los tests de
backend que garantizan la secuencia/forma exacta de los eventos que este JS
consume; sin prueba de navegador real (no solicitada, ver limitación conocida
del proyecto en `.ai/CURRENT_STATE.md`).

---

## Impacto

### Código
- **Archivos modificados**: 5 —
  `src/doc_organize/core/models.py`,
  `src/doc_organize/converter/ocr_scheduler.py`,
  `src/doc_organize/scan/scan_command.py`,
  `src/doc_organize/web/templates/folder_selector.html.j2`,
  `tests/unit/test_scan_command.py`.
  Más `CHANGELOG.md` (entrada de esta sesión).
- **Cambios funcionales**: sí — nuevo comportamiento de UI (segunda barra de
  progreso) y dos tipos de evento nuevos en el protocolo WebSocket de
  escaneo. `OCRScheduler.process_with_ocr()` gana un parámetro opcional; su
  firma anterior sigue siendo válida para cualquier otro llamador.

### Compatibilidad
- **BREAKING**: ninguno.
- **NO BREAKING**: `progress_callback` es opcional (`None` por defecto);
  `ScanEventType` solo gana miembros nuevos (ningún valor existente cambia);
  el frontend ignora eventos desconocidos igual que antes (no hay `default`
  que rompa con tipos nuevos).

### Deuda técnica introducida (documentada, no bloqueante)
- Cancelar la tarea de `_stream_ocr_batch` detiene la espera asíncrona casi
  al instante, pero **no interrumpe el hilo real de Docling** que ya esté
  corriendo (`DocumentConverter.convert_document()` delega el parseo a
  `asyncio.to_thread`, ver `converter.py:182`) — ese hilo sigue vivo en
  segundo plano hasta terminar por su cuenta. Mismo comportamiento que ya
  tenía el `await` bloqueante original (no es una regresión de esta sesión),
  documentado explícitamente en el docstring de `_stream_ocr_batch` tras el
  AUDIT_CODE de esta misma sesión.
- Asimetría de UX menor y deliberada: la barra de conversión general muestra
  "Sin ficheros nuevos que convertir" incluso con `to_process=0`; la barra de
  OCR simplemente no aparece si no hay candidatos (decisión explícita del
  AUDIT_PLAN, no un descuido).
- SonarLint (IDE) marca el `except Exception` de `_run_batch()` como "blind
  exception" — intencional (reenvía cualquier excepción real del scheduler a
  través de la cola sin perderla) y ya justificado con comentario in-line.
  No es una puerta de este proyecto (`CLAUDE.md` solo exige `ruff`/`mypy`/
  `pytest` en verde) — no se ha añadido supresión porque no existe esa
  convención en el resto del código base; queda a criterio del usuario si
  quiere establecerla.

---

## Verificación
```
python -m ruff check src tests                                                   → All checks passed!
python -m mypy src                                                                → Success: no issues found in 53 source files
python -m pytest tests/unit/test_scan_command.py -q                              → 16 passed
python -m pytest -k "scan_command or ocr_scheduler or scan_websocket or scan.py"  → 81 passed, 438 deselected
python -m pytest -q -m "not slow"  (suite completa)                               → 498 passed, 21 deselected
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Cancelar la tarea de OCR no mata el hilo de Docling ya en curso (`asyncio.to_thread`) | Documentado en el docstring de `_stream_ocr_batch`; mismo comportamiento que el código original | Aceptado |
| Barra OCR no distingue "0 candidatos" de "no aplica" (a diferencia de la barra general) | Decisión deliberada del AUDIT_PLAN — no inventar un evento con `to_process=0` que nunca ocurre en la práctica | Aceptado |
| Sin prueba en navegador real de la nueva barra | Mismo criterio que el resto del proyecto (tests contra servidor real, no Selenium/Playwright) | Aceptado |

---

## Siguientes Pasos (Recomendado)
1. Commit + confirmar push.
2. Si se retoma el pendiente de "pruebas en navegador real" (`.ai/CURRENT_STATE.md`), esta
   funcionalidad sería un buen candidato a verificar visualmente (dos barras simultáneas,
   fichero grande con OCR real).

---

## Directrices para Futuras IAs

- **[Progreso en vivo sobre una llamada `await` bloqueante que procesa un batch
  entero]**: si una función async solo puede yieldear al final del batch
  completo (como `OCRScheduler.process_with_ocr()` antes de esta sesión), la
  única forma de obtener progreso en vivo sin reescribirla como generador es
  lanzarla en una `asyncio.Task` paralela con un `progress_callback` que
  empuje eventos a una `asyncio.Queue`, y drenar esa cola desde el generador
  que expone el progreso — ver `ScanCommand._stream_ocr_batch()` como
  plantilla. Puntos a no olvidar si se reutiliza este patrón: (1) el
  `progress_callback` debe capturar excepciones de la tarea productora y
  reenviarlas por la misma cola (si no, un fallo real deja al consumidor
  esperando para siempre); (2) el consumidor debe cancelar la tarea en su
  `finally` si se cierra antes de tiempo (cliente desconectado) — y para que
  ese `finally` se ejecute de verdad hay que envolver el `async for` sobre
  ese generador con `contextlib.aclosing(...)`, no un `async for` a secas
  (un `GeneratorExit` en el generador exterior no cierra automáticamente el
  interior sin eso); (3) distinguir `Exception` de `asyncio.CancelledError`
  (`BaseException`) al capturar dentro de la tarea productora — si se captura
  también `CancelledError`, cancelar la tarea desde fuera deja de funcionar
  como cancelación real (la tarea "atrapa" su propia cancelación y termina
  "con éxito").
- **[Cancelar una `asyncio.Task` que envuelve `asyncio.to_thread(...)` no
  mata el hilo]**: solo detiene la espera asíncrona; el hilo del
  `ThreadPoolExecutor` sigue corriendo hasta terminar por su cuenta. Aplica a
  cualquier cancelación de conversión/OCR en este proyecto (`converter.py`
  usa `asyncio.to_thread` para el parseo real de Docling), no solo a la
  funcionalidad de esta sesión.

---

## Veredicto

### 🟢 COMPLETADA (backend + frontend + tests + changelog)

**Criterios**:
- ✅ Segunda barra de progreso de OCR implementada y en verde (`ruff`/`mypy`/`pytest`)
- ✅ AUDIT_PLAN con decisión explícita del usuario (progreso real en vivo vs. barra indeterminada)
- ✅ AUDIT_CODE ejecutado y sus dos hallazgos corregidos (matiz del docstring de
  cancelación, `noqa: BLE001` inerte eliminado)
- ✅ `CHANGELOG.md` actualizado (`[Unreleased] → Added`)
- ⬜ Commit: pendiente de esta misma sesión
- ⬜ Bump de versión (`pyproject.toml`): fuera de alcance de esta sesión — corresponde a `/version-closure`

**Evidencia**:
- Branch: `develop`
- Tests: `tests/unit/test_scan_command.py` 16 passed (4 nuevos de OCR); suite
  completa 498 passed, 21 deselected (sin regresiones)

**Sesión cerrada**: 2026-09-05
