"""Document AI processing routes for term replacement analysis."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.auth import ActiveUser
from app.core.exceptions import AIServiceError
from app.models.database import Document, ReferenceExample, get_db_session
from app.models.schemas import (
    ApplyReplacementsRequest,
    ApplyReplacementsResponse,
    DocumentAnalysisRequest,
    DocumentAnalysisResponse,
    TermReplacementItem,
)
from app.services.document_ai_processor import (
    DocumentAIProcessor,
    TermReplacement,
    get_document_ai_processor,
)
from app.services.document_parser import DocumentContent, get_document_parser
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
