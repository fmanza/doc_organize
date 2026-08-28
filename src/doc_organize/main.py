"""
CLI de doc_organize: gestión de proyectos y escaneo/conversión de documentos (Fase D-1).
"""

import argparse
import asyncio
import getpass
import sys

from pathlib import Path

from doc_organize.auth import AuthStore
from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME
from doc_organize.core.exceptions import DocOrganizeError
from doc_organize.projects import ProjectRegistry
from doc_organize.scan import ScanCommand, ScanSummary
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

__all__ = ["ScanCommand", "ScanSummary", "build_parser", "main"]


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

    scan_parser = subparsers.add_parser("scan", help="Escanear, cachear, deduplicar y convertir documentos", parents=[registry_flag])
    scan_parser.add_argument("--paths", nargs="+", required=True, help="Carpetas de entrada a escanear")
    scan_parser.add_argument("--project", help="Nombre de un proyecto existente (REQ-008)")
    scan_parser.add_argument("--output-dir", help="Carpeta de salida de conversión (uso avanzado sin proyecto)")
    scan_parser.add_argument("--cache-file", help="Ruta a cache.db (uso avanzado sin proyecto)")
    scan_parser.add_argument("--duplicates-dir", help="Carpeta de duplicados (uso avanzado sin proyecto)")
    scan_parser.add_argument("--deduplicate", action="store_true", help="Detectar y mover duplicados")
    scan_parser.add_argument("--use-ocr", action="store_true", help="Reprocesar con OCR los documentos que lo necesiten")
    scan_parser.add_argument("--use-gpu", action="store_true", help="Usar motor OCR acelerado por GPU (EasyOCR) si --use-ocr")

    auth_db_flag = argparse.ArgumentParser(add_help=False)
    auth_db_flag.add_argument(
        "--auth-db-path",
        help="Ruta alternativa a la base de datos de autenticación (por defecto ~/.doc_organize/auth.db)",
    )

    web_parser = subparsers.add_parser("web", help="Arrancar la interfaz web (REQ-007)", parents=[registry_flag, auth_db_flag])
    web_parser.add_argument("--host", default="127.0.0.1", help="Host de bind (por defecto 127.0.0.1)")
    web_parser.add_argument("--port", type=int, default=8000, help="Puerto de bind (por defecto 8000)")

    tenant_parser = subparsers.add_parser("tenant", help="Gestión de tenants (revisión 8, §2.7.2)")
    tenant_subparsers = tenant_parser.add_subparsers(dest="tenant_command", required=True)
    tenant_create_parser = tenant_subparsers.add_parser("create", help="Crear un tenant nuevo", parents=[auth_db_flag])
    tenant_create_parser.add_argument("name", help="Nombre legible del tenant (el id se deriva como slug)")

    user_parser = subparsers.add_parser("user", help="Gestión de usuarios (revisión 8, §2.7.2)")
    user_subparsers = user_parser.add_subparsers(dest="user_command", required=True)
    user_create_parser = user_subparsers.add_parser("create", help="Crear un usuario nuevo", parents=[auth_db_flag])
    user_create_parser.add_argument("--tenant", required=True, help="Id del tenant al que pertenece")
    user_create_parser.add_argument("username", help="Nombre de usuario, único dentro del tenant")

    return parser


def _registry(args: argparse.Namespace) -> ProjectRegistry:
    registry_path = getattr(args, "registry_path", None)
    return ProjectRegistry(registry_path) if registry_path else ProjectRegistry()


def _auth_store(args: argparse.Namespace) -> AuthStore:
    auth_db_path = getattr(args, "auth_db_path", None)
    return AuthStore(auth_db_path) if auth_db_path else AuthStore()


async def _resolve_scan_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    """Resuelve (output_dir, cache_db, duplicates_dir, folders_json) para `scan`.

    Si se indica --project, las rutas se derivan de su carpeta raíz. Los flags
    explícitos (--output-dir, --cache-file, --duplicates-dir) tienen prioridad si
    se combinan con --project (con warning), tal como especifica REQ-008.
    """
    explicit_any = bool(args.output_dir or args.cache_file or args.duplicates_dir)

    if args.project:
        async with _registry(args) as registry:
            project = await registry.get_project(args.project)
        root = Path(project.root_path)
        if explicit_any:
            logger.warning("Se combinó --project con flags explícitos; los flags explícitos tienen prioridad sobre las rutas derivadas del proyecto.")
        output_dir = Path(args.output_dir) if args.output_dir else root / "Conversión"
        cache_db = Path(args.cache_file) if args.cache_file else root / DEFAULT_CACHE_DB_NAME
        duplicates_dir = Path(args.duplicates_dir) if args.duplicates_dir else root / "duplicados"
        return output_dir, cache_db, duplicates_dir, root / "folders.json"

    if not args.output_dir or not args.cache_file:
        raise DocOrganizeError("Sin --project, hay que indicar --output-dir y --cache-file explícitamente.")
    output_dir = Path(args.output_dir)
    cache_db = Path(args.cache_file)
    duplicates_dir = Path(args.duplicates_dir) if args.duplicates_dir else output_dir.parent / "duplicados"
    return output_dir, cache_db, duplicates_dir, output_dir.parent / "folders.json"


async def _run_project_create(args: argparse.Namespace) -> int:
    async with _registry(args) as registry:
        project = await registry.create_project(args.name, Path(args.location))
    print(f"Proyecto creado: '{project.name}' en '{project.root_path}'")
    return 0


async def _run_tenant_create(args: argparse.Namespace) -> int:
    """Crea un tenant (revisión 8, §2.7.2). El id se deriva de `args.name` (slug)."""
    async with _auth_store(args) as store:
        tenant = await store.create_tenant(args.name)
    print(f"Tenant creado: '{tenant.id}' ({tenant.name})")
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
    output_dir, cache_db, duplicates_dir, folders_json = await _resolve_scan_paths(args)
    summary = await ScanCommand().run(
        paths=args.paths,
        output_dir=output_dir,
        cache_db=cache_db,
        duplicates_dir=duplicates_dir,
        folders_json=folders_json,
        deduplicate=args.deduplicate,
        use_ocr=args.use_ocr,
        use_gpu=args.use_gpu,
    )
    print(summary.render())
    return 0


def _run_web(args: argparse.Namespace) -> int:
    """Arranca la interfaz web (REQ-007). Síncrona a propósito: uvicorn gestiona su
    propio event loop, así que no se envuelve en `asyncio.run()` como el resto de
    comandos.

    Revisión 8 (§2.7.2): ya no exige `DOC_ORGANIZE_API_TOKEN` para arrancar en un
    host no-loopback — la autenticación es multi-usuario (login usuario+contraseña
    vía `/login`), no hay un único secreto compartido que validar al inicio. Sin
    usuarios provisionados (`tenant create`/`user create`), un host no-loopback
    simplemente queda inaccesible: nadie puede autenticarse.
    """
    from doc_organize.core.models import SecurityConfig

    security = SecurityConfig(bind_host=args.host, bind_port=args.port)

    try:
        import uvicorn

        from doc_organize.web import create_app
    except ImportError as exc:
        raise DocOrganizeError("La interfaz web requiere el extra [web]: instala con `pip install doc_organize[web]`.") from exc

    registry_path = getattr(args, "registry_path", None)
    auth_db_path = getattr(args, "auth_db_path", None)
    app = create_app(security=security, registry_path=registry_path, auth_db_path=auth_db_path)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada del CLI (`python -m doc_organize ...`)."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "project" and args.project_command == "create":
            return asyncio.run(_run_project_create(args))
        if args.command == "project" and args.project_command == "list":
            return asyncio.run(_run_project_list(args))
        if args.command == "scan":
            return asyncio.run(_run_scan(args))
        if args.command == "web":
            return _run_web(args)
        if args.command == "tenant" and args.tenant_command == "create":
            return asyncio.run(_run_tenant_create(args))
        if args.command == "user" and args.user_command == "create":
            return asyncio.run(_run_user_create(args))
    except DocOrganizeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.error("Comando no reconocido")
    return 2


if __name__ == "__main__":
    sys.exit(main())
