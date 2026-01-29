"""Robust document parsing service using the unstructured library."""

import io
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

from app.config import get_settings
from app.core.exceptions import FileProcessingError, ValidationError

settings = get_settings()
logger = structlog.get_logger()


class ElementType(str, Enum):
    """Types of document elements."""

    TITLE = "title"
    HEADER = "header"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    FOOTNOTE = "footnote"
    IMAGE = "image"
    PAGE_BREAK = "page_break"
    UNKNOWN = "unknown"


@dataclass
class DocumentSection:
    """Represents a section of a parsed document."""

    element_type: ElementType
    content: str
    page_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert section to dictionary."""
        return {
            "element_type": self.element_type.value,
            "content": self.content,
            "page_number": self.page_number,
            "metadata": self.metadata,
        }


@dataclass
class DocumentContent:
    """Structured representation of a parsed document."""

    full_text: str
    sections: list[DocumentSection]
    title: str | None = None
    page_count: int = 0
    word_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    tables: list[dict[str, Any]] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    footnotes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert document content to dictionary."""
        return {
            "full_text": self.full_text,
            "sections": [s.to_dict() for s in self.sections],
            "title": self.title,
            "page_count": self.page_count,
            "word_count": self.word_count,
            "metadata": self.metadata,
            "tables": self.tables,
            "headers": self.headers,
            "footnotes": self.footnotes,
            "warnings": self.warnings,
        }


class DocumentParser:
    """Service for parsing documents using the unstructured library."""

    # Maximum file size for parsing (100MB default)
    MAX_FILE_SIZE = 100 * 1024 * 1024

    # Supported MIME types
    SUPPORTED_TYPES = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }

    def __init__(self, enable_ocr: bool = True, ocr_languages: list[str] | None = None) -> None:
        """Initialize the document parser.

        Args:
            enable_ocr: Whether to enable OCR for scanned documents
            ocr_languages: List of language codes for OCR (default: ["eng"])
        """
        self.enable_ocr = enable_ocr
        self.ocr_languages = ocr_languages or ["eng"]

    def validate_file(self, file_content: bytes, filename: str, mime_type: str) -> None:
        """Validate file before parsing.

        Args:
            file_content: Raw file bytes
            filename: Original filename
            mime_type: Detected MIME type

        Raises:
            ValidationError: If file is invalid
        """
        # Check file size
        if len(file_content) > self.MAX_FILE_SIZE:
            raise ValidationError(
                f"File size ({len(file_content) / 1024 / 1024:.1f}MB) exceeds "
                f"maximum allowed size ({self.MAX_FILE_SIZE / 1024 / 1024:.0f}MB)"
            )

        # Check MIME type
        if mime_type not in self.SUPPORTED_TYPES:
            raise ValidationError(
                f"Unsupported file type: {mime_type}. "
                f"Supported types: PDF, DOCX"
            )

        # Check if file is empty
        if len(file_content) == 0:
            raise ValidationError("File is empty")

    def _detect_password_protected_pdf(self, file_content: bytes) -> bool:
        """Check if a PDF is password protected."""
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(file_content))
            return reader.is_encrypted
        except Exception:
            return False

    def _map_element_type(self, element_type: str) -> ElementType:
        """Map unstructured element type to our ElementType enum."""
        type_mapping = {
            "Title": ElementType.TITLE,
            "Header": ElementType.HEADER,
            "NarrativeText": ElementType.PARAGRAPH,
            "Text": ElementType.PARAGRAPH,
            "ListItem": ElementType.LIST_ITEM,
            "Table": ElementType.TABLE,
            "FigureCaption": ElementType.IMAGE,
            "Image": ElementType.IMAGE,
            "PageBreak": ElementType.PAGE_BREAK,
            "Footer": ElementType.FOOTNOTE,
            "Footnote": ElementType.FOOTNOTE,
        }
        return type_mapping.get(element_type, ElementType.UNKNOWN)

    async def parse_pdf(self, file_content: bytes, filename: str) -> DocumentContent:
        """Parse a PDF file.

        Args:
            file_content: Raw PDF bytes
            filename: Original filename

        Returns:
            Parsed document content

        Raises:
            FileProcessingError: If parsing fails
        """
        # Check for password protection
        if self._detect_password_protected_pdf(file_content):
            raise FileProcessingError(
                "Password-protected PDFs are not supported. "
                "Please remove the password and try again."
            )

        try:
            from unstructured.partition.pdf import partition_pdf

            # Write to temp file (unstructured works better with files)
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name

            try:
                elements = None
                last_error = None

                # Try hi_res first if OCR enabled, then fallback to fast
                strategies = ["hi_res", "fast"] if self.enable_ocr else ["fast"]

                for strategy in strategies:
                    try:
                        logger.info(
                            "Attempting PDF parsing",
                            filename=filename,
                            strategy=strategy,
                        )
                        elements = partition_pdf(
                            filename=tmp_path,
                            strategy=strategy,
                            languages=self.ocr_languages if strategy == "hi_res" else None,
                            include_page_breaks=True,
                            extract_images_in_pdf=False,
                        )
                        break  # Success, exit loop
                    except Exception as e:
                        last_error = e
                        logger.warning(
                            "PDF parsing strategy failed, trying next",
                            filename=filename,
                            strategy=strategy,
                            error=str(e),
                        )
                        continue

                if elements is None:
                    raise last_error or FileProcessingError("All parsing strategies failed")

                return self._process_elements(elements, filename)

            finally:
                # Clean up temp file
                Path(tmp_path).unlink(missing_ok=True)

        except FileProcessingError:
            raise
        except Exception as e:
            logger.error("PDF parsing failed", filename=filename, error=str(e))
            raise FileProcessingError(f"Failed to parse PDF: {e}") from e

    async def parse_docx(self, file_content: bytes, filename: str) -> DocumentContent:
        """Parse a DOCX file.

        Args:
            file_content: Raw DOCX bytes
            filename: Original filename

        Returns:
            Parsed document content

        Raises:
            FileProcessingError: If parsing fails
        """
        try:
            from unstructured.partition.docx import partition_docx

            # Write to temp file
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name

            try:
                elements = partition_docx(
                    filename=tmp_path,
                    include_page_breaks=True,
                )

                return self._process_elements(elements, filename)

            finally:
                Path(tmp_path).unlink(missing_ok=True)

        except Exception as e:
            logger.error("DOCX parsing failed", filename=filename, error=str(e))

            # Check for specific corruption indicators
            error_str = str(e).lower()
            if "corrupt" in error_str or "invalid" in error_str or "bad" in error_str:
                raise FileProcessingError(
                    "The document appears to be corrupted. "
                    "Please try re-saving it in Word and uploading again."
                ) from e

            raise FileProcessingError(f"Failed to parse DOCX: {e}") from e

    def _process_elements(self, elements: list[Any], filename: str) -> DocumentContent:
        """Process parsed elements into DocumentContent.

        Args:
            elements: List of unstructured elements
            filename: Original filename

        Returns:
            Structured document content
        """
        sections: list[DocumentSection] = []
        text_parts: list[str] = []
        tables: list[dict[str, Any]] = []
        headers: list[str] = []
        footnotes: list[str] = []
        warnings: list[str] = []
        title: str | None = None
        page_numbers: set[int] = set()

        for element in elements:
            element_type = type(element).__name__
            content = str(element)
            mapped_type = self._map_element_type(element_type)

            # Extract metadata
            element_metadata = {}
            page_number = None

            if hasattr(element, "metadata"):
                meta = element.metadata
                if hasattr(meta, "page_number") and meta.page_number is not None:
                    page_number = meta.page_number
                    page_numbers.add(page_number)
                if hasattr(meta, "coordinates") and meta.coordinates is not None:
                    element_metadata["coordinates"] = str(meta.coordinates)
                if hasattr(meta, "text_as_html") and meta.text_as_html:
                    element_metadata["html"] = meta.text_as_html

            # Skip empty elements
            if not content.strip():
                continue

            # Create section
            section = DocumentSection(
                element_type=mapped_type,
                content=content,
                page_number=page_number,
                metadata=element_metadata,
            )
            sections.append(section)

            # Collect full text (skip page breaks)
            if mapped_type != ElementType.PAGE_BREAK:
                text_parts.append(content)

            # Extract title (first title element)
            if mapped_type == ElementType.TITLE and title is None:
                title = content

            # Collect headers
            if mapped_type in (ElementType.TITLE, ElementType.HEADER):
                headers.append(content)

            # Collect tables
            if mapped_type == ElementType.TABLE:
                table_data = {"content": content, "page_number": page_number}
                if "html" in element_metadata:
                    table_data["html"] = element_metadata["html"]
                tables.append(table_data)

            # Collect footnotes
            if mapped_type == ElementType.FOOTNOTE:
                footnotes.append(content)

        # Build full text
        full_text = "\n\n".join(text_parts)
        word_count = len(full_text.split())

        # Calculate page count
        page_count = max(page_numbers) if page_numbers else None

        # Add warnings for potential issues
        if not sections:
            warnings.append("No content could be extracted from the document")

        if (page_count is None or page_count == 1) and word_count > 1000:
            warnings.append(
                "Page count may be inaccurate. "
                "Document appears to have more content than reported pages."
            )

        return DocumentContent(
            full_text=full_text,
            sections=sections,
            title=title,
            page_count=page_count,
            word_count=word_count,
            metadata={"filename": filename, "element_count": len(sections)},
            tables=tables,
            headers=headers,
            footnotes=footnotes,
            warnings=warnings,
        )

    async def parse(
        self, file_content: bytes, filename: str, mime_type: str
    ) -> DocumentContent:
        """Parse a document based on its type.

        Args:
            file_content: Raw file bytes
            filename: Original filename
            mime_type: Detected MIME type

        Returns:
            Parsed document content

        Raises:
            ValidationError: If file is invalid
            FileProcessingError: If parsing fails
        """
        # Validate file
        self.validate_file(file_content, filename, mime_type)

        logger.info(
            "Parsing document",
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(file_content),
        )

        # Route to appropriate parser
        if mime_type == "application/pdf":
            return await self.parse_pdf(file_content, filename)
        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return await self.parse_docx(file_content, filename)
        else:
            raise ValidationError(f"Unsupported file type: {mime_type}")


# Singleton instance
_document_parser_instance: DocumentParser | None = None


def get_document_parser() -> DocumentParser:
    """Get document parser singleton instance."""
    global _document_parser_instance
    if _document_parser_instance is None:
        _document_parser_instance = DocumentParser(
            enable_ocr=True,
            ocr_languages=["eng"],
        )
    return _document_parser_instance
