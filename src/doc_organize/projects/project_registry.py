"""
Registro local de proyectos (REQ-008).
"""

import asyncio
import json
import os
import shutil

from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from doc_organize.core.exceptions import (
    ProjectAlreadyExistsError,
    ProjectError,
    ProjectNameError,
    ProjectNotFoundError,
)
from doc_organize.core.models import Project
from doc_organize.utils.logging import get_logger
from doc_organize.utils.path_utils import safe_path_join
from doc_organize.validators.project_validator import ProjectValidator

_DEFAULT_REGISTRY_PATH = Path.home() / ".doc_organize" / "projects.json"


class ProjectRegistry:
    """Registro local de proyectos: crea, lista y abre proyectos (REQ-008).

    Vive en `~/.doc_organize/projects.json` por defecto — fuera de cualquier
    proyecto concreto, porque cada proyecto puede estar en una ubicación distinta
    elegida por el usuario. Las escrituras son poco frecuentes (crear un proyecto es
    una acción deliberada y rara, no un hot path como `cache.db`), así que un
    `asyncio.Lock` en proceso + escritura atómica (fichero temporal + `os.replace`)
    es proporcionado; si la concurrencia real desde `web/` lo exige, el mismo camino
    que `cache.json` -> SQLite (AUDIT_PLAN revisión 1) aplicaría aquí.

    Attributes:
        registry_path (Path): Ruta al fichero JSON del registro.
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio, tempfile
        >>> from pathlib import Path
        >>> async def main():
        ...     base_location = Path(tempfile.mkdtemp())
        ...     registry_path = base_location / "projects.json"
        ...     async with ProjectRegistry(registry_path) as registry:
        ...         project = await registry.create_project("Mi Proyecto", base_location)
        ...         all_projects = await registry.list_projects()
        ...         return len(all_projects)
        >>> asyncio.run(main())
        1
    """

    def __init__(self, registry_path: str | Path = _DEFAULT_REGISTRY_PATH) -> None:
        self.registry_path = Path(registry_path)
        self.logger = get_logger(__name__)
        self._validator = ProjectValidator()
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        await asyncio.to_thread(self.registry_path.parent.mkdir, parents=True, exist_ok=True)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def create_project(self, name: str, base_location: str | Path, tenant_id: str = "default") -> Project:
        """Crea un proyecto nuevo bajo `base_location` y lo registra.

        Orden de operaciones (para no dejar estado parcial): valida nombre y
        unicidad en memoria -> crea la carpeta en disco -> escribe `project.json`
        dentro -> registra en `projects.json`. Si falla después de crear la carpeta,
        se hace rollback (se borra) antes de propagar el error.

        Args:
            name: Nombre candidato del proyecto (se valida y normaliza).
            base_location: Carpeta padre, ya existente, donde crear `<name>/`.
            tenant_id: Tenant propietario (revisión 8, §2.7.2). Por defecto `"default"`
                — el tenant implícito usado por el CLI y por sesiones web sin
                autenticar (loopback); en web autenticado se resuelve siempre del
                lado servidor desde la sesión, nunca de un parámetro del cliente.
                La unicidad del nombre es por tenant, pero `root_path` sigue siendo
                `<base_location>/<name>/` sin subcarpeta de tenant: si dos tenants
                usan la misma `base_location` con el mismo nombre, la segunda
                creación falla por colisión de carpeta en disco (mismo caso que
                una carpeta preexistente no registrada), no por `ProjectAlreadyExistsError`.
                En la práctica, cada tenant usa su propia `base_location`.

        Returns:
            El `Project` creado y registrado.

        Raises:
            ProjectNameError: Si el nombre no es válido.
            ProjectAlreadyExistsError: Si ya existe un proyecto con ese nombre **en el
                mismo tenant** (case-insensitive); el mismo nombre en otro tenant no
                colisiona.
            ProjectError: Si `base_location` no existe/no es carpeta, o falla la creación.
        """
        validation = self._validator.validate_name(name)
        if not validation.is_valid or validation.normalized_name is None:
            raise ProjectNameError("; ".join(validation.warnings))
        normalized_name = validation.normalized_name

        base_path = Path(base_location)
        if not base_path.is_dir():
            raise ProjectError(f"La ubicación base no existe o no es una carpeta: {base_location}")

        async with self._lock:
            projects = await self._load()
            if any(p.name.lower() == normalized_name.lower() and p.tenant_id == tenant_id for p in projects):
                raise ProjectAlreadyExistsError(normalized_name)

            project_root = safe_path_join(base_path, normalized_name)

            try:
                await asyncio.to_thread(project_root.mkdir, parents=False, exist_ok=False)
            except FileExistsError as exc:
                raise ProjectError(f"Ya existe una carpeta en '{project_root}' (no registrada por doc_organize).") from exc
            except OSError as exc:
                raise ProjectError(f"No se pudo crear la carpeta del proyecto en '{project_root}': {exc}") from exc

            try:
                project = Project(
                    name=normalized_name,
                    root_path=str(project_root),
                    created_at=datetime.now(UTC).isoformat(),
                    tenant_id=tenant_id,
                )
                await asyncio.to_thread(
                    (project_root / "project.json").write_text,
                    project.model_dump_json(indent=2),
                    encoding="utf-8",
                )
                projects.append(project)
                await self._save(projects)
            except Exception:
                await asyncio.to_thread(shutil.rmtree, project_root, ignore_errors=True)
                raise

        self.logger.info(f"Proyecto creado: '{normalized_name}' en '{project_root}' (tenant '{tenant_id}')")
        return project

    async def list_projects(self, tenant_id: str = "default") -> list[Project]:
        """Lista los proyectos de `tenant_id` (no verifica que sus carpetas sigan existiendo)."""
        async with self._lock:
            projects = await self._load()
        return [p for p in projects if p.tenant_id == tenant_id]

    async def get_project(self, name: str, tenant_id: str = "default") -> Project:
        """Devuelve el proyecto `name` de `tenant_id` (comparación de nombre case-insensitive).

        Un proyecto de otro tenant nunca se encuentra, aunque el nombre coincida —
        mismo error que "no existe" en ambos casos, para no revelar que un proyecto
        con ese nombre existe en un tenant distinto.

        Raises:
            ProjectNotFoundError: Si no hay ningún proyecto con ese nombre en `tenant_id`.
        """
        async with self._lock:
            projects = await self._load()
        for project in projects:
            if project.name.lower() == name.lower() and project.tenant_id == tenant_id:
                return project
        raise ProjectNotFoundError(name)

    async def delete_project(self, name: str, tenant_id: str = "default") -> None:
        """Elimina `name` del registro y borra su carpeta de trabajo por completo.

        Orden de operaciones (mismo criterio que `create_project`, invertido): se
        borra primero la carpeta en disco -> si tiene éxito, se quita del registro.
        Si el borrado físico falla a mitad, el proyecto sigue registrado (y
        visible) para poder reintentarlo, en vez de desregistrar un proyecto cuya
        carpeta puede seguir ocupando espacio en disco.

        Args:
            name: Nombre del proyecto a eliminar.
            tenant_id: Tenant propietario.

        Raises:
            ProjectNotFoundError: Si no hay ningún proyecto con ese nombre en `tenant_id`.
            ProjectError: Si la carpeta del proyecto no se pudo borrar por completo.

        Example:
            >>> import asyncio, tempfile
            >>> from pathlib import Path
            >>> async def main():
            ...     base_location = Path(tempfile.mkdtemp())
            ...     async with ProjectRegistry(base_location / "projects.json") as registry:
            ...         await registry.create_project("Temporal", base_location)
            ...         await registry.delete_project("Temporal")
            ...         return await registry.list_projects()
            >>> asyncio.run(main())
            []
        """
        async with self._lock:
            projects = await self._load()
            project = next((p for p in projects if p.name.lower() == name.lower() and p.tenant_id == tenant_id), None)
            if project is None:
                raise ProjectNotFoundError(name)

            root_path = Path(project.root_path)
            if root_path.exists():
                try:
                    await asyncio.to_thread(shutil.rmtree, root_path)
                except OSError as exc:
                    raise ProjectError(f"No se pudo eliminar la carpeta del proyecto '{root_path}': {exc}") from exc

            remaining = [p for p in projects if not (p.name.lower() == name.lower() and p.tenant_id == tenant_id)]
            await self._save(remaining)

        self.logger.info(f"Proyecto eliminado: '{name}' (tenant '{tenant_id}'), carpeta '{root_path}' borrada")

    async def move_project_root(self, name: str, destination_parent: str | Path, tenant_id: str = "default") -> Project:
        """Mueve la carpeta raíz de `name` a `<destination_parent>/<name>/`.

        `destination_parent` debe ser una carpeta ya existente (la carpeta padre
        de destino, elegida por el usuario, no la ruta final) — igual que
        `base_location` en `create_project`. Usa `shutil.move`, que ya resuelve
        internamente "rename atómico si es el mismo volumen, si no copiar y
        borrar el origen" — no hace falta reimplementar esa lógica aquí.

        Si el movimiento físico tiene éxito pero no se puede persistir el
        registro actualizado, se revierte el movimiento (misma carpeta física de
        vuelta al origen) antes de propagar el error, para no dejar el registro
        apuntando a una ruta que ya no coincide con el disco.

        Args:
            name: Nombre del proyecto a mover.
            destination_parent: Carpeta padre de destino, ya existente.
            tenant_id: Tenant propietario.

        Returns:
            El `Project` actualizado, con el nuevo `root_path`.

        Raises:
            ProjectNotFoundError: Si no hay ningún proyecto con ese nombre en `tenant_id`.
            ProjectError: Si `destination_parent` no existe, si el destino ya
                contiene una carpeta con ese nombre, si la carpeta actual del
                proyecto no existe, o si el destino es la ubicación actual.

        Example:
            >>> import asyncio, tempfile
            >>> from pathlib import Path
            >>> async def main():
            ...     base_location = Path(tempfile.mkdtemp())
            ...     new_location = Path(tempfile.mkdtemp())
            ...     async with ProjectRegistry(base_location / "projects.json") as registry:
            ...         await registry.create_project("Movil", base_location)
            ...         moved = await registry.move_project_root("Movil", new_location)
            ...         return moved.root_path == str(new_location / "Movil")
            >>> asyncio.run(main())
            True
        """
        destination_base = Path(destination_parent)
        if not destination_base.is_dir():
            raise ProjectError(f"La carpeta de destino no existe o no es una carpeta: {destination_parent}")

        async with self._lock:
            projects = await self._load()
            index = next(
                (i for i, p in enumerate(projects) if p.name.lower() == name.lower() and p.tenant_id == tenant_id),
                None,
            )
            if index is None:
                raise ProjectNotFoundError(name)
            project = projects[index]

            old_root = Path(project.root_path)
            new_root = safe_path_join(destination_base, project.name)
            if new_root == old_root:
                raise ProjectError("El destino elegido es la ubicación actual del proyecto.")
            if new_root.exists():
                raise ProjectError(f"Ya existe una carpeta en el destino: {new_root}")
            if not old_root.is_dir():
                raise ProjectError(f"La carpeta actual del proyecto no existe: {old_root}")

            try:
                await asyncio.to_thread(shutil.move, str(old_root), str(new_root))
            except OSError as exc:
                raise ProjectError(f"No se pudo mover la carpeta del proyecto de '{old_root}' a '{new_root}': {exc}") from exc
            updated = project.model_copy(update={"root_path": str(new_root)})
            try:
                projects[index] = updated
                await self._save(projects)
            except Exception:
                await asyncio.to_thread(shutil.move, str(new_root), str(old_root))
                raise

        self.logger.info(f"Proyecto '{name}' movido de '{old_root}' a '{new_root}' (tenant '{tenant_id}')")
        return updated

    async def _load(self) -> list[Project]:
        if not self.registry_path.exists():
            return []
        raw = await asyncio.to_thread(self.registry_path.read_text, encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProjectError(f"El registro de proyectos está corrupto: {self.registry_path}") from exc
        return [Project(**entry) for entry in payload.get("projects", [])]

    async def _save(self, projects: list[Project]) -> None:
        payload = {"projects": [p.model_dump() for p in projects]}
        tmp_path = self.registry_path.with_suffix(".tmp")
        await asyncio.to_thread(tmp_path.write_text, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        await asyncio.to_thread(os.replace, tmp_path, self.registry_path)


__all__ = ["ProjectRegistry"]
