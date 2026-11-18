"""
Excepciones especificas de doc_organize.

Jerarquia plana sobre DocOrganizeError para permitir capturar cualquier
error de la libreria con un unico except, o discriminar por tipo cuando
se necesita.
"""


class DocOrganizeError(Exception):
    """Excepcion base para todos los errores de doc_organize."""


class OperationCancelledError(DocOrganizeError):
    """La operación se paró a petición del llamador (`CancelToken.cancel()`), entre dos documentos o grupos (L-2)."""


class MissingDependencyError(DocOrganizeError):
    """Falta una dependencia opcional: se instala con el extra indicado en `extra` (p. ej. `pip install doc_organize[export]`)."""

    def __init__(self, package: str, extra: str) -> None:
        self.package = package
        self.extra = extra
        super().__init__(f"Falta '{package}': instala el extra con `pip install doc_organize[{extra}]`.")


class InvalidPathError(DocOrganizeError):
    """La ruta indicada no existe, no es accesible o no es del tipo esperado."""


class DocumentError(DocOrganizeError):
    """Error relacionado con el descubrimiento o los metadatos de un documento."""


class ConversionError(DocOrganizeError):
    """Error durante la conversion de un documento a Markdown/JSON."""


class ModelsNotAvailableError(ConversionError):
    """Faltan modelos de Docling y las descargas están prohibidas (`allow_model_downloads=False`, L-10b).

    No es un fallo de un documento: se propaga y para la conversión.
    """


class CacheError(DocOrganizeError):
    """Error de almacenamiento o transaccion en el cache de documentos."""


class CacheNotFoundError(CacheError):
    """Se abrió una caché en solo lectura (`CacheManager(read_only=True)`) y el fichero no existe (L-10e)."""


class ProjectError(DocOrganizeError):
    """Error base para operaciones de gestion de proyectos (REQ-008)."""


class ProjectNameError(ProjectError):
    """El nombre de proyecto no es valido."""


class ProjectAlreadyExistsError(ProjectError):
    """Ya existe un proyecto registrado con ese nombre (comparacion case-insensitive)."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Ya existe un proyecto llamado '{name}'.")


class ProjectNotFoundError(ProjectError):
    """No hay ningun proyecto registrado con ese nombre.

    El mensaje se construye aqui (antes se repetia como f-string en cada
    llamador: `ProjectRegistry.get_project`/`delete_project`/`move_project_root`) para que
    las copias no
    puedan divergir entre si (AUDIT_CODE, sesión 2026-09-10 — cluster S1192
    "No existe ningún proyecto llamado").
    """

    def __init__(self, name: str) -> None:
        super().__init__(f"No existe ningún proyecto llamado '{name}'.")


class ProjectNotScannedError(ProjectError):
    """El proyecto no tiene un `folders.json` (no se ha ejecutado ningun escaneo todavia)."""


class ScannedFolderError(DocOrganizeError):
    """Error base de la lista persistente de carpetas de escaneo de un proyecto."""


class ScannedFolderNotFoundError(ScannedFolderError):
    """La carpeta indicada no esta en la lista persistente del proyecto."""


class ScannedFolderInUseError(ScannedFolderError):
    """La carpeta ya se ha usado en un escaneo; no se puede eliminar de la lista."""


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


class SiteBuildError(DocOrganizeError):
    """No se pudo construir el sitio de contexto con Zensical (L-8, G10): `zensical` no está instalado (extra
    `doc_organize[site]`), `zensical build` terminó con error o superó el tiempo indicado.

    `SiteGenerator.generate(build=True)` la lanza en lugar de devolver un sitio sin construir: la configuración
    (`zensical.toml` + `index.md`) ya está escrita cuando se lanza.

    Attributes:
        cause (str | None): Motivo en una línea, listo para mostrar: la última línea de la salida de `zensical build`
            (la del error, p. ej. `RuntimeError: ...`), o el motivo propio si no llegó a ejecutarse o se pasó de
            tiempo. Desde 1.4.0; `None` solo si zensical falló sin escribir nada.
        output_tail (str | None): Final de la salida de error de `zensical build` (como mucho 2000 caracteres), para
            diagnóstico. Desde 1.4.0; `None` si no llegó a ejecutarse o se pasó de tiempo.
    """

    def __init__(self, message: str, *, cause: str | None = None, output_tail: str | None = None) -> None:
        super().__init__(message)
        self.cause = cause
        self.output_tail = output_tail


class IncompleteConversionArtifactsError(ContextError):
    """Un documento no tiene los tres artefactos completos (original + .md + .json).

    Reservada para el paso de copia fisica a `<output_folder_name>/` (Level 2 de la
    sesion `.ai/sessions/2026-09-08-organizacion-documental-contextos/`): copiar un
    documento incompleto SI es un error a levantar (no hay que reintentar a medias).
    `DomainClassifier` (Level 1), en cambio, NO la lanza: un artefacto incompleto
    durante la clasificacion simplemente mueve el documento a "sin clasificar" sin
    interrumpir el resto del lote (ver `domain_classifier.py::read_conversion_json`).
    """


class AiError(DocOrganizeError):
    """Error base del cliente único de IA (`doc_organize.ai.LlmClient`, 2.0.0): el proxy respondió con un error."""


class AiAuthError(AiError):
    """El LiteLLM Proxy rechazó la virtual key de la tarea (HTTP 401/403): no tiene sentido seguir llamando."""


class AiConnectionError(AiError):
    """Error de red o timeout con el LiteLLM Proxy (tras los reintentos de transporte)."""


class AiResponseError(AiError):
    """La respuesta no es el JSON esperado o no cumple su esquema (también tras la caída a `json_object`)."""


class AiConfigurationError(DocOrganizeError):
    """La configuración de la IA no es válida o usa variables de entorno de 1.x, que 2.0 ya no lee (D15).

    El mensaje dice qué variable nueva usar en lugar de cada antigua, para que actualizar sin reconfigurar falle de forma
    visible y no con la IA desactivada en silencio (U17).
    """


__all__ = [
    "AiAuthError",
    "AiConfigurationError",
    "AiConnectionError",
    "AiError",
    "AiResponseError",
    "CacheError",
    "CacheNotFoundError",
    "ContextError",
    "ContextNotFoundError",
    "ConversionError",
    "DocOrganizeError",
    "DocumentError",
    "DomainNotFoundError",
    "IncompleteConversionArtifactsError",
    "InvalidPathError",
    "MissingDependencyError",
    "ModelsNotAvailableError",
    "OperationCancelledError",
    "ProjectAlreadyExistsError",
    "ProjectError",
    "ProjectNameError",
    "ProjectNotFoundError",
    "ProjectNotScannedError",
    "ScannedFolderError",
    "ScannedFolderInUseError",
    "ScannedFolderNotFoundError",
    "SiteBuildError",
    "TaxonomyManifestError",
    "TaxonomyTemplateError",
    "UsageSourceAuthError",
    "UsageSourceConnectionError",
    "UsageSourceError",
]
