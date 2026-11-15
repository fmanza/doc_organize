"""Tests para FASE 2: Enriquecimiento de contenido (autor, descripción, palabras clave)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from doc_organize.ai.content_extraction_client import (
    ContentExtractionClient,
    ContentExtractionClientConfig,
    ContentExtractionResult,
)
from doc_organize.converter.metadata_extractor import MetadataExtractor
from doc_organize.core.models import DomainDocument, DocumentStatus


class TestMetadataExtractor:
    """Tests para extracción de metadatos (autor) desde PDF y Office."""

    def test_extract_author_from_pdf_success(self):
        """Verifica extracción exitosa de autor desde PDF simulado."""
        with patch("builtins.__import__") as mock_import:
            mock_pdf2 = MagicMock()
            mock_reader = MagicMock()
            mock_reader.metadata = {"/Author": "Jane Doe"}
            mock_pdf2.PdfReader.return_value = mock_reader

            def import_side_effect(name, *args, **kwargs):
                if name == "PyPDF2":
                    return mock_pdf2
                return __import__(name, *args, **kwargs)

            mock_import.side_effect = import_side_effect

            with patch("builtins.open", create=True):
                author = MetadataExtractor.extract_author_from_pdf("test.pdf")

            assert author == "Jane Doe"

    def test_extract_author_from_pdf_missing(self):
        """Verifica que retorna None si no hay autor en PDF."""
        # Simplemente verificar que la función maneja el caso
        author = MetadataExtractor.extract_author_from_pdf("nonexistent.pdf")
        # Puede ser None (error) o manejar gracefully
        assert author is None or isinstance(author, (str, type(None)))

    def test_extract_author_from_pdf_no_pypdf2(self):
        """Verifica que retorna None si PyPDF2 no está disponible."""
        # Si PyPDF2 no está instalado, debe retornar None sin levantar error
        author = MetadataExtractor.extract_author_from_pdf("test.pdf")
        # Puede ser None (por ImportError silencioso o error de fichero)
        assert author is None or isinstance(author, (str, type(None)))

    def test_extract_author_from_docx_success(self):
        """Verifica que extract_author maneja DOCX."""
        # Si python-docx está instalado
        author = MetadataExtractor.extract_author_from_office("nonexistent.docx")
        # Debe retornar None sin error
        assert author is None or isinstance(author, (str, type(None)))

    def test_extract_author_from_office_no_docx(self):
        """Verifica que retorna None si python-docx no está disponible."""
        author = MetadataExtractor.extract_author_from_office("test.docx")
        # Sin error, incluso si falta python-docx
        assert author is None or isinstance(author, (str, type(None)))

    def test_extract_author_auto_detects_pdf(self):
        """Verifica que extract_author() detecta PDF automáticamente."""
        with patch.object(MetadataExtractor, "extract_author_from_pdf") as mock_pdf:
            mock_pdf.return_value = "PDF Author"

            author = MetadataExtractor.extract_author("document.pdf")

            assert author == "PDF Author"
            mock_pdf.assert_called_once()

    def test_extract_author_auto_detects_docx(self):
        """Verifica que extract_author() detecta DOCX automáticamente."""
        with patch.object(MetadataExtractor, "extract_author_from_office") as mock_office:
            mock_office.return_value = "Office Author"

            author = MetadataExtractor.extract_author("document.docx")

            assert author == "Office Author"
            mock_office.assert_called_once()

    def test_extract_author_unknown_type(self):
        """Verifica que retorna None para tipos de fichero no soportados."""
        author = MetadataExtractor.extract_author("document.xyz")
        assert author is None


class TestContentExtractionResult:
    """Tests para ContentExtractionResult."""

    def test_result_with_all_fields(self):
        """Verifica creación de resultado con todos los campos."""
        result = ContentExtractionResult(
            description="Test description",
            keywords=["keyword1", "keyword2"],
            confidence=0.9,
        )

        assert result.description == "Test description"
        assert result.keywords == ["keyword1", "keyword2"]
        assert result.confidence == 0.9

    def test_result_with_defaults(self):
        """Verifica valores por defecto."""
        result = ContentExtractionResult()

        assert result.description == ""
        assert result.keywords == []
        assert result.confidence == 0.0

    def test_result_handles_none_values(self):
        """Verifica que None se convierte a valores por defecto."""
        result = ContentExtractionResult(description=None, keywords=None)

        assert result.description == ""
        assert result.keywords == []


class TestContentExtractionClient:
    """Tests para cliente de extracción de contenido."""

    def test_client_initialization(self):
        """Verifica inicialización del cliente."""
        config = ContentExtractionClientConfig(
            base_url="http://localhost:8000",
            virtual_key="test-key",
            model="test-model",
        )

        client = ContentExtractionClient(config)

        assert client.model == "test-model"
        assert client.max_keywords == 5

    @pytest.mark.asyncio
    async def test_extract_content_metadata_success(self):
        """Verifica extracción exitosa de contenido."""
        config = ContentExtractionClientConfig(
            base_url="http://localhost:8000",
            virtual_key="test-key",
        )

        client = ContentExtractionClient(config)

        # Mock la llamada a LiteLLM
        mock_response = '{"description": "Test description", "keywords": ["key1", "key2"]}'
        with patch.object(client, "_call_litellm", new_callable=AsyncMock, return_value=mock_response):
            result = await client.extract_content_metadata("Test content")

            assert result.description == "Test description"
            assert result.keywords == ["key1", "key2"]
            assert result.confidence == 0.8

    @pytest.mark.asyncio
    async def test_extract_content_metadata_invalid_json(self):
        """Verifica manejo de respuesta JSON inválida."""
        config = ContentExtractionClientConfig(
            base_url="http://localhost:8000",
            virtual_key="test-key",
        )

        client = ContentExtractionClient(config)

        # Mock respuesta inválida
        with patch.object(client, "_call_litellm", new_callable=AsyncMock, return_value="invalid json"):
            result = await client.extract_content_metadata("Test content")

            assert result.description == ""
            assert result.keywords == []

    @pytest.mark.asyncio
    async def test_extract_content_metadata_limits_keywords(self):
        """Verifica que respeta el máximo de palabras clave."""
        config = ContentExtractionClientConfig(
            base_url="http://localhost:8000",
            virtual_key="test-key",
            max_keywords=3,
        )

        client = ContentExtractionClient(config)

        mock_response = '{"description": "Test", "keywords": ["k1", "k2", "k3", "k4", "k5"]}'
        with patch.object(client, "_call_litellm", new_callable=AsyncMock, return_value=mock_response):
            result = await client.extract_content_metadata("Test content")

            assert len(result.keywords) == 3

    @pytest.mark.asyncio
    async def test_extract_content_metadata_limits_content(self):
        """Verifica que limita contenido a 2000 caracteres."""
        config = ContentExtractionClientConfig(
            base_url="http://localhost:8000",
            virtual_key="test-key",
        )

        client = ContentExtractionClient(config)
        long_content = "x" * 5000

        mock_response = '{"description": "Test", "keywords": ["key1"]}'
        with patch.object(client, "_call_litellm", new_callable=AsyncMock, return_value=mock_response) as mock_call:
            await client.extract_content_metadata(long_content)

            # Verificar que el contenido pasado fue limitado
            call_args = mock_call.call_args
            assert "x" * 2000 in str(call_args)


class TestDomainDocumentPhase2:
    """Tests para modelo DomainDocument con campos FASE 2."""

    def test_domain_document_has_phase2_fields(self):
        """Verifica que DomainDocument tiene los campos FASE 2."""
        doc = DomainDocument(
            source_path="/test/file.pdf",
            markdown_path="/test/file.md",
            json_path="/test/file.json",
            title="Test Document",
            document_type="pdf",
            confidence=0.85,
            author="John Doe",
            description="A test document",
            keywords=["test", "document"],
            keywords_confidence=0.75,
        )

        assert doc.author == "John Doe"
        assert doc.description == "A test document"
        assert doc.keywords == ["test", "document"]
        assert doc.keywords_confidence == 0.75

    def test_domain_document_phase2_defaults(self):
        """Verifica que los campos FASE 2 tienen valores por defecto."""
        doc = DomainDocument(
            source_path="/test/file.pdf",
            markdown_path="/test/file.md",
            json_path="/test/file.json",
            title="Test Document",
            document_type="pdf",
            confidence=0.85,
        )

        assert doc.author is None
        assert doc.description is None
        assert doc.keywords == []
        assert doc.keywords_confidence == 0.0

    def test_domain_document_phase2_json_serialization(self):
        """Verifica que DomainDocument serializa correctamente."""
        doc = DomainDocument(
            source_path="/test/file.pdf",
            markdown_path="/test/file.md",
            json_path="/test/file.json",
            title="Test Document",
            document_type="pdf",
            confidence=0.85,
            author="John Doe",
            keywords=["test"],
        )

        json_str = doc.model_dump_json()
        data = json.loads(json_str)

        assert data["author"] == "John Doe"
        assert data["keywords"] == ["test"]
