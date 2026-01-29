"""Document processing service for text extraction and analysis."""

import io
import re
from pathlib import Path
from typing import Any

import magic
from docx import Document as DocxDocument
from pypdf import PdfReader

from app.config import get_settings
from app.core.exceptions import FileProcessingError, ValidationError
from app.models.database import DocumentType
from app.services.ai_service import AIService, get_ai_service
from app.services.file_storage import FileStorageService, get_file_storage_service
from app.services.vector_store import VectorStoreService, get_vector_store_service

settings = get_settings()


class DocumentProcessor:
    """Service for processing uploaded documents."""

    def __init__(
        self,
        storage: FileStorageService | None = None,
        vector_store: VectorStoreService | None = None,
        ai_service: AIService | None = None,
    ) -> None:
        self.storage = storage or get_file_storage_service()
        self.vector_store = vector_store or get_vector_store_service()
        self.ai_service = ai_service or get_ai_service()

    def validate_file(self, file_content: bytes, filename: str) -> tuple[str, DocumentType]:
        """Validate file type and size, return mime type and document type."""
        # Check file size
        if len(file_content) > settings.max_file_size_bytes:
            raise ValidationError(
                f"File size exceeds maximum allowed size of {settings.max_file_size_mb}MB"
            )

        # Detect mime type
        mime_type = magic.from_buffer(file_content, mime=True)

        # Map mime type to document type
        mime_to_doctype = {
            "application/pdf": DocumentType.PDF,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentType.DOCX,
            "text/plain": DocumentType.TXT,
            "text/markdown": DocumentType.MARKDOWN,
        }

        if mime_type not in settings.allowed_file_types:
            raise ValidationError(f"File type '{mime_type}' is not supported")

        doc_type = mime_to_doctype.get(mime_type)
        if doc_type is None:
            # Try to infer from extension
            ext = Path(filename).suffix.lower()
            ext_to_doctype = {
                ".pdf": DocumentType.PDF,
                ".docx": DocumentType.DOCX,
                ".txt": DocumentType.TXT,
                ".md": DocumentType.MARKDOWN,
            }
            doc_type = ext_to_doctype.get(ext, DocumentType.TXT)

        return mime_type, doc_type

    def extract_text_from_pdf(self, file_content: bytes) -> tuple[str, int]:
        """Extract text from a PDF file."""
        try:
            pdf_reader = PdfReader(io.BytesIO(file_content))
            page_count = len(pdf_reader.pages)
            text_parts = []

            for page in pdf_reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)

            return "\n\n".join(text_parts), page_count
        except Exception as e:
            raise FileProcessingError(f"Failed to extract text from PDF: {e}") from e

    def extract_text_from_docx(self, file_content: bytes) -> tuple[str, int]:
        """Extract text from a DOCX file."""
        try:
            doc = DocxDocument(io.BytesIO(file_content))
            paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
            # Approximate page count (about 500 words per page)
            word_count = sum(len(para.split()) for para in paragraphs)
            page_count = max(1, word_count // 500)
            return "\n\n".join(paragraphs), page_count
        except Exception as e:
            raise FileProcessingError(f"Failed to extract text from DOCX: {e}") from e

    def extract_text_from_txt(self, file_content: bytes) -> tuple[str, int]:
        """Extract text from a plain text file."""
        try:
            text = file_content.decode("utf-8", errors="replace")
            # Approximate page count
            word_count = len(text.split())
            page_count = max(1, word_count // 500)
            return text, page_count
        except Exception as e:
            raise FileProcessingError(f"Failed to read text file: {e}") from e

    async def extract_text(
        self, file_content: bytes, doc_type: DocumentType
    ) -> tuple[str, int]:
        """Extract text from a document based on its type."""
        extractors = {
            DocumentType.PDF: self.extract_text_from_pdf,
            DocumentType.DOCX: self.extract_text_from_docx,
            DocumentType.TXT: self.extract_text_from_txt,
            DocumentType.MARKDOWN: self.extract_text_from_txt,
        }

        extractor = extractors.get(doc_type)
        if extractor is None:
            raise FileProcessingError(f"Unsupported document type: {doc_type}")

        return extractor(file_content)

    def chunk_text(
        self,
        text: str,
        chunk_size: int = 1000,
        overlap: int = 200,
    ) -> list[str]:
        """Split text into overlapping chunks for embedding."""
        # Clean and normalize text
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size

            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence end
                for sep in [". ", "! ", "? ", "\n"]:
                    last_sep = text.rfind(sep, start + chunk_size // 2, end)
                    if last_sep > start:
                        end = last_sep + 1
                        break

            chunks.append(text[start:end].strip())
            start = end - overlap

        return chunks

    async def process_document(
        self,
        document_id: str,
        file_content: bytes,
        doc_type: DocumentType,
        generate_summary: bool = True,
        extract_metadata: bool = True,
        index_for_search: bool = True,
    ) -> dict[str, Any]:
        """Process a document: extract text, generate summary, create embeddings."""
        result: dict[str, Any] = {
            "extracted_text": None,
            "page_count": None,
            "summary": None,
            "metadata": None,
            "vector_ids": None,
        }

        # Extract text
        text, page_count = await self.extract_text(file_content, doc_type)
        result["extracted_text"] = text
        result["page_count"] = page_count

        if not text.strip():
            raise FileProcessingError("No text could be extracted from the document")

        # Generate summary
        if generate_summary and self.ai_service.is_configured():
            result["summary"] = await self.ai_service.summarize_document(text)

        # Extract metadata
        if extract_metadata and self.ai_service.is_configured():
            result["metadata"] = await self.ai_service.extract_metadata(text)

        # Index for search
        if index_for_search and self.ai_service.is_configured():
            chunks = self.chunk_text(text)
            embeddings = await self.ai_service.generate_embeddings(chunks)

            chunk_metadatas = [
                {"chunk_index": i, "chunk_count": len(chunks)}
                for i in range(len(chunks))
            ]

            vector_ids = await self.vector_store.add_document_chunks(
                document_id=document_id,
                chunks=chunks,
                embeddings=embeddings,
                metadatas=chunk_metadatas,
            )
            result["vector_ids"] = vector_ids

        return result

    async def query_documents(
        self,
        query: str,
        document_ids: list[str] | None = None,
        top_k: int = 5,
        generate_answer: bool = True,
    ) -> dict[str, Any]:
        """Query documents using semantic search."""
        if not self.ai_service.is_configured():
            raise FileProcessingError("AI service not configured for document queries")

        # Generate query embedding
        query_embedding = await self.ai_service.generate_embedding(query)

        # Search vector store
        results = await self.vector_store.search_documents(
            query_embedding=query_embedding,
            document_ids=document_ids,
            top_k=top_k,
        )

        response: dict[str, Any] = {
            "query": query,
            "results": results,
            "answer": None,
        }

        # Generate answer from context
        if generate_answer and results:
            context = [r["content"] for r in results]
            response["answer"] = await self.ai_service.answer_question(query, context)

        return response


_document_processor_instance: DocumentProcessor | None = None


def get_document_processor() -> DocumentProcessor:
    """Get document processor singleton instance."""
    global _document_processor_instance
    if _document_processor_instance is None:
        _document_processor_instance = DocumentProcessor()
    return _document_processor_instance
