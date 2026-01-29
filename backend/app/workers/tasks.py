"""Celery background tasks for document processing."""

import asyncio
import uuid
from datetime import UTC, datetime

from celery import Celery
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.database import Document, DocumentStatus

settings = get_settings()

# Create Celery app
celery_app = Celery(
    "document_processor",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,  # 10 minutes max per task
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)


def run_async(coro):
    """Run async function in sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_document_task(
    self,
    document_id: str,
    generate_summary: bool = True,
    extract_metadata: bool = True,
    index_for_search: bool = True,
) -> dict:
    """Process a document asynchronously."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Create sync engine for Celery worker
    sync_url = str(settings.database_url).replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        try:
            # Get document
            result = db.execute(
                select(Document).where(Document.id == uuid.UUID(document_id))
            )
            document = result.scalar_one_or_none()

            if document is None:
                return {"status": "error", "message": "Document not found"}

            # Import services
            from app.services.document_processor import DocumentProcessor
            from app.services.file_storage import FileStorageService

            storage = FileStorageService()
            processor = DocumentProcessor(storage=storage)

            # Download file content
            file_content = run_async(storage.download_file(document.storage_path))

            # Process document
            result_data = run_async(
                processor.process_document(
                    document_id=document_id,
                    file_content=file_content,
                    doc_type=document.file_type,
                    generate_summary=generate_summary,
                    extract_metadata=extract_metadata,
                    index_for_search=index_for_search,
                )
            )

            # Update document
            document.extracted_text = result_data.get("extracted_text")
            document.page_count = result_data.get("page_count")
            document.summary = result_data.get("summary")
            document.doc_metadata = result_data.get("metadata")
            document.vector_ids = result_data.get("vector_ids")
            document.status = DocumentStatus.COMPLETED
            document.updated_at = datetime.now(UTC)

            db.commit()

            return {
                "status": "success",
                "document_id": document_id,
                "page_count": result_data.get("page_count"),
                "has_summary": bool(result_data.get("summary")),
                "indexed": bool(result_data.get("vector_ids")),
            }

        except Exception as e:
            # Update document status to failed
            if document:
                document.status = DocumentStatus.FAILED
                document.error_message = str(e)[:1000]
                db.commit()

            # Retry or fail
            if self.request.retries < self.max_retries:
                raise self.retry(exc=e)

            return {"status": "error", "message": str(e)}


@celery_app.task
def cleanup_expired_tokens() -> dict:
    """Clean up expired refresh tokens."""
    from sqlalchemy import create_engine, delete
    from sqlalchemy.orm import sessionmaker

    from app.models.database import RefreshToken

    sync_url = str(settings.database_url).replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        result = db.execute(
            delete(RefreshToken).where(RefreshToken.expires_at < datetime.now(UTC))
        )
        deleted_count = result.rowcount
        db.commit()

        return {"deleted_tokens": deleted_count}


@celery_app.task
def reindex_document(document_id: str) -> dict:
    """Re-index a document in the vector store."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    sync_url = str(settings.database_url).replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        try:
            result = db.execute(
                select(Document).where(Document.id == uuid.UUID(document_id))
            )
            document = result.scalar_one_or_none()

            if document is None or not document.extracted_text:
                return {"status": "error", "message": "Document not found or not processed"}

            from app.services.ai_service import AIService
            from app.services.document_processor import DocumentProcessor
            from app.services.vector_store import VectorStoreService

            ai_service = AIService()
            vector_store = VectorStoreService()
            processor = DocumentProcessor(ai_service=ai_service, vector_store=vector_store)

            # Delete existing chunks
            if document.vector_ids:
                run_async(vector_store.delete_document_chunks(document_id))

            # Re-index
            chunks = processor.chunk_text(document.extracted_text)
            embeddings = run_async(ai_service.generate_embeddings(chunks))

            chunk_metadatas = [
                {"chunk_index": i, "chunk_count": len(chunks)}
                for i in range(len(chunks))
            ]

            vector_ids = run_async(
                vector_store.add_document_chunks(
                    document_id=document_id,
                    chunks=chunks,
                    embeddings=embeddings,
                    metadatas=chunk_metadatas,
                )
            )

            document.vector_ids = vector_ids
            document.updated_at = datetime.now(UTC)
            db.commit()

            return {"status": "success", "chunks_indexed": len(chunks)}

        except Exception as e:
            return {"status": "error", "message": str(e)}


# Celery Beat schedule for periodic tasks
celery_app.conf.beat_schedule = {
    "cleanup-expired-tokens": {
        "task": "app.workers.tasks.cleanup_expired_tokens",
        "schedule": 3600.0,  # Every hour
    },
}
