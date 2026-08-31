# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-08-30/31
- **Tipo**: `feature` (PLAN → AUDIT_PLAN → IMPLEMENT) seguido de `hotfix` de un problema de entorno
  detectado al probar la funcionalidad
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (implementación y verificación); commit pendiente — mensaje preparado a
  petición explícita del usuario ("solo mensaje"), no ejecutado

## Objetivo
Añadir un menú lateral colapsable a la web, y en la sección de Escaneo: persistir por proyecto las
carpetas usadas (con botón de búsqueda server-side y borrado solo de las no usadas), mostrar el
resultado del escaneo en un cuadro de texto, y detectar/comunicar si el entorno dispone de GPU
(y las instrucciones para activarla si no lo está). Requisitos originales del usuario, aclarados
durante PLAN/AUDIT_PLAN: la UI usa Tailwind CSS (ya adoptado, vía CDN) y la detección de GPU es
solo de entorno software — sin permiso por rol/usuario.

## Cambios Ejecutados

### ✅ 1. PLAN + AUDIT_PLAN
**Descripción**: se exploró el árbol real (`web/routes/scan.py`, `core/models.py::Project`,
`ProjectRegistry`, `Role.allowed_scan_roots`, `pyproject.toml` extra `ocr-gpu`) antes de proponer
diseño. Primera vuelta quedó `GO_CONDICIONAL` por una ambigüedad genuina ("dispone de GPU" vs. "se
permite su uso"); el usuario la resolvió explícitamente: solo detección de entorno, sin campo nuevo
en `Role`. Verdicto final: `GO`.
**Status**: ✅ sin cambios de código en esta fase.

### ✅ 2. IMPLEMENT — Level 1 (tipos/utilidades)
**Archivo(s)**: `core/models.py` (`ScannedFolder`, `GpuStatus`, `DirectoryListing`),
`core/exceptions.py` (`ScannedFolderError`/`NotFoundError`/`InUseError`), `utils/path_utils.py`
(`paths_within_roots()`, extraída de `scan.py` para compartirla), `utils/gpu_detector.py` (nuevo,
`detect_gpu_status()` cacheada con `lru_cache`).
**Status**: ✅ cubierto por tests nuevos.

### ✅ 3. IMPLEMENT — Level 2 (servicios)
**Archivo(s)**: `projects/scanned_folders_store.py` (nuevo, `ScannedFoldersStore`: lista persistente
por proyecto en `<root_path>/scanned_folders.json`, mismo patrón lock+escritura atómica que
`ProjectRegistry`), `web/dependencies.py` (`get_allowed_scan_roots()`, equivalente HTTP de la
resolución de roles que antes solo existía para el WebSocket; `get_scanned_folders_store()`).
**Status**: ✅ cubierto por tests nuevos.

### ✅ 4. IMPLEMENT — Level 3 (rutas + plantillas)
**Archivo(s)**:
- `web/routes/filesystem.py` (nuevo): `GET /api/fs/browse`, mismo control `allowed_scan_roots` que
  el escaneo — sin privilegio nuevo para ningún rol.
- `web/routes/scan.py`: CRUD `/api/projects/{name}/folders/library`; `folder_selector()` pasa
  `folders` + `gpu_status` a la plantilla; `scan_websocket` marca las carpetas usadas **antes** de
  reenviar el evento `completed` (no después — ver directriz más abajo, corrección de una condición
  de carrera real encontrada por un test).
- `web/app.py`: registra `filesystem_router` y los nuevos códigos de error
  (`InvalidPathError`→422, `ScannedFolderNotFoundError`→404, `ScannedFolderInUseError`→409).
- Plantillas: `base.html.j2` (sidebar colapsable, Tailwind, estado en `localStorage`),
  `_nav_macros.html.j2` (nuevo, macro `project_nav` compartida por dashboard/scan/cache/duplicates),
  `folder_selector.html.j2` reescrita (lista de carpetas con checkbox+eliminar, panel "Buscar…",
  banner GPU, resultado en `<textarea readonly>` en vez de `<ul>`).
**Status**: ✅ 270 tests pasando (incluidos `@slow`), smoke test manual del server real.

### ✅ 5. IMPLEMENT — tests y documentación
**Archivo(s)**: `tests/unit/test_scanned_folders_store.py`, `test_gpu_detector.py`,
`test_web_filesystem.py` (nuevos); `test_web_scan.py` (extendido); `docs/functional/projects.md` y
`docs/api/projects.md` (secciones nuevas: lista persistente de carpetas, detección de GPU).
**Status**: ✅ `mkdocs build --strict` limpio.

### ✅ 6. HOTFIX — diagnóstico y corrección de "GPU no activa" tras instalar/reiniciar
**Archivo(s)**: entorno `.venv` del propio proyecto (reinstalación de `torch`, no código fuente),
`docs/guides/installation.md` (advertencia + comando correcto), `docs/guides/troubleshooting.md`
(entrada reescrita, causa real primero), `utils/gpu_detector.py` (mensaje de instrucciones ampliado).
**Descripción**: el usuario reportó que, tras instalar soporte GPU y reiniciar el servidor, el
banner seguía en rojo/amarillo y el checkbox seguía deshabilitado. Diagnóstico en vivo: el `.venv`
propio del proyecto (el que realmente arranca `python -m doc_organize web`) tenía el build
**CPU-only** de `torch` (`2.13.0+cpu`), distinto del Python global usado para verificar "que
funciona" (`2.13.0+cu132`). Causa raíz real: `pip install doc_organize[web,ocr-gpu]` (o
`pip install torch` a secas) resuelve siempre el wheel CPU de PyPI — el build CUDA solo sale del
índice propio de PyTorch (`--index-url https://download.pytorch.org/whl/cuXXX`). Se corrigió
reinstalando `torch` dentro del `.venv` correcto (wheel ya en caché local, sin descarga larga);
verificado `torch.cuda.is_available()==True` y `detect_gpu_status().gpu_active==True` en ese venv.
**Status**: ✅ corregido y verificado; documentación actualizada para que no vuelva a confundir a
otro usuario (la hipótesis inicial de "solo hace falta reiniciar" —por la caché de
`detect_gpu_status()`— era cierta pero secundaria, no la causa principal en este caso).

---

## Impacto

### Código
- **Archivos modificados/creados**: ver secciones 2-6 arriba (12 ficheros de `src/` nuevos o
  tocados, 4 ficheros de test nuevos/extendidos, 4 ficheros de `docs/`).
- **Cambios funcionales**: sí — nueva superficie de API (`/api/fs/browse`,
  `/api/projects/{name}/folders/library` GET/POST/DELETE), nuevo fichero por proyecto
  (`scanned_folders.json`), nuevo comportamiento visual (sidebar, banner GPU). No se tocó ninguna
  ruta ni contrato existente salvo el orden interno de eventos del WebSocket de escaneo (ver punto
  4 — no observable por un cliente que ya cerraba el socket al recibir `completed`).

### Compatibilidad
- **BREAKING**: ninguno. `folders.json` (formato `{"paths": [...]}`, usado por
  `web/routes/duplicates.py`) no se tocó — `scanned_folders.json` es un fichero nuevo y distinto.
- **NO BREAKING**: toda la superficie pública previa (rutas HTTP, CLI, `ScanCommand`) queda intacta.

---

## Verificación
```
python -m ruff check src tests           → All checks passed!
python -m ruff format --check <ficheros tocados>  → ya formateados tras aplicar ruff format
python -m mypy <ficheros tocados>        → Success: no issues found
python -m pytest -q                      → 270 passed, 96% cobertura (incluye @slow)
python -m mkdocs build --strict          → Documentation built, sin warnings de links/anchors rotos
```
Nota: `python -m mypy src` **completo** (no solo los ficheros tocados) falla por un error
preexistente y no relacionado (`scipy-stubs/__init__.pyi:74: Type statement is only supported in
Python 3.12 and greater`, bajo el intérprete 3.14.2 de este entorno) — confirmado con `git stash`
que el fallo ya existe en `develop` sin los cambios de esta sesión.

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| `mypy src` completo falla por incompatibilidad `scipy-stubs`/Python 3.14, preexistente | Verificar módulos tocados individualmente hasta que se resuelva aparte (no es de esta sesión) | Documentado, no bloqueante |
| `GET /api/fs/browse` expone la estructura de directorios del servidor | Reutiliza `allowed_scan_roots` (mismo control que el escaneo); sin privilegio nuevo para ningún rol | Mitigado por diseño |
| `detect_gpu_status()` cachea el resultado una vez por proceso servidor | Documentado en `troubleshooting.md`; requiere reiniciar el servidor tras cambiar el entorno de `torch`/drivers | Comportamiento intencional, documentado |

---

## Siguientes Pasos (Recomendado)
1. Revisar el mensaje de commit preparado (ver respuesta de esta sesión) y ejecutar `git add`/
   `git commit` cuando el usuario lo confirme explícitamente — no se ejecutó en esta sesión
   ("solo mensaje").
2. AUDIT_CODE formal y VERSION (CHANGELOG.md, `pyproject.toml` version bump) quedan pendientes si el
   usuario los pide — no se tocaron en esta sesión (fuera del alcance pedido).
3. Si en el futuro se decide ampliar el alcance de GPU a detección de hardware real (p. ej.
   `nvidia-smi`) o a permisos por rol, requiere una decisión explícita nueva del usuario — el AUDIT_PLAN
   de esta sesión descartó ambas por scope creep.

---

## Directrices para Futuras IAs

- **[GPU es solo detección de entorno, no permiso]**: `GpuStatus`/`detect_gpu_status()` no tienen
  ningún campo de permiso por rol/usuario — decisión explícita del usuario en el AUDIT_PLAN de esta
  sesión. No añadir un campo `allowed_gpu` a `Role` sin una decisión explícita nueva.
- **[`detect_gpu_status()` cachea por proceso]**: `functools.lru_cache(maxsize=1)` en
  `utils/gpu_detector.py` — instalar/reinstalar `torch` o drivers con el servidor ya arrancado no se
  refleja hasta reiniciar el proceso. Documentado en `docs/guides/troubleshooting.md`.
- **[`pip install torch` da CPU-only por defecto en Windows/PyPI]**: el extra `ocr-gpu` de
  `pyproject.toml` no fija una versión CUDA a propósito. Para el build con GPU hay que reinstalar
  `torch` explícitamente con `--index-url https://download.pytorch.org/whl/cuXXX`, **en el mismo
  entorno virtual que ejecuta `doc_organize web`** — comprobar con `torch.version.cuda` (no basta
  con que `import torch` funcione, eso no distingue CPU de CUDA). Es fácil tener un build GPU en un
  Python del sistema y CPU-only en el `.venv` real del proyecto sin darse cuenta. Ver
  `docs/guides/installation.md` §Aceleración GPU y `docs/guides/troubleshooting.md`.
- **[`mark_used` antes de `completed` en el WebSocket de escaneo]**: en
  `web/routes/scan.py::scan_websocket`, `ScannedFoldersStore.mark_used()` se llama **antes** de
  reenviar el evento `completed` al cliente, no después — el cliente cierra el WebSocket en cuanto
  lo recibe (`folder_selector.html.j2`), así que hacerlo después compite con esa desconexión.
  Detectado por un test (`test_remove_used_folder_from_library_is_rejected`) que fallaba de forma
  intermitente hasta reordenar esa llamada.
- **[`paths_within_roots` es el único punto de la comprobación "¿ruta dentro de `allowed_scan_roots`?"]**:
  vive en `utils/path_utils.py` (antes duplicada solo en `scan.py`). Cualquier ruta nueva que toque
  el sistema de ficheros del servidor con restricción por rol (como `web/routes/filesystem.py`) debe
  reutilizarla, no reimplementar el chequeo.
- **[`mypy src` completo se rompe por `scipy-stubs`, no es de esta sesión]**:
  `scipy-stubs/__init__.pyi:74: Type statement is only supported in Python 3.12 and greater` bajo el
  intérprete 3.14.2 de este entorno — confirmado preexistente en `develop` (sin los cambios de esta
  sesión) vía `git stash`. Verificar los módulos tocados individualmente
  (`mypy <ficheros>`, sin `--follow-imports=skip`: ese flag genera falsos positivos "Returning Any"
  al perder el tipado de los módulos que sí sigue) hasta que se resuelva aparte.
- **[explorador de carpetas del servidor no añade privilegio nuevo]**: `GET /api/fs/browse`
  (`web/routes/filesystem.py`) aplica el mismo `allowed_scan_roots` que ya restringía el escaneo vía
  WebSocket — un rol restringido no gana acceso a nada que no pudiera ya escanear escribiendo la
  ruta a mano.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ PLAN/AUDIT_PLAN con verdicto `GO` antes de escribir código, ambigüedad de requisitos resuelta
  explícitamente por el usuario (no asumida)
- ✅ `ruff check`/`format`, `mypy` (ficheros tocados), `pytest` (270 passed), `mkdocs build --strict`
  — todos en verde
- ✅ Problema real reportado por el usuario tras el IMPLEMENT (GPU seguía "no activa") diagnosticado
  hasta la causa raíz real y corregido, no solo la hipótesis inicial (caché de proceso)
- ✅ Documentación (`installation.md`, `troubleshooting.md`) actualizada con la causa real, para que
  no vuelva a confundir a otro usuario
- ⬜ Commit: pendiente, a petición explícita del usuario en esta misma sesión ("solo mensaje")

**Evidencia**:
- Branch: `develop`
- Commits: ninguno todavía (working tree con cambios sin confirmar — ver `git status`)
- Tests: 270 passed, 96% cobertura

**Sesión cerrada**: 2026-08-31
