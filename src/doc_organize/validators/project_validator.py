"""
Validación de nombres de proyecto (REQ-008).
"""

import unicodedata

from doc_organize.core.constants import (
    PROJECT_NAME_FORBIDDEN_CHARS,
    PROJECT_NAME_MAX_LENGTH,
    PROJECT_NAME_RESERVED_PATTERN,
)
from doc_organize.core.models import ProjectNameValidation
from doc_organize.utils.logging import get_logger


class ProjectValidator:
    """Valida nombres de proyecto: deben ser seguros en cualquier sistema de archivos.

    Sincrono a proposito, igual que FolderValidator (REQ-001): no toca disco, solo
    valida el string. Normaliza a NFC antes de validar, para evitar que acentos en
    forma decompuesta (frecuente en macOS/APFS) se traten como nombres distintos de
    su forma precompuesta.

    Attributes:
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> validator = ProjectValidator()
        >>> result = validator.validate_name("Mi Proyecto")
        >>> result.is_valid
        True
        >>> validator.validate_name("CON").is_valid
        False
    """

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    def validate_name(self, name: str) -> ProjectNameValidation:
        """Valida y normaliza `name` como nombre de proyecto.

        Args:
            name: Nombre candidato, tal como lo escribió el usuario.

        Returns:
            ProjectNameValidation con `is_valid`, `warnings` (motivo de rechazo si
            aplica) y `normalized_name` (NFC + strip, solo si `is_valid`).
        """
        normalized = unicodedata.normalize("NFC", name)
        stripped = normalized.strip()

        if not stripped:
            return self._invalid("El nombre no puede estar vacío.")

        if normalized != stripped:
            return self._invalid("El nombre no puede empezar ni terminar en espacio.")

        if len(stripped) > PROJECT_NAME_MAX_LENGTH:
            return self._invalid(f"El nombre no puede superar los {PROJECT_NAME_MAX_LENGTH} caracteres.")

        if stripped.endswith("."):
            return self._invalid("El nombre no puede terminar en punto.")

        if set(stripped) == {"."}:
            return self._invalid("El nombre no puede consistir solo en puntos.")

        if PROJECT_NAME_FORBIDDEN_CHARS.search(stripped):
            return self._invalid('El nombre contiene caracteres no permitidos: < > : " / \\ | ? * o de control.')

        if PROJECT_NAME_RESERVED_PATTERN.match(stripped):
            return self._invalid("El nombre coincide con un nombre reservado del sistema (CON, PRN, AUX, NUL, COM1-9, LPT1-9).")

        self.logger.info(f"Nombre de proyecto válido: '{stripped}'")
        return ProjectNameValidation(is_valid=True, warnings=[], normalized_name=stripped)

    @staticmethod
    def _invalid(message: str) -> ProjectNameValidation:
        return ProjectNameValidation(is_valid=False, warnings=[message], normalized_name=None)


__all__ = ["ProjectValidator"]
