"""
Escaneo recursivo de documentos (REQ-002).
"""

import asyncio
import os
import re
import time

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import translate
from functools import cached_property, partial
from pathlib import Path
from stat import S_ISDIR, S_ISLNK
from typing import Self

from doc_organize.core.constants import AV_SUPPORTED_EXTENSIONS, IGNORED_NAMES, SUPPORTED_EXTENSIONS
from doc_organize.core.models import CacheEntry, DirectoryTree, DirectoryTreeNode, DocumentMetadata, ScanResult
from doc_organize.utils.hash_utils import hash_file
from doc_organize.utils.io_retry import retry_io, retry_io_async
from doc_organize.utils.logging import get_logger

_DEFAULT_MAX_CONCURRENT_HASHES = 8


def resolve_exclusion(path: str | Path) -> Path:
    """Ruta absoluta de una exclusión, como la ve el recorrido (G41, 1.3.0).

    Se resuelve la carpeta padre y se conserva el último tramo: así una exclusión que es un enlace o una *junction* se
    compara con la entrada del enlace (que el recorrido nunca sigue), no con su destino.
    """
    candidate = Path(path).expanduser()
    if not candidate.name:
        return candidate.resolve()
    return candidate.parent.resolve() / candidate.name


def _key(path: str | Path) -> str:
    """Clave de comparación de rutas: `os.path.normcase` (sin mayúsculas y con un solo separador en Windows)."""
    return os.path.normcase(str(path))


@dataclass(frozen=True)
class EntryFilter:
    """Qué entradas se saltan en el recorrido: `IGNORED_NAMES`, rutas excluidas y patrones de nombre (G41, 1.3.0).

    Las rutas se comparan con `normcase` sobre rutas resueltas (`resolve_exclusion`); los patrones, con `fnmatchcase`
    (`fnmatch.translate`) sobre el nombre en minúsculas, igual en cualquier sistema. Uso interno de `DocumentScanner` y `ScanCommand`.
    """

    excluded: frozenset[str] = frozenset()
    patterns: tuple[str, ...] = ()

    @classmethod
    def build(cls, exclude_paths: Iterable[str | Path] = (), ignore_patterns: Iterable[str] = ()) -> "EntryFilter":
        return cls(
            excluded=frozenset(_key(resolve_exclusion(path)) for path in exclude_paths),
            patterns=tuple(pattern.lower() for pattern in ignore_patterns),
        )

    def excludes_path(self, path: str | Path) -> bool:
        """Si `path` es una ruta excluida (no mira patrones ni `IGNORED_NAMES`)."""
        return bool(self.excluded) and _key(path) in self.excluded

    @cached_property
    def _pattern_regex(self) -> re.Pattern[str] | None:
        # Una sola expresión para todos los patrones: una comparación por entrada en vez de una por patrón.
        return re.compile("|".join(translate(pattern) for pattern in self.patterns)) if self.patterns else None

    def matches_name(self, name: str) -> bool:
        """Si `name` encaja con algún patrón (`fnmatch` sobre el nombre en minúsculas, igual en cualquier sistema)."""
        regex = self._pattern_regex
        return regex is not None and regex.match(name.lower()) is not None

    def skips(self, entry: Path) -> bool:
        """Si el recorrido debe saltarse `entry` (ni ella ni su contenido)."""
        return entry.name in IGNORED_NAMES or self.excludes_path(entry) or self.matches_name(entry.name)

    def covers_cached(self, path: str, roots: Sequence[str]) -> bool:
        """Si una ruta de la caché cae bajo una exclusión o algún tramo bajo su raíz encaja con un patrón.

        Sirve para contar sin recorrer el disco (`ScanSummary.excluded_cached`); `roots` son las carpetas escaneadas,
        ya resueltas.
        """
        key = _key(path)
        if any(key == excluded or key.startswith(excluded.rstrip(os.sep) + os.sep) for excluded in self.excluded):
            return True
        if not self.patterns:
            return False
        for root in roots:
            if key.startswith(_key(root).rstrip(os.sep) + os.sep):
                return any(self.matches_name(part) for part in Path(path).parts[len(Path(root).parts) :])
        return False


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
    hashing (evita bucles y fugas fuera de las carpetas seleccionadas); las
    *junctions* de Windows se tratan igual desde 1.1.0. Solo se resuelve la
    propia carpeta raiz indicada.

    Con `io_retries > 0` (G11, 1.1.0) listar una carpeta, leer los metadatos de
    un fichero y calcular su hash se repiten ante errores de E/S transitorios
    (`utils.io_retry`); el fichero que agota los reintentos queda en
    `ScanResult.unreadable_files` en vez de abortar la carpeta.

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

    def __init__(self, max_concurrent_hashes: int = _DEFAULT_MAX_CONCURRENT_HASHES, *, io_retries: int = 0, io_retry_backoff_s: float = 1.0) -> None:
        """Crea el escáner.

        Args:
            max_concurrent_hashes: Hashes SHA-256 calculados a la vez.
            io_retries: Reintentos ante errores de E/S transitorios (G11, 1.1.0); 0 por defecto.
            io_retry_backoff_s: Espera antes del primer reintento; se duplica en cada uno.
        """
        self.logger = get_logger(__name__)
        self._max_concurrent_hashes = max_concurrent_hashes
        self._io_retries = io_retries
        self._io_retry_backoff_s = io_retry_backoff_s

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def scan_folders(
        self,
        paths: list[str],
        include_audio_video: bool = False,
        exclude_dir: Path | None = None,
        *,
        known_entries: Mapping[str, CacheEntry] | None = None,
        exclude_paths: Sequence[str | Path] = (),
        ignore_patterns: Sequence[str] = (),
    ) -> ScanResult:
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
            known_entries: Entradas de caché por ruta (G11, 1.1.0). Si un fichero
                tiene entrada con el mismo `size_bytes` y la misma fecha de
                modificación (`timestamp`), se reutiliza su `sha256_hash` sin leer
                el fichero. `None` (por defecto): se hashea todo.
            exclude_paths: Carpetas o ficheros que no se recorren, ni ellos ni su
                contenido (G41, 1.3.0). Rutas absolutas; se resuelve su carpeta
                padre, así que un enlace excluido se compara como enlace. Una que
                no existe no es un error; una que es una de `paths` deja esa raíz
                vacía. Lo excluido no va a `unreadable_dirs`/`unreadable_files`.
            ignore_patterns: Patrones `fnmatch` sobre el nombre de cada entrada
                (fichero o carpeta, nunca la ruta), sin distinguir mayúsculas; se
                suman a `IGNORED_NAMES` (G41, 1.3.0). No se aplican a las raíces.

        Returns:
            ScanResult con la lista de documentos descubiertos (con hash
            SHA-256 ya calculado), el conteo por extension, el arbol de
            directorios y las carpetas que no se pudieron listar
            (`unreadable_dirs`, L-10d): su contenido falta de `documents`, asi
            que quien compare contra una caché no debe darlo por eliminado. Lo
            mismo con `unreadable_files` (G11): ficheros que no se pudieron leer.
        """
        start = time.monotonic()
        allowed_extensions = SUPPORTED_EXTENSIONS | AV_SUPPORTED_EXTENSIONS if include_audio_video else SUPPORTED_EXTENSIONS
        root_nodes: list[DirectoryTreeNode] = []
        discovered: list[_DiscoveredFile] = []
        unreadable_dirs: list[str] = []
        unreadable_files: dict[str, str] = {}
        entry_filter = EntryFilter.build([*([exclude_dir] if exclude_dir is not None else []), *exclude_paths], ignore_patterns)

        for raw_path in paths:
            root = Path(raw_path).expanduser().resolve()
            if entry_filter.covers_cached(str(root), ()):  # la raíz es una exclusión o cuelga de una
                root_nodes.append(DirectoryTreeNode(name=root.name or str(root), type="dir", path=str(root), children=[]))
                continue
            node, files, unreadable = await asyncio.to_thread(self._walk_sync, root, allowed_extensions, entry_filter, unreadable_files)
            root_nodes.append(node)
            discovered.extend(files)
            unreadable_dirs.extend(unreadable)

        documents = await self._hash_all(discovered, known_entries or {}, unreadable_files)

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
        return ScanResult(
            documents=documents,
            summary=summary,
            tree=tree,
            scan_duration_seconds=duration,
            unreadable_dirs=unreadable_dirs,
            unreadable_files=dict(sorted(unreadable_files.items())),
        )

    def _walk_sync(
        self,
        root: Path,
        allowed_extensions: frozenset[str],
        entry_filter: EntryFilter | None = None,
        unreadable_files: dict[str, str] | None = None,
    ) -> tuple[DirectoryTreeNode, list[_DiscoveredFile], list[str]]:
        """Recorrido sincrono de un arbol de directorios (se ejecuta en un hilo).

        Devuelve tambien las carpetas que no se pudieron listar (incluida la raiz si
        desaparecio o es inaccesible, p. ej. un montaje de red caido).
        """
        files: list[_DiscoveredFile] = []
        unreadable: list[str] = []
        node = self._build_node(root, files, allowed_extensions, entry_filter or EntryFilter(), unreadable, unreadable_files)
        if node is None:
            # Solo ocurre si la propia raiz desaparece entre la validacion previa
            # (FolderValidator) y este recorrido -- caso extremo; se degrada a un
            # nodo vacio en vez de propagar `None` (AUDIT_CODE, sesion 2026-09-03).
            self.logger.warning(f"La carpeta raíz '{root}' desapareció antes de poder escanearla.")
            node = DirectoryTreeNode(name=root.name or str(root), type="dir", path=str(root), children=[])
            unreadable.append(str(root))
        return node, files, unreadable

    def _build_node(
        self,
        path: Path,
        files: list[_DiscoveredFile],
        allowed_extensions: frozenset[str],
        entry_filter: EntryFilter,
        unreadable: list[str] | None = None,
        unreadable_files: dict[str, str] | None = None,
    ) -> DirectoryTreeNode | None:
        """Devuelve `None` si `path` desapareció entre `iterdir()` y esta llamada
        (TOCTOU: fichero borrado/movido por otra app mientras el escaneo está en
        curso) — el llamador omite ese hijo del árbol en vez de dejar que la
        excepción aborte el escaneo completo por un único fichero (AUDIT_CODE,
        sesión 2026-09-03).

        Un `lstat()` con reintentos (G11) decide si es enlace, carpeta o fichero:
        así un error de E/S no se confunde con «no es un enlace» ni «no es una
        carpeta» (hasta Python 3.13, `is_symlink()` e `is_dir()` se tragan o
        propagan ese error según la versión)."""
        extension = path.suffix.lower().lstrip(".")
        try:
            st = retry_io(path.lstat, retries=self._io_retries, backoff_s=self._io_retry_backoff_s, what=f"leer '{path}'")
        except FileNotFoundError as exc:
            self.logger.warning(f"No se pudo leer '{path}' (¿se eliminó durante el escaneo?): {exc}")
            return None
        except OSError as exc:
            self.logger.warning(f"No se pudo leer '{path}': {exc}")
            if unreadable_files is not None and extension in allowed_extensions:
                unreadable_files[str(path)] = f"No se pudieron leer sus metadatos: {exc}"
            return None
        # Una junction de Windows apunta a otra carpeta igual que un symlink: tampoco se sigue (G11, 1.1.0).
        if S_ISLNK(st.st_mode) or path.is_junction():
            return DirectoryTreeNode(name=path.name, type="file", path=str(path))
        if S_ISDIR(st.st_mode):
            return self._build_dir_node(path, files, allowed_extensions, entry_filter, unreadable, unreadable_files)
        return self._build_file_node(path, files, allowed_extensions, unreadable_files)

    def _build_dir_node(
        self,
        path: Path,
        files: list[_DiscoveredFile],
        allowed_extensions: frozenset[str],
        entry_filter: EntryFilter,
        unreadable: list[str] | None = None,
        unreadable_files: dict[str, str] | None = None,
    ) -> DirectoryTreeNode:
        children: list[DirectoryTreeNode] = []
        for entry in self._list_dir_entries(path, entry_filter, unreadable):
            child = self._build_node(entry, files, allowed_extensions, entry_filter, unreadable, unreadable_files)
            if child is not None:
                children.append(child)
        return DirectoryTreeNode(name=path.name or str(path), type="dir", path=str(path), children=children)

    def _list_dir_entries(self, path: Path, entry_filter: EntryFilter, unreadable: list[str] | None = None) -> list[Path]:
        try:
            listed = retry_io(lambda: list(path.iterdir()), retries=self._io_retries, backoff_s=self._io_retry_backoff_s, what=f"listar '{path}'")
            entries = sorted(listed, key=lambda p: p.name)
        except OSError as exc:
            # Se sigue con el resto del arbol (una subcarpeta sin permisos no debe abortar el escaneo), pero se anota:
            # sus documentos no aparecen y no deben tratarse como eliminados (L-10d, G19).
            self.logger.warning(f"No se pudo listar '{path}': {exc}")
            if unreadable is not None:
                unreadable.append(str(path))
            return []
        return [entry for entry in entries if not entry_filter.skips(entry)]

    def _build_file_node(
        self, path: Path, files: list[_DiscoveredFile], allowed_extensions: frozenset[str], unreadable_files: dict[str, str] | None = None
    ) -> DirectoryTreeNode | None:
        extension = path.suffix.lower().lstrip(".")
        try:
            stat = retry_io(path.stat, retries=self._io_retries, backoff_s=self._io_retry_backoff_s, what=f"leer '{path}'")
        except FileNotFoundError as exc:
            self.logger.warning(f"No se pudo leer '{path}' (¿se eliminó durante el escaneo?): {exc}")
            return None
        except OSError as exc:
            self.logger.warning(f"No se pudo leer '{path}': {exc}")
            if unreadable_files is not None and extension in allowed_extensions:
                unreadable_files[str(path)] = f"No se pudieron leer sus metadatos: {exc}"
            return None
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

    async def _hash_all(
        self, files: list[_DiscoveredFile], known_entries: Mapping[str, CacheEntry], unreadable_files: dict[str, str]
    ) -> list[DocumentMetadata]:
        semaphore = asyncio.Semaphore(self._max_concurrent_hashes)

        async def _hash_one(item: _DiscoveredFile) -> DocumentMetadata | None:
            known = known_entries.get(str(item.full_path))
            if known is not None and known.size_bytes == item.size_bytes and known.timestamp == item.modified_time:
                digest = known.sha256_hash
            else:
                async with semaphore:
                    try:
                        digest = await retry_io_async(
                            partial(hash_file, str(item.full_path)),
                            retries=self._io_retries,
                            backoff_s=self._io_retry_backoff_s,
                            what=f"hash de '{item.full_path}'",
                        )
                    except FileNotFoundError as exc:
                        # TOCTOU: el fichero desapareció entre el recorrido de directorios y
                        # esta fase de hashing -- se omite del resultado en vez de abortar TODO
                        # el escaneo por un único fichero (AUDIT_CODE, sesión 2026-09-03).
                        self.logger.warning(f"No se pudo calcular el hash de '{item.full_path}' (¿se eliminó durante el escaneo?): {exc}")
                        return None
                    except OSError as exc:
                        # G11: sigue ahí pero no se pudo leer (p. ej. corte de red que agotó los reintentos).
                        self.logger.warning(f"No se pudo calcular el hash de '{item.full_path}': {exc}")
                        unreadable_files[str(item.full_path)] = f"No se pudo calcular su hash: {exc}"
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
