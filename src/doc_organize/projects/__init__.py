"""Gestión de proyectos: registro, rutas y carpetas de trabajo (REQ-008, L-4)."""

from doc_organize.projects.layout import ProjectLayout
from doc_organize.projects.project_history_cleaner import ProjectHistoryCleaner
from doc_organize.projects.project_registry import ProjectRegistry
from doc_organize.projects.scanned_folders_store import ScannedFoldersStore

__all__ = ["ProjectHistoryCleaner", "ProjectLayout", "ProjectRegistry", "ScannedFoldersStore"]
