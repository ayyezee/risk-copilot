"""Analytics API routes for processing metrics, patterns, and insights."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.auth import ActiveUser
from app.models.database import ProcessingLog, UserCorrection, get_db_session
from app.models.schemas import (
    AnalyticsDashboardResponse,
    AmbiguousTermResponse,
    CacheStatsResponse,
    CorrectionCreate,
    CorrectionListResponse,
    CorrectionResponse,
    DailyMetricsResponse,
    ProcessingLogListResponse,
    ProcessingLogResponse,
    ProcessingMetricsResponse,
    TermPatternResponse,
    TopReplacementResponse,
)
from app.services.analytics_service import AnalyticsService, get_analytics_service
from app.services.term_cache import TermCache, get_term_cache

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/dashboard", response_model=AnalyticsDashboardResponse)
async def get_analytics_dashboard(
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    analytics: Annotated[AnalyticsService, Depends(get_analytics_service)],
    days: int = Query(default=30, ge=1, le=365, description="Number of days for historical data"),
) -> AnalyticsDashboardResponse:
    """Get the complete analytics dashboard.

    Returns aggregated metrics, top replacements, patterns, and insights.
    """
    dashboard = await analytics.get_dashboard(db, current_user.id, days)

    return AnalyticsDashboardResponse(
        daily_metrics=[
            DailyMetricsResponse(
                date=m.date,
                documents_processed=m.documents_processed,
                total_replacements=m.total_replacements,
                tokens_used=m.tokens_used,
                avg_processing_time_ms=m.avg_processing_time_ms,
            )
            for m in dashboard.daily_metrics
        ],
        weekly_total=ProcessingMetricsResponse(
            total_documents=dashboard.weekly_total.total_documents,
            total_replacements=dashboard.weekly_total.total_replacements,
            total_processing_time_ms=dashboard.weekly_total.total_processing_time_ms,
            total_tokens_used=dashboard.weekly_total.total_tokens_used,
            total_cache_hits=dashboard.weekly_total.total_cache_hits,
            total_cache_misses=dashboard.weekly_total.total_cache_misses,
            avg_processing_time_ms=dashboard.weekly_total.avg_processing_time_ms,
            avg_replacements_per_doc=dashboard.weekly_total.avg_replacements_per_doc,
            cache_hit_rate=dashboard.weekly_total.cache_hit_rate,
            estimated_cost_usd=dashboard.weekly_total.estimated_cost_usd,
        ),
        monthly_total=ProcessingMetricsResponse(
            total_documents=dashboard.monthly_total.total_documents,
            total_replacements=dashboard.monthly_total.total_replacements,
            total_processing_time_ms=dashboard.monthly_total.total_processing_time_ms,
            total_tokens_used=dashboard.monthly_total.total_tokens_used,
            total_cache_hits=dashboard.monthly_total.total_cache_hits,
            total_cache_misses=dashboard.monthly_total.total_cache_misses,
            avg_processing_time_ms=dashboard.monthly_total.avg_processing_time_ms,
            avg_replacements_per_doc=dashboard.monthly_total.avg_replacements_per_doc,
            cache_hit_rate=dashboard.monthly_total.cache_hit_rate,
            estimated_cost_usd=dashboard.monthly_total.estimated_cost_usd,
        ),
        all_time_total=ProcessingMetricsResponse(
            total_documents=dashboard.all_time_total.total_documents,
            total_replacements=dashboard.all_time_total.total_replacements,
            total_processing_time_ms=dashboard.all_time_total.total_processing_time_ms,
            total_tokens_used=dashboard.all_time_total.total_tokens_used,
            total_cache_hits=dashboard.all_time_total.total_cache_hits,
            total_cache_misses=dashboard.all_time_total.total_cache_misses,
            avg_processing_time_ms=dashboard.all_time_total.avg_processing_time_ms,
            avg_replacements_per_doc=dashboard.all_time_total.avg_replacements_per_doc,
            cache_hit_rate=dashboard.all_time_total.cache_hit_rate,
            estimated_cost_usd=dashboard.all_time_total.estimated_cost_usd,
        ),
        top_replacements=[
            TopReplacementResponse(
                original_term=r.original_term,
                replacement_term=r.replacement_term,
                occurrence_count=r.occurrence_count,
                avg_confidence=r.avg_confidence,
                category=r.category,
            )
            for r in dashboard.top_replacements
        ],
        high_confidence_patterns=[
            TermPatternResponse(
                original_term=p.original_term,
                replacement_term=p.replacement_term,
                total_uses=p.total_uses,
                avg_confidence=p.avg_confidence,
                category=p.category,
                is_high_confidence=p.is_high_confidence,
            )
            for p in dashboard.high_confidence_patterns
        ],
        ambiguous_terms=[
            AmbiguousTermResponse(
                term=t.term,
                occurrence_count=t.occurrence_count,
                unique_replacements=t.unique_replacements,
                avg_confidence=t.avg_confidence,
                replacements=t.replacements,
            )
            for t in dashboard.ambiguous_terms
        ],
        cache_stats=CacheStatsResponse(**dashboard.cache_stats),
        total_corrections=dashboard.total_corrections,
        correction_rate=dashboard.correction_rate,
        estimated_monthly_cost_usd=dashboard.estimated_monthly_cost_usd,
    )


@router.get("/patterns", response_model=list[TermPatternResponse])
async def get_term_patterns(
    current_user: ActiveUser,
    min_uses: int = Query(default=3, ge=1, description="Minimum usage count"),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum patterns to return"),
) -> list[TermPatternResponse]:
    """Get frequently occurring term replacement patterns.

    These patterns are tracked in the cache and represent common replacements
    that have been used multiple times.
    """
    term_cache = get_term_cache()
    patterns = await term_cache.get_term_patterns(str(current_user.id), min_uses, limit)

    return [
        TermPatternResponse(
            original_term=p.original_term,
            replacement_term=p.replacement_term,
            total_uses=p.total_uses,
            avg_confidence=p.avg_confidence,
            category=p.category,
            is_high_confidence=p.is_high_confidence,
        )
        for p in patterns
    ]


@router.get("/patterns/high-confidence", response_model=list[TermPatternResponse])
async def get_high_confidence_patterns(
    current_user: ActiveUser,
) -> list[TermPatternResponse]:
    """Get high-confidence patterns that could be promoted to rules.

    These patterns have been used many times with consistently high confidence,
    making them candidates for automatic application without AI analysis.
    """
    term_cache = get_term_cache()
    patterns = await term_cache.get_high_confidence_patterns(str(current_user.id))

    return [
        TermPatternResponse(
            original_term=p.original_term,
            replacement_term=p.replacement_term,
            total_uses=p.total_uses,
            avg_confidence=p.avg_confidence,
            category=p.category,
            is_high_confidence=p.is_high_confidence,
        )
        for p in patterns
    ]


@router.get("/cache-stats", response_model=CacheStatsResponse)
async def get_cache_stats(
    current_user: ActiveUser,
) -> CacheStatsResponse:
    """Get cache performance statistics.

    Shows cache hit/miss rates and estimated API calls saved.
    """
    term_cache = get_term_cache()
    stats = await term_cache.get_cache_stats(str(current_user.id))
    return CacheStatsResponse(**stats)


@router.get("/processing-logs", response_model=ProcessingLogListResponse)
async def list_processing_logs(
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ProcessingLogListResponse:
    """List processing logs for the current user.

    Shows history of document processing operations with metrics.
    """
    # Get total count
    count_result = await db.execute(
        select(func.count(ProcessingLog.id))
        .where(ProcessingLog.owner_id == current_user.id)
    )
    total = count_result.scalar() or 0

    # Get logs
    offset = (page - 1) * page_size
    result = await db.execute(
        select(ProcessingLog)
        .where(ProcessingLog.owner_id == current_user.id)
        .order_by(desc(ProcessingLog.created_at))
        .limit(page_size)
        .offset(offset)
    )
    logs = list(result.scalars().all())

    return ProcessingLogListResponse(
        items=[
            ProcessingLogResponse(
                id=log.id,
                document_id=log.document_id,
                total_replacements=log.total_replacements,
                processing_time_ms=log.processing_time_ms,
                tokens_used=log.tokens_used,
                cache_hits=log.cache_hits,
                cache_misses=log.cache_misses,
                document_word_count=log.document_word_count,
                document_type=log.document_type,
                chunks_processed=log.chunks_processed,
                status=log.status,
                error_message=log.error_message,
                created_at=log.created_at,
                updated_at=log.updated_at,
            )
            for log in logs
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/corrections", response_model=CorrectionResponse, status_code=status.HTTP_201_CREATED)
async def create_correction(
    correction: CorrectionCreate,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    analytics: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> CorrectionResponse:
    """Record a user correction for learning.

    When a user marks a replacement as incorrect or modifies it,
    this feedback helps the system learn and improve.

    Correction types:
    - rejected: The replacement should not have been made
    - modified: A different replacement should have been used
    - accepted: Confirm the replacement was correct (positive feedback)
    """
    # Validate modified type has user_replacement
    if correction.correction_type == "modified" and not correction.user_replacement:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_replacement is required for 'modified' correction type",
        )

    user_correction = await analytics.record_correction(
        db=db,
        owner_id=current_user.id,
        original_term=correction.original_term,
        suggested_replacement=correction.suggested_replacement,
        suggested_confidence=correction.suggested_confidence,
        correction_type=correction.correction_type,
        user_replacement=correction.user_replacement,
        user_reason=correction.user_reason,
        context_before=correction.context_before,
        context_after=correction.context_after,
        processing_log_id=correction.processing_log_id,
        document_id=correction.document_id,
    )
    await db.commit()

    return CorrectionResponse(
        id=user_correction.id,
        original_term=user_correction.original_term,
        suggested_replacement=user_correction.suggested_replacement,
        suggested_confidence=user_correction.suggested_confidence,
        correction_type=user_correction.correction_type,
        user_replacement=user_correction.user_replacement,
        user_reason=user_correction.user_reason,
        context_before=user_correction.context_before,
        context_after=user_correction.context_after,
        processing_log_id=user_correction.processing_log_id,
        document_id=user_correction.document_id,
        processed=user_correction.processed,
        created_at=user_correction.created_at,
        updated_at=user_correction.updated_at,
    )


@router.get("/corrections", response_model=CorrectionListResponse)
async def list_corrections(
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    analytics: Annotated[AnalyticsService, Depends(get_analytics_service)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> CorrectionListResponse:
    """List user corrections.

    Shows history of corrections made for learning.
    """
    offset = (page - 1) * page_size
    corrections, total = await analytics.get_correction_history(
        db, current_user.id, limit=page_size, offset=offset
    )

    return CorrectionListResponse(
        items=[
            CorrectionResponse(
                id=c.id,
                original_term=c.original_term,
                suggested_replacement=c.suggested_replacement,
                suggested_confidence=c.suggested_confidence,
                correction_type=c.correction_type,
                user_replacement=c.user_replacement,
                user_reason=c.user_reason,
                context_before=c.context_before,
                context_after=c.context_after,
                processing_log_id=c.processing_log_id,
                document_id=c.document_id,
                processed=c.processed,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in corrections
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete("/corrections/{correction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_correction(
    correction_id: uuid.UUID,
    current_user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Delete a user correction."""
    result = await db.execute(
        select(UserCorrection).where(
            UserCorrection.id == correction_id,
            UserCorrection.owner_id == current_user.id,
        )
    )
    correction = result.scalar_one_or_none()

    if correction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Correction not found",
        )

    await db.delete(correction)
    await db.commit()


@router.delete("/patterns/{term}", status_code=status.HTTP_204_NO_CONTENT)
async def invalidate_pattern(
    term: str,
    current_user: ActiveUser,
) -> None:
    """Invalidate a cached pattern.

    Use this when a pattern is no longer valid or should be relearned.
    """
    term_cache = get_term_cache()
    await term_cache.invalidate_pattern(str(current_user.id), term)
