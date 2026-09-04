# CURRENT STATE — doc_organize

**Generado**: 2026-08-29 · **actualizado**: 2026-09-04
**Fuente de esta actualización**: `git log`, `pyproject.toml`/`CHANGELOG.md`, y
re-ejecución en vivo de `ruff`/`mypy`/`pytest`/`mkdocs build --strict` — no una
promesa (mismo criterio que `.ai/sessions/2026-09-03-historial-escaneo-fecha-docs-offline/TRACEABILITY.md`).
**Rama activa**: `develop`, al día con lo commiteado (`eef8847` es el HEAD)
**Versión**: `0.7.0` (`pyproject.toml`/`CHANGELOG.md`)

> **Nota de corrección (2026-09-04)**: este documento llevaba desde 2026-08-29
> (`v0.2.0`) sin actualizarse — 5 versiones y ~15 sesiones de trabajo de
> diferencia con el estado real del repositorio. La tabla "Estado de Fase 1",
> el snapshot de calidad y "Trabajo pendiente" de más abajo describían un
> estado ya superado. Se han actualizado con datos verificados en vivo hoy;
> **no** se ha reconstruido a mano el detalle de cada versión intermedia
> (`0.3.0`–`0.7.0`) — para eso, `CHANGELOG.md` es la fuente completa y ya
> mantenida, no hace falta duplicarla aquí.

> Reemplaza una versión anterior (fechada 2026-06-05) que describía otra librería (motores de base
> de datos, `v0.10.0`, migración a "Zenical") — la encarnación previa de este mismo repositorio
> antes de un pivote de dominio completo. Ver `.ai/architecture.md` para el detalle.

---

## Estado general

Fase 1 (escaneo + conversión Docling + OCR + deduplicación + caché + CLI + web
con auth multi-usuario/multi-tenant) está completa desde hace varias
versiones. Desde `v0.2.0`, cada versión siguiente (`CHANGELOG.md` tiene el
detalle completo, no reproducido aquí) añadió, entre otras cosas:

- Reestructuración de navegación web (pestañas Escanear/Caché/Duplicados/Historial/Errores).
- Gestión de errores de escaneo agrupados por ejecución + logging a fichero con rotación diaria.
- Formato de fecha/hora localizado (`Europe/Madrid` por defecto) y duración de ejecuciones.
- Documentación offline (ZIP + checksums) y guías de instalación de OCR/audio-vídeo por SO.
- Duración de conversión/descubrimiento por documento + progreso en vivo de deduplicación
  (WebSocket, mismo patrón que el escaneo).
- Una ronda de `/maturity-assessment` + `/audit-code` completa (sesiones `2026-09-03/04`):
  arquitectura, seguridad web (login CSRF, oráculo de `/api/fs/browse`, filtrado de
  `allowed_scan_roots`), concurrencia real entre WebSocket del mismo proyecto, resiliencia
  por fichero en deduplicación, `pytest --doctest-modules` verificado y añadido a CI.

**Fuente de verdad detallada por versión**: `CHANGELOG.md` (formato Keep a
Changelog, bien mantenido). **Historial de sesiones con directrices para
futuras IAs**: `.ai/sessions/<fecha>[-slug]/TRACEABILITY.md`.

---

## Calidad actual (verificado en vivo, 2026-09-04)

```
python -m ruff check src tests           → All checks passed!
python -m mypy src                        → Success: no issues found in 52 source files
python -m pytest -q --no-cov              → 478 passed
python -m pytest --doctest-modules src    → 26 passed (verificado idempotente, dos ejecuciones)
mkdocs build --strict                     → exit 0, sin links rotos
```

---

## Estructura del código (verificada 2026-09-04)

```
src/doc_organize/
├── core/, utils/               # Nivel 1
├── validators/, scanner/, converter/, dedup/, cache/, projects/, auth/   # Nivel 2
└── scan/, web/, main.py         # Nivel 3
```

52 ficheros `.py` en `src/doc_organize/` (11 paquetes + `main.py`/`__main__.py`).
Excepción documentada a la regla de niveles: `projects/` importa de
`validators/` (ambos Nivel 2) — ver `.ai/architecture.md` para la
justificación. Detalle completo: `.ai/architecture.md`, `docs/functional/index.md`.

---

## Trabajo pendiente conocido (no bloqueante)

- Migración de los 6 enums de `core/models.py` (`DocumentStatus`,
  `ConversionStatus`, `DuplicateReason`, `OcrMode`, `ScanEventType`,
  `DedupEventType`) a `enum.StrEnum` (sugerencia `UP042` de ruff) — diferida
  deliberadamente (sesión `2026-09-04-audit-code-hotfixes`): cambia el
  `str()`/f-string de esos enums de forma observable, necesita su propia
  revisión.
- `LICENSE`: el nombre en el copyright ("Francisco") no se ha confirmado
  contra el nombre legal real del autor — pendiente de que el usuario lo
  confirme antes de tocarlo.
- `README.md:100`: ejemplo de checksum con una versión de ZIP de docs
  obsoleta (`0.3.0`) — cosmético, bajo valor, no priorizado.
- `app.state.active_project_operations` (guarda de concurrencia entre
  escaneo/deduplicación del mismo proyecto, sesión `2026-09-04`) es un `set`
  en memoria de un único proceso — no distribuido. Solo relevante si se
  despliega con más de un worker (`_run_web` no expone `--workers` hoy).
- Pruebas en navegador real de las páginas web — sustituidas por tests contra
  el servidor real (`httpx`/`TestClient`); sigue pendiente una verificación
  genuina en Chrome/Firefox/Safari.
- Tokens de API personales por usuario (acceso programático sin sesión de
  navegador) — nunca implementado, sigue fuera de alcance.
- Bloque de "edge cases de robustez" revisado y aceptado tal cual en la
  sesión `2026-09-04-cierre-backlog-maturity-audit` (sin guarda de re-chequeo
  de rol a mitad de una conexión WebSocket ya autenticada, `stat()` síncrono
  sin `to_thread` en `project_registry.py`/`scanned_folders_store.py`, export
  ZIP sigue symlinks dentro de `Conversión/`, caché de conversiones ya hechas
  se pierde — no se corrompe, solo se reprocesa — si `run_streaming()` aborta
  antes de `cache.save_entries()`, `main.py::_run_deduplicate` no traduce
  excepciones inesperadas a un mensaje limpio) — cada uno con su
  justificación propia documentada en esa sesión, no re-evaluados aquí.

---

## Próximos pasos

1. `git push` a `origin/develop` — confirmar con el usuario antes de cada
   push, nunca automático (ver `CLAUDE.md`/instrucciones de sesión).
2. Si se retoma alguno de los pendientes de arriba, empezar por los que
   tienen dueño claro (LICENSE, StrEnum) antes que por los ya aceptados como
   riesgo conocido.
