"""Analytics service for processing metrics, patterns, and insights.

Provides aggregated statistics, term frequency analysis, and learning insights
to help users understand their document processing patterns.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import ProcessingLog, UserCorrection, Document, ProcessedDocument
from app.services.term_cache import TermCache, TermPattern, get_term_cache

logger = structlog.get_logger()


@dataclass
class ProcessingMetrics:
    """Aggregated processing metrics for a time period."""
    total_documents: int = 0
    total_replacements: int = 0
    total_processing_time_ms: int = 0
    total_tokens_used: int = 0
    total_cache_hits: int = 0
    total_cache_misses: int = 0
    avg_processing_time_ms: float = 0
    avg_replacements_per_doc: float = 0
    cache_hit_rate: float = 0
    estimated_cost_usd: float = 0  # Based on token usage


@dataclass
class DailyMetrics:
    """Metrics for a single day."""
    date: datetime
    documents_processed: int = 0
    total_replacements: int = 0
    tokens_used: int = 0
    avg_processing_time_ms: float = 0


@dataclass
class TopReplacement:
    """A frequently occurring replacement."""
    original_term: str
    replacement_term: str
    occurrence_count: int
    avg_confidence: float
    category: str | None = None


@dataclass
class AmbiguousTerm:
    """A term that often receives different replacements or low confidence."""
    term: str
    occurrence_count: int
    unique_replacements: int
    avg_confidence: float
    replacements: list[str] = field(default_factory=list)


@dataclass
class AnalyticsDashboard:
    """Complete analytics dashboard data."""
    # Time-based metrics
    daily_metrics: list[DailyMetrics]
    weekly_total: ProcessingMetrics
    monthly_total: ProcessingMetrics
    all_time_total: ProcessingMetrics

    # Pattern insights
    top_replacements: list[TopReplacement]
    high_confidence_patterns: list[TermPattern]
    ambiguous_terms: list[AmbiguousTerm]

    # Cache performance
    cache_stats: dict[str, Any]

    # Correction insights
    total_corrections: int
    correction_rate: float  # % of replacements that were corrected

    # Cost estimates (based on Claude API pricing)
    estimated_monthly_cost_usd: float


class AnalyticsService:
    """Service for computing and retrieving analytics."""

    # Approximate Claude API cost per 1M tokens (input + output averaged)
    COST_PER_MILLION_TOKENS = 3.0  # Simplified estimate

    def __init__(self) -> None:
        self.logger = structlog.get_logger()

    async def get_dashboard(
        self,
        db: AsyncSession,
        owner_id: uuid.UUID,
        days: int = 30,
    ) -> AnalyticsDashboard:
        """Get complete analytics dashboard for a user.

        Args:
            db: Database session
            owner_id: User ID
            days: Number of days for historical data

        Returns:
            AnalyticsDashboard with all metrics
        """
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)
        start_date = now - timedelta(days=days)

        # Get daily metrics
        daily_metrics = await self._get_daily_metrics(db, owner_id, start_date, now)

        # Get aggregated metrics for different periods
        weekly_total = await self._get_period_metrics(db, owner_id, week_ago, now)
        monthly_total = await self._get_period_metrics(db, owner_id, month_ago, now)
        all_time_total = await self._get_period_metrics(db, owner_id, None, now)

        # Get top replacements from database
        top_replacements = await self._get_top_replacements(db, owner_id, limit=20)

        # Get patterns from cache
        term_cache = get_term_cache()
        high_confidence_patterns = await term_cache.get_high_confidence_patterns(str(owner_id))

        # Get ambiguous terms
        ambiguous_terms = await self._get_ambiguous_terms(db, owner_id, limit=10)

        # Get cache stats
        cache_stats = await term_cache.get_cache_stats(str(owner_id))

        # Get correction insights
        correction_stats = await self._get_correction_stats(db, owner_id)

        # Estimate monthly cost
        estimated_monthly_cost = (monthly_total.total_tokens_used / 1_000_000) * self.COST_PER_MILLION_TOKENS

        return AnalyticsDashboard(
            daily_metrics=daily_metrics,
            weekly_total=weekly_total,
            monthly_total=monthly_total,
            all_time_total=all_time_total,
            top_replacements=top_replacements,
            high_confidence_patterns=high_confidence_patterns,
            ambiguous_terms=ambiguous_terms,
            cache_stats=cache_stats,
            total_corrections=correction_stats["total_corrections"],
            correction_rate=correction_stats["correction_rate"],
            estimated_monthly_cost_usd=estimated_monthly_cost,
        )

    async def _get_daily_metrics(
        self,
        db: AsyncSession,
        owner_id: uuid.UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> list[DailyMetrics]:
        """Get daily processing metrics."""
        result = await db.execute(
            select(
                func.date_trunc('day', ProcessingLog.created_at).label('date'),
                func.count(ProcessingLog.id).label('count'),
                func.sum(ProcessingLog.total_replacements).label('replacements'),
                func.sum(ProcessingLog.tokens_used).label('tokens'),
                func.avg(ProcessingLog.processing_time_ms).label('avg_time'),
            )
            .where(
                and_(
                    ProcessingLog.owner_id == owner_id,
                    ProcessingLog.created_at >= start_date,
                    ProcessingLog.created_at <= end_date,
                    ProcessingLog.status == "completed",
                )
            )
            .group_by(func.date_trunc('day', ProcessingLog.created_at))
            .order_by(func.date_trunc('day', ProcessingLog.created_at))
        )

        rows = result.all()
        return [
            DailyMetrics(
                date=row.date,
                documents_processed=row.count or 0,
                total_replacements=row.replacements or 0,
                tokens_used=row.tokens or 0,
                avg_processing_time_ms=float(row.avg_time or 0),
            )
            for row in rows
        ]

    async def _get_period_metrics(
        self,
        db: AsyncSession,
        owner_id: uuid.UUID,
        start_date: datetime | None,
        end_date: datetime,
    ) -> ProcessingMetrics:
        """Get aggregated metrics for a time period."""
        conditions = [
            ProcessingLog.owner_id == owner_id,
            ProcessingLog.created_at <= end_date,
            ProcessingLog.status == "completed",
        ]
        if start_date:
            conditions.append(ProcessingLog.created_at >= start_date)

        result = await db.execute(
            select(
                func.count(ProcessingLog.id).label('count'),
                func.sum(ProcessingLog.total_replacements).label('replacements'),
                func.sum(ProcessingLog.processing_time_ms).label('total_time'),
                func.sum(ProcessingLog.tokens_used).label('tokens'),
                func.sum(ProcessingLog.cache_hits).label('hits'),
                func.sum(ProcessingLog.cache_misses).label('misses'),
                func.avg(ProcessingLog.processing_time_ms).label('avg_time'),
            )
            .where(and_(*conditions))
        )

        row = result.one()
        total_docs = row.count or 0
        total_replacements = row.replacements or 0
        total_hits = row.hits or 0
        total_misses = row.misses or 0
        total_cache_requests = total_hits + total_misses

        return ProcessingMetrics(
            total_documents=total_docs,
            total_replacements=total_replacements,
            total_processing_time_ms=row.total_time or 0,
            total_tokens_used=row.tokens or 0,
            total_cache_hits=total_hits,
            total_cache_misses=total_misses,
            avg_processing_time_ms=float(row.avg_time or 0),
            avg_replacements_per_doc=total_replacements / total_docs if total_docs > 0 else 0,
            cache_hit_rate=total_hits / total_cache_requests if total_cache_requests > 0 else 0,
            estimated_cost_usd=((row.tokens or 0) / 1_000_000) * self.COST_PER_MILLION_TOKENS,
        )

    async def _get_top_replacements(
        self,
        db: AsyncSession,
        owner_id: uuid.UUID,
        limit: int = 20,
    ) -> list[TopReplacement]:
        """Get most frequently occurring replacements from processing logs."""
        # Query processing logs and extract replacement patterns
        result = await db.execute(
            select(ProcessingLog.replacements_made)
            .where(
                and_(
                    ProcessingLog.owner_id == owner_id,
                    ProcessingLog.status == "completed",
                    ProcessingLog.replacements_made.isnot(None),
                )
            )
            .order_by(desc(ProcessingLog.created_at))
            .limit(100)  # Look at recent logs
        )

        # Aggregate replacements
        replacement_counts: dict[tuple[str, str], dict] = {}

        for row in result.all():
            replacements = row.replacements_made
            if not replacements or "replacements" not in replacements:
                continue

            for rep in replacements.get("replacements", []):
                key = (rep.get("original_term", "").lower(), rep.get("replacement_term", "").lower())
                if key[0] and key[1]:
                    if key not in replacement_counts:
                        replacement_counts[key] = {
                            "original_term": rep.get("original_term", ""),
                            "replacement_term": rep.get("replacement_term", ""),
                            "count": 0,
                            "total_confidence": 0,
                            "category": rep.get("category"),
                        }
                    replacement_counts[key]["count"] += 1
                    replacement_counts[key]["total_confidence"] += rep.get("confidence", 0.5)

        # Sort by count and return top N
        sorted_replacements = sorted(
            replacement_counts.values(),
            key=lambda x: x["count"],
            reverse=True,
        )[:limit]

        return [
            TopReplacement(
                original_term=r["original_term"],
                replacement_term=r["replacement_term"],
                occurrence_count=r["count"],
                avg_confidence=r["total_confidence"] / r["count"] if r["count"] > 0 else 0,
                category=r["category"],
            )
            for r in sorted_replacements
        ]

    async def _get_ambiguous_terms(
        self,
        db: AsyncSession,
        owner_id: uuid.UUID,
        limit: int = 10,
    ) -> list[AmbiguousTerm]:
        """Find terms that have multiple different replacements or low confidence."""
        # Query processing logs
        result = await db.execute(
            select(ProcessingLog.replacements_made)
            .where(
                and_(
                    ProcessingLog.owner_id == owner_id,
                    ProcessingLog.status == "completed",
                    ProcessingLog.replacements_made.isnot(None),
                )
            )
            .order_by(desc(ProcessingLog.created_at))
            .limit(100)
        )

        # Track terms and their replacements
        term_data: dict[str, dict] = {}

        for row in result.all():
            replacements = row.replacements_made
            if not replacements or "replacements" not in replacements:
                continue

            for rep in replacements.get("replacements", []):
                term = rep.get("original_term", "").lower()
                replacement = rep.get("replacement_term", "")
                confidence = rep.get("confidence", 0.5)

                if term:
                    if term not in term_data:
                        term_data[term] = {
                            "term": rep.get("original_term", ""),
                            "replacements": set(),
                            "count": 0,
                            "total_confidence": 0,
                        }
                    term_data[term]["replacements"].add(replacement)
                    term_data[term]["count"] += 1
                    term_data[term]["total_confidence"] += confidence

        # Find ambiguous terms (multiple replacements or low average confidence)
        ambiguous = []
        for data in term_data.values():
            unique_replacements = len(data["replacements"])
            avg_confidence = data["total_confidence"] / data["count"] if data["count"] > 0 else 0

            # Consider ambiguous if: multiple replacements OR low confidence
            if unique_replacements > 1 or avg_confidence < 0.7:
                ambiguous.append(AmbiguousTerm(
                    term=data["term"],
                    occurrence_count=data["count"],
                    unique_replacements=unique_replacements,
                    avg_confidence=avg_confidence,
                    replacements=list(data["replacements"])[:5],  # Top 5
                ))

        # Sort by occurrence count (most common ambiguous terms first)
        ambiguous.sort(key=lambda x: x.occurrence_count, reverse=True)
        return ambiguous[:limit]

    async def _get_correction_stats(
        self,
        db: AsyncSession,
        owner_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Get statistics about user corrections."""
        # Total corrections
        result = await db.execute(
            select(func.count(UserCorrection.id))
            .where(UserCorrection.owner_id == owner_id)
        )
        total_corrections = result.scalar() or 0

        # Total replacements made
        result = await db.execute(
            select(func.sum(ProcessingLog.total_replacements))
            .where(
                and_(
                    ProcessingLog.owner_id == owner_id,
                    ProcessingLog.status == "completed",
                )
            )
        )
        total_replacements = result.scalar() or 0

        correction_rate = total_corrections / total_replacements if total_replacements > 0 else 0

        return {
            "total_corrections": total_corrections,
            "correction_rate": correction_rate,
        }

    async def log_processing(
        self,
        db: AsyncSession,
        owner_id: uuid.UUID,
        document_id: uuid.UUID | None,
        processed_document_id: uuid.UUID | None,
        total_replacements: int,
        processing_time_ms: int,
        tokens_used: int,
        cache_hits: int,
        cache_misses: int,
        document_word_count: int | None,
        document_type: str | None,
        chunks_processed: int,
        replacements_made: list[dict] | None,
        warnings: list[str] | None,
        reference_examples_used: list[str] | None,
        status: str = "completed",
        error_message: str | None = None,
    ) -> ProcessingLog:
        """Log a processing operation for analytics.

        Args:
            All processing details

        Returns:
            Created ProcessingLog record
        """
        log = ProcessingLog(
            owner_id=owner_id,
            document_id=document_id,
            processed_document_id=processed_document_id,
            total_replacements=total_replacements,
            processing_time_ms=processing_time_ms,
            tokens_used=tokens_used,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            document_word_count=document_word_count,
            document_type=document_type,
            chunks_processed=chunks_processed,
            replacements_made={"replacements": replacements_made} if replacements_made else None,
            warnings=warnings,
            reference_examples_used=reference_examples_used,
            status=status,
            error_message=error_message,
        )
        db.add(log)
        await db.flush()

        self.logger.info(
            "Processing logged",
            log_id=str(log.id),
            owner_id=str(owner_id),
            total_replacements=total_replacements,
            processing_time_ms=processing_time_ms,
        )

        return log

    async def record_correction(
        self,
        db: AsyncSession,
        owner_id: uuid.UUID,
        original_term: str,
        suggested_replacement: str,
        suggested_confidence: float,
        correction_type: str,
        user_replacement: str | None = None,
        user_reason: str | None = None,
        context_before: str | None = None,
        context_after: str | None = None,
        processing_log_id: uuid.UUID | None = None,
        document_id: uuid.UUID | None = None,
    ) -> UserCorrection:
        """Record a user correction for learning.

        Args:
            All correction details

        Returns:
            Created UserCorrection record
        """
        correction = UserCorrection(
            owner_id=owner_id,
            processing_log_id=processing_log_id,
            document_id=document_id,
            original_term=original_term,
            suggested_replacement=suggested_replacement,
            suggested_confidence=suggested_confidence,
            correction_type=correction_type,
            user_replacement=user_replacement,
            user_reason=user_reason,
            context_before=context_before,
            context_after=context_after,
            processed=False,
        )
        db.add(correction)
        await db.flush()

        # If this is a rejection or modification, invalidate the cache pattern
        if correction_type in ("rejected", "modified"):
            term_cache = get_term_cache()
            await term_cache.invalidate_pattern(str(owner_id), original_term)

        self.logger.info(
            "Correction recorded",
            correction_id=str(correction.id),
            original_term=original_term,
            correction_type=correction_type,
        )

        return correction

    async def get_correction_history(
        self,
        db: AsyncSession,
        owner_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[UserCorrection], int]:
        """Get correction history for a user.

        Returns:
            Tuple of (corrections list, total count)
        """
        # Get total count
        count_result = await db.execute(
            select(func.count(UserCorrection.id))
            .where(UserCorrection.owner_id == owner_id)
        )
        total = count_result.scalar() or 0

        # Get corrections
        result = await db.execute(
            select(UserCorrection)
            .where(UserCorrection.owner_id == owner_id)
            .order_by(desc(UserCorrection.created_at))
            .limit(limit)
            .offset(offset)
        )
        corrections = list(result.scalars().all())

        return corrections, total


# Singleton instance
_analytics_service_instance: AnalyticsService | None = None


def get_analytics_service() -> AnalyticsService:
    """Get analytics service singleton instance."""
    global _analytics_service_instance
    if _analytics_service_instance is None:
        _analytics_service_instance = AnalyticsService()
    return _analytics_service_instance
