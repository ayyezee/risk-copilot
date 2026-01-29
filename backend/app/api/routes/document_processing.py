"""Document AI processing routes for term replacement analysis."""

import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.auth import ActiveUser
from app.core.exceptions import AIServiceError, StorageError
from app.models.database import Document, ProcessedDocument, ReferenceExample, get_db_session
from app.models.schemas import (
    ApplyReplacementsRequest,
    ApplyReplacementsResponse,
    DocumentAnalysisRequest,
    DocumentAnalysisResponse,
    GeneratedDocumentResponse,
    ProcessDocumentRequest,
    ProcessDocumentResponse,
    ReplacementMatchDetail,
    TermReplacementItem,
)
from app.services.document_ai_processor import (
    DocumentAIProcessor,
    TermReplacement,
    get_document_ai_processor,
)
from app.services.document_generator import (
    DocumentGenerator,
    GenerationResult,
    get_document_generator,
)
from app.services.document_parser import DocumentContent, get_document_parser
from app.services.file_storage import FileStorageService, get_file_storage_service
from app.services.pgvector_store import PgVectorStore, get_pgvector_store

router = APIRouter(prefix="/process", tags=["document-processing"])


async def get_document_content(
    db: AsyncSession,
    document_id: uuid.UUID | None,
    document_text: str | None,
    owner_id: uuid.UUID,
) -> tuple[DocumentContent, uuid.UUID | None]:
    """Get document content from ID or text.

    Args:
        db: Database session
        document_id: Optional document ID
        document_text: Optional raw text
        owner_id: Owner user ID

    Returns:
        Tuple of (DocumentContent, document_id or None)

    Raises:
        HTTPException: If neither provided or document not found
    """
    if document_id:
        # Fetch from database
        result = await db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.owner_id == owner_id,
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
                detail="Document has no extracted text. Upload and parse it first.",
            )

        # Create DocumentContent from stored data
        content = DocumentContent(
            full_text=document.extracted_text,
            sections=[],
            title=document.original_filename,
            page_count=document.page_count or 0,
            word_count=len(document.extracted_text.split()),
            metadata=document.doc_metadata or {},
        )
        return content, document_id

    elif document_text:
        # Use provided text directly
        content = DocumentContent(
            full_text=document_text,
            sections=[],
            title=None,
            page_count=1,
            word_count=len(document_text.split()),
            metadata={},
        )
        return content, None

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either document_id or document_text must be provided",
        )


async def get_reference_examples(
    db: AsyncSession,
    pgvector: PgVectorStore,
    owner_id: uuid.UUID,
    example_ids: list[uuid.UUID] | None,
    document_text: str,
    top_k: int,
) -> list[ReferenceExample]:
    """Get reference examples by IDs or similarity search.

    Args:
        db: Database session
        pgvector: Vector store service
        owner_id: Owner user ID
        example_ids: Specific example IDs to use
        document_text: Document text for similarity search
        top_k: Number of examples to retrieve if using similarity

    Returns:
        List of ReferenceExample objects
    """
    if example_ids:
        # Fetch specific examples
        result = await db.execute(
            select(ReferenceExample).where(
                ReferenceExample.id.in_(example_ids),
                ReferenceExample.owner_id == owner_id,
            )
        )
        examples = list(result.scalars().all())

        if len(examples) != len(example_ids):
            found_ids = {str(e.id) for e in examples}
            missing = [str(id) for id in example_ids if str(id) not in found_ids]
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Reference examples not found: {missing}",
            )

        return examples

    else:
        # Use similarity search
        try:
            return await pgvector.get_relevant_examples(
                document_text=document_text,
                owner_id=owner_id,
                top_k=top_k,
            )
        except AIServiceError:
            # AI not configured for similarity search, return empty
            # User should specify example_ids explicitly
            return []


@router.post("/analyze", response_model=DocumentAnalysisResponse)
async def analyze_document(
    request: DocumentAnalysisRequest,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    pgvector: Annotated[PgVectorStore, Depends(get_pgvector_store)],
) -> DocumentAnalysisResponse:
    """Analyze a document to identify term replacements.

    This endpoint uses Claude's tool_use to analyze a document and identify
    terms that should be replaced based on reference examples.

    You can either:
    1. Provide a document_id of an already uploaded document
    2. Provide document_text directly

    Reference examples can be:
    1. Specified by reference_example_ids
    2. Retrieved via semantic similarity (top_k_examples)
    """
    # Get document content
    document_content, doc_id = await get_document_content(
        db=db,
        document_id=request.document_id,
        document_text=request.document_text,
        owner_id=current_user.id,
    )

    # Get reference examples
    reference_examples = await get_reference_examples(
        db=db,
        pgvector=pgvector,
        owner_id=current_user.id,
        example_ids=request.reference_example_ids,
        document_text=document_content.full_text,
        top_k=request.top_k_examples,
    )

    if not reference_examples:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No reference examples available. Upload reference examples first, "
                   "or specify reference_example_ids explicitly.",
        )

    # Get AI processor
    try:
        processor = get_document_ai_processor()
    except AIServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI service not configured: {e}",
        )

    # Analyze document
    try:
        result = await processor.analyze_document_for_replacements(
            document_content=document_content,
            reference_examples=reference_examples,
            protected_terms=request.protected_terms,
        )
    except AIServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Analysis failed: {e}",
        )

    # Filter by minimum confidence
    filtered_replacements = [
        TermReplacementItem(
            original_term=r.original_term,
            replacement_term=r.replacement_term,
            reasoning=r.reasoning,
            confidence=r.confidence,
            category=r.category,
        )
        for r in result.replacements
        if r.confidence >= request.min_confidence
    ]

    return DocumentAnalysisResponse(
        replacements=filtered_replacements,
        warnings=result.warnings,
        summary=result.summary,
        chunks_processed=result.chunks_processed,
        total_chunks=result.total_chunks,
        document_id=doc_id,
    )


@router.post("/apply", response_model=ApplyReplacementsResponse)
async def apply_replacements(
    request: ApplyReplacementsRequest,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApplyReplacementsResponse:
    """Apply term replacements to a document.

    Takes a list of replacements (from /analyze or manually specified)
    and applies them to the document text.
    """
    # Get document content
    document_content, _ = await get_document_content(
        db=db,
        document_id=request.document_id,
        document_text=request.document_text,
        owner_id=current_user.id,
    )

    original_text = document_content.full_text

    # Convert to internal format
    replacements = [
        TermReplacement(
            original_term=r.original_term,
            replacement_term=r.replacement_term,
            reasoning=r.reasoning,
            confidence=r.confidence,
            category=r.category,
        )
        for r in request.replacements
    ]

    # Get AI processor for apply function
    try:
        processor = get_document_ai_processor()
    except AIServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI service not configured: {e}",
        )

    # Apply replacements
    modified_text, changes = await processor.apply_replacements(
        text=original_text,
        replacements=replacements,
        min_confidence=request.min_confidence,
    )

    return ApplyReplacementsResponse(
        original_text=original_text,
        modified_text=modified_text,
        changes_applied=changes,
        total_replacements=sum(c["occurrences"] for c in changes),
    )


@router.post("/analyze-and-apply", response_model=ApplyReplacementsResponse)
async def analyze_and_apply(
    request: DocumentAnalysisRequest,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    pgvector: Annotated[PgVectorStore, Depends(get_pgvector_store)],
) -> ApplyReplacementsResponse:
    """Analyze a document and immediately apply replacements.

    This is a convenience endpoint that combines /analyze and /apply
    into a single call. Use this for a complete transformation workflow.
    """
    # Get document content
    document_content, doc_id = await get_document_content(
        db=db,
        document_id=request.document_id,
        document_text=request.document_text,
        owner_id=current_user.id,
    )

    # Get reference examples
    reference_examples = await get_reference_examples(
        db=db,
        pgvector=pgvector,
        owner_id=current_user.id,
        example_ids=request.reference_example_ids,
        document_text=document_content.full_text,
        top_k=request.top_k_examples,
    )

    if not reference_examples:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No reference examples available. Upload reference examples first, "
                   "or specify reference_example_ids explicitly.",
        )

    # Get AI processor
    try:
        processor = get_document_ai_processor()
    except AIServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI service not configured: {e}",
        )

    # Analyze document
    try:
        result = await processor.analyze_document_for_replacements(
            document_content=document_content,
            reference_examples=reference_examples,
            protected_terms=request.protected_terms,
        )
    except AIServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Analysis failed: {e}",
        )

    # Apply replacements
    modified_text, changes = await processor.apply_replacements(
        text=document_content.full_text,
        replacements=result.replacements,
        min_confidence=request.min_confidence,
    )

    return ApplyReplacementsResponse(
        original_text=document_content.full_text,
        modified_text=modified_text,
        changes_applied=changes,
        total_replacements=sum(c["occurrences"] for c in changes),
    )


@router.post("/documents/{document_id}/process", response_model=ProcessDocumentResponse)
async def process_document(
    document_id: uuid.UUID,
    request: ProcessDocumentRequest,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    pgvector: Annotated[PgVectorStore, Depends(get_pgvector_store)],
    storage: Annotated[FileStorageService, Depends(get_file_storage_service)],
) -> ProcessDocumentResponse:
    """Process a document through the full pipeline.

    This endpoint:
    1. Retrieves the original document
    2. Analyzes it for term replacements using Claude
    3. Generates a DOCX with replacements applied (preserving formatting for DOCX input)
    4. Optionally generates a changes report
    5. Stores the output files and returns their IDs

    For DOCX input files, formatting is preserved.
    For PDF input files, a clean DOCX is generated with the modified text.
    """
    # Get the document
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
            detail="Document has no extracted text. Upload and parse it first.",
        )

    # Create DocumentContent from stored data
    document_content = DocumentContent(
        full_text=document.extracted_text,
        sections=[],
        title=document.original_filename,
        page_count=document.page_count or 0,
        word_count=len(document.extracted_text.split()),
        metadata=document.doc_metadata or {},
    )

    # Get reference examples
    reference_examples = await get_reference_examples(
        db=db,
        pgvector=pgvector,
        owner_id=current_user.id,
        example_ids=request.reference_example_ids,
        document_text=document_content.full_text,
        top_k=request.top_k_examples,
    )

    if not reference_examples:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No reference examples available. Upload reference examples first, "
                   "or specify reference_example_ids explicitly.",
        )

    # Get AI processor
    try:
        processor = get_document_ai_processor()
    except AIServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI service not configured: {e}",
        )

    # Analyze document
    try:
        analysis_result = await processor.analyze_document_for_replacements(
            document_content=document_content,
            reference_examples=reference_examples,
            protected_terms=request.protected_terms,
        )
    except AIServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Analysis failed: {e}",
        )

    # Generate DOCX with replacements
    generator = get_document_generator()
    output_file_id: uuid.UUID | None = None
    changes_report_id: uuid.UUID | None = None

    # Check if original is DOCX and we can preserve formatting
    is_docx = document.file_type.lower() in ("docx", "doc") or document.mime_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    )

    try:
        if is_docx:
            # Download original file to preserve formatting
            original_bytes = await storage.download_file(document.storage_path)
            original_file = io.BytesIO(original_bytes)

            gen_result = generator.apply_replacements_to_docx(
                input_file=original_file,
                replacements=analysis_result.replacements,
                case_sensitive=False,
                highlight_changes=request.highlight_changes,
                min_confidence=request.min_confidence,
            )
        else:
            # PDF or other - create new DOCX from text
            gen_result = generator.create_docx_from_text(
                text=document_content.full_text,
                replacements=analysis_result.replacements,
                original_filename=document.original_filename,
                case_sensitive=False,
                highlight_changes=request.highlight_changes,
                min_confidence=request.min_confidence,
            )

        # Store the generated document
        output_storage_path = await storage.upload_file(
            file_content=gen_result.output_bytes,
            filename=gen_result.output_filename,
            content_type=gen_result.content_type,
        )

        # Create database record for processed document
        processed_doc = ProcessedDocument(
            owner_id=current_user.id,
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
        output_file_id = processed_doc.id

        # Generate changes report if requested
        if request.generate_changes_report and gen_result.replacement_details:
            report_result = generator.generate_changes_report(
                replacement_matches=gen_result.replacement_details,
                original_filename=document.original_filename,
                document_summary=analysis_result.summary,
            )

            # Store the changes report
            report_storage_path = await storage.upload_file(
                file_content=report_result.output_bytes,
                filename=report_result.output_filename,
                content_type=report_result.content_type,
            )

            # Create database record for changes report
            report_doc = ProcessedDocument(
                owner_id=current_user.id,
                source_document_id=document.id,
                filename=report_result.output_filename,
                file_size=len(report_result.output_bytes),
                content_type=report_result.content_type,
                storage_path=report_storage_path,
                document_type="changes_report",
                source_format="report",
                total_replacements=len(gen_result.replacement_details),
                replacement_details=None,
                warnings=None,
                processing_summary=analysis_result.summary,
            )
            db.add(report_doc)
            await db.flush()
            changes_report_id = report_doc.id

        await db.commit()

    except StorageError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store generated document: {e}",
        )

    # Convert replacements to response format
    replacements = [
        TermReplacementItem(
            original_term=r.original_term,
            replacement_term=r.replacement_term,
            reasoning=r.reasoning,
            confidence=r.confidence,
            category=r.category,
        )
        for r in analysis_result.replacements
        if r.confidence >= request.min_confidence
    ]

    return ProcessDocumentResponse(
        document_id=document.id,
        status="completed",
        total_replacements=gen_result.total_replacements_applied,
        replacements=replacements,
        warnings=analysis_result.warnings + gen_result.warnings,
        summary=analysis_result.summary,
        output_file_id=output_file_id,
        changes_report_id=changes_report_id,
    )


@router.get("/documents/{document_id}/outputs", response_model=list[GeneratedDocumentResponse])
async def list_document_outputs(
    document_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[GeneratedDocumentResponse]:
    """List all processed outputs for a document."""
    # Verify document ownership
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == current_user.id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Get all processed documents for this source
    result = await db.execute(
        select(ProcessedDocument).where(
            ProcessedDocument.source_document_id == document_id,
            ProcessedDocument.owner_id == current_user.id,
        ).order_by(ProcessedDocument.created_at.desc())
    )
    processed_docs = result.scalars().all()

    return [
        GeneratedDocumentResponse(
            id=doc.id,
            filename=doc.filename,
            content_type=doc.content_type,
            file_size=doc.file_size,
            total_replacements_applied=doc.total_replacements,
            source_format=doc.source_format,
            replacement_details=[
                ReplacementMatchDetail(**m)
                for m in (doc.replacement_details or {}).get("matches", [])
            ],
            warnings=doc.warnings or [],
            created_at=doc.created_at,
        )
        for doc in processed_docs
    ]


@router.get("/outputs/{output_id}/download")
async def download_processed_document(
    output_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[FileStorageService, Depends(get_file_storage_service)],
) -> StreamingResponse:
    """Download a processed document by its ID.

    Returns the DOCX file with all replacements applied.
    """
    # Get the processed document
    result = await db.execute(
        select(ProcessedDocument).where(
            ProcessedDocument.id == output_id,
            ProcessedDocument.owner_id == current_user.id,
        )
    )
    processed_doc = result.scalar_one_or_none()

    if processed_doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Processed document not found",
        )

    # Download the file
    try:
        file_bytes = await storage.download_file(processed_doc.storage_path)
    except StorageError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found in storage: {e}",
        )

    # Return as streaming response
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=processed_doc.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{processed_doc.filename}"',
            "Content-Length": str(processed_doc.file_size),
        },
    )


@router.delete("/outputs/{output_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_processed_document(
    output_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[FileStorageService, Depends(get_file_storage_service)],
) -> None:
    """Delete a processed document."""
    # Get the processed document
    result = await db.execute(
        select(ProcessedDocument).where(
            ProcessedDocument.id == output_id,
            ProcessedDocument.owner_id == current_user.id,
        )
    )
    processed_doc = result.scalar_one_or_none()

    if processed_doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Processed document not found",
        )

    # Delete from storage
    try:
        await storage.delete_file(processed_doc.storage_path)
    except StorageError:
        pass  # File may already be deleted

    # Delete from database
    await db.delete(processed_doc)
    await db.commit()
