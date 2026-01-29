"""Reference examples API for semantic search with pgvector.

This module provides endpoints for managing reference examples (before/after document pairs)
that are used to guide document transformation. Examples are embedded using OpenAI embeddings
and stored in PostgreSQL with pgvector for efficient semantic search.
"""

import uuid
from math import ceil
from typing import Annotated

import magic
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.auth import ActiveUser
from app.core.exceptions import StorageError, ValidationError
from app.models.database import ReferenceExample, get_db_session
from app.models.schemas import (
    ReferenceExampleCreate,
    ReferenceExampleListResponse,
    ReferenceExampleResponse,
    ReferenceExampleSearchRequest,
    ReferenceExampleSearchResponse,
    ReferenceExampleSearchResult,
    TermMapping,
    TermMappingsResponse,
)
from app.services.ai_service import AIService, get_ai_service
from app.services.document_parser import DocumentParser, get_document_parser
from app.services.pgvector_store import PgVectorStore, get_pgvector_store

router = APIRouter(prefix="/reference-library", tags=["reference-library"])


async def extract_term_mappings(
    ai_service: AIService,
    original_text: str,
    converted_text: str,
) -> dict:
    """Use Claude to extract term mappings between original and converted text.

    Args:
        ai_service: AI service for text generation
        original_text: The original document text
        converted_text: The converted/transformed document text

    Returns:
        Dictionary containing extracted mappings and summary
    """
    if not ai_service.is_configured():
        return {"mappings": [], "summary": None}

    system_prompt = """You are an expert document analyst. Your task is to identify and extract
term mappings between an original document and its converted/transformed version.

For each significant change, identify:
1. The original term or phrase
2. The converted term or phrase
3. The context in which the change appears
4. The category of change (legal, financial, technical, formatting, etc.)

Return your analysis as a JSON object with this structure:
{
    "mappings": [
        {
            "original_term": "the original text",
            "converted_term": "the new text",
            "context": "brief context explanation",
            "category": "legal|financial|technical|formatting|other"
        }
    ],
    "summary": "A brief 1-2 sentence summary of the main transformation patterns"
}

Focus on substantive changes, not minor formatting differences."""

    # Truncate texts if too long (keep first 3000 chars of each)
    orig_truncated = original_text[:3000] + ("..." if len(original_text) > 3000 else "")
    conv_truncated = converted_text[:3000] + ("..." if len(converted_text) > 3000 else "")

    prompt = f"""Analyze the following document transformation and extract the term mappings.

ORIGINAL DOCUMENT:
{orig_truncated}

CONVERTED DOCUMENT:
{conv_truncated}

Please extract all significant term mappings between these documents."""

    try:
        response = await ai_service.generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=2000,
            temperature=0.1,
        )

        # Parse JSON response
        import json
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except json.JSONDecodeError:
            pass

        return {"mappings": [], "summary": response[:500], "raw_response": response}

    except Exception as e:
        return {"mappings": [], "summary": None, "error": str(e)}


@router.post("/upload", response_model=ReferenceExampleResponse, status_code=status.HTTP_201_CREATED)
async def upload_reference_pair(
    name: Annotated[str, Form()],
    original_file: UploadFile,
    converted_file: UploadFile,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    ai_service: Annotated[AIService, Depends(get_ai_service)],
    pgvector: Annotated[PgVectorStore, Depends(get_pgvector_store)],
    parser: Annotated[DocumentParser, Depends(get_document_parser)],
    description: Annotated[str | None, Form()] = None,
) -> ReferenceExample:
    """Upload a before/after document pair as a reference example.

    This endpoint:
    1. Parses both uploaded documents
    2. Uses Claude to extract the term mappings (what changed and why)
    3. Embeds the original document for semantic search
    4. Stores everything in PostgreSQL with pgvector
    """
    # Validate file names
    if not original_file.filename or not converted_file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both files must have filenames",
        )

    # Read file contents
    original_content = await original_file.read()
    converted_content = await converted_file.read()

    # Detect MIME types
    original_mime = magic.from_buffer(original_content, mime=True)
    converted_mime = magic.from_buffer(converted_content, mime=True)

    # Parse documents
    try:
        original_parsed = await parser.parse(original_content, original_file.filename, original_mime)
        converted_parsed = await parser.parse(converted_content, converted_file.filename, converted_mime)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse documents: {e}",
        )

    # Extract term mappings using Claude
    term_mappings = await extract_term_mappings(
        ai_service=ai_service,
        original_text=original_parsed.full_text,
        converted_text=converted_parsed.full_text,
    )

    # Create reference example
    example = ReferenceExample(
        owner_id=current_user.id,
        name=name,
        description=description,
        original_text=original_parsed.full_text,
        converted_text=converted_parsed.full_text,
        term_mappings=term_mappings,
        original_filename=original_file.filename,
        converted_filename=converted_file.filename,
        original_file_type=original_mime.split("/")[-1],
        converted_file_type=converted_mime.split("/")[-1],
    )

    # Add to database with embedding (skip if AI not configured)
    try:
        skip_embedding = not ai_service.is_configured()
        example = await pgvector.add_reference_example(db, example, skip_embedding=skip_embedding)
    except StorageError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to store reference example: {e}",
        )

    return example


@router.post("", response_model=ReferenceExampleResponse, status_code=status.HTTP_201_CREATED)
async def create_reference_example(
    example_data: ReferenceExampleCreate,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    ai_service: Annotated[AIService, Depends(get_ai_service)],
    pgvector: Annotated[PgVectorStore, Depends(get_pgvector_store)],
) -> ReferenceExample:
    """Create a reference example from text (without file upload).

    This endpoint accepts raw text for both original and converted versions.
    It automatically extracts term mappings and generates embeddings.
    """
    # Extract term mappings using Claude
    term_mappings = await extract_term_mappings(
        ai_service=ai_service,
        original_text=example_data.original_text,
        converted_text=example_data.converted_text,
    )

    # Create reference example
    example = ReferenceExample(
        owner_id=current_user.id,
        name=example_data.name,
        description=example_data.description,
        original_text=example_data.original_text,
        converted_text=example_data.converted_text,
        term_mappings=term_mappings,
        original_filename=example_data.original_filename,
        converted_filename=example_data.converted_filename,
    )

    # Add to database with embedding (skip if AI not configured)
    try:
        skip_embedding = not ai_service.is_configured()
        example = await pgvector.add_reference_example(db, example, skip_embedding=skip_embedding)
    except StorageError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to store reference example: {e}",
        )

    return example


@router.get("", response_model=ReferenceExampleListResponse)
async def list_reference_examples(
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ReferenceExampleListResponse:
    """List user's reference examples with pagination."""
    # Build queries
    query = select(ReferenceExample).where(ReferenceExample.owner_id == current_user.id)
    count_query = select(func.count(ReferenceExample.id)).where(
        ReferenceExample.owner_id == current_user.id
    )

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results
    query = query.order_by(ReferenceExample.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    items = result.scalars().all()

    return ReferenceExampleListResponse(
        items=[ReferenceExampleResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if total > 0 else 1,
    )


@router.get("/{example_id}", response_model=ReferenceExampleResponse)
async def get_reference_example(
    example_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReferenceExample:
    """Get a specific reference example."""
    result = await db.execute(
        select(ReferenceExample).where(
            ReferenceExample.id == example_id,
            ReferenceExample.owner_id == current_user.id,
        )
    )
    example = result.scalar_one_or_none()

    if example is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reference example not found",
        )

    return example


@router.delete("/{example_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reference_example(
    example_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    pgvector: Annotated[PgVectorStore, Depends(get_pgvector_store)],
) -> None:
    """Delete a reference example."""
    result = await db.execute(
        select(ReferenceExample).where(
            ReferenceExample.id == example_id,
            ReferenceExample.owner_id == current_user.id,
        )
    )
    example = result.scalar_one_or_none()

    if example is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reference example not found",
        )

    await db.delete(example)


@router.post("/search", response_model=ReferenceExampleSearchResponse)
async def search_reference_examples(
    search_request: ReferenceExampleSearchRequest,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    ai_service: Annotated[AIService, Depends(get_ai_service)],
    pgvector: Annotated[PgVectorStore, Depends(get_pgvector_store)],
) -> ReferenceExampleSearchResponse:
    """Search reference examples using semantic similarity.

    This endpoint finds reference examples most similar to the provided query text.
    Use this to find relevant examples for document processing or to debug
    the retrieval system.

    Note: Requires AI service to be configured for embedding generation.
    """
    if not ai_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic search requires AI service configuration (OPENAI_API_KEY or ANTHROPIC_API_KEY). "
                   "Reference examples were stored without embeddings.",
        )

    try:
        results = await pgvector.search_similar_examples(
            session=db,
            query_text=search_request.query,
            owner_id=current_user.id,
            top_k=search_request.top_k,
            similarity_threshold=search_request.similarity_threshold,
        )
    except StorageError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Search failed: {e}",
        )

    # Fetch full examples for response
    if not results:
        return ReferenceExampleSearchResponse(query=search_request.query, results=[])

    example_ids = [uuid.UUID(r["id"]) for r in results]
    query = select(ReferenceExample).where(ReferenceExample.id.in_(example_ids))
    result = await db.execute(query)
    examples_map = {str(e.id): e for e in result.scalars().all()}

    search_results = []
    for r in results:
        example = examples_map.get(r["id"])
        if example:
            search_results.append(
                ReferenceExampleSearchResult(
                    example=ReferenceExampleResponse.model_validate(example),
                    similarity=r["similarity"],
                )
            )

    return ReferenceExampleSearchResponse(
        query=search_request.query,
        results=search_results,
    )


@router.get("/{example_id}/mappings", response_model=TermMappingsResponse)
async def get_term_mappings(
    example_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> TermMappingsResponse:
    """Get the extracted term mappings for a reference example."""
    result = await db.execute(
        select(ReferenceExample).where(
            ReferenceExample.id == example_id,
            ReferenceExample.owner_id == current_user.id,
        )
    )
    example = result.scalar_one_or_none()

    if example is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reference example not found",
        )

    mappings = []
    summary = None

    if example.term_mappings:
        raw_mappings = example.term_mappings.get("mappings", [])
        for m in raw_mappings:
            if isinstance(m, dict):
                mappings.append(
                    TermMapping(
                        original_term=m.get("original_term", ""),
                        converted_term=m.get("converted_term", ""),
                        context=m.get("context"),
                        category=m.get("category"),
                    )
                )
        summary = example.term_mappings.get("summary")

    return TermMappingsResponse(
        example_id=example.id,
        mappings=mappings,
        summary=summary,
    )


@router.post("/{example_id}/reindex", response_model=ReferenceExampleResponse)
async def reindex_reference_example(
    example_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    pgvector: Annotated[PgVectorStore, Depends(get_pgvector_store)],
) -> ReferenceExample:
    """Regenerate the embedding for a reference example.

    Useful if the embedding model has changed or if the original embedding
    was not generated.
    """
    result = await db.execute(
        select(ReferenceExample).where(
            ReferenceExample.id == example_id,
            ReferenceExample.owner_id == current_user.id,
        )
    )
    example = result.scalar_one_or_none()

    if example is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reference example not found",
        )

    try:
        await pgvector.update_reference_embedding(
            session=db,
            example_id=example.id,
            text_to_embed=example.original_text,
        )
    except StorageError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to reindex: {e}",
        )

    await db.refresh(example)
    return example
