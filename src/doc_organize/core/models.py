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

from enum import Enum
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME

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
    """Motivo por el que se agrupan documentos como duplicados."""

    EXACT_DUPLICATE = "exact_duplicate"
    VERSION_CONFLICT = "version_conflict"
    FUZZY_NAME_MATCH = "fuzzy_name_match"


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

    @classmethod
    def from_cache_entry(cls, entry: "CacheEntry") -> "DocumentMetadata":
        """Metadatos de un documento a partir de su entrada de caché, sin leer ni rehashear el fichero (G25, 1.1.0).

        Pensado para buscar duplicados con `DeduplicationManager.find_duplicates` desde la caché. `display_name` es
        el nombre del fichero y `extension` su sufijo en minúsculas, como los calcula `DocumentScanner`.

        Args:
            entry: Entrada guardada por un escaneo de 1.1.0 o posterior (con `size_bytes`).

        Returns:
            DocumentMetadata con el hash, el tamaño y la fecha de modificación de la caché.

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
    "Reintentos ante timeout o error de red/transporte (nunca ante una respuesta HTTP, ni 4xx ni 5xx); 0 (por defecto) "
    "no reintenta. Ojo: reintentar un POST que hizo timeout puede cobrarse dos veces si el proxy sí lo recibió (L-3b)"
)
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

    gpu_support_installed: bool = Field(..., description="Si `torch` (extra `ocr-gpu`) está instalado en este entorno")
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


class UsageLineItem(BaseModel):
    """Una línea de consumo dentro de un `UsageSnapshot`.

    Normaliza tanto `usageItems[]` de la API de Billing Usage de GitHub
    (`quantity`, `unitType`, `netAmount`) como la respuesta de spend de un
    LiteLLM Proxy, para que ambas fuentes se listen de forma uniforme.
    """

    date: str = Field(..., description="Fecha (ISO 8601) de la línea de consumo")
    product: str = Field(..., description="Producto facturado, p.ej. 'copilot' o 'anthropic'")
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
        ..., description="Virtual key del proxy: se usa como Bearer de autenticación y, por defecto, como key consultada en `get_usage()`"
    )
    timeout_s: float = Field(default=30.0, description=_HTTP_TIMEOUT_DESC)
    retries: int = Field(default=0, ge=0, description=_HTTP_RETRIES_DESC)
    retry_backoff_s: float = Field(default=0.5, ge=0.0, description=_HTTP_RETRY_BACKOFF_DESC)


class GitHubCopilotUsageConfig(BaseModel):
    """Configuración de acceso a la API de Billing Usage de GitHub para Copilot Pro.

    Igual criterio que `LiteLLMUsageConfig`: usa
    `github_copilot_usage_config_from_env()` (`doc_organize.ai`) para resolver
    `DOC_ORGANIZE_GITHUB_USERNAME`/`DOC_ORGANIZE_GITHUB_PAT` explícitamente.
    """

    username: str = Field(..., description="Usuario personal de GitHub cuyo consumo de Copilot se consulta")
    personal_access_token: str = Field(
        ..., description="PAT con permiso de lectura de facturación personal (scope exacto sin confirmar, ver AUDIT_PLAN)"
    )
    timeout_s: float = Field(default=30.0, description=_HTTP_TIMEOUT_DESC)
    retries: int = Field(default=0, ge=0, description=_HTTP_RETRIES_DESC)
    retry_backoff_s: float = Field(default=0.5, ge=0.0, description=_HTTP_RETRY_BACKOFF_DESC)


# ===== Modelos de contexto y dominios (organización documental, `doc_organize.context`) =====


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
            "`TaxonomyManifest.material_types`), o `None` en modo sin manifiesto de taxonomía"
        ),
    )
    material_type_name: str | None = Field(
        default=None,
        description=(
            "Nombre legible de `material_type` (`TaxonomyCatalogEntry.name` del manifiesto), o `None` si "
            "`material_type` es el placeholder `sin-clasificar` o no hay manifiesto — el llamador (p. ej. "
            "`SiteGenerator`) recurre entonces a derivar una etiqueta a partir del slug"
        ),
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Score de confianza de la clasificación, 0-1")
    classified_by: str = Field(default="rules", description="'rules' (Sub-fase A) o 'ai' (Sub-fase B) según qué clasificó el documento")
    organized_path: str | None = Field(
        default=None,
        description=(
            "Ruta POSIX del `.md` copiado, relativa a la carpeta reorganizada (`<dominio>/<tipo>/<carpeta>/<stem>.md`), "
            "o `None` si aún no se ha calculado (contextos de antes de 0.14.0). La rellenan `ContextBuilder` y "
            "`Reorganizer` con `resolve_organized_paths` (L-8d); solo informativa: `Reorganizer`/`SiteGenerator` la "
            "recalculan siempre y nunca usan el valor leído de `index.json`"
        ),
    )


class Domain(BaseModel):
    """Un dominio documental dentro del `Context` de un proyecto."""

    slug: str = Field(..., description="Identificador corto del dominio (kebab-case)")
    name: str = Field(..., description="Nombre legible del dominio")
    description: str | None = Field(default=None, description="Descripción del dominio, o `None` si no se ha rellenado todavía")
    status: DomainStatus = Field(default=DomainStatus.DRAFT, description="Estado del dominio")
    predefined: bool = Field(default=False, description="Si el dominio fue predefinido por el usuario (catálogo) o descubierto automáticamente")
    documents: list[DomainDocument] = Field(default_factory=list, description="Documentos clasificados en este dominio")


AiClassificationStopReason = Literal["auth", "connection", "budget"]
"""Motivo por el que `ContextBuilder.build()` detuvo la Sub-fase B (`Context.ai_classification_stopped`, L-3a/L-3b)."""


class Context(BaseModel):
    """Contexto de organización documental de un proyecto: configuración de clasificación + dominios.

    Persistido por `ContextRegistry` en `<project.root_path>/context.json` (metadatos +
    resumen de dominios) más `<project.root_path>/domains/<slug>/{DOMAIN.md,index.json}`
    por dominio (ver §3 del `00_REQUEST.md` de la sesión que originó este modelo).

    Sin `tenant_id` desde 1.0.0 (L-12): un `context.json` antiguo que lo traiga se sigue leyendo y el campo se ignora.
    """

    project_name: str = Field(..., description="Nombre del proyecto propietario de este contexto")
    output_folder_name: str = Field(default="organizado", description="Nombre de la carpeta de salida reorganizada, relativa a `root_path`")
    ai_classification_enabled: bool = Field(default=False, description="Si la Sub-fase B (IA) está activa para este proyecto — opt-in explícito")
    ai_fallback_threshold: float = Field(default=0.5, description="Score mínimo (Sub-fase A) por debajo del cual se intenta la Sub-fase B")
    ai_classification_model: str | None = Field(
        default=None, description="Alias de modelo del LiteLLM Proxy a usar en la Sub-fase B, o `None` para el valor por defecto"
    )
    domains: list[Domain] = Field(default_factory=list, description="Dominios detectados/confirmados")
    unclassified_documents: list[str] = Field(
        default_factory=list,
        description="`source_path` de documentos sin clasificar (score insuficiente, artefactos incompletos, o IA deshabilitada)",
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
    ai_classification_stopped: AiClassificationStopReason | None = Field(
        default=None,
        description=(
            "Por qué se detuvo la Sub-fase B antes de terminar (L-3a/L-3b): `auth` (clave rechazada, 401/403), "
            "`connection` (`ai_max_failures` errores de conexión seguidos) o `budget` (se alcanzó `ai_max_documents`); "
            "`None` si terminó o no se ejecutó. Los documentos que no llegaron a enviarse quedan sin clasificar"
        ),
    )
    ai_documents_sent: int = Field(default=0, ge=0, description="Documentos enviados a la IA en la Sub-fase B (una llamada por documento, L-3c)")
    ai_documents_classified: int = Field(
        default=0, ge=0, description="Documentos enviados a los que la IA asignó al menos un eje del catálogo (L-3c)"
    )
    ai_documents_failed: int = Field(
        default=0,
        ge=0,
        description=(
            "Documentos enviados cuya llamada falló (auth, conexión u otro error, L-3c); `sent = classified + failed + enviados sin asignación`"
        ),
    )
    created_at: str = Field(..., description="Timestamp ISO 8601 de creación del contexto")
    updated_at: str = Field(..., description="Timestamp ISO 8601 de la última reconstrucción del contexto")

    @field_validator("output_folder_name")
    @classmethod
    def _validate_output_folder_name(cls, value: str) -> str:
        """L-8f (G32): mismo criterio que `validate_output_folder_name`; un `context.json` manipulado ("..", una ruta
        absoluta, un nombre reservado) no se carga en vez de usarse para copiar y borrar."""
        # Importación diferida: `projects.layout` importa este módulo (evita el ciclo).
        from doc_organize.core.exceptions import InvalidPathError
        from doc_organize.projects.layout import validate_output_folder_name

        try:
            return validate_output_folder_name(value)
        except InvalidPathError as exc:
            raise ValueError(str(exc)) from exc


class DomainClassificationResult(BaseModel):
    """Resultado de clasificar un documento por IA (Sub-fase B, `DomainClassificationClient`)."""

    domain: str | None = Field(default=None, description="Slug del dominio elegido del catálogo, o `None` si no encaja en ninguno")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confianza reportada por el modelo, 0-1")
    reasoning: str | None = Field(default=None, description="Justificación breve devuelta por el modelo, si la reporta")


class TaxonomyCatalogEntry(BaseModel):
    """Una entrada del catálogo de un `TaxonomyManifest` (un dominio o un tipo de material de origen)."""

    slug: str = Field(..., min_length=1, description="Identificador corto (se sanea a kebab-case antes de usarse como segmento de carpeta)")
    name: str = Field(..., min_length=1, description="Nombre legible")
    description: str | None = Field(default=None, description="Descripción de la entrada, o `None` si no se rellenó")
    keywords: list[str] = Field(default_factory=list, description="Palabras clave adicionales para la puntuación por reglas, además de `slug`")


class TaxonomyManifest(BaseModel):
    """Manifiesto de taxonomía documental de un proyecto: catálogos de dominios y de tipos de material de origen.

    Se lee del front matter YAML de `<project.root_path>/taxonomy_manifest.md` (ver
    `doc_organize.context.taxonomy_manifest.load_taxonomy_manifest`) — el cuerpo Markdown
    del fichero (prosa, tablas, diagramas) es de lectura humana y no se parsea. Cuando un
    proyecto tiene manifiesto, `ContextBuilder` clasifica cada documento en dos ejes
    (dominio + tipo de material) en vez del único eje de dominio del modo sin manifiesto.

    Attributes:
        domains (list[TaxonomyCatalogEntry]): Catálogo cerrado de dominios normativos.
        material_types (list[TaxonomyCatalogEntry]): Catálogo cerrado de tipos de material de origen.

    Example:
        >>> TaxonomyManifest(
        ...     domains=[TaxonomyCatalogEntry(slug="ciberseguridad", name="Ciberseguridad")],
        ...     material_types=[TaxonomyCatalogEntry(slug="normativa", name="Normativa")],
        ... ).domains[0].slug
        'ciberseguridad'
    """

    title: str | None = Field(
        default=None,
        description="Título legible, solo relevante para una plantilla compartida (ver `TaxonomyTemplateRegistry`); `None` en un manifiesto de proyecto",
    )
    description: str | None = Field(
        default=None,
        description="Descripción breve, solo relevante para una plantilla compartida (ver `TaxonomyTemplateRegistry`); `None` en un manifiesto de proyecto",
    )
    domains: list[TaxonomyCatalogEntry] = Field(..., min_length=1, description="Catálogo cerrado de dominios normativos")
    material_types: list[TaxonomyCatalogEntry] = Field(..., min_length=1, description="Catálogo cerrado de tipos de material de origen")


class TaxonomyTemplateSummary(BaseModel):
    """Entrada de listado de `TaxonomyTemplateRegistry.list_templates()`: identifica una
    plantilla de manifiesto compartida sin cargar/parsear sus catálogos completos.
    """

    name: str = Field(..., description="Nombre de la plantilla (slug del fichero, sin extensión) — el identificador que se pasa a `load_template()`")
    title: str | None = Field(default=None, description="Título legible de la plantilla (front matter `title`), o `None` si no se rellenó")
    description: str | None = Field(
        default=None, description="Descripción breve de la plantilla (front matter `description`), o `None` si no se rellenó"
    )


class LiteLLMClassificationConfig(BaseModel):
    """Configuración de acceso al LiteLLM Proxy para `DomainClassificationClient` (Sub-fase B).

    Config propia, no comparte campos ni credenciales con `LiteLLMUsageConfig` (ISP —
    ver §2.5 de `00_REQUEST.md`) aunque en despliegue pueda apuntar a la misma URL de proxy.
    """

    base_url: str = Field(..., description="URL base del LiteLLM Proxy")
    virtual_key: str = Field(..., description="Virtual key con permiso de `chat/completions` para clasificación")
    model: str = Field(default="claude-classifier", description="Alias de modelo configurado en el proxy para clasificar")
    timeout_s: float = Field(default=30.0, description=_HTTP_TIMEOUT_DESC)
    retries: int = Field(default=0, ge=0, description=_HTTP_RETRIES_DESC)
    retry_backoff_s: float = Field(default=0.5, ge=0.0, description=_HTTP_RETRY_BACKOFF_DESC)


class TaxonomyClassificationResult(BaseModel):
    """Resultado de clasificar un documento por IA en los 2 ejes de un manifiesto de taxonomía
    (Sub-fase B combinada, `TaxonomyClassificationClient`) — una sola llamada para dominio y
    tipo de material de origen, en vez de dos llamadas independientes (decisión de la sesión que
    añadió este cliente)."""

    domain: str | None = Field(default=None, description="Slug del dominio elegido del catálogo, o `None` si no encaja en ninguno")
    domain_confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confianza reportada por el modelo para el eje de dominio, 0-1")
    material_type: str | None = Field(default=None, description="Slug del tipo de material elegido del catálogo, o `None` si no encaja en ninguno")
    material_type_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Confianza reportada por el modelo para el eje de tipo de material, 0-1"
    )
    reasoning: str | None = Field(default=None, description="Justificación breve devuelta por el modelo, si la reporta")


class LiteLLMTaxonomyClassificationConfig(BaseModel):
    """Configuración de acceso al LiteLLM Proxy para `TaxonomyClassificationClient` (Sub-fase B,
    manifiesto de taxonomía).

    Config propia, no comparte campos ni credenciales con `LiteLLMClassificationConfig` (ISP —
    mismo criterio que ya separa esa de `LiteLLMUsageConfig`): la clasificación combinada de 2 ejes
    es una carga de trabajo distinta de la clasificación de dominio de 1 eje, aunque en despliegue
    ambas puedan apuntar al mismo LiteLLM Proxy.
    """

    base_url: str = Field(..., description="URL base del LiteLLM Proxy")
    virtual_key: str = Field(..., description="Virtual key con permiso de `chat/completions` para clasificación por manifiesto")
    model: str = Field(default="claude-classifier", description="Alias de modelo configurado en el proxy para clasificar por manifiesto")
    timeout_s: float = Field(default=30.0, description=_HTTP_TIMEOUT_DESC)
    retries: int = Field(default=0, ge=0, description=_HTTP_RETRIES_DESC)
    retry_backoff_s: float = Field(default=0.5, ge=0.0, description=_HTTP_RETRY_BACKOFF_DESC)


class TaxonomyManifestDraftResult(BaseModel):
    """Resultado de pedir a la IA un borrador de manifiesto de taxonomía (dominios + tipos de
    material) a partir de una muestra de documentos ya convertidos (`TaxonomyManifestDraftClient`).

    A diferencia de `TaxonomyClassificationResult` (Sub-fase B, elige DENTRO de un catálogo ya
    confirmado), aquí el catálogo mismo es la propuesta — nunca se aplica directamente, el
    usuario lo revisa/edita antes de guardarlo como `taxonomy_manifest.md`.
    """

    domains: list[TaxonomyCatalogEntry] = Field(..., min_length=1, description="Catálogo de dominios propuesto por la IA")
    material_types: list[TaxonomyCatalogEntry] = Field(..., min_length=1, description="Catálogo de tipos de material propuesto por la IA")
    reasoning: str | None = Field(default=None, description="Justificación breve devuelta por el modelo, si la reporta")


class LiteLLMTaxonomyManifestDraftConfig(BaseModel):
    """Configuración de acceso al LiteLLM Proxy para `TaxonomyManifestDraftClient`.

    Config propia (ISP, mismo criterio que separa `LiteLLMClassificationConfig` de
    `LiteLLMTaxonomyClassificationConfig`): proponer un catálogo nuevo es una carga de trabajo
    distinta de clasificar dentro de uno ya cerrado, aunque en despliegue las tres puedan apuntar
    al mismo LiteLLM Proxy.
    """

    base_url: str = Field(..., description="URL base del LiteLLM Proxy")
    virtual_key: str = Field(..., description="Virtual key con permiso de `chat/completions` para proponer manifiestos de taxonomía")
    model: str = Field(default="claude-classifier", description="Alias de modelo configurado en el proxy para proponer manifiestos")
    timeout_s: float = Field(
        default=60.0,
        description="Timeout de las peticiones HTTP, en segundos (más alto que el resto: el prompt incluye varios documentos a la vez, no uno solo)",
    )
    retries: int = Field(default=0, ge=0, description=_HTTP_RETRIES_DESC)
    retry_backoff_s: float = Field(default=0.5, ge=0.0, description=_HTTP_RETRY_BACKOFF_DESC)


__all__ = [
    "AiClassificationStopReason",
    "AvStatus",
    "CacheConfig",
    "CacheEntry",
    "CacheExportSnapshot",
    "Context",
    "ContextBuildEvent",
    "ContextBuildEventType",
    "ContextDeleteEvent",
    "ContextDeleteEventType",
    "ConversionResult",
    "ConversionStatus",
    "DedupEvent",
    "DedupEventType",
    "DeduplicationReport",
    "DirectoryTree",
    "DirectoryTreeNode",
    "DoclingConfig",
    "DocumentMetadata",
    "DocumentStatus",
    "Domain",
    "DomainClassificationResult",
    "DomainDocument",
    "DomainStatus",
    "DuplicateGroup",
    "DuplicateReason",
    "GitHubCopilotUsageConfig",
    "GpuStatus",
    "LiteLLMClassificationConfig",
    "LiteLLMTaxonomyClassificationConfig",
    "LiteLLMTaxonomyManifestDraftConfig",
    "LiteLLMUsageConfig",
    "OcrMode",
    "OfficeStatus",
    "Project",
    "ProjectNameValidation",
    "ScanErrorEntry",
    "ScanErrorReport",
    "ScanEvent",
    "ScanEventType",
    "ScanResult",
    "ScanRunReport",
    "ScannedFolder",
    "TaxonomyCatalogEntry",
    "TaxonomyClassificationResult",
    "TaxonomyManifest",
    "UsageLineItem",
    "UsageSnapshot",
    "UsageSourceName",
    "ValidationResult",
]
