"""
Core data models for doc_organize.

Pydantic v2 models used across all modules:
- DocumentMetadata: File metadata with SHA-256 hash
- ConversionResult: Output of document conversion
- DuplicateGroup: Group of duplicate/version-conflicted documents
- DeduplicationReport: Result of deduplication
- CacheEntry: Single cache entry in SQLite
- DirectoryTree: Hierarchical directory structure
- CacheExportSnapshot: Read-only export of cache for ZIP download
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ===== Enumerations =====


class DocumentStatus(str, Enum):
    """Status of a document in the pipeline."""

    NEW = "new"
    UNCHANGED = "unchanged"
    MODIFIED = "modified"
    DELETED = "deleted"


class ConversionStatus(str, Enum):
    """Conversion progress status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    ERROR = "error"
    OCR_PENDING = "ocr_pending"
    OCR_IN_PROGRESS = "ocr_in_progress"


class DuplicateReason(str, Enum):
    """Reason for grouping documents as duplicates."""

    EXACT_DUPLICATE = "exact_duplicate"
    VERSION_CONFLICT = "version_conflict"


class OcrMode(str, Enum):
    """OCR processing mode for Docling."""

    FULL_PAGE = "full_page"
    LAYOUT_REGIONS = "layout_regions"
    PDF_AWARE_LAYOUT_REGIONS = "pdf_aware_layout_regions"
    DEFAULT = "default"


class ScanEventType(str, Enum):
    """Progress event kind emitted by `ScanCommand.run_streaming()` (Fase D-2b, §2.7.3)."""

    STARTED = "started"
    SCANNED = "scanned"
    DEDUPLICATED = "deduplicated"
    FILE_CONVERTED = "file_converted"
    OCR_PROCESSED = "ocr_processed"
    COMPLETED = "completed"


# ===== Pydantic Models (API / JSON Serialization) =====


class DocumentMetadata(BaseModel):
    """Metadata for a discovered document file."""

    full_path: str = Field(..., description="Absolute path to the document file")
    display_name: str = Field(..., description="Display name for UI (handles uniqueness)")
    extension: str = Field(..., description="File extension (e.g., 'pdf', 'docx')")
    size_bytes: int = Field(..., description="File size in bytes")
    modified_time: float = Field(..., description="Unix timestamp of last modification")
    sha256_hash: str = Field(..., description="SHA-256 hash (64-char hex string)")

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
    """Result of converting a single document."""

    source_path: str = Field(..., description="Path to source document")
    markdown_path: str | None = Field(None, description="Path to output .md file")
    json_path: str | None = Field(None, description="Path to output .json metadata file")
    success: bool = Field(..., description="Whether conversion succeeded")
    error: str | None = Field(None, description="Error message if failed")
    ocr_required: bool = Field(False, description="Whether OCR was needed (and deferred)")
    duration_seconds: float = Field(0.0, description="Time spent converting (seconds)")

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
            }
        }
    )


class DuplicateGroup(BaseModel):
    """Group of documents identified as duplicates or version conflicts."""

    group_id: str = Field(..., description="Unique ID for this group (UUID)")
    canonical_doc: DocumentMetadata = Field(..., description="Document to keep (canonical)")
    duplicates: list[DocumentMetadata] = Field(..., description="Documents to discard")
    reason: DuplicateReason = Field(..., description="Why they are grouped")
    user_choice: DocumentMetadata | None = Field(None, description="User's selection if overriding default")

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
    """Result of deduplication process."""

    timestamp: str = Field(..., description="ISO 8601 timestamp when dedup was run")
    total_exact_duplicates: int = Field(..., description="Count of exact duplicate files moved")
    total_version_conflicts: int = Field(..., description="Count of version conflicts resolved")
    duplicates_folder_path: str = Field(..., description="Path to folder where duplicates were moved")
    audit_json_path: str = Field(..., description="Path to DEDUP_REPORT.json file")
    groups: list[DuplicateGroup] = Field(default_factory=list, description="Detailed groups")


class CacheEntry(BaseModel):
    """Single entry in the cache database."""

    file_path: str = Field(..., description="Absolute path to the file (PK in cache.db)")
    sha256_hash: str = Field(..., description="SHA-256 of the file")
    timestamp: float = Field(..., description="Unix timestamp when entry was last updated")
    status: DocumentStatus = Field(..., description="Document status (new/unchanged/modified/deleted)")
    conversion_status: ConversionStatus | None = Field(None, description="Conversion progress status")


class CacheExportSnapshot(BaseModel):
    """Read-only snapshot of cache for download/export."""

    export_timestamp: str = Field(..., description="ISO 8601 timestamp when exported")
    total_entries: int = Field(..., description="Total files in cache")
    new_files: list[str] = Field(default_factory=list, description="Paths of new files")
    modified_files: list[str] = Field(default_factory=list, description="Paths of modified files")
    unchanged_files: list[str] = Field(default_factory=list, description="Paths of unchanged files")
    entries: list[CacheEntry] = Field(default_factory=list, description="All cache entries")


class DirectoryTreeNode(BaseModel):
    """Single node in directory tree (file or folder)."""

    name: str = Field(..., description="Name of the file or folder")
    type: str = Field(..., description="'file' or 'dir'")
    path: str = Field(..., description="Relative or absolute path")
    size_bytes: int | None = Field(None, description="File size (if type='file')")
    children: list["DirectoryTreeNode"] = Field(default_factory=list, description="Child nodes (if type='dir')")


DirectoryTreeNode.model_rebuild()  # Required for self-referential model


class DirectoryTree(BaseModel):
    """Hierarchical directory structure from scanning."""

    root_name: str = Field(..., description="Name of root directory")
    root_path: str = Field(..., description="Absolute path of root")
    root_node: DirectoryTreeNode = Field(..., description="Tree structure rooted here")
    total_files: int = Field(..., description="Count of files found")
    file_extension_counts: dict[str, int] = Field(default_factory=dict, description="Count by extension")


class ScanResult(BaseModel):
    """Result of scanning folders for documents."""

    documents: list[DocumentMetadata] = Field(..., description="All documents found")
    summary: dict[str, int] = Field(..., description="File count by extension")
    tree: DirectoryTree = Field(..., description="Directory structure")
    scan_duration_seconds: float = Field(..., description="Time to complete scan")


class ScanEvent(BaseModel):
    """A single progress event from `ScanCommand.run_streaming()` (Fase D-2b, §2.7.3).

    Deliberately a loose `dict[str, Any]` payload rather than a per-event-type model:
    the shapes differ enough (final summary counts vs. a single file's path/success)
    that stronger typing would mean one model per `ScanEventType` for little benefit
    at this stage. Consumers (CLI, WebSocket) key off `event` to interpret `data`.
    """

    event: ScanEventType = Field(..., description="Kind of progress event")
    data: dict[str, Any] = Field(default_factory=dict, description="Event payload, shape depends on `event`")


class ValidationResult(BaseModel):
    """Result of folder validation."""

    is_valid: bool = Field(..., description="Whether folders are valid (no redundancy)")
    warnings: list[str] = Field(default_factory=list, description="List of warnings")
    clean_paths: list[str] = Field(..., description="Validated, non-redundant paths")


class Project(BaseModel):
    """A doc_organize project: a named working folder aggregating scan/convert/dedup/cache state (REQ-008).

    `tenant_id` defaults to `"default"` (revision 8, §2.7.2): projects created via the
    CLI or a loopback/no-auth web session all live in this implicit tenant, and any
    registry entry written before revision 8 (missing the field entirely) parses as
    `"default"` too — no migration script needed. Project name uniqueness is scoped
    per tenant (see `ProjectRegistry.create_project`), not global.
    """

    name: str = Field(..., description="Unique project name within its tenant (validated by ProjectValidator)")
    root_path: str = Field(..., description="Absolute path to the project's working folder")
    created_at: str = Field(..., description="ISO 8601 timestamp of project creation")
    tenant_id: str = Field(default="default", description="Owning tenant (defaults to the implicit 'default' tenant)")


_ISO_TIMESTAMP_DESC = "ISO 8601 timestamp of creation"


class Tenant(BaseModel):
    """An organization/workspace grouping users and projects (revision 8, §2.7.2)."""

    id: str = Field(..., description="Tenant identifier (slug), derived from its name")
    name: str = Field(..., description="Human-readable tenant name")
    created_at: str = Field(..., description=_ISO_TIMESTAMP_DESC)


class Role(BaseModel):
    """A named permission set within a tenant (revision 9, roles y gestión de usuarios).

    `is_admin=True` sees every project in the tenant, present and future —
    `project_names` must then be empty (enforced by `AuthStore.create_role`/
    `update_role`, not by this model, to keep the model a plain data container).
    A non-admin role only sees the projects listed in `project_names`.
    """

    id: str = Field(..., description="Role UUID4")
    tenant_id: str = Field(..., description="Tenant this role belongs to")
    name: str = Field(..., description="Unique within the tenant (not globally)")
    is_admin: bool = Field(default=False, description="Whether this role sees every project in the tenant")
    project_names: list[str] = Field(default_factory=list, description="Projects this role can access (ignored if is_admin)")
    created_at: str = Field(..., description=_ISO_TIMESTAMP_DESC)


class User(BaseModel):
    """A user belonging to exactly one tenant and exactly one role (revision 8 §2.7.2, revision 9).

    Never includes the password hash/salt: those fields live only in
    `auth.db` (AuthStore), so no endpoint can accidentally serialize them
    in a JSON response.
    """

    id: str = Field(..., description="User UUID4")
    tenant_id: str = Field(..., description="Tenant this user belongs to")
    username: str = Field(..., description="Unique within the tenant (not globally)")
    role_id: str = Field(..., description="Role this user is assigned to (revision 9)")
    must_change_password: bool = Field(
        default=False, description="True until the user changes a bootstrap-assigned password (revision 9)"
    )
    created_at: str = Field(..., description=_ISO_TIMESTAMP_DESC)


class Session(BaseModel):
    """An active browser session, created on login (revision 8, §2.7.2)."""

    token: str = Field(..., description="Opaque session token (value of the doc_organize_session cookie)")
    user_id: str = Field(..., description="User this session belongs to")
    tenant_id: str = Field(..., description="User's tenant, copied here to avoid a join on lookups")
    created_at: str = Field(..., description=_ISO_TIMESTAMP_DESC)
    expires_at: str = Field(..., description="ISO 8601 timestamp of expiration (fixed lifetime)")


class ProjectNameValidation(BaseModel):
    """Result of validating a candidate project name (REQ-008).

    Dedicated model, not a reuse of ValidationResult: that model is semantically
    about a list of folder paths (`clean_paths`), not a single project identifier.
    """

    is_valid: bool = Field(..., description="Whether the name is valid")
    warnings: list[str] = Field(default_factory=list, description="Reasons the name was rejected, if any")
    normalized_name: str | None = Field(None, description="NFC-normalized, stripped name, if valid")


# ===== Python Dataclasses (Internal Use, Pre-validation) =====


@dataclass
class DocumentMetadataInternal:
    """Internal representation of document metadata (before Pydantic validation)."""

    full_path: str
    display_name: str
    extension: str
    size_bytes: int
    modified_time: float
    sha256_hash: str

    def to_pydantic(self) -> DocumentMetadata:
        """Convert to Pydantic model for API serialization."""
        return DocumentMetadata(
            full_path=self.full_path,
            display_name=self.display_name,
            extension=self.extension,
            size_bytes=self.size_bytes,
            modified_time=self.modified_time,
            sha256_hash=self.sha256_hash,
        )


@dataclass
class ConversionResultInternal:
    """Internal representation of conversion result."""

    source_path: str
    markdown_path: str | None = None
    json_path: str | None = None
    success: bool = False
    error: str | None = None
    ocr_required: bool = False
    duration_seconds: float = 0.0

    def to_pydantic(self) -> ConversionResult:
        """Convert to Pydantic model."""
        return ConversionResult(
            source_path=self.source_path,
            markdown_path=self.markdown_path,
            json_path=self.json_path,
            success=self.success,
            error=self.error,
            ocr_required=self.ocr_required,
            duration_seconds=self.duration_seconds,
        )


# ===== Configuration Models =====


class DoclingConfig(BaseModel):
    """Configuration for Docling document conversion."""

    ocr_mode: OcrMode = Field(default=OcrMode.DEFAULT, description="OCR mode to use")
    do_ocr: bool = Field(default=False, description="Enable OCR for documents")
    use_gpu: bool = Field(default=False, description="Use GPU if available (torch/cuda)")
    max_workers: int = Field(default=4, description="Number of async workers for conversion")


class CacheConfig(BaseModel):
    """Configuration for cache database."""

    cache_db_path: str = Field(default="cache.db", description="Path to SQLite cache database")
    enable_wal: bool = Field(default=True, description="Enable WAL mode for concurrency")
    auto_backup: bool = Field(default=True, description="Auto-backup cache.db before mass writes")


class SecurityConfig(BaseModel):
    """Security configuration for web app.

    `api_token_env_var` (shared bearer token) was removed in revision 8 (§2.7.2):
    authentication is now per-user (session cookie after `/login`), so there is no
    longer a single shared secret to read from the environment.
    """

    bind_host: str = Field(default="127.0.0.1", description="Host to bind to")
    bind_port: int = Field(default=8000, description="Port to bind to")
    require_auth_if_not_loopback: bool = Field(default=True, description="Require auth on non-loopback")


__all__ = [
    "DocumentStatus",
    "ConversionStatus",
    "DuplicateReason",
    "OcrMode",
    "ScanEventType",
    "DocumentMetadata",
    "ConversionResult",
    "DuplicateGroup",
    "DeduplicationReport",
    "CacheEntry",
    "CacheExportSnapshot",
    "DirectoryTreeNode",
    "DirectoryTree",
    "ScanResult",
    "ScanEvent",
    "ValidationResult",
    "Project",
    "Tenant",
    "Role",
    "User",
    "Session",
    "ProjectNameValidation",
    "DocumentMetadataInternal",
    "ConversionResultInternal",
    "DoclingConfig",
    "CacheConfig",
    "SecurityConfig",
]
