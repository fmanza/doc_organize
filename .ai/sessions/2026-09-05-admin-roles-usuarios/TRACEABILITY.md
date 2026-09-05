# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-05
- **Tipo**: `/new-feature` (gestión de Roles/Usuarios) + `/tech-debt` (extracción de duplicación JS/Jinja)
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (implementación + tests + documentación en verde; el hallazgo residual de `project_selector.html.j2` se resolvió en la misma sesión — ver "Cambios Ejecutados" §5)

## Objetivo
Petición del usuario: al crear un Rol y al crear un Usuario, cada uno debe ser
una opción de menú independiente (no una única página combinada), agrupadas
bajo un apartado "Admin"; el usuario creado debe llevar obligatoriamente un
rol y un checkbox "debe cambiar contraseña"; las "raíces de escaneo
permitidas" de un rol deben construirse como una lista (con "Guardar carpeta"
y "Buscar…", como en "carpeta raíz"), no como texto libre. Al auditar el
código resultante salió deuda técnica (JS/markup duplicado entre plantillas),
que se abordó en la misma sesión con `/tech-debt`.

## Investigación previa
Roles/Usuarios/Tenants ya existían en el proyecto desde una sesión anterior
(2026-08-29) — no era una feature desde cero. Se confirmó por exploración de
código que el modelo de datos (`Role.allowed_scan_roots`, `User.role_id`
obligatorio, `User.must_change_password`) ya soportaba todo lo pedido; lo que
faltaba era exclusivamente la UI/rutas HTML (página combinada, sin checkbox
expuesto, textarea en vez de lista). `Role.allowed_scan_roots` se evaluó
explícitamente por pedido del usuario ("¿sirve realmente, dado que un rol con
acceso a un proyecto ya accede a todo su contenido?") y se concluyó que **no
es redundante**: rige qué carpetas *fuera* de los proyectos ya existentes
puede escanear un rol para crear un proyecto nuevo, mientras que
`project_names` rige el acceso a proyectos *ya creados* — son dos controles
distintos, se mantiene tal cual.

## Cambios Ejecutados

### ✅ 1. Separar `/admin/users` en `/admin/roles` + `/admin/users`
**Archivo(s)**: `src/doc_organize/web/routes/admin.py`,
`src/doc_organize/web/templates/admin_roles.html.j2` (nuevo),
`admin_users.html.j2`, `base.html.j2`.
**Descripción**: `admin_users_page` (única, con formularios de rol y usuario
mezclados) se divide en `admin_roles_page` (`GET /admin/roles`, ya no fetch de
`users`) y `admin_users_page` (`GET /admin/users`, ya no fetch de `projects`).
El sidebar (`base.html.j2`) sustituye el enlace único "Gestión de usuarios"
por un grupo estático "Admin" con dos enlaces ("Roles"/"Usuarios"), visible
solo si `request.state.is_admin`.
**Status**: ✅ cubierto por `test_admin_roles_page_loads_for_admin_with_projects`
y `test_admin_users_page_loads_for_admin` (actualizado) en
`tests/unit/test_web_admin_routes.py`.

### ✅ 2. Checkbox "Debe cambiar contraseña" al crear usuario
**Archivo(s)**: `src/doc_organize/web/routes/admin.py`,
`src/doc_organize/web/templates/admin_users.html.j2`.
**Descripción**: `CreateUserRequest` gana `must_change_password: bool = False`,
propagado a `AuthStore.create_user(..., must_change_password=...)` (el
parámetro ya existía en la capa de persistencia, revisión 9; solo faltaba
exponerlo en el payload del API y en la UI).
**Status**: ✅ `test_create_user_with_must_change_password_checkbox` (con y
sin marcar).

### ✅ 3. Lista de "Raíces de escaneo permitidas" (Guardar carpeta / Buscar / Eliminar)
**Archivo(s)**: `src/doc_organize/web/templates/admin_roles.html.j2`.
**Descripción**: el `<textarea>` de texto libre se sustituye por una lista en
memoria (`scanRoots`, el rol aún no existe al construirla — no hay API que
persista cada ruta antes de crear el rol). "Guardar carpeta" añade la ruta
escrita a mano; "Buscar…" reutiliza `GET /api/fs/browse` (mismo endpoint que
"Carpetas guardadas" de un proyecto); cada entrada tiene botón "Eliminar".
Deduplicación por igualdad exacta de cadena (ver Riesgos Residuales). Al
enviar "Crear rol", `allowed_scan_roots` se toma del array en memoria.
**Status**: ✅ verificado end-to-end contra la app real (no solo mocks):
`GET /api/fs/browse`, `POST /api/roles` con rutas combinadas
manual+explorador, `PATCH /api/roles/{id}` tras quitar una entrada.

### ✅ 4. Deuda técnica: extracción de JS/markup duplicado
**Archivo(s)**: `src/doc_organize/web/templates/_shared_scripts.html.j2`
(nuevo), `_folder_browser_macros.html.j2` (nuevo), `dashboard.html.j2`,
`admin_roles.html.j2`, `admin_users.html.j2`.
**Descripción**: el helper `postJson`/`apiError` y el panel "explorador de
carpetas del servidor" (botones Buscar/Subir/Usar esta carpeta/Cerrar +
listado) estaban duplicados completos entre `dashboard.html.j2` ("Carpetas
guardadas") y el nuevo `admin_roles.html.j2`. Se extraen a un script Jinja
`{% include %}` compartido (`_shared_scripts.html.j2`, función
`initFolderBrowser(idPrefix, onSelect)`) y dos macros Jinja
(`folder_browser_button`/`folder_browser_panel`, parametrizadas por
`id_prefix`). `onSelect(path)` es el único punto de variación entre páginas
(persistir de inmediato en `dashboard.html.j2` vs. añadir a la lista en
memoria en `admin_roles.html.j2`); si `onSelect` lanza un `Error`, su mensaje
se muestra en el propio panel.
**Bug real atrapado durante el propio refactor**: la primera versión desviaba
el error de "Usar esta carpeta" en el dashboard hacia `#folder-list-error` en
vez de al `<p>` de error del propio panel (comportamiento original) —
corregido antes de dar el refactor por bueno.
**Quick wins añadidos de regalo** (detectados en el AUDIT_CODE de esta misma
extracción, no eran objetivo inicial): token de generación de petición en
`browseTo()` (una respuesta de red desordenada, por navegar muy rápido, ya no
pisa la vista con datos de otra carpeta) y deshabilitado del botón "Usar esta
carpeta" mientras `onSelect` está en curso (evita doble clic concurrente).
Ambos bugs eran preexistentes en el `dashboard.html.j2` original, no
introducidos por esta sesión — la extracción los hizo más baratos de arreglar
de una vez.
**Status**: ✅ smoke test repetido contra la app real tras el refactor, sin
diferencias de comportamiento observable.

### ✅ 5. Unificar `project_selector.html.j2` con la abstracción compartida
**Archivo(s)**: `src/doc_organize/web/templates/project_selector.html.j2`,
`_shared_scripts.html.j2`, `_folder_browser_macros.html.j2`.
**Descripción**: al cerrar la sesión se descubrió que `project_selector.html.j2`
tenía su PROPIA implementación equivalente (`apiError()` local +
`createFolderBrowser(ids)`, usada dos veces: `locationBrowser` para elegir
ubicación al crear un proyecto, `moveBrowser` para elegir destino al mover
uno), no detectada al construir `_shared_scripts.html.j2`/
`_folder_browser_macros.html.j2` para `dashboard.html.j2`/`admin_roles.html.j2`.
Se abrió un segundo ciclo `/tech-debt` (PLAN → AUDIT_PLAN → IMPLEMENT) para
unificarlo también. Dos conflictos de diseño reales, no solo de forma:
- **Cierre de panel tras seleccionar**: `locationBrowser`/`moveBrowser` sí
  cerraban el panel al pulsar "Usar esta carpeta"; `dashboard.html.j2`/
  `admin_roles.html.j2` deliberadamente no. Resuelto pasando un segundo
  argumento `close()` a `onSelect(path, close)` — cada página lo invoca o lo
  ignora según su flujo, sin bifurcar `initFolderBrowser`.
- **Clases Tailwind distintas por uso** (`move-browse-btn`/`move-browse-panel`
  con padding/margen propios, `location-browse-panel` con `max-w-2xl`
  añadido): resuelto con un parámetro opcional `class_override` en ambas
  macros, que sustituye por completo las clases por defecto en vez de
  intentar "añadir" (evita clases Tailwind en conflicto tipo `p-2`+`p-3`
  simultáneas).
**Status**: ✅ smoke test contra la app real verificando explícitamente que
las 4 combinaciones de clases CSS (2 por página × 2 páginas) se preservan
byte a byte, más el flujo completo crear-proyecto/mover-proyecto vía API.
Suite completa (519 tests) sin regresiones.

---

## Impacto

### Código
- **Archivos modificados**: `src/doc_organize/web/routes/admin.py`,
  `src/doc_organize/web/templates/{admin_users,base,dashboard,project_selector}.html.j2`,
  `docs/api/index.md`, `tests/unit/test_web_admin_routes.py`,
  `CHANGELOG.md`.
- **Archivos creados**: `src/doc_organize/web/templates/admin_roles.html.j2`,
  `_shared_scripts.html.j2`, `_folder_browser_macros.html.j2`,
  `.ai/sessions/2026-09-05-admin-roles-usuarios/TRACEABILITY.md`.
- **Cambios funcionales**: sí — dos páginas HTML nuevas/separadas, un campo
  nuevo en `POST /api/users`, una lista en vez de un textarea en la UI de
  rol. Los endpoints `/api/roles*` no cambian de contrato salvo la adición
  aditiva en `/api/users`. `project_selector.html.j2` sin cambio de
  comportamiento observable (mismas clases CSS, mismo cierre/no-cierre de
  panel por caso de uso), solo de implementación interna.

### Compatibilidad
- **BREAKING**: ninguno. `GET /admin/users` sigue existiendo en la misma URL
  (ya no incluye el formulario de rol, que se movió a `/admin/roles`, una URL
  nueva). `POST /api/users` es compatible hacia atrás: el campo nuevo tiene
  default `False`, cualquier cliente que no lo envíe se comporta como antes.
- **NO BREAKING**: todo lo demás es aditivo o interno (refactor de plantillas
  sin cambio de comportamiento observable, salvo los 2 arreglos de robustez
  documentados arriba, que son estrictamente mejoras).

---

## Verificación
```
python -m ruff check src tests          → All checks passed!
python -m mypy src                      → Success: no issues found in 53 source files
python -m pytest                        → 519 passed
python -m mkdocs build --strict         → build limpio, sin warnings
```
Más un smoke test real (no solo mocks) contra la app levantada vía
`create_app()` + `httpx.ASGITransport`, reproduciendo exactamente las
llamadas HTTP que dispara cada botón de la UI (Guardar carpeta, Buscar/Usar
esta carpeta, Eliminar, checkbox de usuario, crear/mover proyecto), repetido
tras cada uno de los dos refactors de deuda técnica sin diferencias de
comportamiento, y verificando explícitamente que las clases CSS de
`location-browse-*`/`move-browse-*` se preservan byte a byte tras la
migración a macros con `class_override`.

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Deduplicación de `scanRoots` (lista de raíces de escaneo) por igualdad exacta de cadena — dos rutas que difieren en mayúsculas/minúsculas o una barra final no se detectan como duplicadas | Cosmético; el backend ya tolera rutas repetidas/solapadas | Aceptado |
| Lógica cliente de `scanRoots`/`initFolderBrowser`/`createFolderBrowser` (ya eliminada) sin test automatizado (solo verificación manual reproduciendo llamadas HTTP) | Requiere decidir si se adopta Playwright/navegador headless — no está instalado en este entorno; decisión de arquitectura fuera de alcance de esta sesión | Aceptado, pendiente de decisión explícita del usuario |
| `postAction()` en `project_selector.html.j2` es un CUARTO patrón de "fetch + manejo de error" en la misma plantilla (junto a `postJson` compartido y el `fetch` directo de `add-folder-btn` en `dashboard.html.j2`) — no se tocó, es sobre las acciones del modal de confirmación (clear-history/delete/move), no sobre el explorador de carpetas | Anotado para no descubrirlo tarde en una futura sesión; candidato a un `/tech-debt` aparte si se decide unificar TODOS los helpers de fetch, no solo el explorador de carpetas | Aceptado, no bloqueante |

---

## Siguientes Pasos (Recomendado)
1. Commit (commits separados por tipo de cambio — política del proyecto de
   no mezclar `feat`/`refactor` en un commit):
   - `feat:` gestión de Roles/Usuarios (páginas separadas, checkbox, lista de
     raíces de escaneo).
   - `refactor:` extracción de `_shared_scripts.html.j2`/
     `_folder_browser_macros.html.j2` y migración de las 4 plantillas que
     usaban el explorador de carpetas (`dashboard`, `admin_roles`,
     `project_selector` ×2 usos).
2. (Opcional, futuro) Decidir sobre Playwright/navegador headless para poder
   testear automáticamente la lógica cliente de listas (`scanRoots`,
   `folder-list`) y del explorador de carpetas compartido.
3. (Opcional, futuro) Si se quiere ir más lejos, unificar también `postJson`
   con `postAction()`/el `fetch` directo de "Carpetas guardadas" — mismo
   patrón de deuda, alcance mayor (toca lógica de negocio de cada acción, no
   solo el explorador de carpetas).

---

## Directrices para Futuras IAs

- **[`Role.allowed_scan_roots` no es redundante con `Role.project_names`]**:
  el primero rige qué carpetas *fuera* de los proyectos ya registrados puede
  escanear un rol para crear un proyecto nuevo (`GET /api/fs/browse`, WebSocket
  de escaneo); el segundo rige el acceso a proyectos *ya existentes*. No
  eliminar ni fusionar sin releer esta distinción.
- **[El "explorador de carpetas del servidor" es ahora una única abstracción
  compartida, usada por las 4 plantillas que lo necesitan]**:
  `_shared_scripts.html.j2` (`initFolderBrowser(idPrefix, onSelect)`) +
  `_folder_browser_macros.html.j2` (`folder_browser_button`/
  `folder_browser_panel`, con `class_override` opcional). Usado por
  `dashboard.html.j2` ("Carpetas guardadas"), `admin_roles.html.j2` (raíces de
  escaneo), y `project_selector.html.j2` dos veces ("location" al crear un
  proyecto, "move" al moverlo). Antes de añadir un quinto selector de carpeta
  en cualquier plantilla nueva, usar esta abstracción — no crear una nueva
  variante. Si un caso de uso necesita cerrar el panel tras seleccionar,
  invocar el segundo argumento de `onSelect(path, close)`; si necesita
  clases CSS distintas a las por defecto, pasar `class_override` a las
  macros (sustituye las clases por defecto por completo, no las añade).
- **[Al compartir un callback entre plantillas con comportamientos distintos
  (`onSelect`), no asumir que solo se comparte markup]**: la primera versión
  de esta extracción rompió silenciosamente dónde se mostraba el error de
  "Usar esta carpeta" en `dashboard.html.j2` (iba a un `<p>` equivocado) hasta
  que se revisó explícitamente contra el comportamiento original. Al extraer
  UI compartida entre páginas con flujos distintos (persistir vs. acumular en
  memoria), verificar explícitamente *dónde* se muestra cada error, no solo
  que la llamada HTTP subyacente sea la misma.
- **[Sin Playwright/navegador headless en este entorno]**: confirmado en esta
  sesión (`python -c "import playwright"` falla, no hay `chromium-cli` en
  PATH). Cualquier verificación de JS de cliente en este proyecto, hasta que
  se decida adoptar esa dependencia, pasa por reproducir manualmente las
  llamadas HTTP que dispara cada botón (vía `httpx.ASGITransport` contra
  `create_app()`), no por tests de navegador reales.

---

## Veredicto

### 🟢 COMPLETADA (feature + dos ciclos de refactor de deuda técnica, ambos resueltos)

**Criterios**:
- ✅ Las 3 peticiones funcionales de la feature implementadas y testeadas
- ✅ Deuda técnica (duplicación de `postJson`/`apiError`/explorador de
  carpetas) resuelta en las 4 plantillas que la tenían, incluida la hallada
  tardíamente en `project_selector.html.j2`, con 2 arreglos de robustez de
  regalo (token anti-carrera, guarda anti-doble-clic)
- ✅ Suite completa en verde (519 tests), `ruff`/`mypy`/`mkdocs build --strict`
  limpios
- ✅ Smoke test contra la app real tras cada uno de los tres refactors, sin
  diferencias de comportamiento ni de clases CSS
- ⬜ Ítem de tests JS automatizados (Playwright) y unificación de
  `postJson`/`postAction()` quedan como trabajo futuro explícito, no como
  deuda oculta
- ⬜ Commit: pendiente de esta misma sesión

**Evidencia**:
- Branch: `develop`
- Tests: `tests/unit/test_web_admin_routes.py` (ampliado), suite completa 519
  passed
- Docs: `docs/api/index.md` actualizado, `mkdocs build --strict` limpio

**Sesión cerrada**: 2026-09-05
