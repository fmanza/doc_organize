"""Extracción de metadatos de contenido desde PDF y Office (FASE 2)."""

from pathlib import Path

from doc_organize.utils.logging import get_logger

_logger = get_logger(__name__)


class MetadataExtractor:
    """Extrae metadatos de autoría desde archivos PDF y Office."""

    @staticmethod
    def extract_author_from_pdf(pdf_path: str | Path) -> str | None:
        """Extrae autor desde metadatos PDF: Author, Creator o Producer.

        Args:
            pdf_path: Ruta al fichero PDF

        Returns:
            Nombre del autor/creador, o None si no se puede extraer
        """
        try:
            import PyPDF2

            with open(pdf_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                metadata = reader.metadata
                if metadata:
                    # Intenta diferentes campos según estándar PDF
                    author = metadata.get("/Author") or metadata.get("/Creator") or metadata.get("/Producer")
                    if author:
                        # PyPDF2 puede retornar bytes o str
                        if isinstance(author, bytes):
                            return author.decode("utf-8", errors="ignore").strip()
                        return str(author).strip()
            return None
        except ImportError:
            _logger.debug("PyPDF2 no instalado, no se puede extraer autor de PDF")
            return None
        except Exception as e:
            _logger.debug(f"Error extrayendo autor PDF de '{pdf_path}': {e}")
            return None

    @staticmethod
    def extract_author_from_office(office_path: str | Path) -> str | None:
        """Extrae creador desde metadatos Office (DOCX, XLSX, PPTX).

        Args:
            office_path: Ruta al fichero Office

        Returns:
            Nombre del creador, o None si no se puede extraer
        """
        try:
            from docx import Document as DocxDocument

            path = Path(office_path)

            # DOCX
            if path.suffix.lower() == ".docx":
                try:
                    doc = DocxDocument(str(path))
                    author = doc.core_properties.author
                    if author:
                        return str(author).strip()
                except Exception as e:
                    _logger.debug(f"Error extrayendo autor DOCX de '{path}': {e}")

            # XLSX (openpyxl)
            elif path.suffix.lower() == ".xlsx":
                try:
                    import openpyxl

                    workbook = openpyxl.load_workbook(str(path))
                    author = workbook.properties.creator
                    if author:
                        return str(author).strip()
                except ImportError:
                    pass
                except Exception as e:
                    _logger.debug(f"Error extrayendo autor XLSX de '{path}': {e}")

            # PPTX
            elif path.suffix.lower() == ".pptx":
                try:
                    from pptx import Presentation

                    presentation = Presentation(str(path))
                    author = presentation.core_properties.author
                    if author:
                        return str(author).strip()
                except ImportError:
                    pass
                except Exception as e:
                    _logger.debug(f"Error extrayendo autor PPTX de '{path}': {e}")

            return None
        except ImportError:
            _logger.debug("python-docx no instalado, no se puede extraer autor de Office")
            return None
        except Exception as e:
            _logger.debug(f"Error genérico extrayendo autor Office de '{office_path}': {e}")
            return None

    @staticmethod
    def extract_author(source_path: str | Path) -> str | None:
        """Extrae autor automáticamente según tipo de fichero.

        Intenta primero PDF, luego Office.

        Args:
            source_path: Ruta al fichero

        Returns:
            Nombre del autor, o None si no se puede extraer de ningún tipo
        """
        path = Path(source_path)
        suffix = path.suffix.lower()

        # PDF
        if suffix == ".pdf":
            return MetadataExtractor.extract_author_from_pdf(path)

        # Office
        if suffix in (".docx", ".xlsx", ".pptx"):
            return MetadataExtractor.extract_author_from_office(path)

        return None


__all__ = ["MetadataExtractor"]
