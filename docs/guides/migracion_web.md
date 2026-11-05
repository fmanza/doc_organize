# De la web integrada a doc_organize_web

La web integrada de doc_organize (`doc_organize.web`, `doc_organize.auth`, los subcomandos `web`, `tenant` y `user` y
el extra `[web]`) quedó obsoleta en 0.14.0 y se retiró en 1.0.0. La sustituye
[doc_organize_web](https://github.com/fmanza/doc_organize_web), un proyecto aparte que usa esta librería por debajo.
Desde su versión 0.10.0 cubre todas las pantallas y rutas de la web integrada: su
[inventario de paridad](https://github.com/fmanza/doc_organize_web/blob/main/docs/plan/PARIDAD.md) tiene todas las filas
cerradas.

Esta guía es para quien usaba la web integrada. Si solo usas el CLI (`scan`, `project`, `deduplicate`, `export`) o la
librería desde Python, no tienes que hacer nada: siguen igual.

## Los datos no se migran

doc_organize_web **empieza limpio**: no importa nada de la web integrada.

| Dato de la web integrada | Qué pasa |
|---|---|
| Proyectos de `~/.doc_organize/projects.json` | No se importan. doc_organize_web guarda sus proyectos en su propia base de datos (`config.db`); créalos de nuevo allí |
| Usuarios, tenants, roles y sesiones de `~/.doc_organize/auth.db` | No se importan. El primer administrador se crea por terminal al desplegar (no hay `admin`/`admin` de fábrica) |
| Configuración de IA guardada desde `/admin/configuracion-ia` | No se importa. Vuelve a introducirla en `/admin/ai-settings` |
| Plantillas de taxonomía de `~/.doc_organize/taxonomy_templates/` | No se importan automáticamente. Puedes importarlas como `.md` desde `/admin/taxonomy-templates` |
| Carpetas de los proyectos (`Conversión/`, `cache.db`, `duplicados/`…) | Quedan donde estaban: doc_organize_web no las borra ni las reutiliza. Cada proyecto nuevo escribe en una carpeta de salidas nueva o vacía |

Mientras no borres `~/.doc_organize/`, los proyectos antiguos siguen accesibles con el CLI de esta librería
(`python -m doc_organize project list`, `export zip --project …`).

## Desplegar doc_organize_web

Se despliega con Docker Compose en un servidor Linux. La guía completa, con el primer arranque, los volúmenes, las
copias de seguridad y las actualizaciones, está en
[Despliegue](https://github.com/fmanza/doc_organize_web/blob/main/docs/guides/despliegue.md) del repositorio de
doc_organize_web. En resumen:

```bash
git clone https://github.com/fmanza/doc_organize_web.git
cd doc_organize_web
python3 scripts/generate_secrets.py
docker compose up -d --build
docker compose exec web python -m app.cli create-admin --username <usuario>
```

## Qué sustituye a cada pantalla

| Pantalla de la web integrada | Ruta | Sustituto en doc_organize_web |
|---|---|---|
| Plantilla base y navegación | — | Layout con navegación por fases |
| Inicio de sesión | `/login` | Página de inicio de sesión |
| Cambio de contraseña | `/change-password` | Cambio de contraseña |
| Admin de usuarios | `/admin/users` | Admin de usuarios y sesiones |
| Explorador de carpetas | — | Explorador sobre ubicaciones registradas por un admin |
| Semáforo y avisos de estado | — | Semáforo de estado y ficha de capacidades |
| Selector de proyectos | `/` | Lista y selector de proyectos |
| Dashboard del proyecto | `/projects/{name}` | Dashboard de proyecto |
| Escaneo y carpetas guardadas | `/projects/{name}/scan` | Pantalla de escaneo con ayuda contextual |
| Errores de escaneo | `/projects/{name}/scan-errors` | Errores de escaneo |
| Duplicados | `/projects/{name}/duplicates` | Resolutor de duplicados en dos pasos (vista previa y aplicar) |
| Contexto | `/projects/{name}/context` | Página de contexto y visor del sitio |
| Plantillas de taxonomía | `/admin/plantillas-taxonomia` | `/admin/taxonomy-templates`, con importar y exportar `.md` |
| Configuración de IA | `/admin/configuracion-ia` | `/admin/ai-settings`, y panel de uso nuevo en `/admin/ai-usage` |
| Admin de roles | `/admin/roles` | Admin de roles |
| Admin de tenants | `/admin/tenants` | Admin de tenants |

## Qué sustituye a cada endpoint

En doc_organize_web, las operaciones largas (escanear, deduplicar, exportar, construir el contexto, mover o borrar un
proyecto) son **ejecuciones** encoladas con progreso por SSE: siguen en marcha aunque cierres la pestaña. Los
WebSocket de la web integrada desaparecen.

| Ruta de la web integrada | Sustituto en doc_organize_web |
|---|---|
| `POST /login`, `POST /logout` | `POST /api/v1/auth/login`, `POST /api/v1/auth/logout` |
| `POST /change-password` | `POST /api/v1/auth/password` |
| `GET, POST /api/users` | `/api/v1/users` |
| `GET, PATCH, DELETE /api/users/{user_id}` | `/api/v1/users/{id}` (se desactiva en lugar de borrar) |
| `GET /api/fs/browse` | `GET /api/v1/fs/browse?location=&path=` (sin `Path.home()`) |
| `GET, POST /api/projects` | `/api/v1/projects` |
| `GET, DELETE /api/projects/{name}` | `GET /api/v1/projects/{id}`; borrar es la ejecución `project_delete`, auditada |
| `GET /api/projects/{name}/impact` | Vista previa: la operación con `dry_run` |
| `POST /api/projects/{name}/move` | Ejecución `project_move` |
| `POST /api/projects/{name}/clear-history` | Ejecución `history_clear` |
| `WS /api/projects/{name}/scan` | Ejecución `scan` + SSE |
| `GET, POST, DELETE /api/projects/{name}/folders/library` | `/api/v1/projects/{id}/scanned-folders` |
| `POST /api/projects/{name}/folders/validate` | Validación por el resolvedor de ubicaciones |
| `GET /api/projects/{name}/cache` | `/api/v1/projects/{id}/documents`, paginado |
| `GET /downloads/projects/{name}/export-preview` | Ejecución `export_zip` con `dry_run` |
| `GET /downloads/projects/{name}/export.zip` | Ejecución `export_zip` y su artefacto |
| `GET /downloads/projects/{name}/cache-export.xlsx` | Ejecución `export_xlsx` (caché) |
| `GET /downloads/projects/{name}/scan-errors-export.xlsx` | Ejecución `export_xlsx` (errores) |
| `WS /api/projects/{name}/scan/deduplicate` | Ejecución `dedup_preview` + SSE |
| `GET /api/projects/{name}/duplicates` | Grupos de la vista previa (`/runs/{id}/duplicate-groups`) y Excel como artefacto |
| `POST /api/projects/{name}/duplicates/resolve` | Ejecución `dedup_apply` con los grupos confirmados |
| `GET, POST, DELETE /api/projects/{name}/context` | `GET /api/v1/projects/{id}/context` y `/context/documents`; construir y borrar son ejecuciones |
| `WS /api/projects/{name}/context/build` | Ejecución `context_build` + SSE |
| `WS /api/projects/{name}/context/delete` | Ejecución `context_delete` + SSE |
| `PUT /api/projects/{name}/context/taxonomy-manifest` | Manifiesto de taxonomía del proyecto |
| `GET /projects/{name}/context/site/…` | Sitio Zensical servido aislado |
| `GET /api/taxonomy-templates` | `/api/v1/taxonomy-templates` |
| `GET, PUT, DELETE /api/taxonomy-templates/{template_name}` | `/api/v1/taxonomy-templates/{name}` |
| `POST /api/projects/{name}/context/taxonomy-manifest-draft` | Ejecución `taxonomy_draft` (el borrador va en el resultado y no se guarda) |
| `GET /api/admin/ai-settings` | `/api/v1/admin/ai-settings` (sin secretos en claro) |
| `PUT /api/admin/ai-settings/{family_key}` | `/api/v1/admin/ai-settings/{family}` |
| `GET, POST /api/roles` | `/api/v1/roles` |
| `GET, PATCH, DELETE /api/roles/{role_id}` | `/api/v1/roles/{id}` |
| `GET, POST /api/tenants` | `/api/v1/tenants` |
| `DELETE /api/tenants/{tenant_id}` | `/api/v1/tenants/{id}` |
| `GET, POST /api/tenants/{tenant_id}/users` | Usuarios por tenant |
| `PATCH, DELETE /api/tenants/{tenant_id}/users/{user_id}` | Usuarios por tenant |

## Lo que cambia a propósito

Algunas cosas no se han replicado tal cual:

- **Escaneo**: ya no se cancela al cerrar la pestaña; la ejecución sigue en el worker.
- **Duplicados**: no se mueven dentro del escaneo. Primero hay una vista previa y después se aplican los grupos
  confirmados.
- **Carpetas**: no se navega libremente desde `Path.home()`. Un administrador registra las ubicaciones permitidas.
- **Usuarios**: se desactivan en vez de borrarse, para que la auditoría conserve quién hizo cada cosa.
- **Mover, vaciar o borrar un proyecto**: hacen falta una vista previa, teclear el nombre del proyecto y queda
  auditado.
- **Descargas** (ZIP y Excel): son ejecuciones con el fichero como artefacto, con cuota, retención y cancelación.

La lista completa, con el motivo de cada decisión, está en la sección «Fuera de paridad» del
[inventario de paridad](https://github.com/fmanza/doc_organize_web/blob/main/docs/plan/PARIDAD.md).

## La documentación anterior

La documentación de la web integrada tal como estaba en 0.14.0 (acceso, panel de administración, configuración de IA,
rutas HTTP, estado de la aplicación y el ADR-004) se conserva en el [histórico](../historico/index.md).
