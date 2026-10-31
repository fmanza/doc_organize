"""
Lista persistente de carpetas de escaneo por proyecto (menú Escaneo).
"""

import asyncio
import json
import os

from datetime import UTC, datetime
from pathlib import Path

from doc_organize.core.exceptions import (
    InvalidPathError,
    ProjectError,
    ScannedFolderInUseError,
    ScannedFolderNotFoundError,
)
from doc_organize.core.models import Project, ScannedFolder
from doc_organize.projects.layout import ProjectLayout
from doc_organize.utils.logging import get_logger


class ScannedFoldersStore:
    """Registro por proyecto de las carpetas añadidas para escanear (menú Escaneo).

    Vive en `<project.root_path>/scanned_folders.json`, junto al resto de estado
    propio del proyecto (`cache.db`, `folders.json`). Distinto de `folders.json`
    (escrito por `ScanCommand`, que solo guarda la última tanda de rutas
    escaneadas para que `web/routes/duplicates.py` pueda re-escanear sin
    preguntar): este fichero es una lista gestionable por el usuario desde la UI
    (añadir/eliminar) que además recuerda, de forma permanente, qué carpetas se
    han usado alguna vez en un escaneo real — una carpeta usada no se puede
    eliminar de la lista.

    Mismo patrón de concurrencia que `ProjectRegistry`: un `asyncio.Lock` en
    proceso + escritura atómica (fichero temporal + `os.replace`); las
    escrituras son poco frecuentes (añadir/eliminar una carpeta, o completar un
    escaneo), así que no hace falta más que eso.

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio, tempfile
        >>> async def main():
        ...     project = Project(name="Proyecto", root_path=tempfile.mkdtemp(), created_at="2026-01-01T00:00:00+00:00")
        ...     folder = tempfile.mkdtemp()
        ...     store = ScannedFoldersStore()
        ...     entry = await store.add_folder(project, folder)
        ...     await store.remove_folder(project, folder)
        ...     return entry.used
        >>> asyncio.run(main())
        False
    """

    def __init__(self, registry_path: Path | None = None) -> None:
        """Args:
        registry_path: Fichero del registro (L-5). Por defecto, `scanned_folders.json` en la raíz del proyecto;
            un consumidor que separa el estado pasa `ProjectLayout.scanned_folders_json`.
        """
        self.logger = get_logger(__name__)
        self._lock = asyncio.Lock()
        self._fixed_path = registry_path

    async def list_folders(self, project: Project) -> list[ScannedFolder]:
        """Lista las carpetas guardadas de `project`, más recientes primero."""
        async with self._lock:
            folders = await self._load(project)
        return sorted(folders, key=lambda f: f.added_at, reverse=True)

    async def add_folder(self, project: Project, path: str) -> ScannedFolder:
        """Añade `path` a la lista de `project` (o devuelve la entrada ya existente).

        Raises:
            InvalidPathError: Si `path` no existe o no es una carpeta.
        """
        candidate = Path(path).expanduser().resolve()
        if not candidate.is_dir():
            raise InvalidPathError(f"La carpeta no existe: {path}")
        normalized = str(candidate)

        async with self._lock:
            folders = await self._load(project)
            existing = next((f for f in folders if f.path == normalized), None)
            if existing is not None:
                return existing

            entry = ScannedFolder(path=normalized, added_at=datetime.now(UTC).isoformat(), used=False)
            folders.append(entry)
            await self._save(project, folders)
        return entry

    async def remove_folder(self, project: Project, path: str) -> None:
        """Elimina `path` de la lista de `project`.

        Raises:
            ScannedFolderNotFoundError: Si `path` no está en la lista.
            ScannedFolderInUseError: Si `path` ya se usó en un escaneo — se
                conserva como registro histórico de qué se ha escaneado.
        """
        normalized = str(Path(path).expanduser().resolve())
        async with self._lock:
            folders = await self._load(project)
            entry = next((f for f in folders if f.path == normalized), None)
            if entry is None:
                raise ScannedFolderNotFoundError(f"La carpeta no está en la lista: {path}")
            if entry.used:
                raise ScannedFolderInUseError(f"La carpeta ya se ha usado en un escaneo y no se puede eliminar: {path}")

            remaining = [f for f in folders if f.path != normalized]
            await self._save(project, remaining)

    async def mark_used(self, project: Project, paths: list[str]) -> None:
        """Marca `paths` como usadas, añadiéndolas a la lista si no estaban ya.

        Llamado por `web/routes/scan.py::scan_websocket` tras un escaneo
        correcto — cubre tanto las carpetas elegidas desde la lista persistente
        como cualquier ruta indicada por otra vía (CLI, API directa), para que
        la lista siga siendo un historial completo de lo realmente escaneado.
        """
        if not paths:
            return
        normalized = {str(Path(p).expanduser().resolve()) for p in paths}
        now = datetime.now(UTC).isoformat()

        async with self._lock:
            folders = await self._load(project)
            by_path = {f.path: f for f in folders}
            for path in normalized:
                existing = by_path.get(path)
                if existing is not None:
                    existing.used = True
                else:
                    by_path[path] = ScannedFolder(path=path, added_at=now, used=True)
            await self._save(project, list(by_path.values()))

    def _registry_path(self, project: Project) -> Path:
        if self._fixed_path is not None:
            return self._fixed_path
        return ProjectLayout.for_project(project).scanned_folders_json

    async def _load(self, project: Project) -> list[ScannedFolder]:
        registry_path = self._registry_path(project)
        if not registry_path.exists():
            return []
        raw = await asyncio.to_thread(registry_path.read_text, encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProjectError(f"La lista de carpetas de escaneo está corrupta: {registry_path}") from exc
        return [ScannedFolder(**entry) for entry in payload.get("folders", [])]

    async def _save(self, project: Project, folders: list[ScannedFolder]) -> None:
        registry_path = self._registry_path(project)
        payload = {"folders": [f.model_dump() for f in folders]}
        tmp_path = registry_path.with_suffix(".tmp")
        await asyncio.to_thread(registry_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(tmp_path.write_text, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        await asyncio.to_thread(os.replace, tmp_path, registry_path)


__all__ = ["ScannedFoldersStore"]
