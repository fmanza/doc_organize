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
from typing import Optional

from pydantic import BaseModel, Field

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


# ===== Pydantic Models (API / JSON Serialization) =====


class DocumentMetadata(BaseModel):
    """Metadata for a discovered document file."""

    full_path: str = Field(..., description="Absolute path to the document file")
    display_name: str = Field(..., description="Display name for UI (handles uniqueness)")
    extension: str = Field(..., description="File extension (e.g., 'pdf', 'docx')")
    size_bytes: int = Field(..., description="File size in bytes")
    modified_time: float = Field(..., description="Unix timestamp of last modification")
    sha256_hash: str = Field(..., description="SHA-256 hash (64-char hex string)")

    class Config:
        json_schema_extra = {
            "example": {
                "full_path": "/repo/docs/report.pdf",
                "display_name": "report.pdf",
                "extension": "pdf",
                "size_bytes": 1048576,
                "modified_time": 1693152000.0,
                "sha256_hash": "abc123def456...",
            }
        }


class ConversionResult(BaseModel):
    """Result of converting a single document."""

    source_path: str = Field(..., description="Path to source document")
    markdown_path: Optional[str] = Field(None, description="Path to output .md file")
    json_path: Optional[str] = Field(None, description="Path to output .json metadata file")
    success: bool = Field(..., description="Whether conversion succeeded")
    error: Optional[str] = Field(None, description="Error message if failed")
    ocr_required: bool = Field(False, description="Whether OCR was needed (and deferred)")
    duration_seconds: float = Field(0.0, description="Time spent converting (seconds)")

    class Config:
        json_schema_extra = {
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


class DuplicateGroup(BaseModel):
    """Group of documents identified as duplicates or version conflicts."""

    group_id: str = Field(..., description="Unique ID for this group (UUID)")
    canonical_doc: DocumentMetadata = Field(..., description="Document to keep (canonical)")
    duplicates: list[DocumentMetadata] = Field(..., description="Documents to discard")
    reason: DuplicateReason = Field(..., description="Why they are grouped")
    user_choice: Optional[DocumentMetadata] = Field(None, description="User's selection if overriding default")

    class Config:
        json_schema_extra = {
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
    conversion_status: Optional[ConversionStatus] = Field(None, description="Conversion progress status")


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
    size_bytes: Optional[int] = Field(None, description="File size (if type='file')")
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


class ValidationResult(BaseModel):
    """Result of folder validation."""

    is_valid: bool = Field(..., description="Whether folders are valid (no redundancy)")
    warnings: list[str] = Field(default_factory=list, description="List of warnings")
    clean_paths: list[str] = Field(..., description="Validated, non-redundant paths")


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
    markdown_path: Optional[str] = None
    json_path: Optional[str] = None
    success: bool = False
    error: Optional[str] = None
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
    """Security configuration for web app."""

    bind_host: str = Field(default="127.0.0.1", description="Host to bind to")
    bind_port: int = Field(default=8000, description="Port to bind to")
    api_token_env_var: str = Field(default="DOC_ORGANIZE_API_TOKEN", description="Env var for API token")
    require_auth_if_not_loopback: bool = Field(default=True, description="Require auth on non-loopback")


__all__ = [
    "DocumentStatus",
    "ConversionStatus",
    "DuplicateReason",
    "OcrMode",
    "DocumentMetadata",
    "ConversionResult",
    "DuplicateGroup",
    "DeduplicationReport",
    "CacheEntry",
    "CacheExportSnapshot",
    "DirectoryTreeNode",
    "DirectoryTree",
    "ScanResult",
    "ValidationResult",
    "DocumentMetadataInternal",
    "ConversionResultInternal",
    "DoclingConfig",
    "CacheConfig",
    "SecurityConfig",
]
