"""
Excepciones especificas de doc_organize.

Jerarquia plana sobre DocOrganizeError para permitir capturar cualquier
error de la libreria con un unico except, o discriminar por tipo cuando
se necesita.
"""


class DocOrganizeError(Exception):
    """Excepcion base para todos los errores de doc_organize."""


class InvalidPathError(DocOrganizeError):
    """La ruta indicada no existe, no es accesible o no es del tipo esperado."""


class DocumentError(DocOrganizeError):
    """Error relacionado con el descubrimiento o los metadatos de un documento."""


class ConversionError(DocOrganizeError):
    """Error durante la conversion de un documento a Markdown/JSON."""


class CacheError(DocOrganizeError):
    """Error de almacenamiento o transaccion en el cache de documentos."""


class ProjectError(DocOrganizeError):
    """Error base para operaciones de gestion de proyectos (REQ-008)."""


class ProjectNameError(ProjectError):
    """El nombre de proyecto no es valido."""


class ProjectAlreadyExistsError(ProjectError):
    """Ya existe un proyecto registrado con ese nombre (comparacion case-insensitive)."""


class ProjectNotFoundError(ProjectError):
    """No hay ningun proyecto registrado con ese nombre."""


class AuthError(DocOrganizeError):
    """Error base para autenticacion multi-usuario/multi-tenant (revision 8, §2.7.2)."""


class TenantAlreadyExistsError(AuthError):
    """Ya existe un tenant registrado con ese identificador."""


class TenantNotFoundError(AuthError):
    """No hay ningun tenant registrado con ese identificador."""


class UserAlreadyExistsError(AuthError):
    """Ya existe un usuario con ese nombre dentro del tenant."""


__all__ = [
    "DocOrganizeError",
    "InvalidPathError",
    "DocumentError",
    "ConversionError",
    "CacheError",
    "ProjectError",
    "ProjectNameError",
    "ProjectAlreadyExistsError",
    "ProjectNotFoundError",
    "AuthError",
    "TenantAlreadyExistsError",
    "TenantNotFoundError",
    "UserAlreadyExistsError",
]
