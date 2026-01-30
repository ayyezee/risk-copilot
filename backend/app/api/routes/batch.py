"""Batch document processing API routes with WebSocket progress tracking."""

import asyncio
import io
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.auth import ActiveUser, get_current_user_ws
from app.core.exceptions import StorageError
from app.models.database import (
    BatchJob,
    BatchJobDocument,
    BatchStatus,
    Document,
    DocumentStatus,
    get_db_session,
)
from app.models.schemas import (
    BatchCreateRequest,
    BatchDocumentStatus,
    BatchJobDetailResponse,
    BatchJobResponse,
    BatchListResponse,
    BatchProgressResponse,
)
from app.services.batch_processor import BatchProcessor, BatchProgress, get_batch_processor
from app.services.document_parser import get_document_parser
from app.services.file_storage import FileStorageService, get_file_storage_service

router = APIRouter(prefix="/batch", tags=["batch-processing"])


# WebSocket connection manager
class ConnectionManager:
    """Manages WebSocket connections for batch progress updates."""

    def __init__(self) -> None:
        self.active_connections: dict[uuid.UUID, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, batch_id: uuid.UUID) -> None:
        await websocket.accept()
        if batch_id not in self.active_connections:
            self.active_connections[batch_id] = []
        self.active_connections[batch_id].append(websocket)

    def disconnect(self, websocket: WebSocket, batch_id: uuid.UUID) -> None:
        if batch_id in self.active_connections:
            try:
                self.active_connections[batch_id].remove(websocket)
            except ValueError:
                pass
            if not self.active_connections[batch_id]:
                del self.active_connections[batch_id]

    async def broadcast_progress(self, batch_id: uuid.UUID, progress: BatchProgress) -> None:
        """Broadcast progress update to all connected clients."""
        if batch_id not in self.active_connections:
            return

        message = BatchProgressResponse(
            batch_id=progress.batch_id,
            status=progress.status,
            total_documents=progress.total_documents,
            processed_documents=progress.processed_documents,
            failed_documents=progress.failed_documents,
            current_document=progress.current_document,
            percentage=progress.percentage,
            estimated_remaining_seconds=progress.estimated_remaining_seconds,
        ).model_dump_json()

        dead_connections = []
        for connection in self.active_connections[batch_id]:
            try:
                await connection.send_text(message)
            except Exception:
                dead_connections.append(connection)

        # Clean up dead connections
        for conn in dead_connections:
            self.disconnect(conn, batch_id)


manager = ConnectionManager()


def get_allowed_content_types() -> set[str]:
    """Get allowed file content types for batch upload."""
    return {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "text/plain",
        "text/markdown",
    }


def get_file_type_from_content_type(content_type: str) -> str:
    """Map content type to file type."""
    mapping = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/msword": "doc",
        "text/plain": "txt",
        "text/markdown": "md",
    }
    return mapping.get(content_type, "unknown")


@router.post("/upload", response_model=BatchJobResponse, status_code=status.HTTP_201_CREATED)
async def create_batch(
    background_tasks: BackgroundTasks,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[FileStorageService, Depends(get_file_storage_service)],
    files: list[UploadFile] = File(..., description="Documents to process"),
    reference_example_ids: list[uuid.UUID] | None = Query(default=None),
    protected_terms: list[str] | None = Query(default=None),
    min_confidence: float = Query(default=0.7, ge=0.0, le=1.0),
    highlight_changes: bool = Query(default=True),
    generate_changes_report: bool = Query(default=True),
) -> BatchJobResponse:
    """Upload multiple files and start batch processing.

    Returns a batch job ID immediately. Processing happens in the background.
    Use the WebSocket endpoint or polling to track progress.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided",
        )

    if len(files) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 100 files per batch",
        )

    allowed_types = get_allowed_content_types()
    parser = get_document_parser()

    # Create batch job
    batch = BatchJob(
        owner_id=current_user.id,
        status=BatchStatus.PENDING,
        total_documents=len(files),
        reference_example_ids=[str(id) for id in reference_example_ids] if reference_example_ids else None,
        protected_terms=protected_terms,
        min_confidence=min_confidence,
        highlight_changes=highlight_changes,
        generate_changes_report=generate_changes_report,
    )
    db.add(batch)
    await db.flush()

    # Process each file
    for i, file in enumerate(files):
        # Validate content type
        content_type = file.content_type or "application/octet-stream"
        if content_type not in allowed_types:
            # Create failed batch document entry
            batch_doc = BatchJobDocument(
                batch_job_id=batch.id,
                original_filename=file.filename or f"file_{i}",
                file_type="unknown",
                file_size=0,
                status=DocumentStatus.FAILED,
                error_message=f"Unsupported file type: {content_type}",
                sequence_number=i,
            )
            db.add(batch_doc)
            batch.failed_documents += 1
            continue

        try:
            # Read file content
            content = await file.read()
            file_size = len(content)

            if file_size == 0:
                batch_doc = BatchJobDocument(
                    batch_job_id=batch.id,
                    original_filename=file.filename or f"file_{i}",
                    file_type=get_file_type_from_content_type(content_type),
                    file_size=0,
                    status=DocumentStatus.FAILED,
                    error_message="Empty file",
                    sequence_number=i,
                )
                db.add(batch_doc)
                batch.failed_documents += 1
                continue

            # Upload to storage
            storage_path = await storage.upload_file(
                file_content=content,
                filename=file.filename or f"file_{i}",
                content_type=content_type,
            )

            # Create document record
            document = Document(
                owner_id=current_user.id,
                filename=file.filename or f"file_{i}",
                original_filename=file.filename or f"file_{i}",
                file_type=get_file_type_from_content_type(content_type),
                file_size=file_size,
                mime_type=content_type,
                storage_path=storage_path,
                status=DocumentStatus.PENDING,
            )
            db.add(document)
            await db.flush()

            # Parse document to extract text
            try:
                parsed = await parser.parse(
                    file_content=content,
                    filename=file.filename or f"file_{i}",
                    content_type=content_type,
                )
                document.extracted_text = parsed.full_text
                document.page_count = parsed.page_count
                document.status = DocumentStatus.COMPLETED
            except Exception as e:
                document.status = DocumentStatus.FAILED
                document.error_message = str(e)

            # Create batch document entry
            batch_doc = BatchJobDocument(
                batch_job_id=batch.id,
                document_id=document.id,
                original_filename=file.filename or f"file_{i}",
                file_type=document.file_type,
                file_size=file_size,
                status=DocumentStatus.PENDING if document.status == DocumentStatus.COMPLETED else DocumentStatus.FAILED,
                error_message=document.error_message,
                sequence_number=i,
            )
            db.add(batch_doc)

            if document.status == DocumentStatus.FAILED:
                batch.failed_documents += 1

        except StorageError as e:
            batch_doc = BatchJobDocument(
                batch_job_id=batch.id,
                original_filename=file.filename or f"file_{i}",
                file_type=get_file_type_from_content_type(content_type),
                file_size=0,
                status=DocumentStatus.FAILED,
                error_message=f"Storage error: {e}",
                sequence_number=i,
            )
            db.add(batch_doc)
            batch.failed_documents += 1

    await db.commit()

    # Start background processing
    processor = get_batch_processor()

    # Register WebSocket callback
    def progress_callback(progress: BatchProgress) -> None:
        asyncio.create_task(manager.broadcast_progress(batch.id, progress))

    processor.register_progress_callback(batch.id, progress_callback)
    background_tasks.add_task(processor.process_batch, batch.id)

    return BatchJobResponse(
        id=batch.id,
        status=batch.status,
        total_documents=batch.total_documents,
        processed_documents=batch.processed_documents,
        failed_documents=batch.failed_documents,
        started_at=batch.started_at,
        completed_at=batch.completed_at,
        error_message=batch.error_message,
        has_output_zip=batch.output_zip_path is not None,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


@router.get("", response_model=BatchListResponse)
async def list_batches(
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> BatchListResponse:
    """List all batch jobs for the current user."""
    # Get total count
    count_result = await db.execute(
        select(func.count(BatchJob.id))
        .where(BatchJob.owner_id == current_user.id)
    )
    total = count_result.scalar() or 0

    # Get batches
    offset = (page - 1) * page_size
    result = await db.execute(
        select(BatchJob)
        .where(BatchJob.owner_id == current_user.id)
        .order_by(desc(BatchJob.created_at))
        .limit(page_size)
        .offset(offset)
    )
    batches = list(result.scalars().all())

    return BatchListResponse(
        items=[
            BatchJobResponse(
                id=batch.id,
                status=batch.status,
                total_documents=batch.total_documents,
                processed_documents=batch.processed_documents,
                failed_documents=batch.failed_documents,
                started_at=batch.started_at,
                completed_at=batch.completed_at,
                error_message=batch.error_message,
                has_output_zip=batch.output_zip_path is not None,
                created_at=batch.created_at,
                updated_at=batch.updated_at,
            )
            for batch in batches
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{batch_id}", response_model=BatchJobDetailResponse)
async def get_batch_status(
    batch_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> BatchJobDetailResponse:
    """Get detailed status of a batch job including all documents."""
    # Get the batch
    result = await db.execute(
        select(BatchJob).where(
            BatchJob.id == batch_id,
            BatchJob.owner_id == current_user.id,
        )
    )
    batch = result.scalar_one_or_none()

    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Batch job not found",
        )

    # Get all documents
    result = await db.execute(
        select(BatchJobDocument)
        .where(BatchJobDocument.batch_job_id == batch_id)
        .order_by(BatchJobDocument.sequence_number)
    )
    documents = list(result.scalars().all())

    return BatchJobDetailResponse(
        id=batch.id,
        status=batch.status,
        total_documents=batch.total_documents,
        processed_documents=batch.processed_documents,
        failed_documents=batch.failed_documents,
        started_at=batch.started_at,
        completed_at=batch.completed_at,
        error_message=batch.error_message,
        has_output_zip=batch.output_zip_path is not None,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        documents=[
            BatchDocumentStatus(
                id=doc.id,
                original_filename=doc.original_filename,
                file_type=doc.file_type,
                file_size=doc.file_size,
                status=doc.status,
                error_message=doc.error_message,
                processing_time_ms=doc.processing_time_ms,
                total_replacements=doc.total_replacements,
                sequence_number=doc.sequence_number,
            )
            for doc in documents
        ],
        min_confidence=batch.min_confidence,
        highlight_changes=batch.highlight_changes,
        generate_changes_report=batch.generate_changes_report,
    )


@router.get("/{batch_id}/download")
async def download_batch_zip(
    batch_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[FileStorageService, Depends(get_file_storage_service)],
) -> StreamingResponse:
    """Download all processed documents as a ZIP file."""
    # Get the batch
    result = await db.execute(
        select(BatchJob).where(
            BatchJob.id == batch_id,
            BatchJob.owner_id == current_user.id,
        )
    )
    batch = result.scalar_one_or_none()

    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Batch job not found",
        )

    if batch.status not in (BatchStatus.COMPLETED, BatchStatus.PARTIAL):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch not ready for download. Status: {batch.status}",
        )

    if batch.output_zip_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ZIP file not generated",
        )

    # Download the ZIP file
    try:
        zip_bytes = await storage.download_file(batch.output_zip_path)
    except StorageError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ZIP file not found: {e}",
        )

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="batch_{batch_id}.zip"',
            "Content-Length": str(len(zip_bytes)),
        },
    )


@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_batch(
    batch_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[FileStorageService, Depends(get_file_storage_service)],
) -> None:
    """Cancel a batch job or delete a completed batch."""
    # Get the batch
    result = await db.execute(
        select(BatchJob).where(
            BatchJob.id == batch_id,
            BatchJob.owner_id == current_user.id,
        )
    )
    batch = result.scalar_one_or_none()

    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Batch job not found",
        )

    # If still processing, cancel it
    if batch.status in (BatchStatus.PENDING, BatchStatus.PROCESSING):
        processor = get_batch_processor()
        await processor.cancel_batch(batch_id)

    # Clean up ZIP file if exists
    if batch.output_zip_path:
        try:
            await storage.delete_file(batch.output_zip_path)
        except StorageError:
            pass

    # Delete the batch (cascades to batch documents)
    await db.delete(batch)
    await db.commit()


@router.websocket("/{batch_id}/progress")
async def batch_progress_websocket(
    websocket: WebSocket,
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """WebSocket endpoint for real-time batch progress updates.

    Connect to receive live updates as documents are processed.
    Messages are JSON-encoded BatchProgressResponse objects.
    """
    # Authenticate via query param token
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        return

    try:
        user = await get_current_user_ws(token, db)
    except Exception:
        await websocket.close(code=4001, reason="Invalid authentication token")
        return

    # Verify batch ownership
    result = await db.execute(
        select(BatchJob).where(
            BatchJob.id == batch_id,
            BatchJob.owner_id == user.id,
        )
    )
    batch = result.scalar_one_or_none()

    if batch is None:
        await websocket.close(code=4004, reason="Batch not found")
        return

    # Connect and wait for updates
    await manager.connect(websocket, batch_id)

    # Send initial status
    initial_progress = BatchProgressResponse(
        batch_id=batch.id,
        status=batch.status,
        total_documents=batch.total_documents,
        processed_documents=batch.processed_documents,
        failed_documents=batch.failed_documents,
        percentage=(batch.processed_documents / batch.total_documents * 100)
        if batch.total_documents > 0 else 0,
    )
    await websocket.send_text(initial_progress.model_dump_json())

    try:
        # Keep connection alive and handle any client messages
        while True:
            # Wait for messages (ping/pong handled automatically)
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Client can send "ping" to keep alive
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send ping to check connection
                await websocket.send_text("ping")
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, batch_id)
