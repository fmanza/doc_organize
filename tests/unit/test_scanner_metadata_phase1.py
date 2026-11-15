"""Tests para FASE 1: Metadatos técnicos básicos (tipo MIME, idioma, permisos, fecha creación)."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from doc_organize.scanner.document_scanner import DocumentScanner
from doc_organize.utils.metadata_detector import (
    detect_mime_type,
    extract_basic_metadata,
    get_creation_time,
    get_file_permissions,
    get_owner_name,
)


class TestMetadataDetector:
    """Tests para funciones de detección de metadatos."""

    def test_detect_mime_type_pdf(self):
        """Verifica detección de tipo MIME para PDF."""
        mime = detect_mime_type(Path("test.pdf"))
        assert mime == "application/pdf"

    def test_detect_mime_type_docx(self):
        """Verifica detección de tipo MIME para DOCX."""
        mime = detect_mime_type(Path("test.docx"))
        assert mime in ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain")

    def test_detect_mime_type_xlsx(self):
        """Verifica detección de tipo MIME para XLSX."""
        mime = detect_mime_type(Path("test.xlsx"))
        # XLSX se puede detectar como application/vnd.ms-excel o zip
        assert mime is not None

    def test_detect_mime_type_txt(self):
        """Verifica detección de tipo MIME para TXT."""
        mime = detect_mime_type(Path("test.txt"))
        assert mime == "text/plain"

    def test_detect_mime_type_unknown_extension(self):
        """Verifica fallback para extensión desconocida."""
        mime = detect_mime_type(Path("test.unknown"))
        # Debe retornar algo (mimetypes retorna None, luego fallback)
        assert mime is not None

    def test_detect_mime_type_fallback_binary(self):
        """Verifica fallback a binary para archivo sin extensión."""
        mime = detect_mime_type(Path("test"))
        assert mime is not None

    def test_get_creation_time_macos(self):
        """Verifica obtención de fecha creación (simulado macOS)."""
        mock_stat = MagicMock()
        mock_stat.st_birthtime = 1693151000.0
        mock_stat.st_ctime = 1693150000.0
        mock_stat.st_mtime = 1693152000.0

        created = get_creation_time(mock_stat)
        assert created == 1693151000.0

    def test_get_creation_time_unix_uses_min(self):
        """Verifica obtención de fecha creación en Unix (mín de ctime y mtime)."""
        mock_stat = MagicMock(spec=["st_ctime", "st_mtime"])
        mock_stat.st_ctime = 1693150000.0
        mock_stat.st_mtime = 1693152000.0

        created = get_creation_time(mock_stat)
        assert created == 1693150000.0

    def test_get_file_permissions_octal(self):
        """Verifica extracción de permisos en formato octal."""
        mock_stat = MagicMock()
        # 644 en octal = 420 en decimal, st_mode incluye tipo de archivo
        mock_stat.st_mode = 33188  # Regular file + 644 permisos

        perms = get_file_permissions(mock_stat)
        assert perms == "644"

    def test_get_file_permissions_777(self):
        """Verifica extracción de permisos 777."""
        mock_stat = MagicMock()
        mock_stat.st_mode = 33279  # Regular file + 777 permisos

        perms = get_file_permissions(mock_stat)
        assert perms == "777"

    def test_get_owner_name_error_handling(self):
        """Verifica que el error de propietario no rompe la función."""
        mock_stat = MagicMock()

        owner = get_owner_name(mock_stat, Path("test.txt"))
        # Puede ser None o algún valor, lo importante es que no levanta excepción
        assert owner is None or isinstance(owner, str)

    def test_extract_basic_metadata_complete(self, tmp_path):
        """Verifica que extract_basic_metadata retorna todos los campos."""
        test_file = tmp_path / "test.pdf"
        test_file.write_text("dummy content")

        metadata = extract_basic_metadata(test_file)

        assert "mime_type" in metadata
        assert "created_time" in metadata
        assert "file_permissions" in metadata
        assert "owner_name" in metadata
        assert metadata["mime_type"] is not None

    def test_extract_basic_metadata_missing_file(self):
        """Verifica que extract_basic_metadata maneja archivos faltantes."""
        metadata = extract_basic_metadata(Path("/nonexistent/file.pdf"))

        assert metadata["mime_type"] is None
        assert metadata["created_time"] is None
        assert metadata["file_permissions"] is None
        assert metadata["owner_name"] is None


class TestDocumentScannerMetadataExtraction:
    """Tests para extracción de metadatos en DocumentScanner."""

    @pytest.mark.asyncio
    async def test_scanner_creates_discovered_files_with_metadata(self, tmp_path):
        """Verifica que DocumentScanner crea _DiscoveredFile con metadatos básicos."""
        # Crear archivo de prueba
        test_file = tmp_path / "document.pdf"
        test_file.write_text("PDF content")

        async with DocumentScanner() as scanner:
            result = await scanner.scan_folders([str(tmp_path)])

        assert len(result.documents) == 1
        doc = result.documents[0]

        # Verificar que DocumentMetadata tiene los nuevos campos
        assert doc.mime_type is not None
        assert doc.created_time is not None
        assert doc.file_permissions is not None
        # owner_name puede ser None si no hay permisos

    @pytest.mark.asyncio
    async def test_scanner_preserves_existing_metadata(self, tmp_path):
        """Verifica que los metadatos existentes se preservan."""
        test_file = tmp_path / "document.txt"
        test_file.write_text("text content")

        async with DocumentScanner() as scanner:
            result = await scanner.scan_folders([str(tmp_path)])

        assert len(result.documents) == 1
        doc = result.documents[0]

        # Campos existentes deben estar presentes
        assert doc.full_path is not None
        assert doc.display_name == "document.txt"
        assert doc.extension == "txt"
        assert doc.size_bytes > 0
        assert doc.modified_time > 0
        assert doc.sha256_hash is not None

    @pytest.mark.asyncio
    async def test_scanner_handles_multiple_files(self, tmp_path):
        """Verifica que múltiples archivos se procesan correctamente."""
        (tmp_path / "doc1.pdf").write_text("content1")
        (tmp_path / "doc2.txt").write_text("content2")
        (tmp_path / "doc3.docx").write_text("content3")

        async with DocumentScanner() as scanner:
            result = await scanner.scan_folders([str(tmp_path)])

        assert len(result.documents) == 3

        # Todos deben tener metadatos básicos
        for doc in result.documents:
            assert doc.mime_type is not None
            assert doc.file_permissions is not None

    @pytest.mark.asyncio
    async def test_scanner_mime_type_accuracy(self, tmp_path):
        """Verifica que los tipos MIME detectados son correctos."""
        pdf_file = tmp_path / "document.pdf"
        pdf_file.write_text("PDF content")

        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("Text content")

        async with DocumentScanner() as scanner:
            result = await scanner.scan_folders([str(tmp_path)])

        pdf_doc = next((d for d in result.documents if d.extension == "pdf"), None)
        txt_doc = next((d for d in result.documents if d.extension == "txt"), None)

        assert pdf_doc is not None
        assert pdf_doc.mime_type == "application/pdf"

        assert txt_doc is not None
        assert txt_doc.mime_type == "text/plain"


class TestCacheIntegration:
    """Tests para integración con caché."""

    def test_cache_entry_has_new_fields(self):
        """Verifica que CacheEntry tiene los nuevos campos."""
        from doc_organize.core.models import CacheEntry, DocumentStatus

        entry = CacheEntry(
            file_path="/test/file.pdf",
            sha256_hash="abcd1234" * 8,
            timestamp=1693152000.0,
            status=DocumentStatus.NEW,
            created_time=1693151000.0,
            mime_type="application/pdf",
            file_permissions="644",
            owner_name="user",
        )

        assert entry.created_time == 1693151000.0
        assert entry.mime_type == "application/pdf"
        assert entry.file_permissions == "644"
        assert entry.owner_name == "user"

    def test_cache_entry_backward_compatibility(self):
        """Verifica que CacheEntry anterior funciona sin nuevos campos."""
        from doc_organize.core.models import CacheEntry, DocumentStatus

        # CacheEntry sin los campos nuevos (NULL en BD)
        entry = CacheEntry(
            file_path="/test/file.pdf",
            sha256_hash="abcd1234" * 8,
            timestamp=1693152000.0,
            status=DocumentStatus.UNCHANGED,
        )

        # Los nuevos campos deben ser None
        assert entry.created_time is None
        assert entry.mime_type is None
        assert entry.file_permissions is None
        assert entry.owner_name is None


class TestDocumentMetadataModel:
    """Tests para modelo DocumentMetadata."""

    def test_document_metadata_with_all_phase1_fields(self):
        """Verifica que DocumentMetadata acepta todos los campos FASE 1."""
        from doc_organize.core.models import DocumentMetadata

        doc = DocumentMetadata(
            full_path="/test/file.pdf",
            display_name="file.pdf",
            extension="pdf",
            size_bytes=1024,
            modified_time=1693152000.0,
            sha256_hash="abcd1234" * 8,
            created_time=1693151000.0,
            mime_type="application/pdf",
            detected_language=None,
            file_permissions="644",
            owner_name="user",
        )

        assert doc.created_time == 1693151000.0
        assert doc.mime_type == "application/pdf"
        assert doc.detected_language is None
        assert doc.file_permissions == "644"
        assert doc.owner_name == "user"

    def test_document_metadata_backward_compatibility(self):
        """Verifica que DocumentMetadata funciona sin campos nuevos."""
        from doc_organize.core.models import DocumentMetadata

        doc = DocumentMetadata(
            full_path="/test/file.pdf",
            display_name="file.pdf",
            extension="pdf",
            size_bytes=1024,
            modified_time=1693152000.0,
            sha256_hash="abcd1234" * 8,
        )

        # Los nuevos campos deben ser None
        assert doc.created_time is None
        assert doc.mime_type is None
        assert doc.detected_language is None
        assert doc.file_permissions is None
        assert doc.owner_name is None

    def test_document_metadata_json_serialization(self):
        """Verifica que DocumentMetadata se serializa a JSON correctamente."""
        from doc_organize.core.models import DocumentMetadata

        doc = DocumentMetadata(
            full_path="/test/file.pdf",
            display_name="file.pdf",
            extension="pdf",
            size_bytes=1024,
            modified_time=1693152000.0,
            sha256_hash="abcd1234" * 8,
            created_time=1693151000.0,
            mime_type="application/pdf",
            file_permissions="644",
        )

        json_str = doc.model_dump_json()
        assert "created_time" in json_str
        assert "mime_type" in json_str
        assert "file_permissions" in json_str
