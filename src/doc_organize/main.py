"""
CLI de doc_organize: gestión de proyectos, escaneo/conversión de documentos (Fase D-1) y exportación (L-7).
"""

import argparse
import asyncio
import getpass
import sys
import warnings

from pathlib import Path
from typing import TYPE_CHECKING

from doc_organize._deprecations import web_deprecation_message
from doc_organize.core.exceptions import DocOrganizeError, InvalidPathError
from doc_organize.core.models import DedupEventType
from doc_organize.export import (
    load_cache_entries,
    load_scan_error_history,
    preview_project_zip,
    write_cache_xlsx,
    write_project_zip,
    write_scan_errors_xlsx,
)
from doc_organize.projects import ProjectLayout, ProjectRegistry
from doc_organize.scan import DeduplicationSummary, ScanCommand, ScanSummary
from doc_organize.utils.av_detector import detect_av_status
from doc_organize.utils.logging import configure_logging, get_logger

if TYPE_CHECKING:
    from doc_organize.auth import AuthStore

logger = get_logger(__name__)

_DEPRECATED_COMMANDS = frozenset({"web", "tenant", "user"})
"""Subcomandos de la web integrada, obsoletos desde 0.14.0 (L-10); se retiran en 1.0.0. `doc_organize.auth` se importa
solo dentro de ellos: los comandos de librería (`scan`, `project`, `deduplicate`, `export`) no avisan."""
_OBSOLETE = "[obsoleto] "

__all__ = ["DeduplicationSummary", "ScanCommand", "ScanSummary", "build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos del CLI de doc_organize."""
    parser = argparse.ArgumentParser(prog="python -m doc_organize", description="doc_organize CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    registry_flag = argparse.ArgumentParser(add_help=False)
    registry_flag.add_argument(
        "--registry-path",
        help="Ruta alternativa al registro de proyectos (por defecto ~/.doc_organize/projects.json)",
    )

    project_parser = subparsers.add_parser("project", help="Gestión de proyectos (REQ-008)")
    project_subparsers = project_parser.add_subparsers(dest="project_command", required=True)

    create_parser = project_subparsers.add_parser("create", help="Crear un proyecto nuevo", parents=[registry_flag])
    create_parser.add_argument("name", help="Nombre único del proyecto")
    create_parser.add_argument("--location", required=True, help="Carpeta padre donde crear el proyecto")

    project_subparsers.add_parser("list", help="Listar proyectos existentes", parents=[registry_flag])

    scan_parser = subparsers.add_parser("scan", help="Escanear, cachear y convertir documentos", parents=[registry_flag])
    scan_parser.add_argument("--paths", nargs="+", required=True, help="Carpetas de entrada a escanear")
    scan_parser.add_argument("--project", help="Nombre de un proyecto existente (REQ-008)")
    scan_parser.add_argument("--output-dir", help="Carpeta de salida de conversión (uso avanzado sin proyecto)")
    scan_parser.add_argument("--cache-file", help="Ruta a cache.db (uso avanzado sin proyecto)")
    scan_parser.add_argument("--use-ocr", action="store_true", help="Reprocesar con OCR los documentos que lo necesiten")
    scan_parser.add_argument("--use-gpu", action="store_true", help="Usar motor OCR acelerado por GPU (EasyOCR) si --use-ocr")
    scan_parser.add_argument("--force", action="store_true", help="Forzar rescan completo: vacía la caché y reconvierte todos los documentos")
    scan_parser.add_argument(
        "--include-audio-video",
        action="store_true",
        help="Incluir también audio/vídeo en el escaneo (requiere el extra [av] y el binario ffmpeg)",
    )
    scan_parser.add_argument(
        "--extract-images",
        action="store_true",
        help="Extraer las imágenes embebidas a 'img/<nombre>' junto al .md y referenciarlas, en vez del placeholder por defecto",
    )
    scan_parser.add_argument(
        "--use-picture-description",
        action="store_true",
        help="Generar descripción textual de imágenes (modelo local ligero) en el .json, solo para documentos PDF/imagen",
    )

    dedup_parser = subparsers.add_parser("deduplicate", help="Buscar y mover duplicados, a petición del usuario (REQ-005)", parents=[registry_flag])
    dedup_parser.add_argument("--paths", nargs="+", required=True, help="Carpetas de entrada a deduplicar")
    dedup_parser.add_argument("--project", help="Nombre de un proyecto existente (REQ-008)")
    dedup_parser.add_argument("--duplicates-dir", help="Carpeta de duplicados (uso avanzado sin proyecto)")

    _add_export_parser(subparsers, registry_flag)

    auth_db_flag = argparse.ArgumentParser(add_help=False)
    auth_db_flag.add_argument(
        "--auth-db-path",
        help="Ruta alternativa a la base de datos de autenticación (por defecto ~/.doc_organize/auth.db)",
    )

    templates_flag = argparse.ArgumentParser(add_help=False)
    templates_flag.add_argument(
        "--templates-path",
        help="Ruta alternativa a la biblioteca de plantillas de taxonomía (por defecto ~/.doc_organize/taxonomy_templates)",
    )

    web_parser = subparsers.add_parser(
        "web",
        help=f"{_OBSOLETE}Arrancar la interfaz web (REQ-007)",
        description=f"{_OBSOLETE}Arrancar la interfaz web (REQ-007). {web_deprecation_message("El subcomando 'web'")}",
        parents=[registry_flag, auth_db_flag, templates_flag],
    )
    web_parser.add_argument("--host", default="127.0.0.1", help="Host de bind (por defecto 127.0.0.1)")
    web_parser.add_argument("--port", type=int, default=8000, help="Puerto de bind (por defecto 8000)")

    tenant_parser = subparsers.add_parser(
        "tenant",
        help=f"{_OBSOLETE}Gestión de tenants (revisión 8, §2.7.2)",
        description=f"{_OBSOLETE}Gestión de tenants. {web_deprecation_message("El subcomando 'tenant'")}",
    )
    tenant_subparsers = tenant_parser.add_subparsers(dest="tenant_command", required=True)
    tenant_create_parser = tenant_subparsers.add_parser(
        "create", help=f"{_OBSOLETE}Crear un tenant nuevo", description=f"{_OBSOLETE}Crear un tenant nuevo.", parents=[auth_db_flag]
    )
    tenant_create_parser.add_argument("name", help="Nombre legible del tenant (el id se deriva como slug)")

    user_parser = subparsers.add_parser(
        "user",
        help=f"{_OBSOLETE}Gestión de usuarios (revisión 8, §2.7.2)",
        description=f"{_OBSOLETE}Gestión de usuarios. {web_deprecation_message("El subcomando 'user'")}",
    )
    user_subparsers = user_parser.add_subparsers(dest="user_command", required=True)
    user_create_parser = user_subparsers.add_parser(
        "create", help=f"{_OBSOLETE}Crear un usuario nuevo", description=f"{_OBSOLETE}Crear un usuario nuevo.", parents=[auth_db_flag]
    )
    user_create_parser.add_argument("--tenant", required=True, help="Id del tenant al que pertenece")
    user_create_parser.add_argument("username", help="Nombre de usuario, único dentro del tenant")

    set_instance_admin_parser = user_subparsers.add_parser(
        "set-instance-admin",
        help=f"{_OBSOLETE}Conceder o retirar is_instance_admin a un usuario existente (rediseño Tenant/Role/User)",
        description=f"{_OBSOLETE}Conceder o retirar is_instance_admin a un usuario existente.",
        parents=[auth_db_flag],
    )
    set_instance_admin_parser.add_argument("--tenant", required=True, help="Id del tenant al que pertenece el usuario")
    set_instance_admin_parser.add_argument("username", help="Nombre de usuario existente")
    set_instance_admin_parser.add_argument(
        "--revoke", action="store_true", help="Retirar is_instance_admin en vez de concederlo (por defecto se concede)"
    )

    return parser


def _add_export_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]", registry_flag: argparse.ArgumentParser) -> None:
    """`export zip | cache-xlsx | errors-xlsx` (L-7): rutas de un proyecto del registro o explícitas."""
    sources = argparse.ArgumentParser(add_help=False, parents=[registry_flag])
    sources.add_argument("--project", help="Nombre de un proyecto existente (REQ-008)")
    sources.add_argument("--output-root", help="Raíz de salidas del proyecto (contiene Conversión/), sin --project")
    sources.add_argument("--state-root", help="Raíz del estado (cache.db, errores_escaneo/, duplicados/) si no es la de salidas")
    sources.add_argument("--cache-file", nargs="+", help="Una o varias cache.db (por defecto la del proyecto)")

    export_parser = subparsers.add_parser("export", help="Exportar un proyecto: ZIP, Excel de caché o Excel de errores (L-7)")
    export_subparsers = export_parser.add_subparsers(dest="export_command", required=True)

    zip_parser = export_subparsers.add_parser("zip", help="ZIP con Conversión/, cache_export.json y DEDUP_REPORT.json (si existe)", parents=[sources])
    zip_target = zip_parser.add_mutually_exclusive_group(required=True)
    zip_target.add_argument("-o", "--output", help="Ruta del ZIP a escribir (se sobrescribe si existe)")
    zip_target.add_argument("--preview", action="store_true", help="Solo mostrar cuántos ficheros y bytes incluiría el ZIP")

    cache_parser = export_subparsers.add_parser("cache-xlsx", help="Excel con todas las entradas de la caché", parents=[sources])
    cache_parser.add_argument("-o", "--output", required=True, help="Ruta del .xlsx a escribir (se sobrescribe si existe)")

    errors_parser = export_subparsers.add_parser("errors-xlsx", help="Excel de errores de escaneo: estado actual e histórico", parents=[sources])
    errors_parser.add_argument("-o", "--output", required=True, help="Ruta del .xlsx a escribir (se sobrescribe si existe)")
    errors_parser.add_argument("--errors-log", nargs="+", help="Uno o varios SCAN_ERRORS_HISTORY.jsonl (por defecto el del proyecto)")


def _registry(args: argparse.Namespace) -> ProjectRegistry:
    registry_path = getattr(args, "registry_path", None)
    return ProjectRegistry(registry_path) if registry_path else ProjectRegistry()


def _auth_store(args: argparse.Namespace) -> "AuthStore":
    # Import diferido (L-10): solo `tenant`/`user` cargan `doc_organize.auth`; su aviso ya salió por stderr en `main()`.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from doc_organize.auth import AuthStore

    auth_db_path = getattr(args, "auth_db_path", None)
    return AuthStore(auth_db_path) if auth_db_path else AuthStore()


async def _resolve_scan_paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    """Resuelve (output_dir, cache_db, folders_json) para `scan`.

    Si se indica --project, las rutas se derivan de su carpeta raíz. Los flags
    explícitos (--output-dir, --cache-file) tienen prioridad si se combinan con
    --project (con warning), tal como especifica REQ-008. `scan` ya no
    deduplica (ver `deduplicate`, acción separada) así que no resuelve
    `duplicates_dir` — solo lo necesita `_resolve_dedup_paths`.
    """
    explicit_any = bool(args.output_dir or args.cache_file)

    if args.project:
        async with _registry(args) as registry:
            project = await registry.get_project(args.project)
        root = Path(project.root_path)
        if explicit_any:
            logger.warning("Se combinó --project con flags explícitos; los flags explícitos tienen prioridad sobre las rutas derivadas del proyecto.")
        layout = ProjectLayout(root)
        output_dir = Path(args.output_dir) if args.output_dir else layout.conversion_dir
        cache_db = Path(args.cache_file) if args.cache_file else layout.cache_db
        return output_dir, cache_db, layout.folders_json

    if not args.output_dir or not args.cache_file:
        raise DocOrganizeError("Sin --project, hay que indicar --output-dir y --cache-file explícitamente.")
    output_dir = Path(args.output_dir)
    cache_db = Path(args.cache_file)
    return output_dir, cache_db, ProjectLayout(output_dir.parent).folders_json


async def _resolve_dedup_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    """Resuelve (duplicates_dir, folders_json) para `deduplicate`.

    A diferencia de `_resolve_scan_paths`, esta acción no convierte ni cachea
    nada, así que no exige --output-dir/--cache-file cuando no hay --project:
    solo necesita saber dónde mover los duplicados.
    """
    if args.project:
        async with _registry(args) as registry:
            project = await registry.get_project(args.project)
        root = Path(project.root_path)
        if args.duplicates_dir:
            logger.warning("Se combinó --project con --duplicates-dir; el flag explícito tiene prioridad sobre la ruta derivada del proyecto.")
        layout = ProjectLayout(root)
        duplicates_dir = Path(args.duplicates_dir) if args.duplicates_dir else layout.duplicates_dir
        return duplicates_dir, layout.folders_json

    if not args.duplicates_dir:
        raise DocOrganizeError("Sin --project, hay que indicar --duplicates-dir explícitamente.")
    duplicates_dir = Path(args.duplicates_dir)
    return duplicates_dir, ProjectLayout(duplicates_dir.parent).folders_json


async def _resolve_export_layout(args: argparse.Namespace) -> ProjectLayout:
    """Rutas de `export`: las del proyecto `--project` o las de `--output-root`, con `--state-root` opcional."""
    state_root = Path(args.state_root) if args.state_root else None
    if args.project and args.output_root:
        raise DocOrganizeError("Indica --project o --output-root, no ambos.")
    if args.project:
        async with _registry(args) as registry:
            project = await registry.get_project(args.project)
        return ProjectLayout.for_project(project, state_root=state_root)
    if not args.output_root:
        raise DocOrganizeError("Indica --project o --output-root.")
    return ProjectLayout(Path(args.output_root), state_root=state_root)


async def _run_export(args: argparse.Namespace) -> int:
    layout = await _resolve_export_layout(args)
    cache_dbs = [Path(cache_file) for cache_file in args.cache_file] if args.cache_file else [layout.cache_db]
    entries = await load_cache_entries(cache_dbs)

    if args.export_command == "zip" and args.preview:
        stats = preview_project_zip(entries, layout=layout)
        print(f"El ZIP incluiría {stats.file_count} ficheros ({stats.total_size_bytes} bytes sin comprimir).")
        return 0

    output = Path(args.output)
    if not output.parent.is_dir():
        raise InvalidPathError(f"No existe la carpeta de destino '{output.parent}'.")
    if args.export_command == "zip":
        stats = write_project_zip(output, entries, layout=layout)
        print(f"ZIP escrito en '{output}': {stats.file_count} ficheros ({stats.total_size_bytes} bytes sin comprimir).")
    elif args.export_command == "cache-xlsx":
        rows = write_cache_xlsx(output, entries)
        print(f"Excel de caché escrito en '{output}': {rows} filas.")
    else:
        history_logs = [Path(log) for log in args.errors_log] if args.errors_log else [layout.scan_errors_log]
        rows = write_scan_errors_xlsx(output, entries, load_scan_error_history(history_logs))
        print(f"Excel de errores escrito en '{output}': {rows} filas.")
    return 0


async def _run_project_create(args: argparse.Namespace) -> int:
    async with _registry(args) as registry:
        project = await registry.create_project(args.name, Path(args.location))
    print(f"Proyecto creado: '{project.name}' en '{project.root_path}'")
    return 0


async def _run_tenant_create(args: argparse.Namespace) -> int:
    """Crea un tenant (revisión 8, §2.7.2). El id se deriva de `args.name` (slug).

    Rediseño Tenant/Role/User: ya NO aprovisiona automáticamente un rol ni un
    usuario admin (`Role` ya no está ligado a un tenant) — usa `user create
    --tenant <id>` a continuación, o la pantalla "Tenants y usuarios" de un
    `is_instance_admin`, para dar de alta su primer usuario.
    """
    async with _auth_store(args) as store:
        tenant = await store.create_tenant(args.name)
    print(f"Tenant creado: '{tenant.id}' ({tenant.name}), sin usuarios todavía.")
    return 0


async def _run_user_create(args: argparse.Namespace) -> int:
    """Crea un usuario dentro de `--tenant` (revisión 8, §2.7.2).

    La contraseña se pide de forma interactiva (`getpass`), nunca como argumento de
    CLI: un valor pasado como argumento queda visible en el historial de shell y en
    la lista de procesos de la máquina — mismo motivo por el que no existe
    `--api-token` (AUDIT_PLAN cond. 4, revisión 2).
    """
    password = getpass.getpass("Contraseña: ")
    async with _auth_store(args) as store:
        user = await store.create_user(args.tenant, args.username, password)
    print(f"Usuario creado: '{user.username}' en tenant '{user.tenant_id}'")
    return 0


async def _run_user_set_instance_admin(args: argparse.Namespace) -> int:
    """Concede o retira `is_instance_admin` a un usuario existente (rediseño
    Tenant/Role/User).

    Escape hatch de CLI: una instalación con varios tenants (creados con
    `tenant create` antes de esta revisión) puede quedar, tras migrar, con
    ningún `is_instance_admin` en un tenant que no sea el por defecto — sin
    este comando, la única forma de recuperarse sería editar `auth.db` a mano.
    """
    async with _auth_store(args) as store:
        users = await store.list_users(args.tenant)
        user = next((candidate for candidate in users if candidate.username.lower() == args.username.lower()), None)
        if user is None:
            raise DocOrganizeError(f"No existe ningún usuario '{args.username}' en el tenant '{args.tenant}'.")
        value = not args.revoke
        updated = await store.set_instance_admin(args.tenant, user.id, value)

    action = "concedido" if value else "retirado"
    print(f"is_instance_admin {action} para '{updated.username}' en tenant '{updated.tenant_id}'.")
    return 0


async def _run_project_list(args: argparse.Namespace) -> int:
    async with _registry(args) as registry:
        projects = await registry.list_projects()

    if not projects:
        print("No hay proyectos registrados.")
    else:
        for project in projects:
            missing = "" if Path(project.root_path).exists() else "  [carpeta no encontrada]"
            print(f"{project.name}\t{project.root_path}\t{project.created_at}{missing}")
    return 0


async def _run_scan(args: argparse.Namespace) -> int:
    if args.include_audio_video:
        # Pre-check ANTES de tocar cache_db: sin esto, un escaneo con audio/vídeo sin
        # el extra [av]/ffmpeg instalados fallaría archivo por archivo con una traza
        # críptica de docling, en vez de un mensaje claro de qué falta instalar.
        av_status = detect_av_status()
        if not av_status.ready:
            raise DocOrganizeError(av_status.instructions)

    output_dir, cache_db, folders_json = await _resolve_scan_paths(args)
    state = ProjectLayout(folders_json.parent)
    error_log_path = state.scan_errors_log
    history_log_path = state.scan_history_log
    summary = await ScanCommand().run(
        paths=args.paths,
        output_dir=output_dir,
        cache_db=cache_db,
        folders_json=folders_json,
        use_ocr=args.use_ocr,
        use_gpu=args.use_gpu,
        force=args.force,
        include_audio_video=args.include_audio_video,
        extract_images=args.extract_images,
        use_picture_description=args.use_picture_description,
        error_log_path=error_log_path,
        history_log_path=history_log_path,
    )
    print(summary.render())
    return 0


async def _run_deduplicate(args: argparse.Namespace) -> int:
    duplicates_dir, folders_json = await _resolve_dedup_paths(args)
    summary = DeduplicationSummary()
    async for event in ScanCommand().deduplicate_streaming(paths=args.paths, duplicates_dir=duplicates_dir, folders_json=folders_json):
        if event.event is DedupEventType.COMPLETED:
            summary = DeduplicationSummary(**event.data)
    print(summary.render())
    return 0


def _run_web(args: argparse.Namespace) -> int:
    """Arranca la interfaz web (REQ-007). Síncrona a propósito: uvicorn gestiona su
    propio event loop, así que no se envuelve en `asyncio.run()` como el resto de
    comandos.

    Revisión 8 (§2.7.2): ya no exige `DOC_ORGANIZE_API_TOKEN` para arrancar en un
    host no-loopback — la autenticación es multi-usuario (login usuario+contraseña
    vía `/login`), no hay un único secreto compartido que validar al inicio.
    Rediseño Tenant/Role/User: ya no hace falta aprovisionar nada por CLI antes de
    exponer el host — `AuthStore` crea de fábrica el tenant por defecto y su
    usuario `admin` en el primer arranque, pero esa cuenta no puede completar el
    login en modo no-loopback mientras conserve la contraseña de fábrica (ver
    `web/routes/auth.py::_FACTORY_ADMIN_LOCKOUT_MESSAGE`) — hay que cambiarla
    desde loopback antes de exponer el servidor de verdad.
    """
    from doc_organize.core.models import SecurityConfig

    security = SecurityConfig(bind_host=args.host, bind_port=args.port)

    try:
        import uvicorn

        # El aviso de obsolescencia ya salió por stderr en `main()` (L-10): no se repite al importar.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from doc_organize.web import create_app
    except ImportError as exc:
        raise DocOrganizeError("La interfaz web requiere el extra [web]: instala con `pip install doc_organize[web]`.") from exc

    registry_path = getattr(args, "registry_path", None)
    auth_db_path = getattr(args, "auth_db_path", None)
    templates_path = getattr(args, "templates_path", None)
    app = create_app(security=security, registry_path=registry_path, auth_db_path=auth_db_path, templates_path=templates_path)
    # ws_ping_timeout=None: un escaneo/OCR largo delega el trabajo pesado a un hilo
    # (`asyncio.to_thread`), pero ese hilo compite por el GIL con el propio event
    # loop -- si el pong tarda más de `ws_ping_timeout` (20s por defecto) en
    # procesarse, uvicorn da la conexión por muerta y la cierra él mismo aunque el
    # cliente siga ahí, apareciendo como "Cliente desconectado durante el escaneo"
    # en pleno progreso. El ping (`ws_ping_interval`, sigue en 20s) se sigue
    # enviando para no dejar el socket mudo ante NAT/firewalls intermedios; solo se
    # desactiva el cierre automático por pong tardío.
    uvicorn.run(app, host=args.host, port=args.port, ws_ping_timeout=None)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada del CLI (`python -m doc_organize ...`).

    Configura el logging de todo el proceso (consola + fichero con rotación diaria,
    ver `utils.logging.configure_logging`) antes de despachar cualquier subcomando —
    incluido `web`, que arranca el servidor sobre el mismo proceso. Es el único punto
    donde se llama a `configure_logging()`: `web.create_app()` no lo hace por su
    cuenta (es una factoría pura, reutilizable embebida en otro proceso/test sin
    imponerle esta configuración de logging global).
    """
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in _DEPRECATED_COMMANDS:
        # Por stderr, nunca por stdout (no rompe scripts que lean la salida), y una vez por ejecución (L-10).
        print(f"Aviso: {web_deprecation_message(f"El subcomando '{args.command}'")}", file=sys.stderr)

    try:
        if args.command == "project" and args.project_command == "create":
            return asyncio.run(_run_project_create(args))
        if args.command == "project" and args.project_command == "list":
            return asyncio.run(_run_project_list(args))
        if args.command == "scan":
            return asyncio.run(_run_scan(args))
        if args.command == "deduplicate":
            return asyncio.run(_run_deduplicate(args))
        if args.command == "export":
            return asyncio.run(_run_export(args))
        if args.command == "web":
            return _run_web(args)
        if args.command == "tenant" and args.tenant_command == "create":
            return asyncio.run(_run_tenant_create(args))
        if args.command == "user" and args.user_command == "create":
            return asyncio.run(_run_user_create(args))
        if args.command == "user" and args.user_command == "set-instance-admin":
            return asyncio.run(_run_user_set_instance_admin(args))
    except DocOrganizeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.error("Comando no reconocido")
    return 2


if __name__ == "__main__":
    sys.exit(main())
