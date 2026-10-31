"""Rutas de un proyecto (L-4, huecos G4/G5 de doc_organize_web).

Un proyecto tiene dos raíces:

- ``output_root``: las **salidas** que el usuario consulta (Markdown/JSON convertidos, duplicados movidos, contexto,
  sitio). Puede estar en una carpeta de red.
- ``state_root``: el **estado** interno (``cache.db`` con WAL, carpetas escaneadas, historial y errores de escaneo,
  informes de deduplicación). SQLite no es fiable sobre SMB/NFS, así que un consumidor puede ponerlo en un disco
  local. Por defecto es la misma ``output_root``: las rutas son las de siempre.

Es la única fuente de estas rutas fuera de la web integrada (congelada, se retira en 1.0.0).
"""

from dataclasses import dataclass
from pathlib import Path

from doc_organize.core.constants import (
    CONVERSION_FOLDER_NAME,
    DEDUP_HISTORY_JSONL_NAME,
    DEDUP_REPORT_JSON_NAME,
    DEFAULT_CACHE_DB_NAME,
    DUPLICATES_FOLDER_NAME,
    SCAN_ERRORS_FOLDER_NAME,
    SCAN_ERRORS_HISTORY_JSONL_NAME,
    SCAN_FOLDERS_JSON_NAME,
    SCAN_HISTORY_FOLDER_NAME,
    SCAN_HISTORY_JSONL_NAME,
)
from doc_organize.core.models import Project

#: Nombre del registro de carpetas guardadas (antes privado en ``scanned_folders_store``).
SCANNED_FOLDERS_JSON_NAME = "scanned_folders.json"
#: Carpeta del sitio de contexto generado.
SITE_FOLDER_NAME = "site"


@dataclass(frozen=True)
class ProjectLayout:
    """Todas las rutas de un proyecto a partir de su raíz de salidas y su raíz de estado.

    Example:
        >>> from pathlib import Path
        >>> layout = ProjectLayout(Path("/salidas/Proyecto"), state_root=Path("/estado/7"))
        >>> layout.conversion_dir.as_posix(), layout.cache_db.as_posix()
        ('/salidas/Proyecto/Conversión', '/estado/7/cache.db')
        >>> ProjectLayout(Path("/p")).cache_db.as_posix()
        '/p/cache.db'
    """

    output_root: Path
    state_root: Path | None = None

    @classmethod
    def for_project(cls, project: Project, *, state_root: Path | None = None) -> "ProjectLayout":
        """Rutas de ``project`` (``project.root_path`` es la raíz de salidas)."""
        return cls(Path(project.root_path), state_root=state_root)

    @property
    def state_dir(self) -> Path:
        """Raíz efectiva del estado (``state_root`` o, si no se indicó, ``output_root``)."""
        return self.state_root if self.state_root is not None else self.output_root

    @property
    def separate_state(self) -> bool:
        """Si el estado vive fuera de la raíz de salidas."""
        return self.state_root is not None and Path(self.state_root) != Path(self.output_root)

    # --- salidas -------------------------------------------------------------------------------------------------

    @property
    def conversion_dir(self) -> Path:
        """Markdown, JSON e imágenes convertidos."""
        return self.output_root / CONVERSION_FOLDER_NAME

    @property
    def duplicates_dir(self) -> Path:
        """Destino de los duplicados movidos o copiados."""
        return self.output_root / DUPLICATES_FOLDER_NAME

    @property
    def site_dir(self) -> Path:
        """Sitio de contexto generado."""
        return self.output_root / SITE_FOLDER_NAME

    # --- estado --------------------------------------------------------------------------------------------------

    @property
    def cache_db(self) -> Path:
        """Caché SQLite (WAL) de documentos convertidos."""
        return self.state_dir / DEFAULT_CACHE_DB_NAME

    @property
    def folders_json(self) -> Path:
        """Árbol de carpetas del último escaneo."""
        return self.state_dir / SCAN_FOLDERS_JSON_NAME

    @property
    def scanned_folders_json(self) -> Path:
        """Carpetas guardadas para escanear."""
        return self.state_dir / SCANNED_FOLDERS_JSON_NAME

    @property
    def scan_errors_log(self) -> Path:
        """Historial JSONL de errores de conversión."""
        return self.state_dir / SCAN_ERRORS_FOLDER_NAME / SCAN_ERRORS_HISTORY_JSONL_NAME

    @property
    def scan_history_log(self) -> Path:
        """Historial JSONL de ejecuciones de escaneo."""
        return self.state_dir / SCAN_HISTORY_FOLDER_NAME / SCAN_HISTORY_JSONL_NAME

    @property
    def dedup_report_dir(self) -> Path:
        """Carpeta de ``DEDUP_REPORT.json`` y ``DEDUP_HISTORY.jsonl``."""
        return self.state_dir / DUPLICATES_FOLDER_NAME

    @property
    def dedup_report(self) -> Path:
        """Informe de la última deduplicación."""
        return self.dedup_report_dir / DEDUP_REPORT_JSON_NAME

    @property
    def dedup_history(self) -> Path:
        """Histórico acumulado de deduplicaciones."""
        return self.dedup_report_dir / DEDUP_HISTORY_JSONL_NAME


__all__ = ["SCANNED_FOLDERS_JSON_NAME", "SITE_FOLDER_NAME", "ProjectLayout"]
