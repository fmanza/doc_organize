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
        >>> import asyncio
        >>> async def main():
        ...     async with DocumentScanner() as scanner:
        ...         result = await scanner.scan_folders(["/repo/docs"])
        ...         print(result.summary)
        >>> asyncio.run(main())
    """

    def __init__(self, max_concurrent_hashes: int = _DEFAULT_MAX_CONCURRENT_HASHES) -> None:
        self.logger = get_logger(__name__)
        self._max_concurrent_hashes = max_concurrent_hashes

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def scan_folders(self, paths: list[str], include_audio_video: bool = False) -> ScanResult:
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
            node, files = await asyncio.to_thread(self._walk_sync, root, allowed_extensions)
            root_nodes.append(node)
            discovered.extend(files)

        documents = await self._hash_all(discovered)

        summary: dict[str, int] = {}
        for doc in documents:
            summary[doc.extension] = summary.get(doc.extension, 0) + 1

        tree = DirectoryTree(
            root_name="scan",
            root_path="",
            root_node=DirectoryTreeNode(name="scan", type="dir", path="", children=root_nodes),  # pyright: ignore[reportCallIssue]
            total_files=len(documents),
            file_extension_counts=summary,
        )

        duration = time.monotonic() - start
        self.logger.info(f"Escaneo completado: {len(documents)} documentos en {duration:.2f}s")
        return ScanResult(documents=documents, summary=summary, tree=tree, scan_duration_seconds=duration)

    def _walk_sync(self, root: Path, allowed_extensions: frozenset[str]) -> tuple[DirectoryTreeNode, list[_DiscoveredFile]]:
        """Recorrido sincrono de un arbol de directorios (se ejecuta en un hilo)."""
        files: list[_DiscoveredFile] = []
        node = self._build_node(root, files, allowed_extensions)
        return node, files

    def _build_node(self, path: Path, files: list[_DiscoveredFile], allowed_extensions: frozenset[str]) -> DirectoryTreeNode:
        if path.is_symlink():
            return DirectoryTreeNode(name=path.name, type="file", path=str(path))  # pyright: ignore[reportCallIssue]

        if path.is_dir():
            children: list[DirectoryTreeNode] = []
            try:
                entries = sorted(path.iterdir(), key=lambda p: p.name)
            except OSError as exc:
                self.logger.warning(f"No se pudo listar '{path}': {exc}")
                entries = []
            for entry in entries:
                if entry.name in IGNORED_NAMES:
                    continue
                children.append(self._build_node(entry, files, allowed_extensions))
            return DirectoryTreeNode(name=path.name or str(path), type="dir", path=str(path), children=children)  # pyright: ignore[reportCallIssue]

        stat = path.stat()
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

        async def _hash_one(item: _DiscoveredFile) -> DocumentMetadata:
            async with semaphore:
                digest = await hash_file(str(item.full_path))
            return DocumentMetadata(
                full_path=str(item.full_path),
                display_name=item.display_name,
                extension=item.extension,
                size_bytes=item.size_bytes,
                modified_time=item.modified_time,
                sha256_hash=digest,
            )

        return list(await asyncio.gather(*(_hash_one(item) for item in files)))


__all__ = ["DocumentScanner"]
