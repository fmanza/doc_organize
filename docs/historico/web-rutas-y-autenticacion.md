# Rutas HTTP y autenticación de la web integrada

!!! note "Histórico"
    La web integrada (`doc_organize.web`, `doc_organize.auth` y los subcomandos `web`, `tenant` y `user`) se retiró
    en 1.0.0 (L-11), tras quedar obsoleta en 0.14.0 (L-10). La sustituye
    [doc_organize_web](https://github.com/fmanza/doc_organize_web). Estas secciones se conservan como estaban en 0.14.0
    para consulta; los módulos y ficheros que citan ya no existen.

## Arquitectura de la web integrada (antes en `api/index.md`)

### Autenticación web (host no-loopback)

Sesión por cookie (`HttpOnly`, `SameSite=Strict`), no bearer token compartido:
`POST /login` valida usuario+contraseña+tenant contra `AuthStore` y fija la
cookie; `AuthMiddleware` la exige en toda ruta salvo `/login`/`/logout`. Las
conexiones WebSocket (`web/routes/scan.py`) no pasan por el middleware HTTP
(Starlette no lo intercepta para el scope `"websocket"`) y autentican la sesión
explícitamente en el propio handler.

### Roles y gestión de usuarios (rediseño Tenant/Role/User)

Al abrir `AuthStore` por primera vez (CLI o web), si `DEFAULT_TENANT_ID`
("default") no existe se crea de fábrica, en una única transacción, junto con
un rol **global** `admin` (`is_admin=True`) y un usuario `admin`/`admin`
marcado con `must_change_password=True` **e** `is_instance_admin=True` —
`_ensure_default_tenant_bootstrap()`. Mientras esa marca esté activa y el host
no sea loopback, `AuthMiddleware` bloquea toda ruta salvo `/change-password` y
`/logout`; además, esa identidad exacta (`tenant="default"`, `username="admin"`)
ni siquiera puede completar `POST /login` en modo no-loopback mientras
conserve la contraseña de fábrica (`web/routes/auth.py::login_submit`,
`is_factory_admin_account()`) — se rechaza el login en sí, no solo el resto de
rutas tras entrar. `AuthStore.create_tenant()` (para cualquier tenant
adicional) ya NO aprovisiona ningún rol ni usuario: `Role` no está ligado a un
tenant, así que no hay "rol admin de ESE tenant" que crear; su primer usuario
lo da de alta un `is_instance_admin` o `user create` por CLI.

`Role` es global (`name` único en toda la instalación, sin `tenant_id`): un
mismo rol puede asignarse a usuarios de tenants distintos. `is_admin=True` ve
todos los proyectos del tenant *del usuario que lo tiene asignado*; un rol
no-admin solo ve los proyectos listados en `Role.project_names`, interpretados
siempre dentro del tenant de ese usuario. `AuthStore.can_access_project(role_id,
project_name)` es la única fuente de verdad para esa comprobación, usada tanto
por `require_project_access` (`web/dependencies.py`, aplicada por firma en
cada ruta `{name}`-scoped) como por el handler WebSocket de escaneo.

`Role.allowed_scan_roots` se retiró: el acceso de escaneo de un rol no-admin es
ahora **implícito** — la única raíz permitida es `project.root_path` de cada
proyecto en `project_names` (`get_allowed_scan_roots(request, project)`, sin
consulta a `AuthStore`: ya no hay nada configurable que leer). `GET
/api/fs/browse` gana un parámetro `project: str | None` para saber a qué
proyecto ceñirse; sin él, un rol restringido no tiene ninguna raíz permitida
(`403`). Un rol `is_admin` nunca tiene esta restricción.

`User` gana `is_blocked` (sin acceso; `set_user_blocked(..., True)` invalida
todas sus sesiones en la misma transacción, no solo impide logins futuros) e
`is_instance_admin` (nivel de instancia, independiente del `is_admin` del rol:
ve la pantalla cruzada de tenants, crea/elimina tenants, gestiona roles/usuarios
de cualquier tenant, y es el único que puede tocar `InstanceSecretsStore`/
`TaxonomyTemplateRegistry` — recursos de instancia, no de un tenant).

Tres routers de gestión, cada uno con su propia dependencia a nivel de router
(imposible olvidarla en un endpoint nuevo):

- `/api/roles`, `/api/users` (`web/routes/admin.py`): `require_admin_or_instance_admin`
  — basta `is_admin` del propio tenant, o `is_instance_admin` de cualquiera.
  Operan sobre el catálogo global de roles y sobre los usuarios del tenant de
  la sesión.
- `/api/tenants`, `/api/tenants/{tenant_id}/users*` (`web/routes/tenants.py`):
  `require_instance_admin` — alta/baja de tenants (`delete_tenant` exige cero
  usuarios y cero proyectos) y gestión de usuarios de **cualquier** tenant,
  incluida la única vía para tocar `is_instance_admin` de otro usuario.
- `/admin/configuracion-ia`, `/admin/plantillas-taxonomia` (create/editar/
  borrar): `require_instance_admin` — son recursos de instancia, no de un
  tenant, así que un `is_admin` de un solo tenant no basta.

Páginas HTML: `GET /admin/roles` (`admin_roles.html.j2`), `GET /admin/users`
(`admin_users.html.j2`) y `GET /admin/tenants` (`admin_tenants.html.j2`), cada
una con su entrada de menú en el sidebar (`base.html.j2`), condicionada a
`request.state.is_admin`/`is_instance_admin` según corresponda.

`POST /api/users` acepta `must_change_password: bool = False`: si se marca,
el usuario debe cambiar su contraseña en su primer login (`AuthMiddleware`),
igual que el usuario `admin` de fábrica o tras un reseteo de contraseña vía
`PATCH /api/users/{id}`.


## Rutas HTTP del contexto (antes en `api/context.md`)

### Rutas HTTP

Todas bajo `/projects/{name}/context` (página) y `/api/projects/{name}/context`
(JSON), protegidas por `require_project_access`:

| Ruta | Método | Descripción |
|---|---|---|
| `/projects/{name}/context` | `GET` | Página HTML — lista de dominios, o estado vacío si no hay contexto todavía |
| `/api/projects/{name}/context` | `POST` | Construye/reconstruye: `{candidate_domains?, threshold?, ai_classification_enabled?, taxonomy_template_name?}` → `409` si hay otra operación en curso; `400` si la IA está activada sin el proxy correspondiente configurado (1 eje o 2 ejes según haya o no manifiesto), o si se combinan entre sí `taxonomy_manifest.md` local, `candidate_domains` y `taxonomy_template_name` (cualquier par es excluyente — ver `TaxonomyTemplateRegistry`). Si existe `taxonomy_manifest.md`, se carga automáticamente — no hace falta pasar nada en el payload para activar el modo manifiesto (ni para que `ai_classification_enabled` use el cliente de 2 ejes) |
| `/api/projects/{name}/context` | `GET` | Devuelve el contexto ya construido — `404` si no existe todavía |
| `/api/projects/{name}/context/taxonomy-manifest-draft` | `POST` | Pide a la IA un borrador de manifiesto de taxonomía: `{sample_size?}` (1-60, default 25) → `TaxonomyManifestDraftResponse` (`manifest`, `manifest_markdown`, `reasoning`, `sample_document_count`, `total_document_count`). Endpoint de solo lectura (sin lock de operación, nunca escribe nada en disco) — distinto de `ai_classification_enabled` en `POST .../context` (Sub-fase B: elige DENTRO de un catálogo ya confirmado), aquí la IA propone el catálogo mismo. `400` si el proyecto no tiene documentos convertidos (o ninguno con `.json` legible), o si `DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_*` no está configurado; `502` si el LiteLLM Proxy falla o responde algo que no cumple el schema esperado |
| `/api/taxonomy-templates` | `GET` | Lista las plantillas disponibles (`TaxonomyTemplateRegistry.list_templates()`) — biblioteca compartida, no ligada a ningún proyecto ni tenant |
| `/projects/{name}/context/site` | `GET` | Redirige a `.../site/` (barra final — las páginas del sitio usan URLs relativas que la necesitan) |
| `/projects/{name}/context/site/{file_path}` | `GET` | Sirve el sitio ya construido (`<project.root_path>/site/{file_path}`) — `404` si `site_built` es `False` o si `file_path` no resuelve dentro de `site/`. Acción de solo lectura, independiente de `POST .../context` (nunca se dispara automáticamente tras un build) |


## Rutas HTTP de gestión destructiva (antes en `api/projects.md`)

### Rutas HTTP de gestión destructiva (admin)

Todas bajo `/api/projects/{name}`, solo accesibles a un rol `admin`, y todas
exigen `{"confirm": true}` en el payload y ausencia de una operación en curso
(`409` si hay un escaneo/deduplicación activo sobre el mismo proyecto):

| Ruta | Método | Descripción |
|---|---|---|
| `/impact` | `GET` | `{file_count, total_size_bytes, has_active_operation}` — resumen para la ventana modal de confirmación |
| `/clear-history` | `POST` | Llama a `ProjectHistoryCleaner.clear()` |
| `` (raíz) | `DELETE` | Llama a `ProjectRegistry.delete_project()` |
| `/move` | `POST` | `{destination_path: str, confirm: bool}` → llama a `ProjectRegistry.move_project_root()` |

## Interfaz web (antes en `guides/quick_start.md`)

```bash
pip install doc_organize[web]
python -m doc_organize web
```

Arranca en `http://127.0.0.1:8000` — en loopback, sin autenticación. Desde el
Project Selector puedes crear/abrir proyectos; en la página del proyecto
(Dashboard) gestionas las carpetas guardadas; en Escanear, escanear con
progreso en vivo y consultar el caché (dos pestañas: Escanear / Caché); en
Duplicados, buscar/resolver duplicados y consultar el histórico de
deduplicaciones (dos pestañas: Buscar duplicados / Histórico de
deduplicaciones); y descargar un export ZIP.

#### Exponer la web fuera de tu máquina

En un host no-loopback (`--host 0.0.0.0`), la web exige que los usuarios inicien
sesión. No hace falta provisionar nada por CLI de antemano: al abrir `auth.db`
por primera vez, `doc_organize` crea de fábrica el tenant `default` con un
usuario `admin`/`admin`. Esa cuenta, sin embargo, no puede completar el login
mientras el servidor esté en modo no-loopback y conserve la contraseña de
fábrica — cámbiala primero desde loopback:

```bash


# 1. En loopback (por defecto), entra con admin/admin y cambia la contraseña
python -m doc_organize web
# http://127.0.0.1:8000/login -> te redirige a /change-password tras entrar

# 2. Ahora sí, expón el servidor
python -m doc_organize web --host 0.0.0.0 --port 8000
# entra con admin / la contraseña nueva
```

Para un tenant y usuario propios (en vez de usar el de fábrica), sigue
disponible `tenant create`/`user create` por CLI, o la pantalla "Tenants y
usuarios" del panel `/admin` (solo visible para un usuario `is_instance_admin`,
como el `admin` de fábrica):

```bash
python -m doc_organize tenant create "Mi Organización"     # -> tenant_id, p.ej. "mi-organizacion"
python -m doc_organize user create alice --tenant mi-organizacion
# La contraseña se pide de forma interactiva (nunca como argumento de CLI)
```

No expongas `--host 0.0.0.0` a una red no confiable sin un proxy TLS delante —
`doc_organize` no termina TLS por sí mismo. Ver
[Acceso a la Aplicación](web-access.md) para el detalle completo del
bloqueo de la cuenta de fábrica y el resto del modelo de autenticación.

## `python -m doc_organize web` falla con "instala doc_organize[web]" (antes en `guides/troubleshooting.md`)

No tienes instalado el extra `web`. `pip install doc_organize[web]`.

## No puedo iniciar sesión en la web (host no-loopback) (antes en `guides/troubleshooting.md`)

Comprueba, en este orden:

1. ¿Estás usando `tenant_id="default"`, `username="admin"` y la contraseña de
   fábrica (`admin`)? Ese login se rechaza a propósito (`403` explícito) en
   modo no-loopback mientras esa contraseña siga sin cambiar — cambia la
   contraseña arrancando el servidor en modo loopback primero (`python -m
   doc_organize web`, sin `--host`), entra ahí, y solo entonces expón el host.
   No hace falta provisionar nada por CLI antes: ese tenant/usuario ya existen
   de fábrica.
2. ¿El `tenant_id`/usuario/contraseña son exactos? El formulario devuelve el mismo
   mensaje de error genérico tanto si el tenant no existe, el usuario está
   bloqueado, o la contraseña es incorrecta (deliberado, evita revelar cuál de
   esos motivos fue).
3. ¿El navegador acepta cookies de este origen? La sesión depende de la cookie
   `doc_organize_session` (`HttpOnly`, `SameSite=Strict`).

Ver [Acceso a la Aplicación](web-access.md) para el detalle completo.

## Cerrar sesión en una pestaña me desconecta de las demás (antes en `guides/troubleshooting.md`)

No debería — el logout es selectivo: solo invalida la sesión de la pestaña/
dispositivo desde la que se pide. Si observas lo contrario, es un bug; abre un
issue con los pasos para reproducirlo.

## Gestión destructiva de un proyecto desde la web (antes en `functional/projects.md`)

Cada fila de la lista de proyectos ofrece, únicamente a un rol `admin`, tres
acciones sobre el proyecto completo. Las tres exigen confirmación explícita
del usuario en una ventana modal que muestra primero el **impacto** (nº de
ficheros y tamaño total bajo `root_path`, vía `GET /api/projects/{name}/impact`)
antes de permitir continuar, y las tres se rechazan con `409` si hay un
escaneo o deduplicación en curso para ese proyecto (mismo bloqueo por
`(tenant_id, nombre)` que ya usan `scan_websocket`/`deduplicate_websocket`).

| Acción | Efecto | Endpoint | Reversible |
|---|---|---|---|
| **Vaciar histórico** | Borra TODO el contenido de `root_path` (caché, historial de escaneo/errores/deduplicación, carpetas guardadas, salida de conversión) y regenera `project.json`. El proyecto sigue registrado, vacío. | `POST /api/projects/{name}/clear-history` | No |
| **Eliminar proyecto** | Borra la carpeta de trabajo completa y quita el proyecto del registro. La ventana modal exige escribir el nombre exacto del proyecto para confirmar. | `DELETE /api/projects/{name}` | No — no hay papelera |
| **Mover carpeta raíz** | Mueve `root_path` entero a `<destino>/<nombre>/`, arrastrando todo su contenido (todo vive ya dentro de `root_path`). El destino se elige con el mismo explorador de carpetas del servidor. | `POST /api/projects/{name}/move` | Sí — es solo una reubicación |

Las tres rutas requieren `{"confirm": true}` en el cuerpo de la petición: la
ventana modal del cliente no es la única barrera contra una acción accidental.
