# TRACEABILITY: Resumen de Sesión

> **Nota de reconstrucción**: este fichero no se generó en tiempo real durante el trabajo — los 5
> commits que documenta ya estaban cerrados en `develop` cuando se creó. Reconstruido a partir de
> `git log`/`git show` de cada commit y de una re-ejecución en vivo de
> ruff/mypy/pytest/`mkdocs build --strict` (ver Verificación), no de memoria ni de promesa.

## Sesión
- **Fecha**: 2026-09-10
- **Tipo**: `feature`
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA

## Objetivo
Continuación de la sesión [`2026-09-08-organizacion-documental-contextos`](../2026-09-08-organizacion-documental-contextos/TRACEABILITY.md):
construir el sitio MkDocs a disco de verdad (no solo `mkdocs.yml`), servirlo de forma independiente
del flujo de build, dar progreso en tiempo real a "Construir/Eliminar contexto" con el mismo
semáforo que Escanear/Duplicados, y corregir que las imágenes extraídas de los documentos no
llegaban al sitio generado.

## Cambios Ejecutados

### ✅ 1. Sitio MkDocs construido a disco + carpeta de salida configurable + aviso LiteLLM

**Archivo(s)**: `context/mkdocs_generator.py`, `context/context_registry.py`, `web/routes/context.py`,
`web/templates/context.html.j2`, `core/constants.py`, `core/models.py`
**Descripción**: Construir el contexto ejecuta ahora `mkdocs build` a disco (si `mkdocs` está
instalado) en vez de dejar solo `mkdocs.yml` sin construir. `output_folder_name` es elegible en la
primera construcción de un proyecto (validado contra path traversal y contra nombres ya reservados
por otros subsistemas) y queda fijo hasta que se elimina el contexto por completo (nuevo
`DELETE .../context`, con confirmación explícita) — así se puede elegir otra carpeta sin dejar
copias huérfanas. La página de Contexto avisa si LiteLLM Proxy está configurado antes de que el
usuario intente activar la Sub-fase B.
**Status**: ✅ Completo (commit `25325cf`)

### ✅ 2. Semáforo de progreso en tiempo real + deshabilitar IA sin LiteLLM + refactor de deuda técnica

**Archivo(s)**: `web/dependencies.py`, `web/routes/context.py`, `web/routes/scan.py`,
`web/templates/_semaforo_macros.html.j2` (nuevo), `web/templates/context.html.j2`,
`web/templates/duplicates_resolver.html.j2`, `web/templates/folder_selector.html.j2`
**Descripción**: "Reconstruir/Construir contexto" y "Eliminar contexto" muestran el mismo semáforo
de 3 luces que Escanear/Duplicados (Inicio/Ejecución/Finalización, rojo en error), con progreso real
vía dos WebSocket nuevos (`/context/build`, `/context/delete`) que retransmiten cada paso de
`ContextBuilder`/`Reorganizer`/`MkDocsGenerator` — incluida una barra numérica X/Y para la
clasificación por IA y la copia de documentos. El checkbox de "Clasificación asistida por IA" se
deshabilita (y se fuerza desmarcado) cuando LiteLLM Proxy no está configurado, incluso si un build
anterior lo había dejado activo. De paso, refactor de deuda técnica acumulada en la propia sesión:
la autenticación/lock de los WebSocket de proyecto (antes duplicada entre `scan.py` y `context.py`,
con textos ya divergentes entre sí) se centraliza en `web/dependencies.py`; y el HTML/JS del
semáforo (antes triplicado en Escanear/Duplicados/Contexto) se extrae a `_semaforo_macros.html.j2`.
Verificado en navegador real (Playwright) que las 3 páginas siguen funcionando sin errores de
consola tras la extracción.
**Status**: ✅ Completo (commit `91602ce`)

### ✅ 3. Servir el sitio MkDocs generado, independiente del build

**Archivo(s)**: `web/routes/context.py`, `web/templates/context.html.j2`
**Descripción**: `GET /projects/{name}/context/site[...]` para visualizar el sitio ya construido de
cualquier proyecto sin depender del flujo de build/reconstruir contexto, con el mismo control de
acceso por tenant/rol que el resto de la app (`require_project_access`). Nunca se dispara
automáticamente tras un POST/WS de build — el usuario lo abre desde el enlace "ver documentación
generada" en la página de Contexto, visible solo cuando `mkdocs_site_built` es `True`.
**Status**: ✅ Completo (commit `75980ba`)

### ✅ 4. Fix: imágenes extraídas ausentes en el sitio reorganizado

**Archivo(s)**: `context/domain_classifier.py`, `context/context_builder.py`, `context/reorganizer.py`,
`web/routes/context.py`
**Descripción**: Dos causas del mismo síntoma (MkDocs servía las imágenes de los documentos como
rotas), encontradas en dos pasadas sucesivas. (a) `images_dir` de `ConversionResult` se perdía al
construir `DomainDocument` (`domain_classifier`/`context_builder`) y `Reorganizer._copy_document`
nunca copiaba la carpeta `img/<stem>/` al destino reorganizado. (b) `_gather_converted_documents`
(`web/routes/context.py`) reconstruye cada `ConversionResult` desde `cache.db` recalculando
`markdown_path`/`json_path`, pero no calculaba `images_dir` — que tampoco se persiste en `cache.db`
ni en `document.json` — así que el fix (a) operaba sobre un `ConversionResult` que ya nacía sin él;
las imágenes seguían sin llegar a MkDocs tras reconstruir el contexto.
**Status**: ✅ Completo (commits `802b874`, `a6ffc93`)

---

## Impacto

### Código
- **Archivos modificados/creados** (23 ficheros desde el cierre de la sesión anterior, `c7c3088..a6ffc93`):
  `context/{context_builder,context_registry,domain_classifier,mkdocs_generator,reorganizer}.py`,
  `core/{constants,models}.py`, `main.py`, `web/dependencies.py`, `web/routes/{context,downloads,scan}.py`,
  `web/templates/{_semaforo_macros (nuevo),context,duplicates_resolver,folder_selector}.html.j2`,
  `docs/{api,functional}/context.md`, 5 ficheros de test (`test_context_builder`, `test_context_registry`,
  `test_mkdocs_generator`, `test_reorganizer`, `test_web_context` — +56 tests netos sobre la sesión
  anterior). Total: +2109/−300 líneas.
- **Cambios funcionales**: sí — sitio MkDocs real servido en disco, endpoint de visualización
  independiente, progreso en vivo por WebSocket, `output_folder_name` configurable una vez, fix de
  imágenes rotas. Sin tocar scan/dedup/convert como subsistemas.

### Compatibilidad
- **BREAKING**: Ninguno.
- **NO BREAKING**: Todo aditivo o correctivo — nuevas rutas (`GET .../context/site`,
  `DELETE .../context`, WS `/context/build`, `/context/delete`), `output_folder_name` con valor por
  defecto si no se elige, fix de imágenes es puramente correctivo.

---

## Verificación

Re-ejecutado en vivo el 2026-09-10 sobre `develop` en `a6ffc93` (HEAD):

```
python -m ruff check src tests           → All checks passed!
python -m mypy src                        → Success: no issues found in 65 source files
python -m pytest -q --no-cov              → 643 passed (208.63s)
mkdocs build --strict                     → Documentation built in 2.28s, sin errores
                                             (único aviso: deprecación de Material for MkDocs
                                             sobre MkDocs 2.0 — ruido del tema, no del build)
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| `images_dir` no se persiste en `cache.db` ni en `document.json` — cualquier código futuro que reconstruya `ConversionResult` desde caché debe recalcularlo explícitamente (2 bugs reales ya nacieron de olvidar esto) | Documentado aquí y en `_gather_converted_documents`; sin un test que falle si se vuelve a omitir | Abierto |
| Dos documentos con el mismo `stem` en el mismo dominio/tipo se pisan en `organizado/` (heredado de la sesión anterior) | Documentado como limitación conocida en `Reorganizer`; sin desambiguación todavía | Abierto |
| Sin test de integración real contra un LiteLLM Proxy vía Docker (heredado) | `DomainClassificationClient` probado con `httpx.MockTransport` | Abierto — validar manualmente antes de depender de la Sub-fase B en producción |
| `output_folder_name` queda fijo hasta borrar el contexto completo — no hay forma de renombrar sin perder el sitio ya construido | Decisión deliberada (evita copias huérfanas); documentado en el commit `25325cf` | Aceptado |

---

## Siguientes Pasos (Recomendado)
1. Confirmar con el usuario si procede sincronizar `CHANGELOG.md`/versión (`pyproject.toml` sigue en
   `0.7.0`) — estos 5 commits no tocaron `CHANGELOG.md` ni `.ai/CURRENT_STATE.md`; ver nota abajo.
2. Validar manualmente la Sub-fase B contra un LiteLLM Proxy real (`deploy/litellm/`) antes de
   activarla en un entorno con usuarios reales (heredado de la sesión anterior).
3. Si se detecta colisión real de `stem` duplicados en `organizado/`, añadir desambiguación
   (heredado de la sesión anterior).

---

## Directrices para Futuras IAs

- **[patrón]**: `images_dir` de `ConversionResult` **no** se persiste en `cache.db` ni en
  `document.json` — cualquier ruta que reconstruya un `ConversionResult` desde caché (como
  `_gather_converted_documents` en `web/routes/context.py`) debe recalcularlo explícitamente o las
  imágenes de los documentos quedan rotas en cualquier consumidor downstream (MkDocs incluido). Dos
  bugs reales (`802b874`, `a6ffc93`) nacieron de olvidar este campo en dos sitios distintos del mismo
  flujo.
- **[patrón]**: La autenticación y el lock de los WebSocket de proyecto viven en
  `web/dependencies.py` — antes duplicados entre `scan.py` y `context.py` con textos ya divergentes.
  No reimplementar en un tercer sitio; cualquier WS nuevo de proyecto debe reutilizar esas
  dependencias.
- **[patrón]**: El widget de semáforo de 3 luces (Inicio/Ejecución/Finalización) vive en
  `web/templates/_semaforo_macros.html.j2` — antes triplicado en Escanear/Duplicados/Contexto. No
  reimplementar el HTML/JS del semáforo en una plantilla nueva.
- **[decisión]**: `output_folder_name` solo es elegible en la primera construcción del contexto de
  un proyecto y queda fijo hasta `DELETE .../context` (borrado completo, con confirmación explícita)
  — evita copias huérfanas de un sitio reorganizado bajo un nombre de carpeta antiguo. Renombrar
  implica perder el sitio ya construido, por diseño.
- **[decisión]**: `GET .../context/site` (servir el sitio generado) nunca se dispara automáticamente
  tras un build — solo aparece como enlace manual cuando `mkdocs_site_built` es `True`, para no
  acoplar el flujo de construcción al de visualización.
- **[gap conocido]**: Estos 5 commits no actualizaron `CHANGELOG.md` (el `## [Unreleased]` actual
  documenta otro lote de fixes/features anterior) ni `.ai/CURRENT_STATE.md` (sigue fechado
  2026-09-04, antes de la sesión `2026-09-08` y de esta). Si se cierra una versión pronto, ambos
  ficheros necesitan una pasada de sincronización (`sync.instructions.md`) que cubra también estos
  commits.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- Las 4 sub-áreas de trabajo (build a disco + carpeta configurable, semáforo + refactor deuda
  técnica, servir sitio independiente, fix imágenes en dos pasadas) ya commiteadas en `develop`.
- ruff/mypy/pytest/`mkdocs build --strict` re-verificados en vivo el 2026-09-10, todos en verde.
- Sin cambios breaking.

**Evidencia**:
- Branch: `develop`
- Commits: `25325cf`, `91602ce`, `75980ba`, `802b874`, `a6ffc93`
- Tests: `pytest` → 643 passed (56 más que en el cierre de la sesión anterior, `2026-09-08`, con 587)

**Sesión cerrada**: 2026-09-10
