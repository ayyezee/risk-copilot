"""Reference library routes for storing and searching reusable content."""

import uuid
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.auth import ActiveUser
from app.models.database import ReferenceItem, get_db_session
from app.models.schemas import (
    ReferenceItemCreate,
    ReferenceItemListResponse,
    ReferenceItemResponse,
    ReferenceItemUpdate,
    ReferenceSearchRequest,
    ReferenceSearchResponse,
    ReferenceSearchResult,
)
from app.services.ai_service import AIService, get_ai_service
from app.services.vector_store import VectorStoreService, get_vector_store_service

router = APIRouter(prefix="/references", tags=["references"])


@router.post("", response_model=ReferenceItemResponse, status_code=status.HTTP_201_CREATED)
async def create_reference_item(
    item_data: ReferenceItemCreate,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    ai_service: Annotated[AIService, Depends(get_ai_service)],
    vector_store: Annotated[VectorStoreService, Depends(get_vector_store_service)],
) -> ReferenceItem:
    """Create a new reference library item."""
    # Create database record
    item = ReferenceItem(
        owner_id=current_user.id,
        title=item_data.title,
        content=item_data.content,
        category=item_data.category,
        tags=item_data.tags,
        item_metadata=item_data.metadata,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)

    # Index for search if AI service is configured
    if ai_service.is_configured():
        embedding = await ai_service.generate_embedding(
            f"{item.title}\n\n{item.content}"
        )
        vector_id = await vector_store.add_reference_item(
            item_id=str(item.id),
            content=f"{item.title}\n\n{item.content}",
            embedding=embedding,
            metadata={
                "owner_id": str(current_user.id),
                "category": item.category,
                "tags": item.tags,
            },
        )
        item.vector_id = vector_id

    return item


@router.get("", response_model=ReferenceItemListResponse)
async def list_reference_items(
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category: str | None = None,
    tag: str | None = None,
) -> ReferenceItemListResponse:
    """List user's reference items with pagination."""
    # Build query
    query = select(ReferenceItem).where(ReferenceItem.owner_id == current_user.id)
    count_query = select(func.count(ReferenceItem.id)).where(
        ReferenceItem.owner_id == current_user.id
    )

    if category:
        query = query.where(ReferenceItem.category == category)
        count_query = count_query.where(ReferenceItem.category == category)

    if tag:
        query = query.where(ReferenceItem.tags.contains([tag]))
        count_query = count_query.where(ReferenceItem.tags.contains([tag]))

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results
    query = query.order_by(ReferenceItem.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    items = result.scalars().all()

    return ReferenceItemListResponse(
        items=[ReferenceItemResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size),
    )


@router.get("/{item_id}", response_model=ReferenceItemResponse)
async def get_reference_item(
    item_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReferenceItem:
    """Get a specific reference item."""
    result = await db.execute(
        select(ReferenceItem).where(
            ReferenceItem.id == item_id,
            ReferenceItem.owner_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reference item not found",
        )

    return item


@router.put("/{item_id}", response_model=ReferenceItemResponse)
async def update_reference_item(
    item_id: uuid.UUID,
    item_data: ReferenceItemUpdate,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    ai_service: Annotated[AIService, Depends(get_ai_service)],
    vector_store: Annotated[VectorStoreService, Depends(get_vector_store_service)],
) -> ReferenceItem:
    """Update a reference item."""
    result = await db.execute(
        select(ReferenceItem).where(
            ReferenceItem.id == item_id,
            ReferenceItem.owner_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reference item not found",
        )

    # Update fields
    update_data = item_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)

    # Update vector store if content changed
    if ai_service.is_configured() and ("title" in update_data or "content" in update_data):
        embedding = await ai_service.generate_embedding(
            f"{item.title}\n\n{item.content}"
        )
        if item.vector_id:
            await vector_store.update_reference_item(
                item_id=str(item.id),
                content=f"{item.title}\n\n{item.content}",
                embedding=embedding,
                metadata={
                    "owner_id": str(current_user.id),
                    "category": item.category,
                    "tags": item.tags,
                },
            )
        else:
            vector_id = await vector_store.add_reference_item(
                item_id=str(item.id),
                content=f"{item.title}\n\n{item.content}",
                embedding=embedding,
                metadata={
                    "owner_id": str(current_user.id),
                    "category": item.category,
                    "tags": item.tags,
                },
            )
            item.vector_id = vector_id

    await db.flush()
    await db.refresh(item)

    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reference_item(
    item_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    vector_store: Annotated[VectorStoreService, Depends(get_vector_store_service)],
) -> None:
    """Delete a reference item."""
    result = await db.execute(
        select(ReferenceItem).where(
            ReferenceItem.id == item_id,
            ReferenceItem.owner_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reference item not found",
        )

    # Delete from vector store
    if item.vector_id:
        await vector_store.delete_reference_item(str(item.id))

    # Delete from database
    await db.delete(item)


@router.post("/search", response_model=ReferenceSearchResponse)
async def search_references(
    search_request: ReferenceSearchRequest,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    ai_service: Annotated[AIService, Depends(get_ai_service)],
    vector_store: Annotated[VectorStoreService, Depends(get_vector_store_service)],
) -> ReferenceSearchResponse:
    """Search reference items using semantic search."""
    if not ai_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service not configured for semantic search",
        )

    # Generate query embedding
    query_embedding = await ai_service.generate_embedding(search_request.query)

    # Search vector store
    search_results = await vector_store.search_references(
        query_embedding=query_embedding,
        owner_id=str(current_user.id),
        category=search_request.category,
        tags=search_request.tags,
        top_k=search_request.top_k,
    )

    # Fetch full items from database
    item_ids = [uuid.UUID(r["id"]) for r in search_results]
    if not item_ids:
        return ReferenceSearchResponse(query=search_request.query, results=[])

    result = await db.execute(
        select(ReferenceItem).where(ReferenceItem.id.in_(item_ids))
    )
    items_map = {str(item.id): item for item in result.scalars().all()}

    # Build response with scores
    results = []
    for r in search_results:
        item = items_map.get(r["id"])
        if item:
            results.append(
                ReferenceSearchResult(
                    item=ReferenceItemResponse.model_validate(item),
                    score=r["score"],
                )
            )

    return ReferenceSearchResponse(
        query=search_request.query,
        results=results,
    )


@router.get("/categories/list", response_model=list[str])
async def list_categories(
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[str]:
    """List all unique categories for user's reference items."""
    result = await db.execute(
        select(ReferenceItem.category)
        .where(
            ReferenceItem.owner_id == current_user.id,
            ReferenceItem.category.isnot(None),
        )
        .distinct()
    )
    categories = [row[0] for row in result.all() if row[0]]
    return sorted(categories)
