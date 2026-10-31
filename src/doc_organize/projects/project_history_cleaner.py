"""Vaciado del histórico/contenido de conversión de un proyecto (REQ-008)."""

import asyncio
import shutil

from pathlib import Path

from doc_organize.core.exceptions import ProjectError
from doc_organize.core.models import Project
from doc_organize.utils.logging import get_logger


def _remove_entry(entry: Path) -> None:
    if entry.is_dir() and not entry.is_symlink():
        shutil.rmtree(entry)
    else:
        entry.unlink()


class ProjectHistoryCleaner:
    """Vacía por completo el contenido de `<project.root_path>` (REQ-008, "vaciar histórico").

    A diferencia de `ProjectRegistry.delete_project` (que borra el proyecto
    entero, carpeta y registro incluidos), esta clase deja `root_path` vacío y
    lo reinicializa como si el proyecto se acabara de crear: se borra todo lo
    que hay dentro (caché, historial de escaneo/errores/deduplicación, carpetas
    guardadas, salida de conversión) y se regenera únicamente `project.json`. El
    registro (`projects.json`) no se toca — el proyecto sigue existiendo con el
    mismo nombre y la misma ubicación, listo para volver a escanear desde cero.

    Separada de `ProjectRegistry` a propósito: `ProjectRegistry` no conoce (ni
    debería conocer) el formato de los artefactos que escriben el escaneo, la
    deduplicación o la caché — esa responsabilidad vive aquí.

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio, tempfile
        >>> from pathlib import Path
        >>> from doc_organize.core.models import Project
        >>> async def main():
        ...     root = Path(tempfile.mkdtemp())
        ...     (root / "cache.db").write_text("x")
        ...     (root / "historial_escaneo").mkdir()
        ...     project = Project(name="Demo", root_path=str(root), created_at="2026-01-01T00:00:00+00:00")
        ...     await ProjectHistoryCleaner().clear(project)
        ...     return sorted(p.name for p in root.iterdir())
        >>> asyncio.run(main())
        ['project.json']
    """

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    async def clear(self, project: Project, *, state_root: Path | None = None) -> None:
        """Borra todo el contenido de `project.root_path` y regenera `project.json`.

        Args:
            project: Proyecto cuyo histórico se vacía.
            state_root: Raíz de estado separada del proyecto (L-5, `ProjectLayout.state_root`): su contenido
                (caché, historial, errores, informes) también se borra. Por defecto el estado vive en la propia raíz.

        Raises:
            ProjectError: Si `project.root_path` no existe, o si algún elemento
                no se pudo borrar.
        """
        root = Path(project.root_path)
        if not root.is_dir():
            raise ProjectError(f"La carpeta del proyecto no existe: {root}")

        entries = await asyncio.to_thread(list, root.iterdir())
        for entry in entries:
            try:
                await asyncio.to_thread(_remove_entry, entry)
            except OSError as exc:
                raise ProjectError(f"No se pudo eliminar '{entry}' del histórico del proyecto: {exc}") from exc

        if state_root is not None and Path(state_root).resolve() != root.resolve() and Path(state_root).is_dir():
            for entry in await asyncio.to_thread(list, Path(state_root).iterdir()):
                try:
                    await asyncio.to_thread(_remove_entry, entry)
                except OSError as exc:
                    raise ProjectError(f"No se pudo eliminar '{entry}' del estado del proyecto: {exc}") from exc

        await asyncio.to_thread(
            (root / "project.json").write_text,
            project.model_dump_json(indent=2),
            encoding="utf-8",
        )
        self.logger.info(f"Histórico del proyecto '{project.name}' vaciado por completo")


__all__ = ["ProjectHistoryCleaner"]
