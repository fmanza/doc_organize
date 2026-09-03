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
        >>> import asyncio
        >>> from pathlib import Path
        >>> async def main():
        ...     async with ProjectRegistry() as registry:
        ...         project = await registry.create_project("Mi Proyecto", Path("/repo/workspaces"))
        ...         all_projects = await registry.list_projects()
        >>> asyncio.run(main())
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
                raise ProjectAlreadyExistsError(f"Ya existe un proyecto llamado '{normalized_name}' en este tenant.")

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
        raise ProjectNotFoundError(f"No existe ningún proyecto llamado '{name}'.")

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
