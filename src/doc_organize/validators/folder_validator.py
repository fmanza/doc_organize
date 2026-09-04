"""
Validacion de conjuntos de carpetas de entrada (REQ-001).
"""

from pathlib import Path

from doc_organize.core.exceptions import InvalidPathError
from doc_organize.core.models import ValidationResult
from doc_organize.utils.logging import get_logger
from doc_organize.utils.path_utils import is_subpath


class FolderValidator:
    """Valida que un conjunto de carpetas de entrada no tenga redundancia.

    Es sincrona a proposito: solo hace comprobaciones de existencia (una
    llamada `stat` por carpeta) y comparaciones de rutas en memoria, sin
    leer contenido de archivos ni hacer I/O de red — no aplica aqui la
    convencion de asyncio reservada para I/O de documentos.

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> import tempfile
        >>> base = Path(tempfile.mkdtemp())
        >>> nested = base / "docs"
        >>> _ = nested.mkdir()
        >>> validator = FolderValidator()
        >>> result = validator.validate_folder_set([str(base), str(nested)])
        >>> result.is_valid
        True
        >>> result.clean_paths == [str(base.resolve())]  # la anidada se descarta por redundante
        True
    """

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    def validate_folder_set(self, paths: list[str]) -> ValidationResult:
        """Valida que ninguna ruta de `paths` sea subcarpeta de otra.

        Args:
            paths: Rutas (absolutas o relativas) de las carpetas a validar.

        Returns:
            ValidationResult con `is_valid`, `warnings` (redundancias
            detectadas) y `clean_paths` (rutas resueltas y sin redundancia).

        Raises:
            InvalidPathError: Si alguna ruta no existe o no es una carpeta.
        """
        if not paths:
            return ValidationResult(is_valid=False, warnings=["No se proporcionaron carpetas."], clean_paths=[])

        resolved: list[tuple[str, Path]] = []
        for raw in paths:
            candidate = Path(raw).expanduser().resolve()
            if not candidate.exists():
                raise InvalidPathError(f"La carpeta no existe: {raw}")
            if not candidate.is_dir():
                raise InvalidPathError(f"La ruta no es una carpeta: {raw}")
            resolved.append((raw, candidate))

        warnings: list[str] = []
        kept: list[tuple[str, Path]] = []
        for raw, candidate in resolved:
            parent = next((kr for kr, kp in kept if is_subpath(candidate, kp)), None)
            if parent is not None:
                warnings.append(f"'{raw}' es subcarpeta de '{parent}' y se omite.")
                continue

            absorbed = [kr for kr, kp in kept if kp != candidate and is_subpath(kp, candidate)]
            for kr in absorbed:
                warnings.append(f"'{kr}' es subcarpeta de '{raw}' y se omite.")
            kept = [(kr, kp) for kr, kp in kept if kr not in absorbed]
            kept.append((raw, candidate))

        clean_paths = [str(candidate) for _, candidate in kept]
        self.logger.info(f"Validación de carpetas: {len(clean_paths)} de {len(paths)} carpetas retenidas")
        return ValidationResult(is_valid=True, warnings=warnings, clean_paths=clean_paths)


__all__ = ["FolderValidator"]
