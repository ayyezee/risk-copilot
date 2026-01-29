"""Term replacement cache using Redis for learning and reducing API calls.

This cache stores successful term replacements keyed by the term and surrounding
context, allowing the system to reuse high-confidence replacements without
making additional API calls.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import redis.asyncio as redis
import structlog

from app.config import get_settings

settings = get_settings()
logger = structlog.get_logger()


@dataclass
class CachedReplacement:
    """A cached term replacement."""
    original_term: str
    replacement_term: str
    confidence: float
    times_used: int
    category: str | None
    first_seen: datetime
    last_used: datetime
    context_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_term": self.original_term,
            "replacement_term": self.replacement_term,
            "confidence": self.confidence,
            "times_used": self.times_used,
            "category": self.category,
            "first_seen": self.first_seen.isoformat(),
            "last_used": self.last_used.isoformat(),
            "context_hash": self.context_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CachedReplacement":
        return cls(
            original_term=data["original_term"],
            replacement_term=data["replacement_term"],
            confidence=data["confidence"],
            times_used=data["times_used"],
            category=data.get("category"),
            first_seen=datetime.fromisoformat(data["first_seen"]),
            last_used=datetime.fromisoformat(data["last_used"]),
            context_hash=data["context_hash"],
        )


@dataclass
class TermPattern:
    """A frequently occurring term replacement pattern."""
    original_term: str
    replacement_term: str
    total_uses: int
    avg_confidence: float
    category: str | None
    is_high_confidence: bool  # Could become a rule


class TermCache:
    """Redis-backed cache for term replacements.

    Caching Strategy:
    - Key: hash of (owner_id, original_term, context_snippet)
    - Value: JSON with replacement info
    - TTL: 30 days (refreshed on use)

    The context_snippet is a normalized window of text around the term,
    helping distinguish different uses of the same word.
    """

    # Cache key prefixes
    PREFIX_REPLACEMENT = "term:replacement:"
    PREFIX_PATTERN = "term:pattern:"
    PREFIX_USER_STATS = "term:userstats:"

    # Context window size (characters on each side)
    CONTEXT_WINDOW = 50

    # Cache TTL in seconds (30 days)
    DEFAULT_TTL = 60 * 60 * 24 * 30

    # Minimum confidence to cache
    MIN_CACHE_CONFIDENCE = 0.7

    # Minimum uses to consider a pattern "high confidence"
    HIGH_CONFIDENCE_THRESHOLD = 10

    def __init__(self, redis_url: str | None = None) -> None:
        """Initialize the term cache.

        Args:
            redis_url: Redis connection URL. If not provided, uses settings.
        """
        self.redis_url = redis_url or settings.redis_url
        self._client: redis.Redis | None = None

    async def _get_client(self) -> redis.Redis:
        """Get or create Redis client."""
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._client

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None

    def _normalize_context(self, context: str) -> str:
        """Normalize context for consistent hashing.

        - Lowercase
        - Collapse whitespace
        - Truncate to window size
        """
        normalized = " ".join(context.lower().split())
        # Take middle portion if too long
        if len(normalized) > self.CONTEXT_WINDOW * 2:
            mid = len(normalized) // 2
            normalized = normalized[mid - self.CONTEXT_WINDOW:mid + self.CONTEXT_WINDOW]
        return normalized

    def _make_cache_key(self, owner_id: str, term: str, context: str) -> str:
        """Create a cache key for a term+context combination."""
        normalized_context = self._normalize_context(context)
        key_data = f"{owner_id}:{term.lower()}:{normalized_context}"
        context_hash = hashlib.sha256(key_data.encode()).hexdigest()[:16]
        return f"{self.PREFIX_REPLACEMENT}{context_hash}"

    def _make_pattern_key(self, owner_id: str, term: str) -> str:
        """Create a pattern key for tracking term frequency."""
        return f"{self.PREFIX_PATTERN}{owner_id}:{term.lower()}"

    def _make_user_stats_key(self, owner_id: str) -> str:
        """Create a key for user-level statistics."""
        return f"{self.PREFIX_USER_STATS}{owner_id}"

    async def get_cached_replacement(
        self,
        owner_id: str,
        term: str,
        context: str,
    ) -> CachedReplacement | None:
        """Get a cached replacement for a term in context.

        Args:
            owner_id: User ID for cache isolation
            term: The original term
            context: Surrounding text for context-aware matching

        Returns:
            CachedReplacement if found and valid, None otherwise
        """
        client = await self._get_client()
        cache_key = self._make_cache_key(owner_id, term, context)

        try:
            data = await client.get(cache_key)
            if data:
                cached = CachedReplacement.from_dict(json.loads(data))

                # Update usage stats
                cached.times_used += 1
                cached.last_used = datetime.utcnow()

                # Refresh TTL and update stats
                await client.setex(
                    cache_key,
                    self.DEFAULT_TTL,
                    json.dumps(cached.to_dict()),
                )

                logger.debug(
                    "Cache hit",
                    term=term,
                    replacement=cached.replacement_term,
                    times_used=cached.times_used,
                )
                return cached

        except Exception as e:
            logger.warning("Cache read error", error=str(e))

        return None

    async def cache_replacement(
        self,
        owner_id: str,
        term: str,
        context: str,
        replacement: str,
        confidence: float,
        category: str | None = None,
    ) -> bool:
        """Cache a successful term replacement.

        Args:
            owner_id: User ID for cache isolation
            term: The original term
            context: Surrounding text
            replacement: The replacement term
            confidence: Confidence score (0-1)
            category: Optional category

        Returns:
            True if cached successfully
        """
        # Only cache high-confidence replacements
        if confidence < self.MIN_CACHE_CONFIDENCE:
            return False

        client = await self._get_client()
        cache_key = self._make_cache_key(owner_id, term, context)
        context_hash = hashlib.sha256(
            f"{owner_id}:{term.lower()}:{self._normalize_context(context)}".encode()
        ).hexdigest()[:16]

        now = datetime.utcnow()

        cached = CachedReplacement(
            original_term=term,
            replacement_term=replacement,
            confidence=confidence,
            times_used=1,
            category=category,
            first_seen=now,
            last_used=now,
            context_hash=context_hash,
        )

        try:
            # Cache the replacement
            await client.setex(
                cache_key,
                self.DEFAULT_TTL,
                json.dumps(cached.to_dict()),
            )

            # Update pattern tracking
            await self._update_pattern_stats(
                client, owner_id, term, replacement, confidence, category
            )

            logger.debug(
                "Cached replacement",
                term=term,
                replacement=replacement,
                confidence=confidence,
            )
            return True

        except Exception as e:
            logger.warning("Cache write error", error=str(e))
            return False

    async def _update_pattern_stats(
        self,
        client: redis.Redis,
        owner_id: str,
        term: str,
        replacement: str,
        confidence: float,
        category: str | None,
    ) -> None:
        """Update pattern statistics for term frequency analysis."""
        pattern_key = self._make_pattern_key(owner_id, term)

        # Get existing pattern data
        existing = await client.get(pattern_key)
        if existing:
            pattern_data = json.loads(existing)
        else:
            pattern_data = {
                "original_term": term,
                "replacements": {},
                "total_uses": 0,
            }

        # Update replacement frequency
        rep_key = replacement.lower()
        if rep_key not in pattern_data["replacements"]:
            pattern_data["replacements"][rep_key] = {
                "replacement_term": replacement,
                "count": 0,
                "total_confidence": 0,
                "category": category,
            }

        pattern_data["replacements"][rep_key]["count"] += 1
        pattern_data["replacements"][rep_key]["total_confidence"] += confidence
        pattern_data["total_uses"] += 1

        # Store updated pattern
        await client.setex(
            pattern_key,
            self.DEFAULT_TTL,
            json.dumps(pattern_data),
        )

    async def get_term_patterns(
        self,
        owner_id: str,
        min_uses: int = 3,
        limit: int = 50,
    ) -> list[TermPattern]:
        """Get frequently occurring term patterns for a user.

        Args:
            owner_id: User ID
            min_uses: Minimum usage count to include
            limit: Maximum patterns to return

        Returns:
            List of TermPattern objects sorted by usage
        """
        client = await self._get_client()
        pattern_prefix = f"{self.PREFIX_PATTERN}{owner_id}:"

        patterns: list[TermPattern] = []

        try:
            # Scan for all pattern keys for this user
            async for key in client.scan_iter(match=f"{pattern_prefix}*", count=100):
                data = await client.get(key)
                if not data:
                    continue

                pattern_data = json.loads(data)
                if pattern_data["total_uses"] < min_uses:
                    continue

                # Find most common replacement for this term
                best_rep = None
                best_count = 0
                for rep_data in pattern_data["replacements"].values():
                    if rep_data["count"] > best_count:
                        best_count = rep_data["count"]
                        best_rep = rep_data

                if best_rep:
                    avg_confidence = best_rep["total_confidence"] / best_rep["count"]
                    patterns.append(TermPattern(
                        original_term=pattern_data["original_term"],
                        replacement_term=best_rep["replacement_term"],
                        total_uses=pattern_data["total_uses"],
                        avg_confidence=avg_confidence,
                        category=best_rep.get("category"),
                        is_high_confidence=(
                            pattern_data["total_uses"] >= self.HIGH_CONFIDENCE_THRESHOLD
                            and avg_confidence >= 0.85
                        ),
                    ))

            # Sort by total uses descending
            patterns.sort(key=lambda p: p.total_uses, reverse=True)
            return patterns[:limit]

        except Exception as e:
            logger.warning("Pattern read error", error=str(e))
            return []

    async def get_high_confidence_patterns(
        self,
        owner_id: str,
    ) -> list[TermPattern]:
        """Get patterns that could be promoted to rules.

        These are patterns with high usage and consistently high confidence.
        """
        patterns = await self.get_term_patterns(owner_id, min_uses=self.HIGH_CONFIDENCE_THRESHOLD)
        return [p for p in patterns if p.is_high_confidence]

    async def invalidate_pattern(
        self,
        owner_id: str,
        term: str,
    ) -> bool:
        """Invalidate a cached pattern (e.g., when user corrects it).

        Args:
            owner_id: User ID
            term: The term to invalidate

        Returns:
            True if invalidated
        """
        client = await self._get_client()
        pattern_key = self._make_pattern_key(owner_id, term)

        try:
            # Delete the pattern
            await client.delete(pattern_key)

            # Also delete any cached replacements for this term
            # We need to scan for them since they include context hash
            prefix = f"{self.PREFIX_REPLACEMENT}"
            deleted = 0
            async for key in client.scan_iter(match=f"{prefix}*", count=100):
                data = await client.get(key)
                if data:
                    cached = json.loads(data)
                    if cached.get("original_term", "").lower() == term.lower():
                        await client.delete(key)
                        deleted += 1

            logger.info(
                "Pattern invalidated",
                term=term,
                cached_entries_deleted=deleted,
            )
            return True

        except Exception as e:
            logger.warning("Pattern invalidation error", error=str(e))
            return False

    async def record_cache_stats(
        self,
        owner_id: str,
        hits: int,
        misses: int,
        api_calls_saved: int = 0,
    ) -> None:
        """Record cache performance statistics.

        Args:
            owner_id: User ID
            hits: Number of cache hits
            misses: Number of cache misses
            api_calls_saved: Estimated API calls saved
        """
        client = await self._get_client()
        stats_key = self._make_user_stats_key(owner_id)

        try:
            # Use Redis HINCRBY for atomic increments
            await client.hincrby(stats_key, "total_hits", hits)
            await client.hincrby(stats_key, "total_misses", misses)
            await client.hincrby(stats_key, "api_calls_saved", api_calls_saved)

            # Set expiry if new key
            await client.expire(stats_key, self.DEFAULT_TTL)

        except Exception as e:
            logger.warning("Stats recording error", error=str(e))

    async def get_cache_stats(self, owner_id: str) -> dict[str, Any]:
        """Get cache statistics for a user.

        Returns:
            Dict with hits, misses, hit_rate, api_calls_saved
        """
        client = await self._get_client()
        stats_key = self._make_user_stats_key(owner_id)

        try:
            stats = await client.hgetall(stats_key)
            hits = int(stats.get("total_hits", 0))
            misses = int(stats.get("total_misses", 0))
            total = hits + misses

            return {
                "total_hits": hits,
                "total_misses": misses,
                "hit_rate": hits / total if total > 0 else 0,
                "api_calls_saved": int(stats.get("api_calls_saved", 0)),
            }

        except Exception as e:
            logger.warning("Stats read error", error=str(e))
            return {
                "total_hits": 0,
                "total_misses": 0,
                "hit_rate": 0,
                "api_calls_saved": 0,
            }


# Singleton instance
_term_cache_instance: TermCache | None = None


def get_term_cache() -> TermCache:
    """Get term cache singleton instance."""
    global _term_cache_instance
    if _term_cache_instance is None:
        _term_cache_instance = TermCache()
    return _term_cache_instance
