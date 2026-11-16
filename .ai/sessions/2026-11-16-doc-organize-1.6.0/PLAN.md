# PLAN + AUDIT_PLAN — doc_organize 1.6.0 (2026-11-16)

Pendientes que dejó la 1.5.0 más las dos peticiones de doc_organize_web anotadas en su `docs/plan/DOC_ORGANIZE_GAPS.md`
(G42, G43). Solo PLAN y AUDIT_PLAN: no hay código todavía. El plan de la parte web está en
`doc_organize_web/.ai/sessions/2026-11-16-admin-ia-y-1.6.0/PLAN.md`.

## Inputs

| Campo | Valor |
|---|---|
| Objetivo | Cerrar los tres pendientes del historial del contexto (giro, `created_at`, escrituras concurrentes) y dar a la web metadatos de los sin clasificar (G42) y orden/filtro por las columnas nuevas de la caché (G43) |
| Módulos | `context/context_history.py`, `context/context_builder.py`, `context/context_registry.py`, `core/models.py`, `cache/cache_manager.py`, `export/sources.py`, `projects/layout.py` |
| API pública | Aditiva (ver cada fase). Ningún cambio incompatible: MINOR 1.6.0 |
| Contrato de entrada | Contextos y `CONTEXT_HISTORY.jsonl` escritos por 1.5.0 o anteriores; `cache.db` de cualquier versión (migración aditiva ya existente) |
| Contrato de salida | Lo de antes sigue leyéndose igual; los campos nuevos tienen valor por defecto |
| Reglas de negocio | No inventar metadatos (solo lo que declara el fichero o el idioma detectado; la IA solo con opt-in); orden total y determinista en la caché |
| Restricciones técnicas | Sin dependencias nuevas (bloqueo con la stdlib); async donde ya lo es; funciona en Windows, Linux y sobre SMB/NFS |
| Formatos | `context.json`, `CONTEXT_HISTORY*.jsonl`, `cache.db` (SQLite), Excel del historial |
| Archivos existentes | Sí: los listados arriba |

---

## PLAN

### Fase L1 — Conservar `created_at` entre construcciones

**Estado (2026-11-16)**: implementada en la rama `feat/context-created-at`, sin commit. 923 tests en verde.

**Problema**: `ContextBuilder.build()` pone `created_at = updated_at = now` en cada construcción
([context_builder.py:337-360](../../../src/doc_organize/context/context_builder.py)), así que `Context.created_at` es en la
práctica «última construcción», contra lo que dice su descripción.

**Cambio**: en `_save_and_record`, que ya lee el contexto anterior antes de sobrescribirlo, copiar
`previous.created_at` sobre `context.created_at` cuando hay anterior legible. Sin anterior, o dañado, se queda `now`
(se documenta). Borrar el contexto y volver a construir reinicia la fecha: es un contexto nuevo.

- API: ninguna firma cambia. Cambia el valor devuelto por `build()` (el `Context` se muta antes de guardar).
- Tipos: ninguno.
- Tests: dos construcciones seguidas conservan `created_at` y avanzan `updated_at`; anterior dañado → `now`; borrar y
  reconstruir → `now`.

### Fase L2 — Escrituras concurrentes al historial

**Estado (2026-11-16)**: implementada en la rama `feat/context-created-at` (con L1), sin commit. Con la escritura de
1.5.0, 4 procesos × 40 líneas perdían 16–35 líneas y corrompían 1–6 en NTFS local; con el bloqueo, 160/160.
Diferencias con el plan: la antigüedad del bloqueo se mide con la `mtime` de un fichero de sondeo (reloj del servidor,
T2); en Windows un `PermissionError` al crear el bloqueo («delete pending» en SMB) cuenta como ocupado; la línea se
escribe sin seguir enlaces simbólicos (`O_NOFOLLOW`, mismo criterio que `atomic_write`, G31).

**Problema**: `append_context_build` abre en modo `"a"` sin bloqueo entre procesos. Dos construcciones del mismo proyecto
en procesos distintos (CLI + web, dos workers sin la exclusión que pone la web) pueden intercalar líneas en Windows o en
SMB, donde `O_APPEND` no garantiza escrituras atómicas. Además la Fase L3 renombra ficheros, lo que exige exclusión.

**Cambio**: módulo interno `utils/file_lock.py` con `exclusive_lock(path, timeout, stale_after)` (context manager
síncrono, usado dentro de `asyncio.to_thread`):

- Fichero de bloqueo `CONTEXT_HISTORY.jsonl.lock` creado con `os.open(O_CREAT | O_EXCL | O_WRONLY)` (funciona igual en
  Windows, Linux, SMB y NFSv3+; `fcntl`/`msvcrt` no son fiables en red). Contenido: pid, host y hora.
- Reintento con espera corta hasta `timeout` (5 s por defecto); un bloqueo más viejo que `stale_after` (60 s) se
  considera huérfano y se borra (proceso muerto).
- La línea se escribe con una sola llamada `write` y `flush` + `os.fsync`.
- Si no se consigue el bloqueo: `OSError` → ya se trata en `_save_and_record` como aviso y la construcción no falla
  (comportamiento actual ante un historial no escribible).

- API: `append_context_build(history_path, record)` sin cambios de firma. `exclusive_lock` no es pública.
- Tests: dos procesos (`multiprocessing`) añadiendo 200 líneas cada uno → 400 líneas válidas; bloqueo huérfano se
  recupera; bloqueo vivo agota el `timeout` → `OSError`.

### Fase L3 — Giro del historial

**Estado (2026-11-16)**: implementada en la rama `feat/context-created-at` (con L1 y L2), sin commit. Diferencias con
el plan: el listado y los nombres de los ficheros girados viven en `projects/layout.py` (`context_history_files`,
`rotated_context_history_path`), que solo depende de `core`; `history_file_set` evita duplicados en
`load_context_history`; reducir `backups` borra las copias que sobran en el siguiente giro. Probado con 4 procesos
escribiendo y girando a la vez: 160/160 construcciones.

**Problema**: `CONTEXT_HISTORY.jsonl` crece sin límite: cada construcción guarda la lista de cambios, que en la primera
construcción de un proyecto grande son todos sus documentos.

**Cambio** (bajo el bloqueo de L2):

- Antes de añadir, si el fichero supera `max_bytes` (5 MB por defecto), se gira: `CONTEXT_HISTORY.jsonl` →
  `CONTEXT_HISTORY.1.jsonl`, `.1` → `.2`, …, y se borra lo que pase de `backups` (4 por defecto). Mismo esquema que
  `logging.handlers.RotatingFileHandler`, con `os.replace`.
- `list_context_builds(history_path, *, include_rotated=True)` lee el actual y los girados, más recientes primero. Un
  fichero que desaparece entre listar y abrir (giro concurrente) se trata como vacío.
- `export.sources` (`load_context_history`) y `write_context_history_xlsx` heredan el comportamiento.
- `ProjectLayout`: `context_history_files()` devuelve el actual y los girados, para que el consumidor pueda listarlos
  (vista previa de borrado en la web).
- Configuración: dataclass pública `ContextHistoryPolicy(max_bytes: int = 5_000_000, backups: int = 4)` en
  `doc_organize.context`; `ContextBuilder(..., history_policy: ContextHistoryPolicy | None = None)` y
  `append_context_build(..., policy=None)`. `backups=0` = sin giro (crecimiento libre, como en 1.5.0).

- Tests: giro al pasar el umbral, cuenta de copias, lectura en orden a través de varios ficheros, `backups=0`,
  historial de 1.5.0 sin girar se lee igual.

### Fase L4 — G43: ordenar y filtrar la caché por las columnas de 1.5.0

**Estado (2026-11-16)**: implementada en la rama `feat/context-created-at` (con L1–L3), sin commit. T4 medido: con
100 000 entradas, ≤ 151 ms por página (`owner_name`, offset alto), sin índice. Diferencias con el plan: `owner_name` se
ordena sin distinguir mayúsculas (`py_lower`); `list_mime_types` admite también `search`/`relative_to`/
`conversion_status` para que el recuento coincida con la lista filtrada; `mime_type=[]` no filtra (como `search=""`).

**Cambio** en `cache/cache_manager.py`:

- `CacheOrderBy` gana `"mime_type"`, `"created_time"`, `"owner_name"`. Mismo contrato que G40: empate por `file_path`
  ascendente, `NULL` al final en los dos sentidos (las entradas de antes de 1.5.0 no tienen estos valores).
- `load_cache_page` y `count_entries` ganan `mime_type: str | Sequence[str] | None = None` (igualdad exacta; varios
  valores = `IN`). Se añade a `_build_filters` como parámetro, nunca interpolado.
- Nuevo `list_mime_types(*, relative_to=None) -> list[tuple[str, int]]`: valores distintos con su recuento, para que el
  consumidor construya el desplegable del filtro sin leer toda la caché.
- `owner_name` no se filtra (dato personal; ver AUDIT_PLAN).

- Tests: orden por cada columna nueva en los dos sentidos con `NULL`; filtro simple y múltiple combinado con `search`,
  `relative_to` y `conversion_status`; `count_entries` coherente con `load_cache_page`; `list_mime_types` con caché de
  1.4.0 (todo `NULL`) devuelve `[]`.

### Fase L4b — G44: leer las propiedades de los originales en paralelo

**Origen**: medición W0 de la web (`doc_organize_web/docs/plan/MEDICION_CONTEXTO_RED.md`, 2026-11-16). En un recurso
SMB, `read_document_properties` cuesta 55 ms de mediana (p95 141 ms) frente a 8 ms en local en primera lectura: unos
3,5 min más por construcción en 2613 documentos. Con 4 hilos baja a 33 ms efectivos por documento; con 8 apenas mejora
y satura el NAS.

**Cambio**:

- `_apply_document_properties` lee las propiedades de todos los documentos con concurrencia acotada
  (`asyncio.Semaphore` + `asyncio.to_thread`) en vez de uno detrás de otro. El idioma (que lee el `.json`) sigue igual.
- `ContextBuilder(..., properties_concurrency: int = 4)`; `1` = comportamiento de 1.5.0.
- **PDFium no es thread-safe** (pypdfium2 5.14, «Incompatibility with Threading»): nunca dos llamadas a PDFium a la vez.
  - OOXML (`zipfile`): en hilos, sin cerrojo.
  - PDF, opción A (preferida si la medición la confirma): leer los bytes del fichero en el hilo (la E/S de red, que es
    lo caro) y abrirlos con `PdfDocument(bytes)` bajo un `threading.Lock` del módulo (solo CPU, unos ms). Por encima de
    un tamaño (p. ej. 16 MB) se abre por ruta bajo el cerrojo, para no cargar ficheros enormes en memoria.
  - PDF, opción B: pool de procesos. Aislado y sin cerrojo, pero caro de arrancar en Windows y con más memoria.
  - Antes de elegir: ampliar `bench_context_network.py` de la web con la opción A y medirla en el mismo NAS.
- `read_document_properties` mantiene su firma y su contrato (nunca lanza).

- Tests: el orden y los valores no cambian con concurrencia; un cerrojo comprueba que PDFium nunca se llama dos veces a
  la vez (doble que cuenta llamadas simultáneas); `properties_concurrency=1` reproduce 1.5.0; error en un fichero no
  afecta a los demás; cancelación (`checkpoint`) entre lotes.

### Fase L5 — G42: metadatos de los documentos sin clasificar

**Problema**: `Context.unclassified_documents: list[str]` solo guarda la ruta; los sin clasificar no tienen autor,
descripción, palabras clave ni idioma.

**Cambio**:

- Modelo nuevo `UnclassifiedDocument` (no se reutiliza `DomainDocument`: un sin clasificar puede no tener `.md`/`.json`
  y no tiene confianza ni dominio): `source_path`, `title: str | None`, `document_type`, `markdown_path: str | None`,
  `json_path: str | None`, `reason: Literal["below_threshold", "incomplete_artifacts", "ai_disabled"]`, `author`,
  `description`, `keywords`, `language`, más `rules_domain`/`rules_confidence` cuando las reglas propusieron algo.
- `Context.unclassified_details: list[UnclassifiedDocument] = []`. **`unclassified_documents: list[str]` se mantiene**
  (lo usan `diff_contexts`, el recuento del historial y los consumidores); ambas listas en el mismo orden.
- Relleno: `_apply_document_properties` se extiende a los sin clasificar (propiedades del original; idioma solo si hay
  `.json`). **El enriquecimiento por IA no se aplica** a los sin clasificar (coste; nada lo pide).
- Persistencia: fichero aparte `unclassified.json` junto a `context.json`, escrito y leído por `ContextRegistry` con la
  misma escritura atómica. Motivo: `context.json` se diseñó pequeño (resumen + un `index.json` por dominio) y un proyecto
  con miles de sin clasificar lo inflaría. Un contexto sin ese fichero se carga con `unclassified_details=[]`.
- `SiteGenerator`/`Reorganizer` no cambian (no copian sin clasificar).

- Tests: cada `reason`; contexto de 1.5.0 se carga; `unclassified.json` dañado → `ContextError` (mismo criterio que un
  `index.json` dañado); propiedades de un original borrado → campos vacíos.

### Fase L6 — Cierre de versión 1.6.0

`CHANGELOG.md`, `docs/api/publica.md` (fila 1.6.0), `docs/api/context.md`, `docs/api/cache.md`, `docs/functional/*`,
`zensical.toml` si hay página nueva, `zensical build --strict`, versión en `pyproject.toml`, wheel con SHA-256 en las
notas de la release. Avisar a la web de que G42 y G43 están disponibles.

### Orden y dependencias

```
L1 ──┐
L2 ──┴─> L3 ─────────┐
L4 ──────────────────┼─> L6
L4b (G44) ──> L5 ────┘   (W0 hecha: L5 va después de G44)
```

L1, L2, L4 son independientes; cada fase va en su PR contra `develop`.

### Rutas afectadas

- `src/doc_organize/context/context_history.py`, `context_builder.py`, `context_registry.py`, `__init__.py`
- `src/doc_organize/core/models.py`
- `src/doc_organize/cache/cache_manager.py`, `cache/__init__.py`
- `src/doc_organize/export/sources.py`
- `src/doc_organize/projects/layout.py`
- `src/doc_organize/utils/file_lock.py` (nuevo, interno)
- `tests/unit/...` de cada módulo; `tests/unit/test_public_api.py` si fija exportaciones
- `docs/api/`, `docs/functional/`, `CHANGELOG.md`

### Tipos nuevos

`ContextHistoryPolicy` (dataclass), `UnclassifiedDocument` (pydantic), `UnclassifiedReason` (Literal),
`CacheOrderBy` ampliado.

---

## AUDIT_PLAN

### Riesgos funcionales

| # | Riesgo | Mitigación |
|---|---|---|
| F1 | L1 cambia el valor de `created_at` que los consumidores ya muestran (la web lo muestra como «creado») | Es la corrección de un bug, pero se avisa en el CHANGELOG como cambio de comportamiento |
| F2 | L3: un consumidor que lea `CONTEXT_HISTORY.jsonl` directamente (sin la API) deja de ver lo girado | La web usa `load_context_history`; documentarlo. Ningún otro consumidor conocido |
| F3 | L5 añade una lectura del original por cada sin clasificar; en red el coste está sin medir (es justo la medición W0 de la web) | No fusionar L5 hasta tener W0. Si la red sale cara, L5 incorpora la lectura concurrente acotada (ver S2) |
| F4 | L5: `unclassified_details` y `unclassified_documents` pueden desincronizarse si alguien modifica uno solo | Se construyen juntas en `build()`; validador de modelo que comprueba mismas rutas si `unclassified_details` no está vacía |
| F5 | L4: ordenar por `created_time` mezcla «fecha del sistema de ficheros» de Windows (creación) y de Linux (cambio de metadatos, `st_ctime`) | Ya documentado en 1.5.0 para el campo; repetirlo en el docstring de `order_by` |

### Riesgos técnicos

| # | Riesgo | Mitigación |
|---|---|---|
| T1 | Bloqueo `O_EXCL` huérfano tras un `kill -9` bloquea el historial hasta `stale_after` | `stale_after` 60 s ≫ duración de un append; el fallo no rompe la construcción (solo aviso) |
| T2 | Relojes desincronizados entre hosts que comparten la carpeta (SMB) hacen que un bloqueo vivo parezca huérfano | Se usa la `mtime` del propio fichero de bloqueo (reloj del servidor de ficheros), no la hora escrita dentro |
| T3 | `os.replace` sobre un fichero abierto por un lector falla en Windows (`PermissionError`) | Reintento corto; si persiste, se omite el giro esta vez (aviso) y se añade igualmente la línea |
| T4 | L4: ordenar por columnas sin índice en cachés grandes | Mismo patrón actual (ordenar `rowid` y luego leer filas). Medir con 100 000 entradas; si pasa de 300 ms, índice en la migración aditiva existente |
| T5 | LSP/ISP: `ContextBuilder` gana un parámetro opcional más; `CacheManager` dos métodos con un parámetro más | Todo opcional con valor por defecto que reproduce 1.5.0; contratos async sin cambios; `list_mime_types` es async como el resto de lecturas de `CacheManager`. No se crea interfaz nueva |
| T6 | `test_library_architecture.py` / API pública fijada en tests | Actualizar la lista de exportaciones en el mismo PR |

### Riesgos de seguridad

| # | Riesgo | Mitigación |
|---|---|---|
| S1 | L4: filtro `mime_type` como vector de inyección SQL | Siempre parámetro `?`; `order_by` sigue validado contra `CacheOrderBy` (lista blanca) |
| S2 | `owner_name` es dato personal; ordenar por él permite inferirlo a quien no deba verlo | La librería lo ofrece; la web solo lo expone a quien tenga el permiso (condición en el plan web). No se añade filtro por propietario |
| S3 | Fichero de bloqueo con pid y host revela nombre de máquina en el destino compartido | Aceptable (ya hay rutas absolutas en el historial); se documenta |
| S4 | `unclassified.json` manipulado | Mismo validador pydantic que el resto; rutas solo informativas (no se copian ni borran a partir de ellas) |

### Simplificaciones posibles

- **L3**: en vez de copias numeradas, compactar a las últimas N construcciones en un solo fichero. Más simple para los
  lectores, pero pierde historial. Se descarta salvo que el mantenedor prefiera simplicidad.
- **L4**: `list_mime_types` es opcional; la web podría usar una lista fija de tipos. Se mantiene porque la caché es la
  única que sabe qué tipos hay.
- **L5**: guardar los sin clasificar dentro de `context.json` (lo que dice literalmente G42) evita un fichero nuevo, a
  costa de su tamaño. Decisión del mantenedor (ver Condiciones).
- **L2 + L3** pueden ir en un solo PR si se prefiere: comparten el bloqueo.

### Veredicto: **GO_CONDICIONAL**

Condiciones:

1. ~~Decidir dónde viven los sin clasificar (L5)~~ — **Resuelta (2026-11-16)**: `unclassified.json` aparte, junto a
   `context.json`. G42 en el documento de huecos de la web se actualiza para reflejarlo.
2. ~~L5 no se fusiona hasta tener el resultado de la medición W0 en red~~ — **Resuelta (2026-11-16)**: W0 supera el
   umbral (red 7× local). Nueva condición: **L5 va después de L4b (G44)**, para no ampliar a los sin clasificar una
   lectura secuencial que ya es cara en red.
5. L4b: elegir la vía para PDF (A: bytes en hilos + cerrojo; B: procesos) tras medir la opción A en el NAS. Ningún
   diseño puede llamar a PDFium desde dos hilos a la vez.
3. ~~Valores por defecto del giro~~ — **Resuelta (2026-11-16)**: 5 MB y 4 copias.
4. Test de concurrencia de L2 ejecutado en Windows y en Linux (CI) antes de fusionar. **Abierta** (se comprueba al implementar).

L1–L4 pueden empezar ya; L4b espera a medir la opción A; L5 va después de L4b.
