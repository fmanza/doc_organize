"""
Escaneo recursivo de documentos (REQ-002).
"""

import asyncio
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Self

from doc_organize.core.constants import AV_SUPPORTED_EXTENSIONS, IGNORED_NAMES, SUPPORTED_EXTENSIONS
from doc_organize.core.models import DirectoryTree, DirectoryTreeNode, DocumentMetadata, ScanResult
from doc_organize.utils.hash_utils import hash_file
from doc_organize.utils.logging import get_logger

_DEFAULT_MAX_CONCURRENT_HASHES = 8


@dataclass
class _DiscoveredFile:
    """Representacion interna, previa al calculo de hash (hot path de escaneo)."""

    full_path: Path
    display_name: str
    extension: str
    size_bytes: int
    modified_time: float


class DocumentScanner:
    """Escanea recursivamente carpetas y descubre documentos soportados.

    El recorrido de directorios (potencialmente 10K+ entradas) se ejecuta
    en un hilo aparte via `asyncio.to_thread` para no bloquear el event
    loop; el hash SHA-256 de cada documento se calcula de forma concurrente
    (acotada por un semaforo) delegando en `utils.hash_utils.hash_file()`,
    la unica fuente de verdad de hashing del proyecto. Los symlinks no se
    seleccion: se representan como nodo opaco en el arbol, sin recursion ni
    hashing (evita bucles y fugas fuera de las carpetas seleccionadas).

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import asyncio, tempfile
        >>> from pathlib import Path
        >>> async def main():
        ...     docs_dir = Path(tempfile.mkdtemp())
        ...     (docs_dir / "informe.txt").write_text("contenido de prueba")
        ...     async with DocumentScanner() as scanner:
        ...         result = await scanner.scan_folders([str(docs_dir)])
        ...         return result.summary
        >>> asyncio.run(main())
        {'txt': 1}
    """

    def __init__(self, max_concurrent_hashes: int = _DEFAULT_MAX_CONCURRENT_HASHES) -> None:
        self.logger = get_logger(__name__)
        self._max_concurrent_hashes = max_concurrent_hashes

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def scan_folders(self, paths: list[str], include_audio_video: bool = False, exclude_dir: Path | None = None) -> ScanResult:
        """Escanea recursivamente `paths` y devuelve documentos, resumen y arbol.

        Args:
            paths: Carpetas raiz a escanear (deben existir; validarlas antes
                con FolderValidator).
            include_audio_video: Si `True`, amplia el filtro de extension con
                `AV_SUPPORTED_EXTENSIONS` ademas de `SUPPORTED_EXTENSIONS`. Por
                defecto `False`: audio/video son opt-in porque requieren el extra
                `av` (Whisper + ffmpeg) para convertirse, ver
                `doc_organize.utils.av_detector`. `txt` (y el resto de formatos
                sin dependencias extra) ya forma parte de `SUPPORTED_EXTENSIONS`,
                sin necesitar flag.
            exclude_dir: Si se indica (resuelto, absoluto), esta carpeta se omite
                por completo del recorrido (ni ella ni su contenido aparecen en
                `documents` ni en el arbol). Pensado para excluir el `output_dir`
                del propio proyecto (p.ej. "Conversión/"): si una de `paths` lo
                contiene, sin esto el escaneo redescubriria como "documentos
                nuevos" las imagenes que el propio `DocumentConverter` extrajo en
                `img/<stem>/` (`extract_images=True`), con el riesgo de que una
                reconversion posterior borre esa carpeta a mitad de escaneo
                (`shutil.rmtree` en `_write_outputs`) y el intento de "convertir"
                esa imagen falle con `FileNotFoundError`.

        Returns:
            ScanResult con la lista de documentos descubiertos (con hash
            SHA-256 ya calculado), el conteo por extension y el arbol de
            directorios.
        """
        start = time.monotonic()
        allowed_extensions = SUPPORTED_EXTENSIONS | AV_SUPPORTED_EXTENSIONS if include_audio_video else SUPPORTED_EXTENSIONS
        root_nodes: list[DirectoryTreeNode] = []
        discovered: list[_DiscoveredFile] = []

        for raw_path in paths:
            root = Path(raw_path).expanduser().resolve()
            node, files = await asyncio.to_thread(self._walk_sync, root, allowed_extensions, exclude_dir)
            root_nodes.append(node)
            discovered.extend(files)

        documents = await self._hash_all(discovered)

        summary: dict[str, int] = {}
        for doc in documents:
            summary[doc.extension] = summary.get(doc.extension, 0) + 1

        tree = DirectoryTree(
            root_name="scan",
            root_path="",
            root_node=DirectoryTreeNode(name="scan", type="dir", path="", children=root_nodes),
            total_files=len(documents),
            file_extension_counts=summary,
        )

        duration = time.monotonic() - start
        self.logger.info(f"Escaneo completado: {len(documents)} documentos en {duration:.2f}s")
        return ScanResult(documents=documents, summary=summary, tree=tree, scan_duration_seconds=duration)

    def _walk_sync(
        self, root: Path, allowed_extensions: frozenset[str], exclude_dir: Path | None = None
    ) -> tuple[DirectoryTreeNode, list[_DiscoveredFile]]:
        """Recorrido sincrono de un arbol de directorios (se ejecuta en un hilo)."""
        files: list[_DiscoveredFile] = []
        node = self._build_node(root, files, allowed_extensions, exclude_dir)
        if node is None:
            # Solo ocurre si la propia raiz desaparece entre la validacion previa
            # (FolderValidator) y este recorrido -- caso extremo; se degrada a un
            # nodo vacio en vez de propagar `None` (AUDIT_CODE, sesion 2026-09-03).
            self.logger.warning(f"La carpeta raíz '{root}' desapareció antes de poder escanearla.")
            node = DirectoryTreeNode(name=root.name or str(root), type="dir", path=str(root), children=[])
        return node, files

    def _build_node(
        self, path: Path, files: list[_DiscoveredFile], allowed_extensions: frozenset[str], exclude_dir: Path | None = None
    ) -> DirectoryTreeNode | None:
        """Devuelve `None` si `path` desapareció entre `iterdir()` y esta llamada
        (TOCTOU: fichero borrado/movido por otra app mientras el escaneo está en
        curso) — el llamador omite ese hijo del árbol en vez de dejar que la
        excepción aborte el escaneo completo por un único fichero (AUDIT_CODE,
        sesión 2026-09-03)."""
        if path.is_symlink():
            return DirectoryTreeNode(name=path.name, type="file", path=str(path))
        if path.is_dir():
            return self._build_dir_node(path, files, allowed_extensions, exclude_dir)
        return self._build_file_node(path, files, allowed_extensions)

    def _build_dir_node(
        self, path: Path, files: list[_DiscoveredFile], allowed_extensions: frozenset[str], exclude_dir: Path | None
    ) -> DirectoryTreeNode:
        children: list[DirectoryTreeNode] = []
        for entry in self._list_dir_entries(path, exclude_dir):
            child = self._build_node(entry, files, allowed_extensions, exclude_dir)
            if child is not None:
                children.append(child)
        return DirectoryTreeNode(name=path.name or str(path), type="dir", path=str(path), children=children)

    def _list_dir_entries(self, path: Path, exclude_dir: Path | None) -> list[Path]:
        try:
            entries = sorted(path.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            self.logger.warning(f"No se pudo listar '{path}': {exc}")
            return []
        return [entry for entry in entries if entry.name not in IGNORED_NAMES and entry != exclude_dir]

    def _build_file_node(self, path: Path, files: list[_DiscoveredFile], allowed_extensions: frozenset[str]) -> DirectoryTreeNode | None:
        try:
            stat = path.stat()
        except OSError as exc:
            self.logger.warning(f"No se pudo leer '{path}' (¿se eliminó durante el escaneo?): {exc}")
            return None
        extension = path.suffix.lower().lstrip(".")
        if extension in allowed_extensions:
            files.append(
                _DiscoveredFile(
                    full_path=path,
                    display_name=path.name,
                    extension=extension,
                    size_bytes=stat.st_size,
                    modified_time=stat.st_mtime,
                )
            )
        return DirectoryTreeNode(name=path.name, type="file", path=str(path), size_bytes=stat.st_size)

    async def _hash_all(self, files: list[_DiscoveredFile]) -> list[DocumentMetadata]:
        semaphore = asyncio.Semaphore(self._max_concurrent_hashes)

        async def _hash_one(item: _DiscoveredFile) -> DocumentMetadata | None:
            async with semaphore:
                try:
                    digest = await hash_file(str(item.full_path))
                except OSError as exc:
                    # TOCTOU: el fichero desapareció (o dejó de ser legible) entre
                    # el recorrido de directorios y esta fase de hashing -- se omite
                    # del resultado en vez de abortar TODO el escaneo por un único
                    # fichero (AUDIT_CODE, sesión 2026-09-03).
                    self.logger.warning(f"No se pudo calcular el hash de '{item.full_path}' (¿se eliminó durante el escaneo?): {exc}")
                    return None
            return DocumentMetadata(
                full_path=str(item.full_path),
                display_name=item.display_name,
                extension=item.extension,
                size_bytes=item.size_bytes,
                modified_time=item.modified_time,
                sha256_hash=digest,
            )

        results = await asyncio.gather(*(_hash_one(item) for item in files))
        return [doc for doc in results if doc is not None]


__all__ = ["DocumentScanner"]
