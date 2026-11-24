"""
Modelos de datos base de doc_organize.

Modelos Pydantic v2 usados en todos los módulos:
- DocumentMetadata: metadatos de fichero con hash SHA-256
- ConversionResult: resultado de la conversión de un documento
- DuplicateGroup: grupo de documentos duplicados/en conflicto de versión
- DeduplicationReport: resultado de la deduplicación
- CacheEntry: entrada individual del cache en SQLite
- DirectoryTree: estructura jerárquica de directorios
- CacheExportSnapshot: exportación de solo lectura del cache para descarga ZIP
- ScanRunReport: duración de una ejecución de escaneo (histórico de tiempos)
"""

import warnings

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, field_validator, model_serializer, model_validator

from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME, UNCLASSIFIED_SLUG

# ===== Enumeraciones =====


class DocumentStatus(str, Enum):
    """Estado de un documento en el pipeline."""

    NEW = "new"
    UNCHANGED = "unchanged"
    MODIFIED = "modified"
    DELETED = "deleted"


class ConversionStatus(str, Enum):
    """Estado de progreso de la conversión."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    ERROR = "error"
    OCR_PENDING = "ocr_pending"
    OCR_IN_PROGRESS = "ocr_in_progress"


class DuplicateReason(str, Enum):
    """Motivo por el que se agrupan documentos como duplicados.

    `SAME_CONTENT` y `SEMANTIC_CONTENT_MATCH` (2.2.0) salen de `ContentDuplicateFinder`, sobre el texto ya convertido:
    el mismo texto normalizado en ficheros distintos (p. ej. un `.docx` y su `.pdf`) y un contenido parecido según los
    embeddings. Como `FUZZY_NAME_MATCH`, nunca se resuelven sin que una persona elija qué conservar.
    """

    EXACT_DUPLICATE = "exact_duplicate"
    VERSION_CONFLICT = "version_conflict"
    FUZZY_NAME_MATCH = "fuzzy_name_match"
    SAME_CONTENT = "same_content"
    SEMANTIC_CONTENT_MATCH = "semantic_content_match"


class OcrMode(str, Enum):
    """Modo de procesamiento OCR para Docling."""

    FULL_PAGE = "full_page"
    LAYOUT_REGIONS = "layout_regions"
    PDF_AWARE_LAYOUT_REGIONS = "pdf_aware_layout_regions"
    DEFAULT = "default"


class ScanEventType(str, Enum):
    """Tipo de evento de progreso emitido por `ScanCommand.run_streaming()` (Fase D-2b, §2.7.3)."""

    STARTED = "started"
    SCANNED = "scanned"
    FILE_STARTED = "file_started"
    FILE_CONVERTED = "file_converted"
    OCR_STARTED = "ocr_started"
    OCR_FILE_STARTED = "ocr_file_started"
    OCR_PROCESSED = "ocr_processed"
    COMPLETED = "completed"
    #: Parada a petición del llamador (L-2); es el último evento, en lugar de `COMPLETED`.
    CANCELLED = "cancelled"


class DedupEventType(str, Enum):
    """Tipo de evento de progreso emitido por `ScanCommand.deduplicate_streaming()`.

    Mismo criterio que `ScanEventType`: `DUPLICATES_FOUND` (tras `find_duplicates()`)
    es el análogo de `SCANNED`, y `GROUP_STARTED`/`GROUP_RESOLVED` (antes/después de
    mover cada grupo) el análogo de `FILE_STARTED`/`FILE_CONVERTED`.
    """

    STARTED = "started"
    DUPLICATES_FOUND = "duplicates_found"
    GROUP_STARTED = "group_started"
    GROUP_RESOLVED = "group_resolved"
    COMPLETED = "completed"
    #: Parada a petición del llamador (L-2); es el último evento, en lugar de `COMPLETED`.
    CANCELLED = "cancelled"


class ContextBuildEventType(str, Enum):
    """Tipo de evento de progreso emitido al construir un contexto (semáforo
    de "Reconstruir/Construir contexto"). `AI_CLASSIFYING_STARTED`/`AI_DOCUMENT_CLASSIFIED`
    solo se emiten si la Sub-fase B está activa; `REORGANIZE_STARTED` lleva el
    `total` de documentos a copiar, pero `AI_CLASSIFYING_STARTED` no (el total de la
    Sub-fase B no se conoce hasta que termina la Sub-fase A, dentro de la misma
    llamada a `ContextBuilder.build()`) — el cliente toma el `total` del primer
    `AI_DOCUMENT_CLASSIFIED` que reciba."""

    STARTED = "started"
    AI_CLASSIFYING_STARTED = "ai_classifying_started"
    AI_DOCUMENT_CLASSIFIED = "ai_document_classified"
    REORGANIZE_STARTED = "reorganize_started"
    DOCUMENT_COPIED = "document_copied"
    #: Un documento no se pudo copiar a la carpeta reorganizada (L-8a); el resto sigue. `data`: `index`, `total`,
    #: `path`, `error`.
    DOCUMENT_FAILED = "document_failed"
    #: Generación del sitio de contexto (con Zensical desde 0.13.0; el valor conserva el nombre de antes).
    MKDOCS_STARTED = "mkdocs_started"
    COMPLETED = "completed"
    #: Parada a petición del llamador (L-2); es el último evento, en lugar de `COMPLETED`.
    CANCELLED = "cancelled"


class ContextDeleteEventType(str, Enum):
    """Tipo de evento de progreso emitido al eliminar un contexto (semáforo
    de "Eliminar contexto"). Solo 3 pasos macro, sin bucles reales que reportar —
    a diferencia de `ContextBuildEventType`, no hay eventos por documento."""

    STARTED = "started"
    OUTPUT_DELETED = "output_deleted"
    SITE_DELETED = "site_deleted"
    COMPLETED = "completed"


class UsageSourceName(str, Enum):
    """Fuente que produjo un `UsageSnapshot` (monitorización de uso/coste de IA, fase 2)."""

    LITELLM = "litellm"
    GITHUB_COPILOT = "github_copilot"


class DomainStatus(str, Enum):
    """Estado de un `Domain` dentro del contexto de un proyecto (organización documental)."""

    DRAFT = "borrador"
    CONFIRMED = "confirmado"


# ===== Modelos Pydantic (API / serialización JSON) =====


class DocumentMetadata(BaseModel):
    """Metadatos de un fichero de documento descubierto."""

    full_path: str = Field(..., description="Ruta absoluta al fichero del documento")
    display_name: str = Field(..., description="Nombre para mostrar en la UI (gestiona unicidad)")
    extension: str = Field(..., description="Extensión del fichero (p. ej. 'pdf', 'docx')")
    size_bytes: int = Field(..., description="Tamaño del fichero en bytes")
    modified_time: float = Field(..., description="Timestamp Unix de la última modificación")
    sha256_hash: str = Field(..., description="Hash SHA-256 (cadena hexadecimal de 64 caracteres)")
    created_time: float | None = Field(
        default=None,
        description="Timestamp Unix de creación (`st_birthtime`, 1.5.0); None en Linux, que no la da",
    )
    mime_type: str | None = Field(default=None, description="Tipo MIME según la extensión (1.5.0); None si la extensión no es conocida")
    file_permissions: str | None = Field(default=None, description="Permisos POSIX en octal, p. ej. '644' (1.5.0); None en Windows")
    owner_name: str | None = Field(
        default=None,
        description="Cuenta propietaria (1.5.0); solo con `ScanOptions.capture_owner=True`, None si no se resuelve",
    )

    @classmethod
    def from_cache_entry(cls, entry: "CacheEntry") -> "DocumentMetadata":
        """Metadatos de un documento a partir de su entrada de caché, sin leer ni rehashear el fichero (G25, 1.1.0).

        Pensado para buscar duplicados con `DeduplicationManager.find_duplicates` desde la caché. `display_name` es
        el nombre del fichero y `extension` su sufijo en minúsculas, como los calcula `DocumentScanner`.

        Args:
            entry: Entrada guardada por un escaneo de 1.1.0 o posterior (con `size_bytes`).

        Returns:
            DocumentMetadata con el hash, el tamaño, la fecha de modificación y los metadatos de fichero de 1.5.0
            (`None` si la entrada es anterior) de la caché.

        Raises:
            ValueError: La entrada no tiene `size_bytes` (la escribió una versión anterior a 1.1.0); se rellena en el
                siguiente escaneo del documento.

        Example:
            >>> entry = CacheEntry(file_path="/repo/Informe.PDF", sha256_hash="ab" * 32, timestamp=1693152000.0,
            ...                    status=DocumentStatus.UNCHANGED, size_bytes=2048)
            >>> doc = DocumentMetadata.from_cache_entry(entry)
            >>> doc.display_name, doc.extension, doc.size_bytes
            ('Informe.PDF', 'pdf', 2048)
        """
        if entry.size_bytes is None:
            raise ValueError(f"La entrada de caché de '{entry.file_path}' no tiene tamaño (anterior a 1.1.0): vuelve a escanear")
        path = Path(entry.file_path)
        return cls(
            full_path=entry.file_path,
            display_name=path.name,
            extension=path.suffix.lower().lstrip("."),
            size_bytes=entry.size_bytes,
            modified_time=entry.timestamp,
            sha256_hash=entry.sha256_hash,
            created_time=entry.created_time,
            mime_type=entry.mime_type,
            file_permissions=entry.file_permissions,
            owner_name=entry.owner_name,
        )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "full_path": "/repo/docs/report.pdf",
                "display_name": "report.pdf",
                "extension": "pdf",
                "size_bytes": 1048576,
                "modified_time": 1693152000.0,
                "sha256_hash": "abc123def456...",
                "created_time": 1693151000.0,
                "mime_type": "application/pdf",
                "file_permissions": "644",
                "owner_name": None,
            }
        }
    )


class ConversionResult(BaseModel):
    """Resultado de convertir un único documento."""

    source_path: str = Field(..., description="Ruta al documento de origen")
    markdown_path: str | None = Field(default=None, description="Ruta al fichero .md de salida")
    json_path: str | None = Field(default=None, description="Ruta al fichero .json de metadatos de salida")
    success: bool = Field(..., description="Si la conversión tuvo éxito")
    error: str | None = Field(default=None, description="Mensaje de error si falló")
    source_sha256: str | None = Field(
        default=None,
        description=(
            "SHA-256 del original según la caché (`CacheEntry.sha256_hash`, 2.0.0): el consumidor lo pasa al construir el "
            "contexto para poder comprobar después si está al día (`check_context_freshness`); None si no se conoce"
        ),
    )
    ocr_required: bool = Field(default=False, description="Si se necesitó OCR (y quedó diferido)")
    duration_seconds: float = Field(default=0.0, description="Tiempo empleado en convertir (segundos)")
    images_dir: str | None = Field(
        default=None,
        description="Carpeta con las imágenes extraídas del documento (subcarpeta de 'img' por documento), si `extract_images=True` y el documento generó alguna",
    )
    picture_description_applied: bool = Field(
        default=False,
        description="Si `use_picture_description=True` tuvo efecto real en esta conversión (solo aplica al pipeline PDF/imagen; se ignora en silencio para el resto de formatos)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "source_path": "/repo/docs/report.pdf",
                "markdown_path": "/Conversión/docs/report.md",
                "json_path": "/Conversión/docs/report.json",
                "success": True,
                "error": None,
                "ocr_required": False,
                "duration_seconds": 2.5,
                "images_dir": None,
                "picture_description_applied": False,
            }
        }
    )


class DuplicateGroup(BaseModel):
    """Grupo de documentos identificados como duplicados o conflictos de versión."""

    group_id: str = Field(..., description="ID único de este grupo (UUID)")
    canonical_doc: DocumentMetadata = Field(..., description="Documento a conservar (canónico)")
    duplicates: list[DocumentMetadata] = Field(..., description="Documentos a descartar")
    reason: DuplicateReason = Field(..., description="Motivo por el que se agrupan")
    user_choice: DocumentMetadata | None = Field(default=None, description="Selección del usuario si sobrescribe la elección por defecto")
    similarity: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Similitud semántica del grupo (2.2.0): la menor entre sus miembros; None si no es por contenido parecido",
    )
    lexical_similarity: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Similitud de texto (Jaccard de trozos de 5 palabras, 2.2.0): la menor entre sus miembros. Alta = casi el mismo"
            " texto; baja con similitud semántica alta = reescrito o la misma plantilla con otros datos"
        ),
    )
    contained: bool = Field(
        default=False,
        description="Algún miembro está contenido en otro (2.2.0): el parecido es alto en un sentido y no en el otro",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "group_id": "550e8400-e29b-41d4-a716-446655440000",
                "canonical_doc": {
                    "full_path": "/repo/file.pdf",
                    "display_name": "file.pdf",
                    "extension": "pdf",
                    "size_bytes": 1048576,
                    "modified_time": 1693152000.0,
                    "sha256_hash": "abc123...",
                },
                "duplicates": [
                    {
                        "full_path": "/repo/file_copy.pdf",
                        "display_name": "file_copy.pdf",
                        "extension": "pdf",
                        "size_bytes": 1048576,
                        "modified_time": 1693152001.0,
                        "sha256_hash": "abc123...",
                    }
                ],
                "reason": "exact_duplicate",
                "user_choice": None,
            }
        }
    )


#: Qué hacer con los descartados de cada grupo (L-6): moverlos, copiarlos (el origen no se toca) o solo informar.
DedupMode = Literal["move", "copy", "report_only"]


class DeduplicationReport(BaseModel):
    """Resultado del proceso de deduplicación."""

    timestamp: str = Field(..., description="Timestamp ISO 8601 de cuándo se ejecutó la deduplicación")
    mode: DedupMode = Field(default="move", description="Modo aplicado: move, copy o report_only (L-6)")
    total_exact_duplicates: int = Field(..., description="Número de ficheros duplicados exactos movidos (o copiados/señalados según `mode`)")
    total_version_conflicts: int = Field(..., description="Número de conflictos de versión resueltos")
    duplicates_folder_path: str = Field(..., description="Ruta a la carpeta donde se movieron los duplicados")
    audit_json_path: str = Field(..., description="Ruta al fichero DEDUP_REPORT.json")
    groups: list[DuplicateGroup] = Field(default_factory=list, description="Grupos detallados")
    started_at: str | None = Field(
        default=None, description="Timestamp ISO 8601 de inicio de esta ejecución (None en históricos previos a este campo)"
    )
    duration_seconds: float | None = Field(
        default=None, description="Tiempo total transcurrido entre inicio y fin (None en históricos previos a este campo)"
    )
    failed_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Rutas que no se pudieron mover (permiso denegado, fichero ausente/bloqueado, "
            "colisión doble tras sufijo de hash) — no abortan el resto del lote (AUDIT_CODE, "
            "sesión 2026-09-04). Lista vacía en históricos previos a este campo."
        ),
    )


class CacheEntry(BaseModel):
    """Entrada individual en la base de datos de cache."""

    file_path: str = Field(..., description="Ruta absoluta al fichero (PK en cache.db)")
    sha256_hash: str = Field(..., description="SHA-256 del fichero")
    timestamp: float = Field(..., description="Fecha de modificación del fichero (timestamp Unix) cuando se escaneó")
    status: DocumentStatus = Field(..., description="Estado del documento (new/unchanged/modified/deleted)")
    conversion_status: ConversionStatus | None = Field(default=None, description="Estado de progreso de la conversión")
    error_message: str | None = Field(default=None, description="Mensaje de error de la última conversión fallida")
    error_retry_count: int = Field(default=0, description="Fallos consecutivos sin cambios en el fichero (0 si el último intento tuvo éxito)")
    size_bytes: int | None = Field(
        default=None, description="Tamaño del fichero en bytes cuando se escaneó (None en entradas anteriores a 1.1.0, G25)"
    )
    created_time: float | None = Field(default=None, description="`DocumentMetadata.created_time` (1.5.0; None en entradas anteriores)")
    mime_type: str | None = Field(default=None, description="`DocumentMetadata.mime_type` (1.5.0; None en entradas anteriores)")
    file_permissions: str | None = Field(default=None, description="`DocumentMetadata.file_permissions` (1.5.0; None en entradas anteriores)")
    owner_name: str | None = Field(default=None, description="`DocumentMetadata.owner_name` (1.5.0; None en entradas anteriores)")


class ScanErrorEntry(BaseModel):
    """Un documento cuya conversión/OCR falló en una ejecución de escaneo concreta."""

    file_path: str = Field(..., description="Ruta absoluta al fichero que falló")
    error_message: str = Field(..., description="Mensaje de error capturado")
    error_retry_count: int = Field(..., description="Fallos consecutivos acumulados en este fichero, incluido este")
    capped: bool = Field(
        default=False,
        description="Si el fichero alcanzó MAX_AUTO_ERROR_RETRIES y no se reintentó automáticamente en esta ejecución",
    )


class ScanErrorReport(BaseModel):
    """Errores de conversión/OCR producidos en una ejecución de `ScanCommand.run_streaming()`.

    Se persiste solo cuando `entries` no está vacío (append-only, una línea JSON por
    ejecución con errores, mismo patrón que `DEDUP_HISTORY.jsonl`): un escaneo sin
    ningún error no añade línea al histórico, para que este quede acotado a lo
    relevante para la gestión de errores en vez de crecer con cada escaneo rutinario.
    """

    scan_run_id: str = Field(..., description="Identificador único de esta ejecución de escaneo (UUID4 hex)")
    timestamp: str = Field(..., description="Timestamp ISO 8601 de finalización del escaneo")
    total_scanned: int = Field(..., description="Total de documentos escaneados en esta ejecución")
    entries: list[ScanErrorEntry] = Field(default_factory=list, description="Errores detectados en esta ejecución")


class ScanRunReport(BaseModel):
    """Duración de una ejecución de `ScanCommand.run_streaming()` (histórico de tiempos).

    Se persiste siempre (append-only, una línea JSON por ejecución, mismo patrón que
    `ScanErrorReport`), a diferencia de `ScanErrorReport` que solo se escribe si hubo
    errores: aquí el objetivo es visibilidad de cuánto tarda cada escaneo, incluidas
    ejecuciones canceladas o interrumpidas por una excepción (`completed=False`).
    """

    scan_run_id: str = Field(..., description="Identificador único de esta ejecución de escaneo (UUID4 hex)")
    started_at: str = Field(..., description="Timestamp ISO 8601 de inicio del escaneo")
    finished_at: str = Field(..., description="Timestamp ISO 8601 de fin (éxito, error o cancelación)")
    duration_seconds: float = Field(..., description="Tiempo total transcurrido entre inicio y fin")
    total_scanned: int = Field(..., description="Total de documentos escaneados en esta ejecución (0 si no llegó a escanear)")
    completed: bool = Field(..., description="Si el escaneo llegó a emitir el evento COMPLETED, o se interrumpió antes")
    discovery_duration_seconds: float | None = Field(
        default=None, description="Tiempo empleado en descubrir/hashear ficheros (None en históricos previos a este campo)"
    )
    total_conversion_seconds: float | None = Field(
        default=None,
        description="Suma de la duración de conversión de cada documento procesado, incluido OCR (None en históricos previos a este campo)",
    )


class CacheExportSnapshot(BaseModel):
    """Instantánea de solo lectura del cache para descarga/exportación."""

    export_timestamp: str = Field(..., description="Timestamp ISO 8601 de cuándo se exportó")
    total_entries: int = Field(..., description="Total de ficheros en cache")
    new_files: list[str] = Field(default_factory=list, description="Rutas de ficheros nuevos")
    modified_files: list[str] = Field(default_factory=list, description="Rutas de ficheros modificados")
    unchanged_files: list[str] = Field(default_factory=list, description="Rutas de ficheros sin cambios")
    entries: list[CacheEntry] = Field(default_factory=list, description="Todas las entradas del cache")


class DirectoryTreeNode(BaseModel):
    """Nodo individual del árbol de directorios (fichero o carpeta)."""

    name: str = Field(..., description="Nombre del fichero o carpeta")
    type: str = Field(..., description="'file' o 'dir'")
    path: str = Field(..., description="Ruta relativa o absoluta")
    size_bytes: int | None = Field(default=None, description="Tamaño del fichero (si type='file')")
    children: list["DirectoryTreeNode"] = Field(default_factory=list, description="Nodos hijos (si type='dir')")


DirectoryTreeNode.model_rebuild()  # Necesario para un modelo autorreferencial


class DirectoryTree(BaseModel):
    """Estructura jerárquica de directorios obtenida del escaneo."""

    root_name: str = Field(..., description="Nombre del directorio raíz")
    root_path: str = Field(..., description="Ruta absoluta de la raíz")
    root_node: DirectoryTreeNode = Field(..., description="Estructura de árbol con raíz aquí")
    total_files: int = Field(..., description="Número de ficheros encontrados")
    file_extension_counts: dict[str, int] = Field(default_factory=dict, description="Conteo por extensión")


class ScanResult(BaseModel):
    """Resultado de escanear carpetas en busca de documentos."""

    documents: list[DocumentMetadata] = Field(..., description="Todos los documentos encontrados")
    summary: dict[str, int] = Field(..., description="Conteo de ficheros por extensión")
    tree: DirectoryTree = Field(..., description="Estructura de directorios")
    scan_duration_seconds: float = Field(..., description="Tiempo empleado en completar el escaneo")
    unreadable_dirs: list[str] = Field(
        default_factory=list,
        description="Carpetas que no se pudieron listar (permiso denegado, montaje caído); su contenido falta de `documents`",
    )
    unreadable_files: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Ficheros descubiertos que no se pudieron leer tras agotar los reintentos (ruta → error, G11, 1.1.0); faltan "
            "de `documents` pero no han desaparecido. Un fichero borrado durante el escaneo no aparece aquí"
        ),
    )


#: Versión del esquema de los eventos de progreso (L-6b). Sube cuando cambian los campos de `to_dict()` o el
#: significado de un tipo de evento; añadir un tipo de evento nuevo no la cambia.
EVENT_SCHEMA_VERSION: Final = 1


class VersionedEvent(BaseModel):
    """Base de los eventos de progreso con esquema versionado (L-6b, hueco G7 de doc_organize_web).

    `to_dict()` es la forma estable para serializar un evento (JSON, SSE, ficheros): `{"schema_version", "event",
    "data"}`, con `event` como su valor de texto y `data` en tipos JSON.

    Example:
        >>> ScanEvent(event=ScanEventType.STARTED).to_dict()
        {'schema_version': 1, 'event': 'started', 'data': {}}
    """

    schema_version: Literal[1] = Field(default=EVENT_SCHEMA_VERSION, description="Versión del esquema del evento")

    def to_dict(self) -> dict[str, Any]:
        """Representación estable y serializable en JSON."""
        dumped = self.model_dump(mode="json")
        return {"schema_version": dumped["schema_version"], "event": dumped["event"], "data": dumped["data"]}


#: Longitud máxima de un patrón de `ScanOptions.ignore_patterns` (G41, 1.3.0).
MAX_IGNORE_PATTERN_LENGTH: Final = 64


class ScanOptions(BaseModel):
    """Opciones de un escaneo (G13): sustituyen a los indicadores sueltos de `ScanCommand.run`/`run_streaming`.

    Pasarlas con `options=ScanOptions(...)` evita desordenar argumentos posicionales del mismo tipo.

    Example:
        >>> ScanOptions(use_ocr=True).use_gpu
        False
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    use_ocr: bool = Field(default=True, description="Aplicar OCR a imágenes y PDF escaneados")
    use_gpu: bool = Field(default=False, description="Usar la GPU para el OCR si está disponible")
    force: bool = Field(default=False, description="Ignorar la caché y reconvertirlo todo")
    include_audio_video: bool = Field(default=False, description="Incluir audio y vídeo (requiere el extra `av`)")
    extract_images: bool = Field(default=False, description="Extraer las imágenes de los documentos")
    use_picture_description: bool = Field(default=False, description="Describir las imágenes con un modelo de visión")
    cache_save_every: int = Field(default=20, ge=0, description="Guardar la caché cada N documentos convertidos (0: no)")
    cache_save_seconds: float = Field(default=30.0, ge=0, description="Guardar la caché cada X segundos de conversión (0: no)")
    artifacts_path: Path | None = Field(default=None, description="Carpeta de modelos de Docling (sin ella, Docling los descarga)")
    allow_model_downloads: bool = Field(
        default=True, description="Permitir que Docling descargue modelos; con `False` falta un modelo → `ModelsNotAvailableError`"
    )
    root_name_in_output: bool = Field(default=False, description="Incluir el nombre de la carpeta escaneada en la ruta de salida")
    json_source_path: Literal["relative", "absolute"] = Field(
        default="relative", description="`source_path` del JSON de cada documento: relativo a la carpeta escaneada o absoluto"
    )
    max_documents: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Parar de forma ordenada tras N conversiones de Docling (primera pasada y OCR cuentan por separado); "
            "lo pendiente sigue en la llamada siguiente (G38, 1.1.0). None: sin límite"
        ),
    )
    document_timeout_s: float | None = Field(
        default=None, gt=0, description="Segundos máximos por documento y pasada; el que los supera queda en error (G11). None: sin límite"
    )
    io_retries: int = Field(
        default=0, ge=0, description="Reintentos ante errores de E/S transitorios al listar, leer, hashear y copiar (G11). 0: ninguno"
    )
    io_retry_backoff_s: float = Field(default=1.0, ge=0, description="Espera antes del primer reintento de E/S; se duplica en cada reintento (G11)")
    reuse_unchanged_hashes: bool = Field(
        default=False,
        description=(
            "No rehashear un fichero cuyo tamaño y fecha de modificación coinciden con la caché: se reutiliza su hash (G11). "
            "No detecta un cambio que conserve tamaño y fecha"
        ),
    )
    capture_owner: bool = Field(
        default=False,
        description=(
            "Guardar la cuenta propietaria de cada documento en `DocumentMetadata.owner_name` y en la caché (1.5.0). "
            "Desactivado por defecto: es un dato personal y en Windows cuesta una llamada al sistema por fichero"
        ),
    )
    exclude_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Carpetas o ficheros (rutas absolutas) que no se recorren, ni ellos ni su contenido (G41, 1.3.0). "
            "Sin `force`, lo ya convertido se conserva; con `force`, cuenta como eliminado"
        ),
    )
    ignore_patterns: list[str] = Field(
        default_factory=list,
        description=(
            "Patrones `fnmatch` sobre el nombre de cada fichero o carpeta (nunca la ruta), sin distinguir mayúsculas, "
            f"que no se recorren; se suman a `IGNORED_NAMES` (G41, 1.3.0). Hasta {MAX_IGNORE_PATTERN_LENGTH} caracteres, "
            "sin separadores"
        ),
    )

    @field_validator("exclude_paths")
    @classmethod
    def _non_empty_paths(cls, paths: list[str]) -> list[str]:
        if any(not path.strip() for path in paths):
            raise ValueError("exclude_paths no admite rutas vacías")
        return paths

    @field_validator("ignore_patterns")
    @classmethod
    def _valid_patterns(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            if not pattern.strip():
                raise ValueError("ignore_patterns no admite patrones vacíos")
            if "/" in pattern or "\\" in pattern:
                raise ValueError(f"ignore_patterns son patrones de nombre, sin separadores: {pattern!r}")
            if len(pattern) > MAX_IGNORE_PATTERN_LENGTH:
                raise ValueError(f"ignore_patterns admite hasta {MAX_IGNORE_PATTERN_LENGTH} caracteres: {pattern!r}")
        return patterns


class ScanEvent(VersionedEvent):
    """Un evento de progreso emitido por `ScanCommand.run_streaming()` (Fase D-2b, §2.7.3).

    Deliberadamente un payload `dict[str, Any]` laxo en vez de un modelo por tipo de
    evento: las formas difieren lo suficiente (contadores del resumen final frente a
    la ruta/éxito de un único fichero) como para que un tipado más estricto supusiera
    un modelo por `ScanEventType` con poco beneficio en esta etapa. Los consumidores
    (CLI, WebSocket) usan `event` para interpretar `data`.
    """

    event: ScanEventType = Field(..., description="Tipo de evento de progreso")
    data: dict[str, Any] = Field(default_factory=dict, description="Payload del evento; su forma depende de `event`")


class DedupEvent(VersionedEvent):
    """Un evento de progreso emitido por `ScanCommand.deduplicate_streaming()`.

    Mismo criterio que `ScanEvent`: payload `dict[str, Any]` laxo en vez de un
    modelo por tipo de evento.
    """

    event: DedupEventType = Field(..., description="Tipo de evento de progreso")
    data: dict[str, Any] = Field(default_factory=dict, description="Payload del evento; su forma depende de `event`")


class ContextBuildEvent(VersionedEvent):
    """Un evento de progreso emitido al construir un contexto.

    Mismo criterio que `ScanEvent`/`DedupEvent`: payload `dict[str, Any]` laxo.
    """

    event: ContextBuildEventType = Field(..., description="Tipo de evento de progreso")
    data: dict[str, Any] = Field(default_factory=dict, description="Payload del evento; su forma depende de `event`")


class ContextDeleteEvent(VersionedEvent):
    """Un evento de progreso emitido al eliminar un contexto.

    Mismo criterio que `ScanEvent`/`DedupEvent`: payload `dict[str, Any]` laxo.
    """

    event: ContextDeleteEventType = Field(..., description="Tipo de evento de progreso")
    data: dict[str, Any] = Field(default_factory=dict, description="Payload del evento; su forma depende de `event`")


class ValidationResult(BaseModel):
    """Resultado de la validación de carpetas."""

    is_valid: bool = Field(..., description="Si las carpetas son válidas (sin redundancia)")
    warnings: list[str] = Field(default_factory=list, description="Lista de avisos")
    clean_paths: list[str] = Field(..., description="Rutas validadas, sin redundancia")


class Project(BaseModel):
    """Un proyecto de doc_organize: una carpeta de trabajo con nombre que agrega el estado de scan/convert/dedup/cache (REQ-008).

    Sin `tenant_id` desde 1.0.0 (L-12): un `projects.json` antiguo que lo traiga se sigue leyendo y el campo se
    ignora. Los tenants los gestiona doc_organize_web en su base de datos.
    """

    name: str = Field(..., description="Nombre único del proyecto en el registro (validado por ProjectValidator)")
    root_path: str = Field(..., description="Ruta absoluta a la carpeta de trabajo del proyecto")
    created_at: str = Field(..., description="Timestamp ISO 8601 de creación del proyecto")


_HTTP_TIMEOUT_DESC = "Timeout de las peticiones HTTP, en segundos"
_HTTP_RETRIES_DESC = (
    "Reintentos ante timeout o error de red/transporte; 0 (por defecto) no reintenta. Las respuestas HTTP no se "
    "reintentan, salvo 429/503 (`rate_limit_retries`). Ojo: reintentar un POST que hizo timeout puede cobrarse dos veces "
    "si el proxy sí lo recibió (L-3b)"
)
_HTTP_RATE_LIMIT_RETRIES_DESC = (
    "Reintentos ante una respuesta 429 o 503 (D5, 2.0.0), esperando lo que pida `Retry-After` o, si no lo trae, "
    "`retry_backoff_s` doblado en cada intento; la espera es compartida por todas las llamadas del cliente. 0 no reintenta"
)
_HTTP_MAX_RETRY_WAIT_DESC = "Tope de cada espera ante 429/503, en segundos (aunque `Retry-After` pida más)"
_HTTP_RETRY_BACKOFF_DESC = "Espera base entre reintentos, en segundos: se duplica en cada intento (0.5, 1, 2...) (L-3b)"


class ProjectNameValidation(BaseModel):
    """Resultado de validar un nombre de proyecto candidato (REQ-008).

    Modelo dedicado, no una reutilización de ValidationResult: ese modelo trata
    semánticamente de una lista de rutas de carpetas (`clean_paths`), no de un
    único identificador de proyecto.
    """

    is_valid: bool = Field(..., description="Si el nombre es válido")
    warnings: list[str] = Field(default_factory=list, description="Motivos por los que se rechazó el nombre, si los hay")
    normalized_name: str | None = Field(default=None, description="Nombre normalizado a NFC y sin espacios, si es válido")


# ===== Modelos de configuración =====


class DoclingConfig(BaseModel):
    """Configuración para la conversión de documentos con Docling."""

    ocr_mode: OcrMode = Field(default=OcrMode.DEFAULT, description="Modo de OCR a usar")
    do_ocr: bool = Field(default=False, description="Activar OCR para los documentos")
    use_gpu: bool = Field(default=False, description="Usar GPU si está disponible (torch/cuda)")
    max_workers: int = Field(default=4, description="Número de workers async para la conversión")


class CacheConfig(BaseModel):
    """Configuración de la base de datos de cache."""

    cache_db_path: str = Field(default=DEFAULT_CACHE_DB_NAME, description="Ruta a la base de datos SQLite de cache")
    enable_wal: bool = Field(default=True, description="Activar modo WAL para concurrencia")
    auto_backup: bool = Field(default=True, description="Backup automático de cache.db antes de escrituras masivas")


class ScannedFolder(BaseModel):
    """Una carpeta guardada en la lista persistente de escaneo de un proyecto (menú Escaneo).

    `used=True` es permanente una vez marcado: registra que la carpeta se usó
    alguna vez en un escaneo real, tanto para informar a qué carpetas se ha
    escaneado como para impedir su eliminación accidental de la lista.
    """

    path: str = Field(..., description="Ruta absoluta de la carpeta")
    added_at: str = Field(..., description="Timestamp ISO 8601 de cuándo se añadió a la lista")
    used: bool = Field(default=False, description="Si esta carpeta ya se ha usado en algún escaneo")


class GpuStatus(BaseModel):
    """Estado de soporte de GPU del entorno donde corre doc_organize (menú Escaneo de la web).

    Detección de entorno software, no de permisos por usuario/rol: el mismo
    resultado aplica a cualquier sesión, porque depende únicamente de qué hay
    instalado/disponible en el proceso servidor, no de quién pregunta.
    """

    gpu_support_installed: bool = Field(..., description="Si `torch` con CUDA (extra `ocr-gpu`) está instalado en este entorno")
    gpu_active: bool = Field(..., description="Si hay una GPU CUDA disponible y utilizable ahora mismo")
    instructions: str | None = Field(default=None, description="Instrucciones para activar la GPU, si `gpu_active` es `False`")


class AvStatus(BaseModel):
    """Estado de soporte de audio/vídeo del entorno donde corre el servidor (menú Escaneo).

    Mismo patrón que `GpuStatus`: detección de entorno software, sin permisos por
    usuario/rol. A diferencia de la GPU (cuya ausencia solo degrada a CPU), sin
    `asr_installed`/`ffmpeg_installed` la conversión de audio/vídeo falla siempre
    — por eso `ready` se usa también como pre-check bloqueante en el CLI
    (`_run_scan`), no solo como aviso informativo en una interfaz.
    """

    asr_installed: bool = Field(..., description="Si el backend de transcripción ASR (extra `av`, Whisper) está instalado")
    ffmpeg_installed: bool = Field(..., description="Si el binario `ffmpeg` está disponible en el PATH del sistema (necesario para vídeo)")
    ready: bool = Field(..., description="Si `asr_installed` y `ffmpeg_installed` son ambos `True`")
    instructions: str | None = Field(
        default=None, description="Qué falta instalar/configurar, específico a lo que falte; `None` si `ready` es `True`"
    )


EnvironmentCheckStatus = Literal["ok", "warning", "error"]


class EnvironmentCheck(BaseModel):
    """Una comprobación del entorno (`check_environment`, 2.0.0, F2).

    Attributes:
        name (str): Qué se comprueba (`python`, `docling`, `extra:site`, `ai:<nombre>`...).
        status (str): `ok`, `warning` (funciona con limitaciones) o `error` (algo no funcionará).
        detail (str): Qué se encontró (versiones, sin rutas ni claves).
        remedy (str | None): Qué hacer si no es `ok`.
        model (str | None): En las de IA (2.2.0), el modelo que se pidió (alias del proxy).
        served_model (str | None): En las de IA (2.2.0), el modelo que dice la respuesta que contestó, si lo dice
            (el que hay detrás del alias, según el proxy); `None` si no lo dice.
        dimension (int | None): En las de embeddings (2.2.0), la dimensión de los vectores.
    """

    name: str
    status: EnvironmentCheckStatus
    detail: str
    remedy: str | None = None
    model: str | None = None
    served_model: str | None = None
    dimension: int | None = None


class EnvironmentReport(BaseModel):
    """Resultado de `check_environment` (2.0.0, F2): una entrada por comprobación.

    Attributes:
        checks (list[EnvironmentCheck]): Comprobaciones en orden.
        checked_at (str): Cuándo se hizo (ISO 8601, UTC).
    """

    checks: list[EnvironmentCheck] = Field(default_factory=list)
    checked_at: str

    @property
    def ok(self) -> bool:
        """Sin errores (los avisos no cuentan)."""
        return all(check.status != "error" for check in self.checks)


class OfficeStatus(BaseModel):
    """Estado de soporte de LibreOffice del entorno donde corre el servidor (menú Escaneo).

    Mismo patron que `AvStatus`/`GpuStatus`: deteccion de entorno software, sin
    permisos por usuario/rol. Necesario porque Docling delega en `soffice`/
    `libreoffice` (via PATH) la conversion de Excel legado (`.xls`) a `.xlsx`
    antes de poder parsearlo -- a diferencia de audio/video, `.xls` no es
    opt-in (forma parte de `SUPPORTED_EXTENSIONS` siempre activo), asi que este
    estado no bloquea el escaneo entero: solo evita el viaje de ida y vuelta
    por Docling para un `.xls` concreto cuando ya se sabe que va a fallar (ver
    `converter.py::convert_document`).
    """

    libreoffice_installed: bool = Field(..., description="Si el binario `soffice`/`libreoffice` esta disponible en el PATH del sistema")
    instructions: str | None = Field(default=None, description="Instrucciones para instalar LibreOffice, si `libreoffice_installed` es `False`")


# ===== Modelos de monitorización de uso/coste de IA (fase 2, `doc_organize.ai`) =====


#: Aviso de obsolescencia de GitHub Copilot (2.1.0): todo el uso de IA pasa por LiteLLM; se retira en 3.0.
COPILOT_DEPRECATION_MESSAGE: Final = (
    "El soporte de GitHub Copilot (GitHubCopilotUsageClient, GitHubCopilotUsageConfig, "
    "github_copilot_usage_config_from_env) está obsoleto desde doc_organize 2.1.0 y se retirará en 3.0: "
    "consulta el uso y el coste de IA en LiteLLM (LiteLLMUsageClient)."
)


class UsageLineItem(BaseModel):
    """Una línea de consumo dentro de un `UsageSnapshot`.

    Normaliza tanto `usageItems[]` de la API de Billing Usage de GitHub
    (`quantity`, `unitType`, `netAmount`) como la respuesta de spend de un
    LiteLLM Proxy, para que ambas fuentes se listen de forma uniforme.
    """

    date: str = Field(..., description="Fecha (ISO 8601) de la línea de consumo")
    product: str = Field(..., description="Producto facturado: 'litellm' (2.5.0) o 'copilot'")
    sku: str | None = Field(default=None, description="SKU/identificador de tarifa, si la fuente lo reporta")
    quantity: float = Field(..., description="Cantidad consumida (tokens, requests o premium requests, según `unit_type`)")
    unit_type: str = Field(..., description="Unidad de `quantity`, p.ej. 'tokens', 'requests', 'premium_requests', 'usd'")
    cost_usd: float | None = Field(default=None, description="Coste en USD, o `None` si la fuente no lo reporta (p.ej. Copilot Pro sin overage)")


class UsageSnapshot(BaseModel):
    """Resultado normalizado de consultar una fuente de uso/coste de IA (`doc_organize.ai`)."""

    source: UsageSourceName = Field(..., description="Fuente que produjo este snapshot")
    period_start: str = Field(..., description="Inicio del periodo consultado (ISO 8601, fecha)")
    period_end: str = Field(..., description="Fin del periodo consultado (ISO 8601, fecha)")
    items: list[UsageLineItem] = Field(default_factory=list, description="Líneas de consumo del periodo")
    raw: dict[str, Any] = Field(default_factory=dict, description="Payload original de la fuente, sin transformar, para depuración")


class LiteLLMUsageConfig(BaseModel):
    """Configuración de acceso a un LiteLLM Proxy externo para consultar spend/uso.

    Ningún campo se lee del entorno aquí (DIP: el llamador decide su origen) —
    usa `litellm_usage_config_from_env()` (`doc_organize.ai`) para resolver
    `DOC_ORGANIZE_LITELLM_BASE_URL`/`DOC_ORGANIZE_LITELLM_VIRTUAL_KEY` explícitamente.
    """

    base_url: str = Field(..., description="URL base del LiteLLM Proxy, p.ej. 'https://litellm.example.com'")
    virtual_key: str = Field(
        ...,
        repr=False,  # 2.4.2: fuera de logs y trazas, como en `AiSettings`; `model_dump()` la sigue incluyendo
        description="Virtual key del proxy: se usa como Bearer de autenticación y, por defecto, como key consultada en `get_usage()`",
    )
    timeout_s: float = Field(default=30.0, description=_HTTP_TIMEOUT_DESC)
    retries: int = Field(default=0, ge=0, description=_HTTP_RETRIES_DESC)
    retry_backoff_s: float = Field(default=0.5, ge=0.0, description=_HTTP_RETRY_BACKOFF_DESC)
    rate_limit_retries: int = Field(default=3, ge=0, description=_HTTP_RATE_LIMIT_RETRIES_DESC)
    max_retry_wait_s: float = Field(default=60.0, ge=0.0, description=_HTTP_MAX_RETRY_WAIT_DESC)


class GitHubCopilotUsageConfig(BaseModel):
    """Configuración de acceso a la API de Billing Usage de GitHub para Copilot Pro.

    Igual criterio que `LiteLLMUsageConfig`: usa
    `github_copilot_usage_config_from_env()` (`doc_organize.ai`) para resolver
    `DOC_ORGANIZE_GITHUB_USERNAME`/`DOC_ORGANIZE_GITHUB_PAT` explícitamente.

    Deprecated:
        Obsoleto desde 2.1.0 y se retira en 3.0: el uso y el coste de IA se consultan en LiteLLM
        (`LiteLLMUsageClient`). Crear una instancia emite `DeprecationWarning`.
    """

    username: str = Field(..., description="Usuario personal de GitHub cuyo consumo de Copilot se consulta")
    personal_access_token: str = Field(
        ...,
        repr=False,  # 2.4.2: fuera de logs y trazas
        description="PAT con permiso de lectura de facturación personal (scope exacto sin confirmar, ver AUDIT_PLAN)",
    )
    timeout_s: float = Field(default=30.0, description=_HTTP_TIMEOUT_DESC)
    retries: int = Field(default=0, ge=0, description=_HTTP_RETRIES_DESC)
    retry_backoff_s: float = Field(default=0.5, ge=0.0, description=_HTTP_RETRY_BACKOFF_DESC)
    rate_limit_retries: int = Field(default=3, ge=0, description=_HTTP_RATE_LIMIT_RETRIES_DESC)
    max_retry_wait_s: float = Field(default=60.0, ge=0.0, description=_HTTP_MAX_RETRY_WAIT_DESC)

    def model_post_init(self, context: Any, /) -> None:
        """Avisa de que la clase está obsoleta (2.1.0; se retira en 3.0)."""
        warnings.warn(COPILOT_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=3)


# ===== Modelos de contexto y dominios (organización documental, `doc_organize.context`) =====


DocumentEnrichmentField = Literal["description", "keywords"]
"""Campos de `DomainDocument` que la IA puede rellenar (`DomainDocument.ai_filled`, 1.5.0)."""


AxisClassifiedBy = Literal["rules", "semantic", "ai", "human"]
"""Quién asignó un valor de un eje (`AxisValue.classified_by`, 2.0.0): reglas, semántica (embeddings), IA o una persona."""


class AxisValue(BaseModel):
    """Un valor de un eje asignado a un documento (2.0.0, A3).

    Attributes:
        slug (str): Valor del catálogo del eje (saneado).
        name (str): Nombre legible del valor.
        confidence (float): Confianza 0-1 de quien lo asignó.
        classified_by (str): `rules`, `semantic`, `ai` o `human`.
        evidence (str | None): Cita literal del documento que lo justifica (IA, 2.0.0 M5); `None` si no hay.
        evidence_verified (bool | None): Si la cita aparece en el texto enviado; `None` sin cita.

    Example:
        >>> AxisValue(slug="ens", name="ENS", confidence=0.6, classified_by="rules").evidence is None
        True
    """

    slug: str = Field(..., min_length=1, description="Valor del catálogo del eje")
    name: str = Field(..., description="Nombre legible del valor")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confianza 0-1")
    classified_by: AxisClassifiedBy = Field(..., description="Quién lo asignó")
    evidence: str | None = Field(default=None, description="Cita literal que justifica el valor, si la hay")
    evidence_verified: bool | None = Field(default=None, description="Si la cita aparece en el texto del documento; `None` sin cita")

    @model_serializer(mode="wrap")
    def _omit_missing_evidence(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Sin cita, `evidence` y `evidence_verified` no se escriben: hay un valor por eje y documento, y en un corpus
        grande esos dos `null` pesaban casi un tercio de la clasificación en `index.json`."""
        data: dict[str, Any] = handler(self)
        for key in ("evidence", "evidence_verified"):
            if data.get(key) is None:
                data.pop(key, None)
        return data


class DocumentClassification(BaseModel):
    """Clasificación de un documento en todos los ejes de la taxonomía (2.0.0, A3).

    `axes` tiene una clave por eje del contexto (`Context.taxonomy_axes`): una lista vacía significa que el eje se
    evaluó y no se asignó ningún valor (en un eje organizador, el documento queda en «Sin Clasificar»).

    Example:
        >>> classification = DocumentClassification(
        ...     axes={"normative_frameworks": [AxisValue(slug="ens", name="ENS", confidence=0.6, classified_by="rules")]}
        ... )
        >>> classification.slugs("normative_frameworks"), classification.slugs("evidence")
        (['ens'], [])
    """

    axes: dict[str, list[AxisValue]] = Field(default_factory=dict, description="Valores asignados por clave de eje")

    def slugs(self, key: str) -> list[str]:
        """Los slugs asignados en el eje `key` (vacío si ninguno o si el eje no existe)."""
        return [value.slug for value in self.axes.get(key, [])]


class DomainDocument(BaseModel):
    """Un documento clasificado dentro de un `Domain` (Sub-fase A o B, ver `.ai/sessions/2026-09-08-organizacion-documental-contextos/00_REQUEST.md` §2.4-§2.5)."""

    source_path: str = Field(..., description="Ruta del documento original")
    markdown_path: str = Field(..., description="Ruta del `.md` generado por `converter/`")
    json_path: str = Field(..., description="Ruta del `.json` generado por `converter/` (fuente de la clasificación, §2.4)")
    images_dir: str | None = Field(
        default=None,
        description="Carpeta con las imágenes extraídas del documento (`ConversionResult.images_dir`), si las hubo",
    )
    title: str = Field(..., description="Título del documento")
    document_type: str = Field(..., description="Tipo de documento dentro del dominio (extensión original, en minúsculas, sin punto)")
    material_type: str | None = Field(
        default=None,
        description=(
            "Slug del tipo de material de origen (segundo eje de clasificación, catálogo de "
            "eje `subfolder` del `TaxonomyManifest`), o `None` en modo sin manifiesto de taxonomía"
        ),
    )
    material_type_name: str | None = Field(
        default=None,
        description=(
            "Nombre legible de `material_type` (`TaxonomyEntry.name` del eje `subfolder` del manifiesto), o `None` si "
            "`material_type` es el placeholder `sin-clasificar` o no hay manifiesto — el llamador (p. ej. "
            "`SiteGenerator`) recurre entonces a derivar una etiqueta a partir del slug"
        ),
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Score de confianza de la clasificación, 0-1")
    classified_by: str = Field(default="rules", description="'rules' (Sub-fase A) o 'ai' (Sub-fase B) según qué clasificó el documento")
    rules_domain: str | None = Field(
        default=None,
        description=(
            "Dominio que propusieron las reglas (Sub-fase A), aunque no alcanzase el umbral y lo decidiera la IA (1.5.0); "
            "None si las reglas no propusieron ninguno o el contexto es anterior"
        ),
    )
    rules_confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Score de las reglas para `rules_domain` (1.5.0); None si el contexto es anterior"
    )
    ai_domain: str | None = Field(
        default=None,
        description=(
            "Dominio que propuso la IA, si se le preguntó (1.5.0). En modo manifiesto puede no coincidir con el dominio "
            "del documento: si las reglas ya lo habían decidido, la propuesta de la IA para ese eje no se aplica"
        ),
    )
    ai_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confianza que dio la IA en `ai_domain`, si se le preguntó por este documento (1.5.0); None si no",
    )
    ai_reasoning: str | None = Field(
        default=None, description="Justificación breve que dio la IA al clasificar este documento (1.5.0, hasta 500 caracteres); None si no"
    )
    material_type_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Score del eje de tipo de material, de las reglas o de la IA según quién lo decidió (1.5.0, modo manifiesto); None si no",
    )
    organized_path: str | None = Field(
        default=None,
        description=(
            "Ruta POSIX del `.md` copiado, relativa a la carpeta reorganizada (`<dominio>/<tipo>/<carpeta>/<stem>.md`), "
            "o `None` si aún no se ha calculado (contextos de antes de 0.14.0). La rellenan `ContextBuilder` y "
            "`Reorganizer` con `resolve_organized_paths` (L-8d); solo informativa: `Reorganizer`/`SiteGenerator` la "
            "recalculan siempre y nunca usan el valor leído de `index.json`"
        ),
    )
    author: str | None = Field(
        default=None, description="Autor declarado en el propio documento (PDF `/Author`, Office `dc:creator`, 1.5.0); nunca la IA"
    )
    description: str | None = Field(
        default=None,
        description="Descripción declarada en el documento (PDF `/Subject`, Office `dc:description` o `dc:subject`), o de la IA si falta (1.5.0)",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Palabras clave declaradas en el documento (PDF `/Keywords`, Office `cp:keywords`), o de la IA si faltan (1.5.0)",
    )
    language: str | None = Field(
        default=None,
        description="Idioma principal (ISO 639-1, p. ej. 'es') detectado en el texto convertido con py3langid (1.5.0); None si no es seguro",
    )
    ai_filled: list[DocumentEnrichmentField] = Field(
        default_factory=list, description="Campos que rellenó la IA porque el documento no los declaraba (1.5.0); vacío si ninguno"
    )
    source_sha256: str | None = Field(
        default=None, description="SHA-256 del original al construir el contexto (2.0.0, F4); None si no se conocía o el contexto es anterior"
    )
    version: str | None = Field(default=None, description="Versión del documento en su grupo (`1.2`, 2.0.0 F5); None si no tiene")
    version_group: str | None = Field(default=None, description="Clave de su grupo de versiones (`DocumentVersionGroup.key`)")
    is_current: bool | None = Field(default=None, description="Si es la versión vigente de su grupo; None si no tiene grupo")
    classification: DocumentClassification = Field(
        default_factory=DocumentClassification,
        description=(
            "Valores de cada eje (2.0.0): los organizadores repiten el dominio y `material_type`, con quién los asignó; "
            "los demás ejes solo están aquí"
        ),
    )


UnclassifiedReason = Literal["incomplete_artifacts", "below_threshold"]
"""Por qué un documento quedó sin clasificar (`UnclassifiedDocument.reason`, 1.6.0).

- `"incomplete_artifacts"`: la conversión falló o falta su `.md` o su `.json` (o el `.json` no se puede leer).
- `"below_threshold"`: tiene sus artefactos, pero las reglas no llegaron al umbral y la IA no lo asignó (estaba
  desactivada, se detuvo o no eligió ningún dominio).
"""


class UnclassifiedDocument(BaseModel):
    """Un documento que `ContextBuilder.build()` dejó sin clasificar, con lo que se sabe de él (1.6.0, G42).

    Persistido por `ContextRegistry` en `unclassified.json`, junto a `context.json`. No reutiliza `DomainDocument`:
    puede no tener `.md` ni `.json`, y no tiene dominio ni confianza. La IA no lo enriquece: `description` y `keywords`
    son solo lo que declara el original.

    Example:
        >>> document = UnclassifiedDocument(source_path="/datos/acta.pdf", document_type="pdf", reason="incomplete_artifacts")
        >>> document.reason, document.title, document.keywords
        ('incomplete_artifacts', None, [])
    """

    source_path: str = Field(..., description="Ruta del documento original")
    title: str | None = Field(
        default=None, description="Título del `.json` de conversión o, si no lo da, el nombre del `.md`; None si no hay ninguno"
    )
    document_type: str = Field(..., description="Extensión original en minúsculas, sin punto ('desconocido' si no tiene)")
    markdown_path: str | None = Field(default=None, description="Ruta del `.md` generado, si la conversión lo dejó")
    json_path: str | None = Field(default=None, description="Ruta del `.json` generado, si la conversión lo dejó")
    reason: UnclassifiedReason = Field(..., description="Por qué quedó sin clasificar")
    rules_domain: str | None = Field(
        default=None, description="Dominio que propusieron las reglas por debajo del umbral; None si no propusieron ninguno"
    )
    rules_confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Confianza de `rules_domain`; None si las reglas no puntuaron el documento"
    )
    author: str | None = Field(default=None, description="Autor declarado en el original (como `DomainDocument.author`)")
    description: str | None = Field(default=None, description="Descripción declarada en el original; nunca de la IA")
    keywords: list[str] = Field(default_factory=list, description="Palabras clave declaradas en el original; nunca de la IA")
    language: str | None = Field(default=None, description="Idioma detectado en el texto convertido (ISO 639-1); None sin `.json` o si no es seguro")
    classification: DocumentClassification = Field(
        default_factory=DocumentClassification, description="Valores de los ejes que no organizan carpetas (2.0.0); vacío sin texto"
    )
    source_sha256: str | None = Field(default=None, description="SHA-256 del original al construir el contexto (2.0.0, F4); None si no se conocía")
    version: str | None = Field(default=None, description="Versión del documento en su grupo (`1.2`, 2.0.0 F5); None si no tiene")
    version_group: str | None = Field(default=None, description="Clave de su grupo de versiones (`DocumentVersionGroup.key`)")
    is_current: bool | None = Field(default=None, description="Si es la versión vigente de su grupo; None si no tiene grupo")


class Domain(BaseModel):
    """Un dominio documental dentro del `Context` de un proyecto."""

    slug: str = Field(..., description="Identificador corto del dominio (kebab-case)")
    name: str = Field(..., description="Nombre legible del dominio")
    description: str | None = Field(default=None, description="Descripción del dominio, o `None` si no se ha rellenado todavía")
    status: DomainStatus = Field(default=DomainStatus.DRAFT, description="Estado del dominio")
    predefined: bool = Field(default=False, description="Si el dominio fue predefinido por el usuario (catálogo) o descubierto automáticamente")
    documents: list[DomainDocument] = Field(default_factory=list, description="Documentos clasificados en este dominio")


AiClassificationStopReason = Literal["auth", "connection", "budget"]
"""Motivo por el que `ContextBuilder.build()` detuvo una fase de IA (`AiPhaseStats.stopped`, L-3a/L-3b)."""

AiScope = Literal["off", "unclassified", "missing_axes"]
"""Qué documentos van a la IA para clasificarse (`ContextBuilder.build(ai_scope=)`, 2.0.0): ninguno; los que las reglas
dejaron sin clasificar en algún eje organizador (`unclassified`, la Sub-fase B de 1.x); o además los que tienen vacío
algún eje que solo etiqueta (`missing_axes`, opt-in: más documentos van a la IA)."""


class AiPhaseStats(BaseModel):
    """Recuentos de una fase de IA de una construcción (2.0.0; antes campos sueltos `ai_documents_*` y `ai_enrichment_*`).

    `sent == assigned + failed + enviados sin asignación` siempre.

    Attributes:
        sent (int): Documentos enviados (una llamada por documento).
        assigned (int): Enviados en los que la IA asignó algo (un eje, o un campo al describir).
        failed (int): Enviados cuya llamada falló.
        stopped (str | None): Por qué paró antes de terminar (`auth`, `connection`, `budget`), o `None`.
        prompt_tokens (int): Tokens de entrada, según el proxy.
        completion_tokens (int): Tokens de salida, según el proxy.
        response_format (str | None): `json_schema` o `json_object` (si el modelo no admite el esquema), en la última
            llamada que respondió.
        cached (int): Documentos resueltos con la caché de resultados (`AiResultCache`), sin llamar al modelo; no
            cuentan en `sent` ni consumen `ai_max_documents`.
    """

    sent: int = Field(default=0, ge=0)
    assigned: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    stopped: AiClassificationStopReason | None = None
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    response_format: Literal["json_schema", "json_object"] | None = None
    cached: int = Field(default=0, ge=0, description="Documentos resueltos con la caché de resultados, sin llamar al modelo (2.0.0)")


class AiStats(BaseModel):
    """Qué hizo la IA en una construcción (2.0.0, `Context.ai_stats`).

    Attributes:
        scope (AiScope): Alcance de la clasificación con IA.
        enrich (bool): Si se pidió describir los documentos que no declaran descripción o palabras clave.
        classification (AiPhaseStats): Clasificación (tarea `classify`).
        enrichment (AiPhaseStats): Descripción (tarea `enrich`).
    """

    scope: AiScope = "off"
    enrich: bool = False
    classification: AiPhaseStats = Field(default_factory=AiPhaseStats)
    enrichment: AiPhaseStats = Field(default_factory=AiPhaseStats)
    semantic: bool = Field(default=False, description="Si se usó la sub-fase semántica (2.0.0, G4)")
    semantic_classification: AiPhaseStats = Field(
        default_factory=AiPhaseStats,
        description="Sub-fase semántica: `sent` = textos embebidos, `cached` = sacados del índice, `assigned` = documentos con algún eje asignado",
    )


class DocumentCredentialFindings(BaseModel):
    """Credenciales redactadas en el texto de un documento antes de enviarlo a la IA (1.7.0), **sin los valores**.

    Attributes:
        source_path (str): Documento, con la misma ruta que su `DomainDocument`/`UnclassifiedDocument`.
        rules (dict[str, int]): Cuántos valores se redactaron por regla (`doc_organize.security.CREDENTIAL_RULES`).
    """

    source_path: str
    rules: dict[str, int] = Field(default_factory=dict)


DecisionAction = Literal["confirm", "set_axis", "exclude", "set_current_version"]
"""Qué decide una persona sobre un documento (2.0.0, F6): confirmar su clasificación (los valores de todos sus ejes en
`ClassificationDecision.axes`), fijar los valores de un eje, sacarlo del contexto, o marcarlo como la versión vigente
de su grupo de versiones (F5)."""

DecisionIssueReason = Literal["source_changed", "unknown_axis", "unknown_value", "missing_document", "no_manifest", "not_versioned"]


class ClassificationDecision(BaseModel):
    """Una decisión de una persona sobre la clasificación de un documento (2.0.0, F6).

    Se aplica en cada construcción **después de las reglas y antes de la IA**: los ejes decididos quedan con
    `classified_by="human"` y ni las reglas ni la IA los cambian. Si el original cambió desde la decisión
    (`source_sha256` distinto), deja de aplicarse y aparece en `Context.stale_decisions` para revisarla.

    Attributes:
        id (str): Identificador único (lo pone `ClassificationDecisionStore.add` si falta).
        document_key (str): Ruta del original relativa a la raíz de escaneo (`document_key`).
        source_sha256 (str | None): Huella del original cuando se decidió; `None` = vale para cualquier versión.
        action (DecisionAction): `confirm`, `set_axis` o `exclude`.
        axes (dict[str, list[str]]): Valores por eje: uno solo en `set_axis`, todos los del documento en `confirm`,
            vacío en `exclude`. En un eje que organiza (carpeta, subcarpeta) va exactamente un valor.
        author (str | None): Quién decidió.
        decided_at (str): Cuándo (ISO 8601).
        reason (str | None): Por qué, si se dijo.
        revoked_at (str | None): Cuándo se revocó o sustituyó (solo en el historial).
        revoked_by (str | None): Quién la revocó.
        revoke_reason (str | None): Por qué (`"replaced"` si la sustituyó otra).

    Example:
        >>> decision = ClassificationDecision(document_key="ENS/plan.pdf", action="set_axis", axes={"domains": ["seguridad"]})
        >>> decision.axis
        'domains'
    """

    id: str = Field(default="", description="Identificador único")
    document_key: str = Field(..., min_length=1, description="Ruta del original relativa a la raíz de escaneo")
    source_sha256: str | None = Field(default=None, description="Huella del original al decidir; None = cualquier versión")
    action: DecisionAction = Field(..., description="confirm, set_axis o exclude")
    axes: dict[str, list[str]] = Field(default_factory=dict, description="Valores decididos por eje")
    author: str | None = Field(default=None, description="Quién decidió")
    decided_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"), description="Cuándo (ISO 8601)")
    reason: str | None = Field(default=None, description="Por qué")
    revoked_at: str | None = Field(default=None, description="Cuándo se revocó (historial)")
    revoked_by: str | None = Field(default=None, description="Quién la revocó")
    revoke_reason: str | None = Field(default=None, description="Por qué se revocó; 'replaced' si la sustituyó otra")

    @model_validator(mode="after")
    def _check_axes(self) -> "ClassificationDecision":
        if self.action == "set_axis" and len(self.axes) != 1:
            raise ValueError("set_axis decide exactamente un eje")
        if self.action == "confirm" and not self.axes:
            raise ValueError("confirm necesita los valores de los ejes que se confirman")
        if self.action in ("exclude", "set_current_version") and self.axes:
            raise ValueError(f"{self.action} no lleva valores")
        return self

    @property
    def axis(self) -> str | None:
        """El eje de un `set_axis`; `None` en las demás acciones."""
        return next(iter(self.axes)) if self.action == "set_axis" else None


class DecisionIssue(BaseModel):
    """Una decisión que no se aplicó en una construcción, y por qué (2.0.0, F6).

    `reason`: `source_changed` (el original cambió desde la decisión), `unknown_axis`/`unknown_value` (el eje o el
    valor ya no están en el catálogo), `missing_document` (el documento no está en la construcción), `no_manifest`
    (sin manifiesto no se aplican decisiones) o `not_versioned` (`set_current_version` de un documento que no está en
    ningún grupo de versiones).
    """

    decision_id: str
    document_key: str
    reason: DecisionIssueReason
    detail: str | None = None


VersionsMode = Literal["all", "mark", "current_only"]
"""Qué hace la construcción con las versiones de un mismo documento (2.0.0, F5): `all` (como 1.x: cada fichero es un
documento), `mark` (todas se clasifican y llevan su versión y si son la vigente) o `current_only` (solo la vigente se
clasifica, se publica y va a la IA; las demás quedan en `Context.superseded_documents`)."""


class DocumentVersionGroup(BaseModel):
    """Un grupo de versiones de un mismo documento en el contexto (2.0.0, F5).

    Attributes:
        key (str): Carpeta y nombre sin el marcador de versión, normalizados.
        members (list[str]): Originales, de la versión más baja a la más alta.
        versions (list[str]): Versión de cada uno (`1.2`), en el mismo orden.
        current (str): Original vigente: la versión más alta o la que decidió una persona.
        confirmed (bool): Si la vigente la confirmó una persona (`set_current_version`).
    """

    key: str
    members: list[str]
    versions: list[str]
    current: str
    confirmed: bool = False


class Context(BaseModel):
    """Contexto de organización documental de un proyecto: configuración de clasificación + dominios.

    Persistido por `ContextRegistry` en `<project.root_path>/context.json` (metadatos +
    resumen de dominios) más `<project.root_path>/domains/<slug>/{DOMAIN.md,index.json}`
    por dominio (ver §3 del `00_REQUEST.md` de la sesión que originó este modelo).

    Sin `tenant_id` desde 1.0.0 (L-12): un `context.json` antiguo que lo traiga se sigue leyendo y el campo se ignora.
    """

    schema_version: int = Field(
        default=1,
        description=(
            "Versión del formato (2.0.0: 2). Un `context.json` de 1.x (sin el campo) se migra al leerlo: "
            "`taxonomy_axes` y la `classification` de cada documento salen de su dominio y su tipo de material"
        ),
    )
    project_name: str = Field(..., description="Nombre del proyecto propietario de este contexto")
    taxonomy_axes: "list[TaxonomyAxis]" = Field(
        default_factory=list,
        description="Ejes con los que se clasificó (2.0.0), sin `keywords` ni `examples`; sin manifiesto, solo `domains`",
    )
    output_folder_name: str = Field(default="organizado", description="Nombre de la carpeta de salida reorganizada, relativa a `root_path`")
    ai_fallback_threshold: float = Field(default=0.5, description="Score mínimo de las reglas para clasificar un eje sin IA")
    built_with_version: str | None = Field(
        default=None,
        description=(
            "Versión de doc_organize que construyó el contexto (1.5.0): identifica las reglas de clasificación, que son "
            "código; `None` en contextos anteriores"
        ),
    )
    domains: list[Domain] = Field(default_factory=list, description="Dominios detectados/confirmados")
    unclassified_documents: list[str] = Field(
        default_factory=list,
        description="`source_path` de documentos sin clasificar (score insuficiente, artefactos incompletos, o IA deshabilitada)",
    )
    unclassified_details: list[UnclassifiedDocument] = Field(
        default_factory=list,
        description=(
            "Los mismos documentos que `unclassified_documents`, en el mismo orden, con motivo, título, autor, descripción, "
            "palabras clave e idioma (1.6.0, G42). Se guarda aparte, en `unclassified.json`; vacía en contextos anteriores"
        ),
    )
    reorganized: bool = Field(
        default=False,
        description="Si `Reorganizer.reorganize()` terminó con éxito para esta versión del contexto — `False` si nunca se intentó o si falló a medias (AUDIT_CODE sesión 2026-09-08)",
    )
    reorganize_failed_documents: list[str] = Field(
        default_factory=list,
        description=(
            "`source_path` de los documentos que `Reorganizer.reorganize()` no pudo copiar en la última reorganización "
            "(p. ej. algún tramo es un enlace simbólico, L-8a); el resto sí se copió"
        ),
    )
    site_generated: bool = Field(
        default=False,
        validation_alias=AliasChoices("site_generated", "mkdocs_generated"),
        description="Si `SiteGenerator.generate()` escribió la configuración del sitio (`zensical.toml` + `index.md`) para esta versión del contexto",
    )
    site_built: bool = Field(
        default=False,
        validation_alias=AliasChoices("site_built", "mkdocs_site_built"),
        description="Si `zensical build` terminó con éxito sobre la configuración generada (sitio navegable en `site/`)",
    )
    taxonomy_manifest_used: bool = Field(
        default=False,
        description=(
            "Si esta construcción usó un manifiesto de taxonomía (`taxonomy_manifest.md`, "
            "clasificación de 2 ejes: dominio + tipo de material) en vez de `candidate_domains`/"
            "descubrimiento (1 eje) — determina si `Reorganizer`/`SiteGenerator` agrupan también "
            "por `DomainDocument.material_type`"
        ),
    )
    taxonomy_template_name: str | None = Field(
        default=None,
        description=(
            "Nombre de la plantilla de taxonomía compartida (`TaxonomyTemplateRegistry`) usada en "
            "esta construcción, o `None` si se usó un `taxonomy_manifest.md` local, o ningún "
            "manifiesto — solo informativo (no afecta la reconstrucción, que exige repetir la "
            "elección en cada `POST`, igual que `candidate_domains`)"
        ),
    )
    ai_stats: AiStats = Field(default_factory=AiStats, description="Qué hizo la IA en esta construcción (2.0.0): alcance, recuentos y tokens")
    decisions_applied: int = Field(default=0, description="Decisiones de personas aplicadas en esta construcción (2.0.0, F6)")
    stale_decisions: list[DecisionIssue] = Field(
        default_factory=list, description="Decisiones que no se aplicaron porque el original o el catálogo cambiaron (2.0.0, F6)"
    )
    orphan_decisions: list[DecisionIssue] = Field(
        default_factory=list, description="Decisiones de documentos que no están en esta construcción (2.0.0, F6)"
    )
    excluded_documents: list[str] = Field(default_factory=list, description="Originales que una persona sacó del contexto (`exclude`, 2.0.0 F6)")
    versions_mode: VersionsMode = Field(default="all", description="Qué se hizo con las versiones de un documento (2.0.0, F5)")
    versions_across_extensions: bool = Field(
        default=False, description="Si las versiones se agruparon también entre formatos (`version_across_extensions`, 2.5.0)"
    )
    version_groups: list[DocumentVersionGroup] = Field(
        default_factory=list, description="Grupos de versiones detectados (con `versions` `mark` o `current_only`, 2.0.0 F5)"
    )
    superseded_documents: list[str] = Field(
        default_factory=list, description='Versiones antiguas que no entraron en el contexto (`versions="current_only"`)'
    )
    ai_provenance: "list[PromptProvenance]" = Field(
        default_factory=list, description="Prompt y modelo de cada tarea de IA que llegó a enviar algo (2.0.0, G1)"
    )
    ai_redact_credentials: bool = Field(
        default=False,
        description=(
            "Si el texto enviado a la IA se redactó antes (`AiSettings.redact_credentials`; en 1.7, `ContextBuilder(ai_redact_credentials=True)`). `False` en "
            "contextos anteriores a la 1.7.0"
        ),
    )
    credential_findings: list[DocumentCredentialFindings] = Field(
        default_factory=list,
        description=(
            "Documentos enviados a la IA en los que se redactaron credenciales, con el recuento por regla y nunca el "
            "valor (1.7.0). Vacío sin IA o con la redacción desactivada"
        ),
    )
    created_at: str = Field(
        ...,
        description=(
            "Timestamp ISO 8601 de creación del contexto. `ContextBuilder` lo conserva al reconstruir desde 1.6.0 (antes "
            "era la hora de cada construcción); vuelve a empezar si el contexto se borra o el anterior no se puede leer"
        ),
    )
    updated_at: str = Field(..., description="Timestamp ISO 8601 de la última reconstrucción del contexto")

    @field_validator("output_folder_name")
    @classmethod
    def _validate_output_folder_name(cls, value: str) -> str:
        """L-8f (G32): mismo criterio que `validate_output_folder_name`; un `context.json` manipulado ("..", una ruta
        absoluta, un nombre reservado) no se carga en vez de usarse para copiar y borrar."""
        from doc_organize.core.exceptions import InvalidPathError
        from doc_organize.core.output_folder import validate_output_folder_name

        try:
            return validate_output_folder_name(value)
        except InvalidPathError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="before")
    @classmethod
    def _migrate_v1_ai_fields(cls, data: Any) -> Any:
        """Los recuentos de IA de 1.x (`ai_documents_*`, `ai_enrichment_*`...) pasan a `ai_stats` (2.0.0)."""
        if not isinstance(data, dict) or "ai_stats" in data:
            return data
        data = dict(data)
        legacy = {key: data.pop(key) for key in list(data) if key in _LEGACY_AI_FIELDS}
        if legacy:
            data["ai_stats"] = {
                "scope": "unclassified" if legacy.get("ai_classification_enabled") else "off",
                "enrich": bool(legacy.get("ai_enrichment_enabled")),
                "classification": {
                    "sent": legacy.get("ai_documents_sent") or 0,
                    "assigned": legacy.get("ai_documents_classified") or 0,
                    "failed": legacy.get("ai_documents_failed") or 0,
                    "stopped": legacy.get("ai_classification_stopped"),
                },
                "enrichment": {
                    "sent": legacy.get("ai_enrichment_sent") or 0,
                    "assigned": legacy.get("ai_enrichment_applied") or 0,
                    "failed": legacy.get("ai_enrichment_failed") or 0,
                    "stopped": legacy.get("ai_enrichment_stopped"),
                },
            }
            # El modelo de cada fase, con el prompt marcado como de 1.x (no se guardaba cuál).
            data.setdefault(
                "ai_provenance",
                [
                    {"task": task, "prompt_id": "1.x", "version": "1.x", "source": "builtin", "sha256": "", "model": legacy[key]}
                    for task, key in (("classify", "ai_classification_model"), ("enrich", "ai_enrichment_model"))
                    if legacy.get(key)
                ],
            )
        return data

    def model_for_task(self, task: "AiTask") -> str | None:
        """Modelo con el que se hizo `task` en esta construcción (de `ai_provenance`), o `None`."""
        return next((item.model for item in self.ai_provenance if item.task == task), None)

    @model_validator(mode="after")
    def _migrate_v1(self) -> "Context":
        """Un contexto de 1.x (o creado a mano sin `schema_version`) pasa a 2: ejes y clasificación desde sus campos."""
        if self.schema_version >= CONTEXT_SCHEMA_VERSION:
            return self
        _migrate_context_v1(self)
        self.schema_version = CONTEXT_SCHEMA_VERSION
        return self


#: Campos de IA de un `context.json` de 1.x que pasan a `Context.ai_stats`.
_LEGACY_AI_FIELDS = frozenset(
    {
        "ai_classification_enabled",
        "ai_classification_model",
        "ai_enrichment_model",
        "ai_classification_stopped",
        "ai_documents_sent",
        "ai_documents_classified",
        "ai_documents_failed",
        "ai_enrichment_enabled",
        "ai_enrichment_stopped",
        "ai_enrichment_sent",
        "ai_enrichment_applied",
        "ai_enrichment_failed",
    }
)
#: Versión de `context.json` que escribe esta versión de doc_organize.
CONTEXT_SCHEMA_VERSION: Final = 2
#: Claves de los ejes organizadores de un contexto de 1.x (y del modo sin manifiesto).
LEGACY_FOLDER_AXIS_KEY: Final = "domains"
LEGACY_SUBFOLDER_AXIS_KEY: Final = "material_types"


def _migrate_context_v1(context: Context) -> None:
    """Rellena `taxonomy_axes` y la clasificación de los ejes organizadores de un contexto de 1.x.

    De quién vino cada eje solo se sabe a medias en 1.x (`classified_by` era del documento): el dominio es de la IA si
    ella lo propuso y las reglas no lo habían decidido; el tipo de material, si la IA intervino y el dominio no era
    suyo. Es una aproximación, solo para contextos antiguos.
    """
    folder_entries = [
        TaxonomyEntry(slug=domain.slug, name=domain.name, description=domain.description)
        for domain in context.domains
        if domain.slug != UNCLASSIFIED_SLUG
    ]
    material_names: dict[str, str] = {}
    for domain in context.domains:
        for document in domain.documents:
            if document.material_type and document.material_type != UNCLASSIFIED_SLUG:
                material_names.setdefault(document.material_type, document.material_type_name or document.material_type.replace("-", " ").title())
    if not context.taxonomy_axes and folder_entries:
        axes = [TaxonomyAxis(key=LEGACY_FOLDER_AXIS_KEY, name="Dominios", organizes="folder", entries=folder_entries)]
        if context.taxonomy_manifest_used and material_names:
            entries = [TaxonomyEntry(slug=slug, name=name) for slug, name in material_names.items()]
            axes.append(TaxonomyAxis(key=LEGACY_SUBFOLDER_AXIS_KEY, name="Tipos de material", organizes="subfolder", entries=entries))
        context.taxonomy_axes = axes
    threshold = context.ai_fallback_threshold
    for domain in context.domains:
        for document in domain.documents:
            if document.classification.axes:
                continue
            folder_by_ai = (
                document.classified_by == "ai"
                and document.ai_domain == domain.slug
                and (document.rules_domain != domain.slug or (document.rules_confidence or 0.0) < threshold)
            )
            axes_values: dict[str, list[AxisValue]] = {LEGACY_FOLDER_AXIS_KEY: []}
            if domain.slug != UNCLASSIFIED_SLUG:
                axes_values[LEGACY_FOLDER_AXIS_KEY] = [
                    AxisValue(slug=domain.slug, name=domain.name, confidence=document.confidence, classified_by="ai" if folder_by_ai else "rules")
                ]
            if context.taxonomy_manifest_used:
                material = document.material_type
                axes_values[LEGACY_SUBFOLDER_AXIS_KEY] = (
                    [
                        AxisValue(
                            slug=material,
                            name=material_names.get(material, material),
                            confidence=document.material_type_confidence if document.material_type_confidence is not None else document.confidence,
                            classified_by="ai" if document.classified_by == "ai" and not folder_by_ai else "rules",
                        )
                    ]
                    if material and material != UNCLASSIFIED_SLUG
                    else []
                )
            document.classification = DocumentClassification(axes=axes_values)


ContextChangeKind = Literal["added", "removed", "reclassified", "superseded", "excluded"]
"""Tipo de cambio de un documento entre dos construcciones del contexto (`ContextChange.change`, 1.5.0). Desde 2.0.0, un
documento que sale porque hay una versión más nueva es `superseded` y uno que excluyó una persona, `excluded` (no
`removed`)."""


class ContextChange(BaseModel):
    """Un documento que entró, salió o cambió de sitio entre la construcción anterior del contexto y esta (1.5.0).

    `domain`/`material_type` en `None` significa «sin clasificar» (o sin manifiesto, para el tipo de material). Un
    documento que pasa de clasificado a sin clasificar, o al revés, es `reclassified`; `added`/`removed` es que no
    estaba o que ya no está en ninguno de los dos.
    """

    source_path: str = Field(..., description="Ruta del documento original")
    change: ContextChangeKind = Field(..., description="`added`, `removed`, `reclassified`, `superseded` o `excluded`")
    previous_domain: str | None = Field(default=None, description="Dominio en la construcción anterior; None si sin clasificar o `added`")
    domain: str | None = Field(default=None, description="Dominio en esta construcción; None si sin clasificar o `removed`")
    previous_material_type: str | None = Field(default=None, description="Tipo de material en la construcción anterior")
    material_type: str | None = Field(default=None, description="Tipo de material en esta construcción")
    classified_by: str | None = Field(default=None, description="'rules' o 'ai' en esta construcción; None si no quedó clasificado")


class ContextBuildRecord(BaseModel):
    """Una construcción del contexto en el histórico `CONTEXT_HISTORY.jsonl` (1.5.0).

    Escrito por `ContextBuilder.build()` tras persistir el contexto; leído con
    `context.context_history.list_context_builds` y exportado con `export.write_context_history_xlsx`.
    """

    built_at: str = Field(..., description="Timestamp ISO 8601 de la construcción (`Context.updated_at`)")
    previous_built_at: str | None = Field(
        default=None,
        description=(
            "`updated_at` de la construcción con la que se compara; None si es la primera o la anterior no se pudo "
            "leer (entonces todos los documentos cuentan como `added`)"
        ),
    )
    project_name: str = Field(..., description="Proyecto del contexto")
    built_with_version: str | None = Field(default=None, description="Versión de doc_organize que construyó el contexto")
    taxonomy_manifest_used: bool = Field(default=False, description="Si se clasificó con manifiesto de taxonomía")
    ai_classification_model: str | None = Field(default=None, description="Modelo con el que se ejecutó la Sub-fase B, si se ejecutó")
    ai_enrichment_model: str | None = Field(default=None, description="Modelo con el que se ejecutó el enriquecimiento, si se ejecutó")
    classified: int = Field(..., ge=0, description="Documentos clasificados en algún dominio")
    unclassified: int = Field(..., ge=0, description="Documentos sin clasificar")
    changes: list[ContextChange] = Field(default_factory=list, description="Documentos que entraron, salieron o cambiaron de sitio")


#: Límites de un manifiesto de taxonomía (2.0.0, A1): protegen la construcción, el prompt y la web de un YAML enorme.
TAXONOMY_MAX_AXES: Final = 10
TAXONOMY_MAX_ENTRIES_PER_AXIS: Final = 150
TAXONOMY_MAX_DESCRIPTION_CHARS: Final = 500
#: Clave de un eje: también es nombre de columna en el Excel y segmento de URL en el sitio.
TAXONOMY_AXIS_KEY_PATTERN: Final = r"^[a-z][a-z0-9_]{0,40}$"

AxisOrganizes = Literal["folder", "subfolder"]


class TaxonomyEntry(BaseModel):
    """Un valor de un eje de la taxonomía (un dominio, un tipo de material, un marco normativo...).

    Attributes:
        slug (str): Identificador corto; se sanea a kebab-case antes de usarse como carpeta o clave.
        name (str): Nombre legible.
        description (str | None): Qué cubre el valor; en 2.0 se envía al modelo para desempatar.
        keywords (list[str]): Términos para la clasificación por reglas, además del slug.
        examples (list[str]): Títulos o frases de ejemplo de documentos de este valor.

    Example:
        >>> TaxonomyEntry(slug="iso-27001", name="ISO/IEC 27001", keywords=["SGSI"]).keywords
        ['SGSI']
    """

    slug: str = Field(..., min_length=1, description="Identificador corto (se sanea a kebab-case antes de usarse como segmento de carpeta)")
    name: str = Field(..., min_length=1, description="Nombre legible")
    description: str | None = Field(
        default=None, max_length=TAXONOMY_MAX_DESCRIPTION_CHARS, description="Descripción de la entrada, o `None` si no se rellenó"
    )
    keywords: list[str] = Field(default_factory=list, description="Palabras clave adicionales para la puntuación por reglas, además de `slug`")
    examples: list[str] = Field(default_factory=list, description="Ejemplos de documentos de este valor (títulos o frases)")


class TaxonomyAxis(BaseModel):
    """Un eje de la taxonomía: un catálogo cerrado de valores en el que se clasifica cada documento.

    El eje con `organizes="folder"` es el **dominio** (carpeta de la reorganización y sección del sitio) y el de
    `organizes="subfolder"` el **tipo de material** (subcarpeta). Los demás ejes (marcos normativos, sistema de
    gestión...) solo etiquetan: no cambian carpetas.

    Attributes:
        key (str): Identificador del eje (`^[a-z][a-z0-9_]{0,40}$`), único en el manifiesto.
        name (str): Nombre legible del eje.
        description (str | None): Qué clasifica el eje.
        multiple (bool): Si un documento puede tener varios valores (como mucho 5). Los ejes organizadores no.
        threshold (float | None): Confianza mínima propia del eje; `None` = el umbral de la construcción.
        rules (bool): `False` si el eje no se clasifica por palabras (solo IA o semántica).
        organizes (Literal["folder", "subfolder"] | None): Si el eje decide la carpeta o la subcarpeta.
        entries (list[TaxonomyEntry]): Valores del eje (1-150).

    Example:
        >>> axis = TaxonomyAxis(
        ...     key="normative_frameworks",
        ...     name="Marcos normativos",
        ...     multiple=True,
        ...     entries=[TaxonomyEntry(slug="ens", name="ENS")],
        ... )
        >>> axis.organizes is None
        True
    """

    key: str = Field(..., pattern=TAXONOMY_AXIS_KEY_PATTERN, description="Identificador del eje, único en el manifiesto")
    name: str = Field(..., min_length=1, description="Nombre legible del eje")
    description: str | None = Field(default=None, max_length=TAXONOMY_MAX_DESCRIPTION_CHARS, description="Qué clasifica el eje")
    multiple: bool = Field(default=False, description="Un documento puede tener varios valores del eje (como mucho 5)")
    threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="Umbral propio del eje; `None` = el de la construcción")
    rules: bool = Field(default=True, description="`False`: el eje no se clasifica por reglas (solo IA o semántica)")
    organizes: AxisOrganizes | None = Field(default=None, description="`folder` = dominio, `subfolder` = tipo de material, `None` = solo etiqueta")
    entries: list[TaxonomyEntry] = Field(..., description="Valores del eje")

    @field_validator("entries")
    @classmethod
    def _check_entries(cls, entries: list[TaxonomyEntry]) -> list[TaxonomyEntry]:
        if not entries:
            raise ValueError("un eje necesita al menos una entrada")
        if len(entries) > TAXONOMY_MAX_ENTRIES_PER_AXIS:
            raise ValueError(f"un eje admite como mucho {TAXONOMY_MAX_ENTRIES_PER_AXIS} entradas (tiene {len(entries)})")
        return entries

    @model_validator(mode="after")
    def _check_organizing(self) -> "TaxonomyAxis":
        if self.organizes is not None and self.multiple:
            raise ValueError(f"el eje '{self.key}' organiza carpetas ({self.organizes}) y no puede ser de varios valores")
        if self.organizes is not None and not self.rules:
            raise ValueError(f"el eje '{self.key}' organiza carpetas ({self.organizes}) y necesita reglas")
        return self


PROFILE_MAX_CHARS: Final = 8000
PROFILE_MAX_EXAMPLES: Final = 20


class ProjectProfile(BaseModel):
    """Lo que el modelo necesita saber del proyecto para clasificar como lo haría una persona de dentro (2.0.0, G2).

    Sale de cuatro secciones del cuerpo del manifiesto o la plantilla (`## Contexto del proyecto`, `## Reglas de
    desempate`, `## Glosario` y `## Ejemplos`) y, si existe, de `<raíz>/.doc_organize/profile.md` del proyecto, que
    **añade** a lo de la plantilla (D11). Va en el prompt, así que tiene un tope: `PROFILE_MAX_CHARS` caracteres en total
    y `PROFILE_MAX_EXAMPLES` ejemplos.

    Attributes:
        context (str | None): Qué es el proyecto y qué documentos tiene.
        tie_breakers (str | None): Cómo decidir entre dos valores parecidos («una norma publicada por ISO es referencial
            normativo aunque hable de procedimientos»).
        glossary (str | None): Siglas y términos propios.
        examples (list[str]): Ejemplos de documentos y su clasificación, uno por línea.

    Example:
        >>> ProjectProfile(context="SGSI de una empresa", examples=["Política de seguridad → gobernanza"]).is_empty
        False
    """

    context: str | None = None
    tie_breakers: str | None = None
    glossary: str | None = None
    examples: list[str] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """Sin nada que decir al modelo."""
        return not (self.context or self.tie_breakers or self.glossary or self.examples)

    def merged(self, other: "ProjectProfile | None") -> "ProjectProfile":
        """Este perfil con lo de `other` añadido detrás (D11: el del proyecto añade al de la plantilla)."""
        if other is None:
            return self

        def join(first: str | None, second: str | None) -> str | None:
            return "\n\n".join(part for part in (first, second) if part) or None

        return ProjectProfile(
            context=join(self.context, other.context),
            tie_breakers=join(self.tie_breakers, other.tie_breakers),
            glossary=join(self.glossary, other.glossary),
            examples=[*self.examples, *other.examples][:PROFILE_MAX_EXAMPLES],
        )


class TaxonomyManifest(BaseModel):
    """Manifiesto de taxonomía de un proyecto o de una plantilla: una lista de **ejes** (2.0.0).

    Se lee del front matter YAML de `<project.root_path>/taxonomy_manifest.md` o de una plantilla
    (`schema: 2` y `axes:`); el cuerpo Markdown es de lectura humana. Un front matter de 1.x (`domains`,
    `material_types`, `facets:` o ejes implícitos) se migra al leerlo (`migrate_manifest_v1`).

    Debe haber exactamente un eje `organizes="folder"` (dominio) y uno `organizes="subfolder"` (tipo de material): la
    reorganización y el sitio salen de ellos, como en 1.x. Los demás ejes solo etiquetan.

    Attributes:
        schema_version (int): Versión del formato (`schema` en el YAML); siempre 2.
        title (str | None): Título legible (plantillas compartidas).
        description (str | None): Descripción breve (plantillas compartidas).
        axes (list[TaxonomyAxis]): Ejes de la taxonomía (1-10, claves únicas).

    Example:
        >>> manifest = TaxonomyManifest(
        ...     axes=[
        ...         TaxonomyAxis(key="domains", name="Dominios", organizes="folder",
        ...                      entries=[TaxonomyEntry(slug="ciberseguridad", name="Ciberseguridad")]),
        ...         TaxonomyAxis(key="material_types", name="Tipos de material", organizes="subfolder",
        ...                      entries=[TaxonomyEntry(slug="normativa", name="Normativa")]),
        ...     ]
        ... )
        >>> manifest.folder_axis.entries[0].slug
        'ciberseguridad'
    """

    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal[2] = Field(default=2, alias="schema", description="Versión del formato del manifiesto (`schema` en el YAML)")
    title: str | None = Field(
        default=None,
        description="Título legible, solo relevante para una plantilla compartida (ver `TaxonomyTemplateRegistry`); `None` en un manifiesto de proyecto",
    )
    description: str | None = Field(
        default=None,
        description="Descripción breve, solo relevante para una plantilla compartida (ver `TaxonomyTemplateRegistry`); `None` en un manifiesto de proyecto",
    )
    axes: list[TaxonomyAxis] = Field(..., description="Ejes de la taxonomía")
    profile: ProjectProfile | None = Field(
        default=None, description="Perfil del proyecto, de las secciones del cuerpo (2.0.0, G2); `None` si no tiene"
    )

    @field_validator("axes")
    @classmethod
    def _check_axes(cls, axes: list[TaxonomyAxis]) -> list[TaxonomyAxis]:
        if len(axes) > TAXONOMY_MAX_AXES:
            raise ValueError(f"un manifiesto admite como mucho {TAXONOMY_MAX_AXES} ejes (tiene {len(axes)})")
        keys = [axis.key for axis in axes]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if repeated:
            raise ValueError(f"claves de eje repetidas: {', '.join(repeated)}")
        for organizes, label in (("folder", "dominio"), ("subfolder", "tipo de material")):
            found = [axis.key for axis in axes if axis.organizes == organizes]
            if len(found) != 1:
                detail = f"hay {len(found)}: {', '.join(found)}" if found else "no hay ninguno"
                raise ValueError(f"debe haber exactamente un eje con organizes: {organizes} ({label}); {detail}")
        return axes

    @property
    def folder_axis(self) -> TaxonomyAxis:
        """El eje que decide la carpeta (dominio)."""
        return next(axis for axis in self.axes if axis.organizes == "folder")

    @property
    def subfolder_axis(self) -> TaxonomyAxis:
        """El eje que decide la subcarpeta (tipo de material)."""
        return next(axis for axis in self.axes if axis.organizes == "subfolder")

    @property
    def tag_axes(self) -> list[TaxonomyAxis]:
        """Los ejes que solo etiquetan (sin `organizes`), en el orden del manifiesto."""
        return [axis for axis in self.axes if axis.organizes is None]

    def axis(self, key: str) -> TaxonomyAxis | None:
        """El eje de clave `key`, o `None`."""
        return next((axis for axis in self.axes if axis.key == key), None)


class FreshnessReport(BaseModel):
    """Si el contexto de un proyecto sigue al día respecto a la caché del último escaneo (2.0.0, F4).

    Lo calcula `check_context_freshness` sin leer originales ni `.json`. Las rutas son `source_path`, ordenadas.

    Attributes:
        changed (list[str]): Originales cuya huella en la caché ya no es la del contexto.
        added (list[str]): Originales convertidos que el contexto no tiene.
        removed (list[str]): Documentos del contexto que ya no están convertidos en la caché (borrados, movidos o
            que ahora fallan).
        unknown (list[str]): Documentos del contexto sin huella (construido antes de 2.0 o sin `source_sha256`):
            no se puede saber si cambiaron; reconstruir una vez lo activa.
        stale_site (bool): El sitio se generó antes de la última construcción del contexto.
        scanned_at (str | None): Cuándo se escaneó por última vez, si lo dio quien llama: el informe solo es tan
            reciente como la caché.
    """

    changed: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)
    stale_site: bool = False
    scanned_at: str | None = None

    @property
    def up_to_date(self) -> bool:
        """Sin cambios, altas, bajas ni sitio desfasado (los `unknown` no cuentan: no se sabe)."""
        return not (self.changed or self.added or self.removed or self.stale_site)


class TaxonomyFrontMatterReport(BaseModel):
    """Qué se leerá de un front matter de taxonomía, para avisar al autor (`inspect_taxonomy_front_matter`).

    Attributes:
        axes (list[str]): Claves de los ejes que se leerán, en orden.
        implicit_axes (list[str]): Las que salen del formato implícito de 1.x (claves de nivel superior con una lista
            de entradas `{slug, name}`): conviene declararlas como ejes explícitos.
        ignored_keys (list[str]): Claves de nivel superior que no se usan.
        legacy_format (bool): El front matter es de 1.x (sin `schema: 2`) y se migra al leerlo.
    """

    axes: list[str] = Field(default_factory=list, description="Claves de los ejes que se leerán")
    implicit_axes: list[str] = Field(default_factory=list, description="Ejes leídos del formato implícito de 1.x")
    ignored_keys: list[str] = Field(default_factory=list, description="Claves de nivel superior que no se usan")
    legacy_format: bool = Field(default=False, description="Front matter de 1.x, migrado al leerlo")


class TaxonomyTemplateSummary(BaseModel):
    """Entrada de listado de `TaxonomyTemplateRegistry.list_templates()`: identifica una
    plantilla de manifiesto compartida sin cargar/parsear sus catálogos completos.
    """

    name: str = Field(..., description="Nombre de la plantilla (slug del fichero, sin extensión) — el identificador que se pasa a `load_template()`")
    title: str | None = Field(default=None, description="Título legible de la plantilla (front matter `title`), o `None` si no se rellenó")
    description: str | None = Field(
        default=None, description="Descripción breve de la plantilla (front matter `description`), o `None` si no se rellenó"
    )


AiTask = Literal["classify", "enrich", "taxonomy_design", "agent", "embed", "dedup"]
"""Tareas del cliente único de IA (2.0.0, G1): clasificar ejes, enriquecer, diseñar la taxonomía, agentes, embeddings del
contexto y (2.2.0) embeddings de la búsqueda de duplicados por contenido, con su propio modelo y clave."""

AI_TASKS: Final[tuple[AiTask, ...]] = ("classify", "enrich", "taxonomy_design", "agent", "embed", "dedup")

#: Tareas que piden vectores a `/embeddings` (no `/chat/completions`).
EMBEDDING_TASKS: Final[frozenset[AiTask]] = frozenset({"embed", "dedup"})


#: Tope de tokens de la respuesta de cada tarea si no se configura otro (`TaskSettings.max_tokens`). Holgado para la
#: respuesta normal (en CALIDAD_VD, `classify` da ~350 de mediana) y suficiente para cortar las que se desbocan.
DEFAULT_MAX_TOKENS: dict[str, int] = {"classify": 1024, "enrich": 512, "taxonomy_design": 4096, "agent": 4096}


def default_model_alias(task: AiTask) -> str:
    """El alias del modelo de `task` en el LiteLLM Proxy si no se configura otro: `doc-organize-<tarea>` (recomendado,
    no obligatorio: U10).

    Example:
        >>> default_model_alias("taxonomy_design")
        'doc-organize-taxonomy-design'
    """
    return f"doc-organize-{task.replace('_', '-')}"


class TaskSettings(BaseModel):
    """Modelo y, si se quiere, clave propia de una tarea de IA (2.0.0, G1; claves por tarea opcionales, D12).

    Attributes:
        model (str): Alias del modelo en el LiteLLM Proxy (o el nombre real del modelo: los alias se recomiendan, no se
            exigen, U10).
        virtual_key (str | None): Clave propia de la tarea (presupuesto y límites aparte en el proxy); `None` = la de
            `AiSettings`.
        max_tokens (int | None): Tope de tokens de la respuesta; `None` = el de la tarea (`DEFAULT_MAX_TOKENS`). Corta
            las respuestas que se desbocan (una respuesta cortada no pasa la validación y cuenta como fallo).
        timeout_s (float | None): Timeout de cada llamada de la tarea; `None` = el de `AiSettings` (un borrador de
            taxonomía o un agente con un modelo local tardan más que una clasificación).
        retries (int | None): Reintentos de transporte de la tarea; `None` = los de `AiSettings`.
        max_documents (int | None): Documentos como mucho por construcción en la fase de la tarea (`classify`,
            `enrich`); se combina con `ContextBuilder.build(ai_max_documents=)` (manda el menor). `None` = sin tope
            propio.
    """

    model_config = ConfigDict(frozen=True)

    model: str = Field(..., min_length=1, description="Alias del modelo en el proxy para esta tarea")
    virtual_key: str | None = Field(default=None, repr=False, description="Clave propia de la tarea; None = la general")
    max_tokens: int | None = Field(default=None, gt=0, description="Tope de tokens de la respuesta; None = el de la tarea")
    timeout_s: float | None = Field(default=None, gt=0, description="Timeout de la tarea, en segundos; None = el general")
    retries: int | None = Field(default=None, ge=0, description="Reintentos de transporte de la tarea; None = los generales")
    max_documents: int | None = Field(default=None, ge=0, description="Documentos como mucho en la fase de la tarea; None = sin tope propio")


class PromptProvenance(BaseModel):
    """Con qué prompt y qué modelo se hizo una tarea de IA en una construcción (2.0.0, G1; `Context.ai_provenance`).

    Attributes:
        task (AiTask): Tarea.
        prompt_id (str): `id` del prompt.
        version (str): `version` del prompt.
        source (str): `builtin` (empaquetado) o `project` (`<raíz>/.doc_organize/prompts/`).
        sha256 (str): Huella del texto del prompt: distingue dos prompts de proyecto con el mismo `id` y `version`.
        model (str): Modelo usado.
    """

    task: AiTask
    prompt_id: str
    version: str
    source: Literal["builtin", "project"]
    sha256: str
    model: str


class AiSettings(BaseModel):
    """Configuración del cliente único de IA (`LlmClient`, 2.0.0): un proxy, una clave y un modelo por tarea.

    Sustituye a las cuatro `LiteLLM*Config` de 1.x (clasificación, clasificación por manifiesto, enriquecimiento y
    borrador). Una tarea sin entrada en `tasks` usa el alias recomendado `doc-organize-<tarea>`.

    Attributes:
        base_url (str): URL del LiteLLM Proxy.
        virtual_key (str): Clave general (las tareas pueden tener la suya).
        tasks (dict[AiTask, TaskSettings]): Modelo (y clave) por tarea.
        timeout_s (float): Timeout de cada llamada; un modelo local en frío puede tardar (M0: 47 s).
        retries, retry_backoff_s, rate_limit_retries, max_retry_wait_s: Reintentos (ver `AiHttpClientBase`).
        redact_credentials (bool): Redactar credenciales de todo lo que sale (D7); por defecto activado.
        tags (list[str]): Etiquetas para el proxy (`metadata.tags`), además de `doc_organize` y `task:<tarea>`.

    Example:
        >>> settings = AiSettings(base_url="http://localhost:4000", virtual_key="sk-x", tasks={"classify": TaskSettings(model="qwen")})
        >>> settings.model_for("classify"), settings.model_for("enrich")
        ('qwen', 'doc-organize-enrich')
    """

    model_config = ConfigDict(frozen=True)

    base_url: str = Field(..., min_length=1, description="URL del LiteLLM Proxy")
    virtual_key: str = Field(..., min_length=1, repr=False, description="Clave general del proxy")
    tasks: dict[AiTask, TaskSettings] = Field(default_factory=dict, description="Modelo y clave por tarea")
    timeout_s: float = Field(default=120.0, gt=0, description="Timeout de cada llamada, en segundos")
    retries: int = Field(default=0, ge=0, description=_HTTP_RETRIES_DESC)
    retry_backoff_s: float = Field(default=0.5, ge=0.0, description=_HTTP_RETRY_BACKOFF_DESC)
    rate_limit_retries: int = Field(default=3, ge=0, description=_HTTP_RATE_LIMIT_RETRIES_DESC)
    max_retry_wait_s: float = Field(default=60.0, ge=0.0, description=_HTTP_MAX_RETRY_WAIT_DESC)
    redact_credentials: bool = Field(default=True, description="Redactar credenciales de todo lo que sale hacia la IA (D7)")
    tags: list[str] = Field(default_factory=list, description="Etiquetas para el proxy (`metadata.tags`)")

    def model_for(self, task: AiTask) -> str:
        """El modelo de `task`: el configurado o el alias recomendado (`default_model_alias`)."""
        configured = self.tasks.get(task)
        return configured.model if configured is not None else default_model_alias(task)

    def timeout_for(self, task: AiTask) -> float:
        """El timeout de `task`: el suyo o el general."""
        configured = self.tasks.get(task)
        return configured.timeout_s if configured is not None and configured.timeout_s is not None else self.timeout_s

    def retries_for(self, task: AiTask) -> int:
        """Los reintentos de transporte de `task`: los suyos o los generales."""
        configured = self.tasks.get(task)
        return configured.retries if configured is not None and configured.retries is not None else self.retries

    def max_documents_for(self, task: AiTask) -> int | None:
        """El tope de documentos propio de la fase de `task`, o `None`."""
        configured = self.tasks.get(task)
        return configured.max_documents if configured is not None else None

    def key_for(self, task: AiTask) -> str:
        """La clave de `task`: la suya si la tiene, si no la general."""
        configured = self.tasks.get(task)
        return configured.virtual_key if configured is not None and configured.virtual_key else self.virtual_key

    def max_tokens_for(self, task: AiTask) -> int | None:
        """El tope de tokens de la respuesta de `task`: el configurado o el de la tarea (`DEFAULT_MAX_TOKENS`).

        Example:
            >>> AiSettings(base_url="http://proxy", virtual_key="sk").max_tokens_for("classify")
            1024
        """
        configured = self.tasks.get(task)
        if configured is not None and configured.max_tokens is not None:
            return configured.max_tokens
        return DEFAULT_MAX_TOKENS.get(task)


class TaxonomyManifestDraftResult(BaseModel):
    """Resultado de pedir a la IA un borrador de manifiesto de taxonomía (dominios + tipos de
    material) a partir de una muestra de documentos ya convertidos (`doc_organize.ai.draft_taxonomy`).

    A diferencia de la clasificación (`classify_document`, elige DENTRO de un catálogo ya
    confirmado), aquí el catálogo mismo es la propuesta — nunca se aplica directamente, el
    usuario lo revisa/edita antes de guardarlo como `taxonomy_manifest.md`.
    """

    domains: list[TaxonomyEntry] = Field(..., min_length=1, description="Catálogo de dominios propuesto por la IA")
    material_types: list[TaxonomyEntry] = Field(..., min_length=1, description="Catálogo de tipos de material propuesto por la IA")
    profile: ProjectProfile | None = Field(default=None, description="Perfil inicial del proyecto propuesto por la IA (2.0.0)")
    reasoning: str | None = Field(default=None, description="Justificación breve devuelta por el modelo, si la reporta")

    def to_manifest(self) -> TaxonomyManifest:
        """El borrador como manifiesto v2: eje `domains` (carpeta), eje `material_types` (subcarpeta) y su perfil.

        Example:
            >>> draft = TaxonomyManifestDraftResult(
            ...     domains=[TaxonomyEntry(slug="calidad", name="Calidad")],
            ...     material_types=[TaxonomyEntry(slug="procedimiento", name="Procedimiento")],
            ... )
            >>> tuple(axis.key for axis in draft.to_manifest().axes)
            ('domains', 'material_types')
        """
        return TaxonomyManifest(
            axes=[
                TaxonomyAxis(key="domains", name="Dominios", organizes="folder", entries=self.domains),
                TaxonomyAxis(key="material_types", name="Tipos de material", organizes="subfolder", entries=self.material_types),
            ],
            profile=self.profile,
        )


class DocumentEnrichmentResult(BaseModel):
    """Descripción y palabras clave que propone la IA para un documento (`doc_organize.ai.enrich_document`).

    Ya saneadas por el cliente: una línea, longitud acotada y sin repetidos; `None`/lista vacía si el modelo no dio
    un valor utilizable.
    """

    description: str | None = Field(default=None, description="Descripción de 1-2 frases, o `None`")
    keywords: list[str] = Field(default_factory=list, description="Palabras clave, o lista vacía")


Context.model_rebuild()  # `taxonomy_axes` y `ai_provenance` usan modelos definidos después

__all__ = [
    "AI_TASKS",
    "CONTEXT_SCHEMA_VERSION",
    "DEFAULT_MAX_TOKENS",
    "EMBEDDING_TASKS",
    "LEGACY_FOLDER_AXIS_KEY",
    "LEGACY_SUBFOLDER_AXIS_KEY",
    "AiClassificationStopReason",
    "AiPhaseStats",
    "AiScope",
    "AiSettings",
    "AiStats",
    "AiTask",
    "AvStatus",
    "AxisClassifiedBy",
    "AxisValue",
    "CacheConfig",
    "CacheEntry",
    "CacheExportSnapshot",
    "ClassificationDecision",
    "Context",
    "ContextBuildEvent",
    "ContextBuildEventType",
    "ContextBuildRecord",
    "ContextChange",
    "ContextChangeKind",
    "ContextDeleteEvent",
    "ContextDeleteEventType",
    "ConversionResult",
    "ConversionStatus",
    "DecisionAction",
    "DecisionIssue",
    "DecisionIssueReason",
    "DedupEvent",
    "DedupEventType",
    "DeduplicationReport",
    "DirectoryTree",
    "DirectoryTreeNode",
    "DoclingConfig",
    "DocumentClassification",
    "DocumentCredentialFindings",
    "DocumentEnrichmentField",
    "DocumentEnrichmentResult",
    "DocumentMetadata",
    "DocumentStatus",
    "DocumentVersionGroup",
    "Domain",
    "DomainDocument",
    "DomainStatus",
    "DuplicateGroup",
    "DuplicateReason",
    "EnvironmentCheck",
    "EnvironmentCheckStatus",
    "EnvironmentReport",
    "FreshnessReport",
    "GitHubCopilotUsageConfig",
    "GpuStatus",
    "LiteLLMUsageConfig",
    "OcrMode",
    "OfficeStatus",
    "Project",
    "ProjectNameValidation",
    "ProjectProfile",
    "PromptProvenance",
    "ScanErrorEntry",
    "ScanErrorReport",
    "ScanEvent",
    "ScanEventType",
    "ScanResult",
    "ScanRunReport",
    "ScannedFolder",
    "TaskSettings",
    "TaxonomyAxis",
    "TaxonomyEntry",
    "TaxonomyFrontMatterReport",
    "TaxonomyManifest",
    "UnclassifiedDocument",
    "UnclassifiedReason",
    "UsageLineItem",
    "UsageSnapshot",
    "UsageSourceName",
    "ValidationResult",
    "VersionsMode",
]
