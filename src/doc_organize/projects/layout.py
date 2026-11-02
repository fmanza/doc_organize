"""Rutas de un proyecto (L-4, huecos G4/G5 de doc_organize_web).

Un proyecto tiene dos raíces:

- ``output_root``: las **salidas** que el usuario consulta (Markdown/JSON convertidos, duplicados movidos, contexto,
  sitio). Puede estar en una carpeta de red.
- ``state_root``: el **estado** interno (``cache.db`` con WAL, carpetas escaneadas, historial y errores de escaneo,
  informes de deduplicación). SQLite no es fiable sobre SMB/NFS, así que un consumidor puede ponerlo en un disco
  local. Por defecto es la misma ``output_root``: las rutas son las de siempre.

Es la única fuente de estas rutas, también para la web integrada (congelada, se retira en 1.0.0). Incluye las del
contexto de organización documental y del sitio (L-8b, G28) y los nombres que no puede usar la carpeta reorganizada
(``RESERVED_OUTPUT_FOLDER_NAMES``).

También define dónde va la salida de cada documento (``resolve_output_paths``, ``resolve_images_dir``) y su ruta
relativa a la carpeta escaneada (``relative_source_path``): sin Docling, para que un consumidor que no convierte (la
API de la web, G20) calcule las mismas rutas que ``DocumentConverter``.
"""

import re
import unicodedata

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from doc_organize.core.constants import (
    CONTEXT_FILE_NAME,
    CONVERSION_FOLDER_NAME,
    DEDUP_HISTORY_JSONL_NAME,
    DEDUP_REPORT_JSON_NAME,
    DEFAULT_CACHE_DB_NAME,
    DOMAINS_FOLDER_NAME,
    DUPLICATES_FOLDER_NAME,
    LEGACY_MKDOCS_CONFIG_NAME,
    SCAN_ERRORS_FOLDER_NAME,
    SCAN_ERRORS_HISTORY_JSONL_NAME,
    SCAN_FOLDERS_JSON_NAME,
    SCAN_HISTORY_FOLDER_NAME,
    SCAN_HISTORY_JSONL_NAME,
    SITE_CACHE_FOLDER_NAME,
    SITE_CONFIG_FILE_NAME,
    SITE_FOLDER_NAME,
    TAXONOMY_MANIFEST_FILE_NAME,
)
from doc_organize.core.exceptions import InvalidPathError
from doc_organize.core.models import Project

#: Nombre del registro de carpetas guardadas (antes privado en ``scanned_folders_store``).
SCANNED_FOLDERS_JSON_NAME = "scanned_folders.json"

#: Nombres de la raíz del proyecto que no puede usar ``Context.output_folder_name`` (se comparan sin distinguir
#: mayúsculas): la carpeta reorganizada se borra entera al reconstruir o eliminar el contexto, así que coincidir con
#: una carpeta o un fichero de otro subsistema lo pisaría (L-8b, G28).
RESERVED_OUTPUT_FOLDER_NAMES: frozenset[str] = frozenset(
    {
        CONVERSION_FOLDER_NAME,
        DUPLICATES_FOLDER_NAME,
        SCAN_ERRORS_FOLDER_NAME,
        SCAN_HISTORY_FOLDER_NAME,
        DOMAINS_FOLDER_NAME,
        SITE_FOLDER_NAME,
        SITE_CACHE_FOLDER_NAME,
        CONTEXT_FILE_NAME,
        SITE_CONFIG_FILE_NAME,
        LEGACY_MKDOCS_CONFIG_NAME,
        TAXONOMY_MANIFEST_FILE_NAME,
        DEFAULT_CACHE_DB_NAME,
        SCAN_FOLDERS_JSON_NAME,
        SCANNED_FOLDERS_JSON_NAME,
    }
)

#: Nombre simple de carpeta: letras, dígitos, ``_``, ``.``, ``-`` y espacios (sin separadores de ruta).
_OUTPUT_FOLDER_NAME_PATTERN = re.compile(r"^[\w.\- ]+$")


def _folder_key(name: str) -> str:
    """Clave de comparación: sin puntos ni espacios finales (Windows los quita), en NFC y sin mayúsculas."""
    return unicodedata.normalize("NFC", name.rstrip(" .")).casefold()


_RESERVED_KEYS = frozenset(_folder_key(reserved) for reserved in RESERVED_OUTPUT_FOLDER_NAMES)


def validate_output_folder_name(name: str) -> str:
    """Valida ``name`` como carpeta reorganizada del contexto y lo devuelve sin espacios a los lados.

    Tiene que ser un nombre simple (sin separadores de ruta, ni ``.``/``..``) y no puede coincidir, sin distinguir
    mayúsculas, con ``RESERVED_OUTPUT_FOLDER_NAMES`` (tampoco con puntos o espacios finales, que Windows quita, ni en
    otra forma Unicode).

    Raises:
        InvalidPathError: Si el nombre está vacío, no es simple o está reservado.

    Example:
        >>> validate_output_folder_name(" organizado ")
        'organizado'
        >>> validate_output_folder_name("Site")
        Traceback (most recent call last):
            ...
        doc_organize.core.exceptions.InvalidPathError: 'Site' es un nombre de carpeta reservado por el proyecto — elige otro.
    """
    candidate = name.strip()
    key = _folder_key(candidate)
    if not key or not _OUTPUT_FOLDER_NAME_PATTERN.fullmatch(candidate):
        raise InvalidPathError(f"Nombre de carpeta de salida inválido: '{name}'.")
    if key in _RESERVED_KEYS:
        raise InvalidPathError(f"'{name}' es un nombre de carpeta reservado por el proyecto — elige otro.")
    return candidate


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
        """Sitio de contexto generado (destino por defecto de ``zensical build``)."""
        return self.output_root / SITE_FOLDER_NAME

    # --- contexto y sitio (L-8b) -----------------------------------------------------------------------------------

    @property
    def context_file(self) -> Path:
        """``context.json``: metadatos del contexto y resumen de sus dominios."""
        return self.output_root / CONTEXT_FILE_NAME

    @property
    def domains_dir(self) -> Path:
        """``domains/<slug>/{DOMAIN.md,index.json}`` de cada dominio del contexto."""
        return self.output_root / DOMAINS_FOLDER_NAME

    @property
    def taxonomy_manifest_file(self) -> Path:
        """Manifiesto de taxonomía local del proyecto (``taxonomy_manifest.md``)."""
        return self.output_root / TAXONOMY_MANIFEST_FILE_NAME

    @property
    def site_config_file(self) -> Path:
        """Configuración del sitio de contexto (``zensical.toml``)."""
        return self.output_root / SITE_CONFIG_FILE_NAME

    @property
    def site_cache_dir(self) -> Path:
        """Caché que Zensical crea junto a su configuración (``.cache/``)."""
        return self.output_root / SITE_CACHE_FOLDER_NAME

    @property
    def legacy_mkdocs_config_file(self) -> Path:
        """``mkdocs.yml`` de un contexto generado antes de 0.13.0 (se borra al regenerar el sitio)."""
        return self.output_root / LEGACY_MKDOCS_CONFIG_NAME

    def reorganized_dir(self, output_folder_name: str) -> Path:
        """Carpeta reorganizada del contexto (``Context.output_folder_name``), validada con
        ``validate_output_folder_name``.

        Raises:
            InvalidPathError: Si el nombre no es simple o está reservado.

        Example:
            >>> ProjectLayout(Path("/p")).reorganized_dir("organizado").as_posix()
            '/p/organizado'
        """
        return self.output_root / validate_output_folder_name(output_folder_name)

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


def _match_scan_root(full_path: str, scan_roots: Sequence[str]) -> tuple[Path | None, tuple[str, ...]]:
    """Raíz más profunda de ``scan_roots`` de la que cuelga ``full_path`` y la ruta relativa a ella (partes)."""
    resolved = Path(full_path).resolve()
    best_root: Path | None = None
    relative_parts: tuple[str, ...] = ()
    for root in scan_roots:
        resolved_root = Path(root).resolve()
        try:
            relative = resolved.relative_to(resolved_root)
        except ValueError:
            continue
        if best_root is None or len(resolved_root.parts) > len(best_root.parts):
            best_root = resolved_root
            relative_parts = relative.parts
    return best_root, relative_parts


def resolve_output_paths(full_path: str, output_dir: Path, scan_roots: Sequence[str] = (), *, include_root_name: bool = False) -> tuple[Path, Path]:
    """Deriva ``(markdown_path, json_path)`` para el fichero fuente ``full_path`` bajo ``output_dir``.

    Determinista y basado solo en la ruta del fichero fuente (nunca en su hash). Si ``full_path`` cuelga de alguna de
    ``scan_roots`` (las carpetas indicadas al escanear; gana la más profunda), replica la jerarquía relativa a esa raíz
    bajo ``output_dir`` -- nunca la ruta absoluta completa del disco de origen: ``output_dir`` puede vivir en otra rama
    del árbol, y mezclar ahí la ruta absoluta generaba una jerarquía duplicada e inexistente (bug real: ``.docx`` con
    imágenes, ``[Errno 2]``, sesión 2026-09-05). Si ninguna raíz coincide, usa solo el ``stem`` del fichero (una carpeta
    plana bajo ``output_dir``).

    Cada segmento (carpetas intermedias y ``stem``) se sanea con ``rstrip(" .")``: Windows quita espacios y puntos
    finales de un componente solo cuando es el último de la ruta; sin sanear, ``img/<stem>/`` se creaba sin el espacio
    y al escribir ``img/<stem>/imagen.png`` se buscaba con él (``[Errno 2]``, sesión 2026-09-05).

    Args:
        full_path: Ruta del documento de origen.
        output_dir: Carpeta raíz de salida (``Conversión/``).
        scan_roots: Carpetas raíz del escaneo (``clean_paths`` de ``ScanCommand``).
        include_root_name: Antepone el nombre de la raíz a la ruta relativa (``2024/x/a.md`` en lugar de ``x/a.md``),
            para que varias raíces no colisionen (L-10c, G18). Por defecto ``False``: la ruta de siempre.

    Example:
        >>> from pathlib import Path
        >>> md, js = resolve_output_paths("/d/2024/x/a.pdf", Path("/out"), ["/d/2024"], include_root_name=True)
        >>> md.as_posix(), js.name
        ('/out/2024/x/a.md', 'a.json')
    """
    root, relative_parts = _match_scan_root(full_path, scan_roots)
    if include_root_name and root is not None and root.name:
        relative_parts = (root.name, *relative_parts)
    stem = Path(relative_parts[-1]).stem if relative_parts else Path(full_path).resolve().stem
    stem = stem.rstrip(" .")
    dir_parts = [part.rstrip(" .") for part in relative_parts[:-1]]
    target_dir = output_dir.joinpath(*dir_parts) if dir_parts else output_dir
    return target_dir / f"{stem}.md", target_dir / f"{stem}.json"


def resolve_images_dir(markdown_path: Path) -> Path:
    """Carpeta de imágenes del documento (``img/<stem>/`` junto a ``markdown_path``), la que usa ``extract_images=True``.

    Example:
        >>> from pathlib import Path
        >>> resolve_images_dir(Path("out/x/a.md")).as_posix()
        'out/x/img/a'
    """
    return markdown_path.parent / "img" / markdown_path.stem


def relative_source_path(full_path: str, scan_roots: Sequence[str] = ()) -> str:
    """Ruta de ``full_path`` relativa a la raíz de ``scan_roots`` de la que cuelga (POSIX), sin datos del servidor.

    Es el ``source_path`` del JSON de cada documento desde 0.12.0 (G23). Si no cuelga de ninguna raíz, devuelve solo
    el nombre del fichero (nunca una ruta absoluta).

    Example:
        >>> relative_source_path("/mnt/datos/2024/x/a.pdf", ["/mnt/datos/2024"])
        'x/a.pdf'
    """
    _root, relative_parts = _match_scan_root(full_path, scan_roots)
    if not relative_parts:
        return Path(full_path).name
    return PurePosixPath(*relative_parts).as_posix()


__all__ = [
    "RESERVED_OUTPUT_FOLDER_NAMES",
    "SCANNED_FOLDERS_JSON_NAME",
    "SITE_FOLDER_NAME",
    "ProjectLayout",
    "relative_source_path",
    "resolve_images_dir",
    "resolve_output_paths",
    "validate_output_folder_name",
]
