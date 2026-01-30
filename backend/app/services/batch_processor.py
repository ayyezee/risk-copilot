"""Batch document processing service with concurrent execution.

Handles processing multiple documents with progress tracking,
rate limiting, and error handling for individual failures.
"""

import asyncio
import io
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import AIServiceError, StorageError
from app.models.database import (
    BatchJob,
    BatchJobDocument,
    BatchStatus,
    Document,
    DocumentStatus,
    ProcessedDocument,
    ReferenceExample,
    get_async_session,
)
from app.services.analytics_service import AnalyticsService, get_analytics_service
from app.services.document_ai_processor import (
    DocumentAIProcessor,
    TermReplacementResult,
    get_document_ai_processor,
)
from app.services.document_generator import DocumentGenerator, get_document_generator
from app.services.document_parser import DocumentContent, DocumentParser, get_document_parser
from app.services.file_storage import FileStorageService, get_file_storage_service
from app.services.pgvector_store import PgVectorStore, get_pgvector_store
from app.services.term_cache import TermCache, get_term_cache

settings = get_settings()
logger = structlog.get_logger()


@dataclass
class BatchProgress:
    """Current progress of a batch job."""
    batch_id: uuid.UUID
    status: str
    total_documents: int
    processed_documents: int
    failed_documents: int
    current_document: str | None = None
    percentage: float = 0.0
    estimated_remaining_seconds: int | None = None


@dataclass
class DocumentResult:
    """Result of processing a single document in a batch."""
    batch_document_id: uuid.UUID
    document_id: uuid.UUID | None
    processed_document_id: uuid.UUID | None
    success: bool
    error_message: str | None = None
    processing_time_ms: int = 0
    total_replacements: int = 0


# Type for progress callback
ProgressCallback = Callable[[BatchProgress], None]


class BatchProcessor:
    """Processes batches of documents with concurrent execution."""

    # Maximum concurrent document processing
    MAX_CONCURRENT = 5

    # Rate limiting - max API calls per minute
    RATE_LIMIT_PER_MINUTE = 50

    def __init__(
        self,
        storage: FileStorageService | None = None,
        parser: DocumentParser | None = None,
        ai_processor: DocumentAIProcessor | None = None,
        generator: DocumentGenerator | None = None,
        term_cache: TermCache | None = None,
        analytics: AnalyticsService | None = None,
    ) -> None:
        """Initialize the batch processor.

        Args:
            All services are optional and will use singletons if not provided.
        """
        self.storage = storage or get_file_storage_service()
        self.parser = parser or get_document_parser()
        self.generator = generator or get_document_generator()
        self.term_cache = term_cache or get_term_cache()
        self.analytics = analytics or get_analytics_service()

        # AI processor is lazy-loaded since it requires API key
        self._ai_processor = ai_processor

        self.logger = structlog.get_logger()

        # Semaphore for concurrency control
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)

        # Rate limiting
        self._rate_limit_tokens = self.RATE_LIMIT_PER_MINUTE
        self._rate_limit_last_refill = time.time()

        # Progress callbacks (for WebSocket updates)
        self._progress_callbacks: dict[uuid.UUID, list[ProgressCallback]] = {}

    def _get_ai_processor(self) -> DocumentAIProcessor:
        """Get AI processor, initializing if needed."""
        if self._ai_processor is None:
            self._ai_processor = get_document_ai_processor()
        return self._ai_processor

    async def _acquire_rate_limit(self) -> None:
        """Acquire a rate limit token, waiting if necessary."""
        while True:
            now = time.time()
            elapsed = now - self._rate_limit_last_refill

            # Refill tokens based on elapsed time
            if elapsed >= 60:
                self._rate_limit_tokens = self.RATE_LIMIT_PER_MINUTE
                self._rate_limit_last_refill = now
            elif elapsed > 0:
                refill = int(elapsed * (self.RATE_LIMIT_PER_MINUTE / 60))
                self._rate_limit_tokens = min(
                    self.RATE_LIMIT_PER_MINUTE,
                    self._rate_limit_tokens + refill
                )
                if refill > 0:
                    self._rate_limit_last_refill = now

            if self._rate_limit_tokens > 0:
                self._rate_limit_tokens -= 1
                return

            # Wait for token refill
            await asyncio.sleep(1)

    def register_progress_callback(
        self,
        batch_id: uuid.UUID,
        callback: ProgressCallback,
    ) -> None:
        """Register a callback for progress updates.

        Args:
            batch_id: The batch job ID
            callback: Function to call with progress updates
        """
        if batch_id not in self._progress_callbacks:
            self._progress_callbacks[batch_id] = []
        self._progress_callbacks[batch_id].append(callback)

    def unregister_progress_callback(
        self,
        batch_id: uuid.UUID,
        callback: ProgressCallback,
    ) -> None:
        """Unregister a progress callback."""
        if batch_id in self._progress_callbacks:
            try:
                self._progress_callbacks[batch_id].remove(callback)
            except ValueError:
                pass
            if not self._progress_callbacks[batch_id]:
                del self._progress_callbacks[batch_id]

    async def _notify_progress(self, progress: BatchProgress) -> None:
        """Notify all registered callbacks of progress update."""
        callbacks = self._progress_callbacks.get(progress.batch_id, [])
        for callback in callbacks:
            try:
                callback(progress)
            except Exception as e:
                self.logger.warning("Progress callback error", error=str(e))

    async def process_batch(
        self,
        batch_id: uuid.UUID,
    ) -> None:
        """Process all documents in a batch.

        This is the main entry point for background batch processing.
        It handles all documents concurrently (up to MAX_CONCURRENT),
        tracks progress, and generates the final ZIP file.

        Args:
            batch_id: The batch job ID to process
        """
        async with get_async_session() as db:
            # Get the batch job
            result = await db.execute(
                select(BatchJob).where(BatchJob.id == batch_id)
            )
            batch = result.scalar_one_or_none()

            if batch is None:
                self.logger.error("Batch job not found", batch_id=str(batch_id))
                return

            if batch.status == BatchStatus.CANCELLED:
                self.logger.info("Batch was cancelled", batch_id=str(batch_id))
                return

            # Update status to processing
            batch.status = BatchStatus.PROCESSING
            batch.started_at = datetime.now(UTC)
            await db.commit()

            self.logger.info(
                "Starting batch processing",
                batch_id=str(batch_id),
                total_documents=batch.total_documents,
            )

            # Get all batch documents
            result = await db.execute(
                select(BatchJobDocument)
                .where(BatchJobDocument.batch_job_id == batch_id)
                .order_by(BatchJobDocument.sequence_number)
            )
            batch_documents = list(result.scalars().all())

            # Get reference examples
            reference_examples = await self._get_reference_examples(
                db, batch.owner_id, batch.reference_example_ids
            )

            if not reference_examples:
                batch.status = BatchStatus.FAILED
                batch.error_message = "No reference examples available"
                batch.completed_at = datetime.now(UTC)
                await db.commit()
                return

            # Process documents concurrently
            start_time = time.time()
            results: list[DocumentResult] = []

            # Create tasks for all documents
            tasks = [
                self._process_single_document(
                    db=db,
                    batch=batch,
                    batch_doc=batch_doc,
                    reference_examples=reference_examples,
                    owner_id=batch.owner_id,
                )
                for batch_doc in batch_documents
            ]

            # Process with progress tracking
            for i, coro in enumerate(asyncio.as_completed(tasks)):
                result = await coro
                results.append(result)

                # Update batch progress
                batch.processed_documents = i + 1
                if not result.success:
                    batch.failed_documents += 1

                # Calculate progress
                elapsed = time.time() - start_time
                docs_remaining = batch.total_documents - batch.processed_documents
                avg_time_per_doc = elapsed / batch.processed_documents if batch.processed_documents > 0 else 0
                estimated_remaining = int(docs_remaining * avg_time_per_doc) if docs_remaining > 0 else 0

                progress = BatchProgress(
                    batch_id=batch_id,
                    status=batch.status,
                    total_documents=batch.total_documents,
                    processed_documents=batch.processed_documents,
                    failed_documents=batch.failed_documents,
                    current_document=None,
                    percentage=(batch.processed_documents / batch.total_documents) * 100,
                    estimated_remaining_seconds=estimated_remaining,
                )
                await self._notify_progress(progress)
                await db.commit()

            # Generate ZIP file with all processed documents
            if batch.processed_documents > batch.failed_documents:
                try:
                    zip_path = await self._generate_batch_zip(db, batch)
                    batch.output_zip_path = zip_path
                except Exception as e:
                    self.logger.error("ZIP generation failed", error=str(e))
                    batch.error_message = f"ZIP generation failed: {e}"

            # Update final status
            batch.completed_at = datetime.now(UTC)
            if batch.failed_documents == 0:
                batch.status = BatchStatus.COMPLETED
            elif batch.failed_documents == batch.total_documents:
                batch.status = BatchStatus.FAILED
            else:
                batch.status = BatchStatus.PARTIAL

            await db.commit()

            # Final progress update
            progress = BatchProgress(
                batch_id=batch_id,
                status=batch.status,
                total_documents=batch.total_documents,
                processed_documents=batch.processed_documents,
                failed_documents=batch.failed_documents,
                percentage=100.0,
            )
            await self._notify_progress(progress)

            self.logger.info(
                "Batch processing complete",
                batch_id=str(batch_id),
                status=batch.status,
                processed=batch.processed_documents,
                failed=batch.failed_documents,
                total_time_seconds=int(time.time() - start_time),
            )

    async def _get_reference_examples(
        self,
        db: AsyncSession,
        owner_id: uuid.UUID,
        example_ids: list[str] | None,
    ) -> list[ReferenceExample]:
        """Get reference examples for the batch."""
        if example_ids:
            # Fetch specific examples
            uuids = [uuid.UUID(id) for id in example_ids]
            result = await db.execute(
                select(ReferenceExample).where(
                    ReferenceExample.id.in_(uuids),
                    ReferenceExample.owner_id == owner_id,
                )
            )
            return list(result.scalars().all())
        else:
            # Get all examples for user (limited)
            result = await db.execute(
                select(ReferenceExample)
                .where(ReferenceExample.owner_id == owner_id)
                .limit(10)
            )
            return list(result.scalars().all())

    async def _process_single_document(
        self,
        db: AsyncSession,
        batch: BatchJob,
        batch_doc: BatchJobDocument,
        reference_examples: list[ReferenceExample],
        owner_id: uuid.UUID,
    ) -> DocumentResult:
        """Process a single document within the batch.

        Uses semaphore for concurrency control and rate limiting.
        """
        async with self._semaphore:
            await self._acquire_rate_limit()

            start_time = time.time()

            # Update status to processing
            batch_doc.status = DocumentStatus.PROCESSING
            await db.commit()

            try:
                # Get the document
                if batch_doc.document_id is None:
                    raise ValueError("Document not uploaded")

                result = await db.execute(
                    select(Document).where(Document.id == batch_doc.document_id)
                )
                document = result.scalar_one_or_none()

                if document is None or not document.extracted_text:
                    raise ValueError("Document not found or not parsed")

                # Create DocumentContent
                document_content = DocumentContent(
                    full_text=document.extracted_text,
                    sections=[],
                    title=document.original_filename,
                    page_count=document.page_count or 0,
                    word_count=len(document.extracted_text.split()),
                    metadata=document.doc_metadata or {},
                )

                # Analyze document
                ai_processor = self._get_ai_processor()
                analysis_result = await ai_processor.analyze_document_for_replacements(
                    document_content=document_content,
                    reference_examples=reference_examples,
                    protected_terms=batch.protected_terms or [],
                )

                # Cache successful replacements
                for replacement in analysis_result.replacements:
                    if replacement.confidence >= batch.min_confidence:
                        term_pos = document_content.full_text.lower().find(
                            replacement.original_term.lower()
                        )
                        if term_pos >= 0:
                            context_start = max(0, term_pos - 50)
                            context_end = min(
                                len(document_content.full_text),
                                term_pos + len(replacement.original_term) + 50
                            )
                            context = document_content.full_text[context_start:context_end]

                            await self.term_cache.cache_replacement(
                                owner_id=str(owner_id),
                                term=replacement.original_term,
                                context=context,
                                replacement=replacement.replacement_term,
                                confidence=replacement.confidence,
                                category=replacement.category,
                            )

                # Generate DOCX
                is_docx = document.file_type.lower() in ("docx", "doc")

                if is_docx:
                    original_bytes = await self.storage.download_file(document.storage_path)
                    original_file = io.BytesIO(original_bytes)

                    gen_result = self.generator.apply_replacements_to_docx(
                        input_file=original_file,
                        replacements=analysis_result.replacements,
                        case_sensitive=False,
                        highlight_changes=batch.highlight_changes,
                        min_confidence=batch.min_confidence,
                    )
                else:
                    gen_result = self.generator.create_docx_from_text(
                        text=document_content.full_text,
                        replacements=analysis_result.replacements,
                        original_filename=document.original_filename,
                        case_sensitive=False,
                        highlight_changes=batch.highlight_changes,
                        min_confidence=batch.min_confidence,
                    )

                # Store processed document
                output_storage_path = await self.storage.upload_file(
                    file_content=gen_result.output_bytes,
                    filename=gen_result.output_filename,
                    content_type=gen_result.content_type,
                )

                processed_doc = ProcessedDocument(
                    owner_id=owner_id,
                    source_document_id=document.id,
                    filename=gen_result.output_filename,
                    file_size=len(gen_result.output_bytes),
                    content_type=gen_result.content_type,
                    storage_path=output_storage_path,
                    document_type="processed",
                    source_format=gen_result.source_format,
                    total_replacements=gen_result.total_replacements_applied,
                    replacement_details={
                        "matches": [
                            {
                                "original_term": m.original_term,
                                "replacement_term": m.replacement_term,
                                "paragraph_index": m.paragraph_index,
                                "location_description": m.location_description,
                                "reasoning": m.reasoning,
                                "confidence": m.confidence,
                            }
                            for m in gen_result.replacement_details
                        ]
                    },
                    warnings=gen_result.warnings,
                    processing_summary=analysis_result.summary,
                )
                db.add(processed_doc)
                await db.flush()

                # Update batch document
                processing_time_ms = int((time.time() - start_time) * 1000)
                batch_doc.status = DocumentStatus.COMPLETED
                batch_doc.processed_document_id = processed_doc.id
                batch_doc.processing_time_ms = processing_time_ms
                batch_doc.total_replacements = gen_result.total_replacements_applied
                await db.commit()

                return DocumentResult(
                    batch_document_id=batch_doc.id,
                    document_id=batch_doc.document_id,
                    processed_document_id=processed_doc.id,
                    success=True,
                    processing_time_ms=processing_time_ms,
                    total_replacements=gen_result.total_replacements_applied,
                )

            except Exception as e:
                processing_time_ms = int((time.time() - start_time) * 1000)
                batch_doc.status = DocumentStatus.FAILED
                batch_doc.error_message = str(e)
                batch_doc.processing_time_ms = processing_time_ms
                await db.commit()

                self.logger.error(
                    "Document processing failed",
                    batch_doc_id=str(batch_doc.id),
                    error=str(e),
                )

                return DocumentResult(
                    batch_document_id=batch_doc.id,
                    document_id=batch_doc.document_id,
                    processed_document_id=None,
                    success=False,
                    error_message=str(e),
                    processing_time_ms=processing_time_ms,
                )

    async def _generate_batch_zip(
        self,
        db: AsyncSession,
        batch: BatchJob,
    ) -> str:
        """Generate a ZIP file containing all processed documents.

        Args:
            db: Database session
            batch: The batch job

        Returns:
            Storage path of the generated ZIP file
        """
        # Get all successfully processed documents
        result = await db.execute(
            select(BatchJobDocument)
            .where(
                BatchJobDocument.batch_job_id == batch.id,
                BatchJobDocument.status == DocumentStatus.COMPLETED,
                BatchJobDocument.processed_document_id.isnot(None),
            )
            .order_by(BatchJobDocument.sequence_number)
        )
        batch_docs = list(result.scalars().all())

        if not batch_docs:
            raise ValueError("No documents to include in ZIP")

        # Create ZIP in memory
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for batch_doc in batch_docs:
                # Get the processed document
                result = await db.execute(
                    select(ProcessedDocument)
                    .where(ProcessedDocument.id == batch_doc.processed_document_id)
                )
                processed_doc = result.scalar_one_or_none()

                if processed_doc is None:
                    continue

                # Download the file
                try:
                    file_bytes = await self.storage.download_file(processed_doc.storage_path)

                    # Use sequence number prefix for ordering
                    filename = f"{batch_doc.sequence_number:03d}_{processed_doc.filename}"
                    zf.writestr(filename, file_bytes)
                except StorageError as e:
                    self.logger.warning(
                        "Could not include file in ZIP",
                        processed_doc_id=str(processed_doc.id),
                        error=str(e),
                    )

        # Upload ZIP to storage
        zip_buffer.seek(0)
        zip_filename = f"batch_{batch.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        zip_path = await self.storage.upload_file(
            file_content=zip_buffer.getvalue(),
            filename=zip_filename,
            content_type="application/zip",
        )

        return zip_path

    async def cancel_batch(self, batch_id: uuid.UUID) -> bool:
        """Cancel a batch job.

        Args:
            batch_id: The batch job ID

        Returns:
            True if cancelled, False if not found or already complete
        """
        async with get_async_session() as db:
            result = await db.execute(
                select(BatchJob).where(BatchJob.id == batch_id)
            )
            batch = result.scalar_one_or_none()

            if batch is None:
                return False

            if batch.status in (BatchStatus.COMPLETED, BatchStatus.FAILED, BatchStatus.PARTIAL):
                return False

            batch.status = BatchStatus.CANCELLED
            batch.completed_at = datetime.now(UTC)
            await db.commit()

            self.logger.info("Batch cancelled", batch_id=str(batch_id))
            return True


# Singleton instance
_batch_processor_instance: BatchProcessor | None = None


def get_batch_processor() -> BatchProcessor:
    """Get batch processor singleton instance."""
    global _batch_processor_instance
    if _batch_processor_instance is None:
        _batch_processor_instance = BatchProcessor()
    return _batch_processor_instance
