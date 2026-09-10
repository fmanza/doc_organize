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


class ProjectNotScannedError(ProjectError):
    """El proyecto no tiene un `folders.json` (no se ha ejecutado ningun escaneo todavia)."""


class ScannedFolderError(DocOrganizeError):
    """Error base de la lista persistente de carpetas de escaneo de un proyecto."""


class ScannedFolderNotFoundError(ScannedFolderError):
    """La carpeta indicada no esta en la lista persistente del proyecto."""


class ScannedFolderInUseError(ScannedFolderError):
    """La carpeta ya se ha usado en un escaneo; no se puede eliminar de la lista."""


class AuthError(DocOrganizeError):
    """Error base para autenticacion multi-usuario/multi-tenant (revision 8, §2.7.2)."""


class TenantAlreadyExistsError(AuthError):
    """Ya existe un tenant registrado con ese identificador."""


class TenantNotFoundError(AuthError):
    """No hay ningun tenant registrado con ese identificador."""


class UserAlreadyExistsError(AuthError):
    """Ya existe un usuario con ese nombre dentro del tenant."""


class UserNotFoundError(AuthError):
    """No hay ningun usuario registrado con ese id dentro del tenant."""


class RoleAlreadyExistsError(AuthError):
    """Ya existe un rol con ese nombre dentro del tenant."""


class RoleNotFoundError(AuthError):
    """No hay ningun rol registrado con ese id dentro del tenant."""


class RoleInUseError(AuthError):
    """El rol no se puede eliminar: lo usan usuarios, o es el ultimo rol admin del tenant."""


class UsageSourceError(DocOrganizeError):
    """Error base para los clientes de monitorizacion de uso/coste de IA (`doc_organize.ai`, fase 2)."""


class UsageSourceAuthError(UsageSourceError):
    """La fuente de uso rechazo la credencial (API key/PAT invalida o sin permiso)."""


class UsageSourceConnectionError(UsageSourceError):
    """Error de red o timeout al consultar una fuente de uso/coste de IA."""


class ContextError(DocOrganizeError):
    """Error base para la gestion de contexto/dominios de un proyecto (organizacion documental)."""


class ContextNotFoundError(ContextError):
    """El proyecto no tiene contexto construido todavia (falta `context.json`)."""


class DomainNotFoundError(ContextError):
    """No hay ningun dominio con ese slug en el contexto del proyecto."""


class TaxonomyManifestError(ContextError):
    """`taxonomy_manifest.md` existe pero su front matter falta, no es YAML válido, o no cumple el schema de `TaxonomyManifest`."""


class TaxonomyTemplateError(ContextError):
    """El nombre de plantilla no es un slug válido, no existe ninguna plantilla con ese nombre
    (ni en `~/.doc_organize/taxonomy_templates/` ni entre las empaquetadas con `doc_organize`), o la
    plantilla existe pero su front matter falta, no es YAML válido, o no cumple el schema de
    `TaxonomyManifest` — mismos motivos que `TaxonomyManifestError`, ver `TaxonomyTemplateRegistry`."""


class IncompleteConversionArtifactsError(ContextError):
    """Un documento no tiene los tres artefactos completos (original + .md + .json).

    Reservada para el paso de copia fisica a `<output_folder_name>/` (Level 2 de la
    sesion `.ai/sessions/2026-09-08-organizacion-documental-contextos/`): copiar un
    documento incompleto SI es un error a levantar (no hay que reintentar a medias).
    `DomainClassifier` (Level 1), en cambio, NO la lanza: un artefacto incompleto
    durante la clasificacion simplemente mueve el documento a "sin clasificar" sin
    interrumpir el resto del lote (ver `domain_classifier.py::read_conversion_json`).
    """


class DomainClassificationError(DocOrganizeError):
    """Error base del cliente de clasificacion de dominios por IA (`doc_organize.ai`, Sub-fase B)."""


class DomainClassificationAuthError(DomainClassificationError):
    """El LiteLLM Proxy rechazo la virtual key de clasificacion (credencial invalida o sin permiso)."""


class DomainClassificationConnectionError(DomainClassificationError):
    """Error de red o timeout consultando el LiteLLM Proxy para clasificar un documento."""


class TaxonomyClassificationError(DocOrganizeError):
    """Error base del cliente de clasificacion combinada dominio + tipo de material por IA (`doc_organize.ai`, Sub-fase B, manifiesto de taxonomia)."""


class TaxonomyClassificationAuthError(TaxonomyClassificationError):
    """El LiteLLM Proxy rechazo la virtual key de clasificacion por manifiesto (credencial invalida o sin permiso)."""


class TaxonomyClassificationConnectionError(TaxonomyClassificationError):
    """Error de red o timeout consultando el LiteLLM Proxy para clasificar un documento por manifiesto."""


__all__ = [
    "AuthError",
    "CacheError",
    "ContextError",
    "ContextNotFoundError",
    "ConversionError",
    "DocOrganizeError",
    "DocumentError",
    "DomainClassificationAuthError",
    "DomainClassificationConnectionError",
    "DomainClassificationError",
    "DomainNotFoundError",
    "IncompleteConversionArtifactsError",
    "InvalidPathError",
    "ProjectAlreadyExistsError",
    "ProjectError",
    "ProjectNameError",
    "ProjectNotFoundError",
    "ProjectNotScannedError",
    "RoleAlreadyExistsError",
    "RoleInUseError",
    "RoleNotFoundError",
    "ScannedFolderError",
    "ScannedFolderInUseError",
    "ScannedFolderNotFoundError",
    "TaxonomyClassificationAuthError",
    "TaxonomyClassificationConnectionError",
    "TaxonomyClassificationError",
    "TaxonomyManifestError",
    "TaxonomyTemplateError",
    "TenantAlreadyExistsError",
    "TenantNotFoundError",
    "UsageSourceAuthError",
    "UsageSourceConnectionError",
    "UsageSourceError",
    "UserAlreadyExistsError",
    "UserNotFoundError",
]
