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
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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
    OCR_PROCESSED = "ocr_processed"
    COMPLETED = "completed"


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


# ===== Modelos Pydantic (API / serialización JSON) =====


class DocumentMetadata(BaseModel):
    """Metadatos de un fichero de documento descubierto."""

    full_path: str = Field(..., description="Ruta absoluta al fichero del documento")
    display_name: str = Field(..., description="Nombre para mostrar en la UI (gestiona unicidad)")
    extension: str = Field(..., description="Extensión del fichero (p. ej. 'pdf', 'docx')")
    size_bytes: int = Field(..., description="Tamaño del fichero en bytes")
    modified_time: float = Field(..., description="Timestamp Unix de la última modificación")
    sha256_hash: str = Field(..., description="Hash SHA-256 (cadena hexadecimal de 64 caracteres)")

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
    markdown_path: str | None = Field(None, description="Ruta al fichero .md de salida")
    json_path: str | None = Field(None, description="Ruta al fichero .json de metadatos de salida")
    success: bool = Field(..., description="Si la conversión tuvo éxito")
    error: str | None = Field(None, description="Mensaje de error si falló")
    ocr_required: bool = Field(False, description="Si se necesitó OCR (y quedó diferido)")
    duration_seconds: float = Field(0.0, description="Tiempo empleado en convertir (segundos)")
    images_dir: str | None = Field(
        None,
        description="Carpeta con las imágenes extraídas del documento (subcarpeta de 'img' por documento), si `extract_images=True` y el documento generó alguna",
    )
    picture_description_applied: bool = Field(
        False,
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
    user_choice: DocumentMetadata | None = Field(None, description="Selección del usuario si sobrescribe la elección por defecto")

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


class DeduplicationReport(BaseModel):
    """Resultado del proceso de deduplicación."""

    timestamp: str = Field(..., description="Timestamp ISO 8601 de cuándo se ejecutó la deduplicación")
    total_exact_duplicates: int = Field(..., description="Número de ficheros duplicados exactos movidos")
    total_version_conflicts: int = Field(..., description="Número de conflictos de versión resueltos")
    duplicates_folder_path: str = Field(..., description="Ruta a la carpeta donde se movieron los duplicados")
    audit_json_path: str = Field(..., description="Ruta al fichero DEDUP_REPORT.json")
    groups: list[DuplicateGroup] = Field(default_factory=list, description="Grupos detallados")
    started_at: str | None = Field(None, description="Timestamp ISO 8601 de inicio de esta ejecución (None en históricos previos a este campo)")
    duration_seconds: float | None = Field(None, description="Tiempo total transcurrido entre inicio y fin (None en históricos previos a este campo)")
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
    timestamp: float = Field(..., description="Timestamp Unix de la última actualización de la entrada")
    status: DocumentStatus = Field(..., description="Estado del documento (new/unchanged/modified/deleted)")
    conversion_status: ConversionStatus | None = Field(None, description="Estado de progreso de la conversión")
    error_message: str | None = Field(None, description="Mensaje de error de la última conversión fallida")
    error_retry_count: int = Field(0, description="Fallos consecutivos sin cambios en el fichero (0 si el último intento tuvo éxito)")


class ScanErrorEntry(BaseModel):
    """Un documento cuya conversión/OCR falló en una ejecución de escaneo concreta."""

    file_path: str = Field(..., description="Ruta absoluta al fichero que falló")
    error_message: str = Field(..., description="Mensaje de error capturado")
    error_retry_count: int = Field(..., description="Fallos consecutivos acumulados en este fichero, incluido este")
    capped: bool = Field(
        False,
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
        None, description="Tiempo empleado en descubrir/hashear ficheros (None en históricos previos a este campo)"
    )
    total_conversion_seconds: float | None = Field(
        None, description="Suma de la duración de conversión de cada documento procesado, incluido OCR (None en históricos previos a este campo)"
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
    size_bytes: int | None = Field(None, description="Tamaño del fichero (si type='file')")
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


class ScanEvent(BaseModel):
    """Un evento de progreso emitido por `ScanCommand.run_streaming()` (Fase D-2b, §2.7.3).

    Deliberadamente un payload `dict[str, Any]` laxo en vez de un modelo por tipo de
    evento: las formas difieren lo suficiente (contadores del resumen final frente a
    la ruta/éxito de un único fichero) como para que un tipado más estricto supusiera
    un modelo por `ScanEventType` con poco beneficio en esta etapa. Los consumidores
    (CLI, WebSocket) usan `event` para interpretar `data`.
    """

    event: ScanEventType = Field(..., description="Tipo de evento de progreso")
    data: dict[str, Any] = Field(default_factory=dict, description="Payload del evento; su forma depende de `event`")


class DedupEvent(BaseModel):
    """Un evento de progreso emitido por `ScanCommand.deduplicate_streaming()`.

    Mismo criterio que `ScanEvent`: payload `dict[str, Any]` laxo en vez de un
    modelo por tipo de evento.
    """

    event: DedupEventType = Field(..., description="Tipo de evento de progreso")
    data: dict[str, Any] = Field(default_factory=dict, description="Payload del evento; su forma depende de `event`")


class ValidationResult(BaseModel):
    """Resultado de la validación de carpetas."""

    is_valid: bool = Field(..., description="Si las carpetas son válidas (sin redundancia)")
    warnings: list[str] = Field(default_factory=list, description="Lista de avisos")
    clean_paths: list[str] = Field(..., description="Rutas validadas, sin redundancia")


class Project(BaseModel):
    """Un proyecto de doc_organize: una carpeta de trabajo con nombre que agrega el estado de scan/convert/dedup/cache (REQ-008).

    `tenant_id` vale `"default"` por defecto (revisión 8, §2.7.2): los proyectos creados
    vía CLI o una sesión web loopback/sin auth viven todos en este tenant implícito, y
    cualquier entrada del registro escrita antes de la revisión 8 (sin el campo) se
    parsea también como `"default"` — sin necesidad de script de migración. La
    unicidad del nombre de proyecto es por tenant (ver `ProjectRegistry.create_project`),
    no global.
    """

    name: str = Field(..., description="Nombre único del proyecto dentro de su tenant (validado por ProjectValidator)")
    root_path: str = Field(..., description="Ruta absoluta a la carpeta de trabajo del proyecto")
    created_at: str = Field(..., description="Timestamp ISO 8601 de creación del proyecto")
    tenant_id: str = Field(default="default", description="Tenant propietario (por defecto el tenant implícito 'default')")


_ISO_TIMESTAMP_DESC = "Timestamp ISO 8601 de creación"


class Tenant(BaseModel):
    """Una organización/espacio de trabajo que agrupa usuarios y proyectos (revisión 8, §2.7.2)."""

    id: str = Field(..., description="Identificador del tenant (slug), derivado de su nombre")
    name: str = Field(..., description="Nombre legible del tenant")
    created_at: str = Field(..., description=_ISO_TIMESTAMP_DESC)


class Role(BaseModel):
    """Un conjunto de permisos con nombre dentro de un tenant (revisión 9, roles y gestión de usuarios).

    `is_admin=True` ve todos los proyectos del tenant, presentes y futuros —
    `project_names` debe entonces estar vacío (impuesto por `AuthStore.create_role`/
    `update_role`, no por este modelo, para que el modelo siga siendo un simple
    contenedor de datos). Un rol no-admin solo ve los proyectos listados en
    `project_names`.
    """

    id: str = Field(..., description="UUID4 del rol")
    tenant_id: str = Field(..., description="Tenant al que pertenece este rol")
    name: str = Field(..., description="Único dentro del tenant (no globalmente)")
    is_admin: bool = Field(default=False, description="Si este rol ve todos los proyectos del tenant")
    project_names: list[str] = Field(default_factory=list, description="Proyectos a los que este rol puede acceder (se ignora si is_admin)")
    allowed_scan_roots: list[str] = Field(
        default_factory=list,
        description=(
            "Raíces del sistema de ficheros que este rol puede escanear vía /api/projects/{name}/scan "
            "(se ignora si is_admin, que puede escanear cualquier ruta). Vacío significa que no puede "
            "escanear ninguna carpeta externa — un rol restringido no puede eludir su project_names "
            "apuntando el escaneo a una ruta arbitraria del servidor."
        ),
    )
    created_at: str = Field(..., description=_ISO_TIMESTAMP_DESC)


class User(BaseModel):
    """Un usuario que pertenece exactamente a un tenant y exactamente a un rol (revisión 8 §2.7.2, revisión 9).

    Nunca incluye el hash/salt de la contraseña: esos campos viven solo en
    `auth.db` (AuthStore), así que ningún endpoint puede serializarlos
    accidentalmente en una respuesta JSON.
    """

    id: str = Field(..., description="UUID4 del usuario")
    tenant_id: str = Field(..., description="Tenant al que pertenece este usuario")
    username: str = Field(..., description="Único dentro del tenant (no globalmente)")
    role_id: str = Field(..., description="Rol asignado a este usuario (revisión 9)")
    must_change_password: bool = Field(
        default=False, description="True hasta que el usuario cambie una contraseña asignada por bootstrap (revisión 9)"
    )
    created_at: str = Field(..., description=_ISO_TIMESTAMP_DESC)


class Session(BaseModel):
    """Una sesión de navegador activa, creada al hacer login (revisión 8, §2.7.2)."""

    token: str = Field(..., description="Token de sesión opaco (valor de la cookie doc_organize_session)")
    user_id: str = Field(..., description="Usuario al que pertenece esta sesión")
    tenant_id: str = Field(..., description="Tenant del usuario, copiado aquí para evitar un join en las consultas")
    created_at: str = Field(..., description=_ISO_TIMESTAMP_DESC)
    expires_at: str = Field(..., description="Timestamp ISO 8601 de expiración (vida fija)")


class ProjectNameValidation(BaseModel):
    """Resultado de validar un nombre de proyecto candidato (REQ-008).

    Modelo dedicado, no una reutilización de ValidationResult: ese modelo trata
    semánticamente de una lista de rutas de carpetas (`clean_paths`), no de un
    único identificador de proyecto.
    """

    is_valid: bool = Field(..., description="Si el nombre es válido")
    warnings: list[str] = Field(default_factory=list, description="Motivos por los que se rechazó el nombre, si los hay")
    normalized_name: str | None = Field(None, description="Nombre normalizado a NFC y sin espacios, si es válido")


# ===== Modelos de configuración =====


class DoclingConfig(BaseModel):
    """Configuración para la conversión de documentos con Docling."""

    ocr_mode: OcrMode = Field(default=OcrMode.DEFAULT, description="Modo de OCR a usar")
    do_ocr: bool = Field(default=False, description="Activar OCR para los documentos")
    use_gpu: bool = Field(default=False, description="Usar GPU si está disponible (torch/cuda)")
    max_workers: int = Field(default=4, description="Número de workers async para la conversión")


class CacheConfig(BaseModel):
    """Configuración de la base de datos de cache."""

    cache_db_path: str = Field(default="cache.db", description="Ruta a la base de datos SQLite de cache")
    enable_wal: bool = Field(default=True, description="Activar modo WAL para concurrencia")
    auto_backup: bool = Field(default=True, description="Backup automático de cache.db antes de escrituras masivas")


class SecurityConfig(BaseModel):
    """Configuración de seguridad de la app web.

    `api_token_env_var` (bearer token compartido) se eliminó en la revisión 8
    (§2.7.2): la autenticación es ahora por usuario (cookie de sesión tras
    `/login`), así que ya no hay un único secreto compartido que leer del entorno.
    """

    bind_host: str = Field(default="127.0.0.1", description="Host al que hacer bind")
    bind_port: int = Field(default=8000, description="Puerto al que hacer bind")
    require_auth_if_not_loopback: bool = Field(default=True, description="Exigir autenticación si no es loopback")


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
    """Estado de soporte de GPU del entorno donde corre el servidor web (menú Escaneo).

    Detección de entorno software, no de permisos por usuario/rol: el mismo
    resultado aplica a cualquier sesión, porque depende únicamente de qué hay
    instalado/disponible en el proceso servidor, no de quién pregunta.
    """

    gpu_support_installed: bool = Field(..., description="Si `torch` (extra `ocr-gpu`) está instalado en este entorno")
    gpu_active: bool = Field(..., description="Si hay una GPU CUDA disponible y utilizable ahora mismo")
    instructions: str | None = Field(None, description="Instrucciones para activar la GPU, si `gpu_active` es `False`")


class AvStatus(BaseModel):
    """Estado de soporte de audio/vídeo del entorno donde corre el servidor (menú Escaneo).

    Mismo patrón que `GpuStatus`: detección de entorno software, sin permisos por
    usuario/rol. A diferencia de la GPU (cuya ausencia solo degrada a CPU), sin
    `asr_installed`/`ffmpeg_installed` la conversión de audio/vídeo falla siempre
    — por eso `ready` se usa también como pre-check bloqueante en el CLI
    (`_run_scan`), no solo como aviso informativo en la UI web.
    """

    asr_installed: bool = Field(..., description="Si el backend de transcripción ASR (extra `av`, Whisper) está instalado")
    ffmpeg_installed: bool = Field(..., description="Si el binario `ffmpeg` está disponible en el PATH del sistema (necesario para vídeo)")
    ready: bool = Field(..., description="Si `asr_installed` y `ffmpeg_installed` son ambos `True`")
    instructions: str | None = Field(None, description="Qué falta instalar/configurar, específico a lo que falte; `None` si `ready` es `True`")


class DirectoryListing(BaseModel):
    """Resultado de listar el contenido de una carpeta del servidor (explorador de carpetas de escaneo)."""

    current_path: str = Field(..., description="Ruta absoluta listada")
    parent_path: str | None = Field(None, description="Ruta absoluta de la carpeta padre, o `None` si no hay/no es accesible")
    entries: list[str] = Field(default_factory=list, description="Nombres de las subcarpetas inmediatas, ordenados alfabéticamente")


__all__ = [
    "AvStatus",
    "CacheConfig",
    "CacheEntry",
    "CacheExportSnapshot",
    "ConversionResult",
    "ConversionStatus",
    "DedupEvent",
    "DedupEventType",
    "DeduplicationReport",
    "DirectoryListing",
    "DirectoryTree",
    "DirectoryTreeNode",
    "DoclingConfig",
    "DocumentMetadata",
    "DocumentStatus",
    "DuplicateGroup",
    "DuplicateReason",
    "GpuStatus",
    "OcrMode",
    "Project",
    "ProjectNameValidation",
    "Role",
    "ScanErrorEntry",
    "ScanErrorReport",
    "ScanEvent",
    "ScanEventType",
    "ScanResult",
    "ScanRunReport",
    "ScannedFolder",
    "SecurityConfig",
    "Session",
    "Tenant",
    "User",
    "ValidationResult",
]
