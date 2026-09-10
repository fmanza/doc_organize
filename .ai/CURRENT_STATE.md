# CURRENT STATE — doc_organize

**Generado**: 2026-08-29 · **actualizado**: 2026-09-10
**Fuente de esta actualización**: `git log`, `pyproject.toml`/`CHANGELOG.md`, y
re-ejecución en vivo de `ruff`/`mypy`/`pytest`/`mkdocs build --strict` — no una
promesa (mismo criterio que `.ai/sessions/2026-09-03-historial-escaneo-fecha-docs-offline/TRACEABILITY.md`).
**Rama activa**: `develop`, HEAD commiteado `a6ffc93` + cierre de versión 0.8.0 pendiente de commit
(`pyproject.toml`/`CHANGELOG.md`/`COMPATIBILITY.md` ya actualizados en el working tree)
**Versión**: `0.8.0` (`pyproject.toml`/`CHANGELOG.md`) — cierra todo lo acumulado en `[Unreleased]`
desde la 0.7.0, incluido el paquete `context/` completo (sesiones `2026-09-08`/`2026-09-10`)

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
- Resolución de diagnósticos de IDE (SonarLint/Pylance) señalados sobre el working
  tree ya cerrado (sesión `2026-09-04-fixes-sonarlint-pylance`): complejidad
  cognitiva de `AuthMiddleware.dispatch()` y `DocumentScanner._build_node()`, import
  privado de Docling, causa raíz de un falso "falta argumento" de pyright en 16
  campos `Field()` de `core/models.py`, excepción redundante en `av_detector.py`.
- Nuevo paquete `context/` (extra `context`, sesión `2026-09-08-organizacion-documental-contextos`):
  organiza los documentos ya convertidos de un proyecto por dominios (clasificación por reglas,
  opcionalmente asistida por IA vía LiteLLM Proxy), los copia a una carpeta reorganizada configurable
  y genera/construye un sitio MkDocs navegable a partir de ella. Continuado en la sesión
  `2026-09-10-context-mkdocs-site-imagenes`: build a disco real (antes solo dejaba `mkdocs.yml` sin
  construir), endpoint para servir el sitio ya construido independiente del flujo de build, semáforo
  de progreso en tiempo real (mismo patrón que Escanear/Duplicados) y fix de imágenes rotas
  (`images_dir` no se persiste en `cache.db`, hay que recalcularlo al reconstruir desde caché).
  Cerrado en la versión `0.8.0` (2026-09-10).

**Fuente de verdad detallada por versión**: `CHANGELOG.md` (formato Keep a
Changelog, bien mantenido). **Historial de sesiones con directrices para
futuras IAs**: `.ai/sessions/<fecha>[-slug]/TRACEABILITY.md`.

---

## Calidad actual (verificado en vivo, 2026-09-10)

```
python -m ruff check src tests           → All checks passed!
python -m mypy src                        → Success: no issues found in 65 source files
python -m pytest -q --no-cov              → 643 passed
mkdocs build --strict                     → Documentation built in 2.45s, sin errores
                                             (único aviso: deprecación de Material for MkDocs
                                             sobre MkDocs 2.0 — ruido del tema, no del build)
python -m build                           → doc_organize-0.8.0.tar.gz y
                                             doc_organize-0.8.0-py3-none-any.whl generados sin error
```

`python -m pytest --doctest-modules src -q` → 35 passed, 3 skipped (subía de 26 passed en la
verificación anterior, sesión `2026-09-04-cierre-backlog-maturity-audit`, por los docstrings con
ejemplo del nuevo paquete `context/`).

---

## Estructura del código (recuento verificado 2026-09-10, diagrama de niveles sin revisar desde 2026-09-04)

```
src/doc_organize/
├── core/, utils/               # Nivel 1
├── validators/, scanner/, converter/, dedup/, cache/, projects/, auth/   # Nivel 2
└── scan/, web/, main.py         # Nivel 3
```

65 ficheros `.py` en `src/doc_organize/` (13 paquetes + `main.py`/`__main__.py`) — subió de 52
ficheros/11 paquetes con los paquetes `ai/` (monitorización de uso/coste + cliente de clasificación
por dominios, sesiones `2026-09-07`/`2026-09-08`) y `context/` (organización documental por
dominios, sesiones `2026-09-08`/`2026-09-10`). **Pendiente**: `.ai/architecture.md` no se ha
actualizado con el nivel de `ai/`/`context/` en el diagrama — no asumir su nivel sin revisar sus
imports reales.
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
- `context/`: dos documentos con el mismo `stem` en el mismo dominio/tipo se pisan en
  `organizado/` — sin desambiguación todavía (limitación conocida, documentada en `Reorganizer`).
- `context/`: sin test de integración real contra un LiteLLM Proxy vía Docker (solo
  `httpx.MockTransport`) — validar manualmente antes de depender de la Sub-fase B en producción.
- `context/`: `images_dir` de `ConversionResult` no se persiste en `cache.db` ni en `document.json`
  — cualquier código futuro que reconstruya `ConversionResult` desde caché debe recalcularlo
  explícitamente (dos bugs reales, sesión `2026-09-10-context-mkdocs-site-imagenes`, nacieron de
  olvidar este campo en dos sitios del mismo flujo). Sin test de regresión que falle si se vuelve a
  omitir.

---

## Próximos pasos

1. `git push` a `origin/develop` — confirmar con el usuario antes de cada
   push, nunca automático (ver `CLAUDE.md`/instrucciones de sesión).
2. Si se retoma alguno de los pendientes de arriba, empezar por los que
   tienen dueño claro (LICENSE, StrEnum) antes que por los ya aceptados como
   riesgo conocido.
