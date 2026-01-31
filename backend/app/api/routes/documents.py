"""Document management routes."""

import uuid
from math import ceil
from typing import Annotated, Any

import magic
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.auth import ActiveUser
from app.core.exceptions import FileProcessingError, ValidationError
from app.models.database import Document, DocumentStatus, get_db_session
from app.models.schemas import (
    DocumentListResponse,
    DocumentParseResponse,
    DocumentProcessRequest,
    DocumentQueryRequest,
    DocumentQueryResponse,
    DocumentQueryResult,
    DocumentResponse,
    DocumentSectionResponse,
    DocumentUploadResponse,
)
from app.services.document_parser import DocumentParser, get_document_parser
from app.services.document_processor import DocumentProcessor, get_document_processor
from app.services.file_storage import FileStorageService, get_file_storage_service
from app.services.term_extractor import extract_defined_terms, ExtractedTerm
from app.workers.tasks import process_document_task

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[FileStorageService, Depends(get_file_storage_service)],
    processor: Annotated[DocumentProcessor, Depends(get_document_processor)],
) -> Document:
    """Upload a new document for processing."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )

    # Read file content
    content = await file.read()

    # Validate file
    mime_type, doc_type = processor.validate_file(content, file.filename)

    # Upload to storage
    storage_path = await storage.upload_file(content, file.filename, mime_type)

    # Create document record
    document = Document(
        owner_id=current_user.id,
        filename=storage_path.split("/")[-1],
        original_filename=file.filename,
        file_type=doc_type,
        file_size=len(content),
        mime_type=mime_type,
        storage_path=storage_path,
        status=DocumentStatus.PENDING,
    )
    db.add(document)
    await db.flush()
    await db.refresh(document)

    return document


@router.post("/upload", response_model=DocumentParseResponse, status_code=status.HTTP_201_CREATED)
async def upload_and_parse_document(
    file: UploadFile,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[FileStorageService, Depends(get_file_storage_service)],
    parser: Annotated[DocumentParser, Depends(get_document_parser)],
) -> DocumentParseResponse:
    """Upload and parse a document, extracting structured content.

    This endpoint accepts PDF or DOCX files and uses the unstructured library
    to extract:
    - Full text with structure preserved
    - Section headers and footnotes
    - Paragraphs
    - Tables (if any)
    - Metadata

    Supports:
    - Scanned PDFs (with OCR fallback)
    - Large files (up to 100MB)

    Returns a structured DocumentContent object with all extracted data.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )

    # Read file content
    content = await file.read()

    # Detect mime type
    mime_type = magic.from_buffer(content, mime=True)

    # Validate file extension matches mime type
    filename_lower = file.filename.lower()
    if mime_type == "application/pdf" and not filename_lower.endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File extension does not match content type (expected .pdf)",
        )
    if (
        mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        and not filename_lower.endswith(".docx")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File extension does not match content type (expected .docx)",
        )

    # Validate and parse the document
    try:
        parser.validate_file(content, file.filename, mime_type)
        parsed_content = await parser.parse(content, file.filename, mime_type)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except FileProcessingError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    # Upload to storage
    storage_path = await storage.upload_file(content, file.filename, mime_type)

    # Determine document type
    doc_type = "pdf" if mime_type == "application/pdf" else "docx"

    # Create document record
    document = Document(
        owner_id=current_user.id,
        filename=storage_path.split("/")[-1],
        original_filename=file.filename,
        file_type=doc_type,
        file_size=len(content),
        mime_type=mime_type,
        storage_path=storage_path,
        status=DocumentStatus.COMPLETED,
        extracted_text=parsed_content.full_text,
        page_count=parsed_content.page_count,
        doc_metadata=parsed_content.to_dict(),
    )
    db.add(document)
    await db.flush()
    await db.refresh(document)

    # Build response
    sections = [
        DocumentSectionResponse(
            element_type=s.element_type.value,
            content=s.content,
            page_number=s.page_number,
            metadata=s.metadata,
        )
        for s in parsed_content.sections
    ]

    return DocumentParseResponse(
        id=document.id,
        filename=document.filename,
        original_filename=document.original_filename,
        file_type=document.file_type,
        file_size=document.file_size,
        status=document.status.value if isinstance(document.status, DocumentStatus) else document.status,
        title=parsed_content.title,
        full_text=parsed_content.full_text,
        sections=sections,
        page_count=parsed_content.page_count,
        word_count=parsed_content.word_count,
        headers=parsed_content.headers,
        tables=parsed_content.tables,
        footnotes=parsed_content.footnotes,
        metadata=parsed_content.metadata,
        warnings=parsed_content.warnings,
    )


@router.post("/{document_id}/process", response_model=DocumentResponse)
async def process_document(
    document_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    process_options: DocumentProcessRequest | None = None,
) -> Document:
    """Queue document for processing."""
    # Get document
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == current_user.id,
        )
    )
    document = result.scalar_one_or_none()

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if document.status == DocumentStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is already being processed",
        )

    # Update status and queue for processing
    document.status = DocumentStatus.PROCESSING
    await db.flush()

    # Queue background task
    options = process_options or DocumentProcessRequest()
    process_document_task.delay(
        document_id=str(document_id),
        generate_summary=options.generate_summary,
        extract_metadata=options.extract_metadata,
        index_for_search=options.index_for_search,
    )

    await db.refresh(document)
    return document


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: DocumentStatus | None = None,
) -> DocumentListResponse:
    """List user's documents with pagination."""
    # Build query
    query = select(Document).where(Document.owner_id == current_user.id)
    count_query = select(func.count(Document.id)).where(Document.owner_id == current_user.id)

    if status_filter:
        query = query.where(Document.status == status_filter)
        count_query = count_query.where(Document.status == status_filter)

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results
    query = query.order_by(Document.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    documents = result.scalars().all()

    return DocumentListResponse(
        items=[DocumentResponse.model_validate(doc) for doc in documents],
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size),
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Document:
    """Get a specific document."""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == current_user.id,
        )
    )
    document = result.scalar_one_or_none()

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[FileStorageService, Depends(get_file_storage_service)],
    processor: Annotated[DocumentProcessor, Depends(get_document_processor)],
) -> None:
    """Delete a document and its associated data."""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == current_user.id,
        )
    )
    document = result.scalar_one_or_none()

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Delete from storage
    await storage.delete_file(document.storage_path)

    # Delete from vector store if indexed
    if document.vector_ids:
        await processor.vector_store.delete_document_chunks(str(document.id))

    # Delete from database
    await db.delete(document)


@router.post("/query", response_model=DocumentQueryResponse)
async def query_documents(
    query_request: DocumentQueryRequest,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    processor: Annotated[DocumentProcessor, Depends(get_document_processor)],
) -> DocumentQueryResponse:
    """Query documents using semantic search."""
    # Verify user owns the specified documents
    document_ids = query_request.document_ids
    if document_ids:
        result = await db.execute(
            select(Document.id).where(
                Document.id.in_(document_ids),
                Document.owner_id == current_user.id,
            )
        )
        owned_ids = {row[0] for row in result.all()}

        if len(owned_ids) != len(document_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more documents not found",
            )

        document_ids_str = [str(doc_id) for doc_id in document_ids]
    else:
        # Query all user's documents
        result = await db.execute(
            select(Document.id).where(
                Document.owner_id == current_user.id,
                Document.status == DocumentStatus.COMPLETED,
            )
        )
        document_ids_str = [str(row[0]) for row in result.all()]

    if not document_ids_str:
        return DocumentQueryResponse(query=query_request.query, results=[], answer=None)

    # Perform query
    query_result = await processor.query_documents(
        query=query_request.query,
        document_ids=document_ids_str,
        top_k=query_request.top_k,
    )

    # Enrich results with document info
    doc_ids_to_fetch = {r["document_id"] for r in query_result["results"]}
    result = await db.execute(
        select(Document).where(Document.id.in_([uuid.UUID(d) for d in doc_ids_to_fetch]))
    )
    documents_map = {str(doc.id): doc for doc in result.scalars().all()}

    results = []
    for r in query_result["results"]:
        doc = documents_map.get(r["document_id"])
        if doc:
            results.append(
                DocumentQueryResult(
                    document_id=doc.id,
                    filename=doc.original_filename,
                    content=r["content"],
                    score=r["score"],
                    metadata=r.get("metadata"),
                )
            )

    return DocumentQueryResponse(
        query=query_request.query,
        results=results,
        answer=query_result.get("answer"),
    )


@router.post("/{document_id}/extract-terms")
async def extract_document_terms(
    document_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Extract defined terms from a document using AI.

    Returns a list of terms with their contexts for the Term Mapper UI.
    """
    import traceback

    try:
        # Get document
        result = await db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.owner_id == current_user.id,
            )
        )
        document = result.scalar_one_or_none()

        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )

        if not document.extracted_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document has not been parsed yet. Upload using /upload endpoint first.",
            )

        # Get existing reference examples for suggestions
        from app.models.database import ReferenceExample

        examples_result = await db.execute(
            select(ReferenceExample).where(ReferenceExample.owner_id == current_user.id)
        )
        existing_mappings = [
            {"original_text": ex.original_text, "converted_text": ex.converted_text}
            for ex in examples_result.scalars().all()
        ]

        # Extract terms using AI
        extracted_terms = await extract_defined_terms(
            document_text=document.extracted_text,
            existing_mappings=existing_mappings,
        )

        return {
            "document_id": str(document_id),
            "terms": [
                {
                    "term": t.term,
                    "contexts": t.contexts,
                    "definition": t.definition,
                    "suggested_replacement": t.suggested_replacement,
                }
                for t in extracted_terms
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Term extraction error: {e}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to extract terms: {str(e)}",
        )


@router.get("/{document_id}/download")
async def download_original_document(
    document_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[FileStorageService, Depends(get_file_storage_service)],
) -> StreamingResponse:
    """Download the original uploaded document."""
    # Get document
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == current_user.id,
        )
    )
    document = result.scalar_one_or_none()

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    try:
        # Download file from storage
        print(f"Downloading file from storage path: {document.storage_path}")
        file_content = await storage.download_file(document.storage_path)
        print(f"Downloaded {len(file_content)} bytes")

        # Determine content type
        content_type = document.mime_type or "application/octet-stream"

        # Stream the response
        from io import BytesIO
        return StreamingResponse(
            BytesIO(file_content),
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{document.original_filename}"'
            },
        )
    except Exception as e:
        import traceback
        print(f"Download error: {e}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download file: {str(e)}",
        )
