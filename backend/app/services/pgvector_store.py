"""pgvector-based vector store service for semantic search.

Uses PostgreSQL with pgvector extension for efficient similarity search
of reference examples. This is preferred over ChromaDB for production
use cases where data persistence and ACID compliance are important.
"""

import uuid
from typing import Any

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import StorageError
from app.models.database import ReferenceExample, get_async_session_factory
from app.services.ai_service import AIService, get_ai_service

settings = get_settings()

# Embedding dimension for OpenAI text-embedding-3-small
EMBEDDING_DIMENSION = 1536


class PgVectorStore:
    """Service for managing vector embeddings with pgvector in PostgreSQL."""

    def __init__(self, ai_service: AIService | None = None) -> None:
        self.ai_service = ai_service or get_ai_service()
        self._session_factory = None

    @property
    def session_factory(self):
        """Get async session factory lazily."""
        if self._session_factory is None:
            self._session_factory = get_async_session_factory()
        return self._session_factory

    async def ensure_extension(self, session: AsyncSession) -> None:
        """Ensure pgvector extension is installed."""
        try:
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await session.commit()
        except Exception as e:
            await session.rollback()
            raise StorageError(f"Failed to create pgvector extension: {e}") from e

    async def generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for a text using configured AI provider."""
        if not self.ai_service.is_configured():
            raise StorageError("AI service not configured for embeddings")
        return await self.ai_service.generate_embedding(text)

    async def add_reference_example(
        self,
        session: AsyncSession,
        example: ReferenceExample,
        embedding: list[float] | None = None,
        skip_embedding: bool = False,
    ) -> ReferenceExample:
        """Add a reference example with its embedding.

        Args:
            session: Database session
            example: ReferenceExample object (without embedding)
            embedding: Pre-computed embedding or None to generate
            skip_embedding: If True, skip embedding generation (useful when AI not configured)

        Returns:
            The created ReferenceExample with embedding (if generated)
        """
        try:
            # Add the example to the database first
            session.add(example)
            await session.flush()

            # Generate embedding if not provided and not skipped
            if not skip_embedding:
                if embedding is None:
                    try:
                        # Embed the original text for similarity search
                        embedding = await self.generate_embedding(example.original_text)
                    except (StorageError, Exception) as embed_error:
                        # AI service not configured or embedding failed, skip embedding
                        import structlog
                        logger = structlog.get_logger()
                        logger.warning(
                            "Skipping embedding generation",
                            example_id=str(example.id),
                            error=str(embed_error),
                        )
                        embedding = None

                # Update embedding using raw SQL if we have one
                if embedding is not None:
                    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
                    await session.execute(
                        text(
                            "UPDATE reference_examples SET embedding = :embedding::vector "
                            "WHERE id = :id"
                        ),
                        {"embedding": embedding_str, "id": str(example.id)},
                    )

            await session.refresh(example)
            return example

        except Exception as e:
            raise StorageError(f"Failed to add reference example: {e}") from e

    async def update_reference_embedding(
        self,
        session: AsyncSession,
        example_id: uuid.UUID,
        text_to_embed: str,
    ) -> None:
        """Update the embedding for an existing reference example.

        Args:
            session: Database session
            example_id: ID of the example to update
            text_to_embed: Text to generate embedding from
        """
        try:
            embedding = await self.generate_embedding(text_to_embed)
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

            await session.execute(
                text(
                    "UPDATE reference_examples SET embedding = :embedding::vector "
                    "WHERE id = :id"
                ),
                {"embedding": embedding_str, "id": str(example_id)},
            )

        except Exception as e:
            raise StorageError(f"Failed to update reference embedding: {e}") from e

    async def search_similar_examples(
        self,
        session: AsyncSession,
        query_text: str,
        owner_id: uuid.UUID | None = None,
        top_k: int = 3,
        similarity_threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Search for similar reference examples using cosine similarity.

        Args:
            session: Database session
            query_text: Text to search for
            owner_id: Optional user ID to filter by
            top_k: Number of results to return
            similarity_threshold: Minimum similarity score (0-1)

        Returns:
            List of dictionaries with example data and similarity scores
        """
        try:
            # Generate query embedding
            query_embedding = await self.generate_embedding(query_text)
            embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

            # Build query with cosine similarity
            # Note: pgvector uses <=> for cosine distance, so we need 1 - distance for similarity
            if owner_id:
                query = text("""
                    SELECT
                        id, name, description, original_text, converted_text,
                        term_mappings, original_filename, converted_filename,
                        created_at, owner_id,
                        1 - (embedding <=> :embedding::vector) as similarity
                    FROM reference_examples
                    WHERE owner_id = :owner_id
                      AND embedding IS NOT NULL
                      AND 1 - (embedding <=> :embedding::vector) >= :threshold
                    ORDER BY embedding <=> :embedding::vector
                    LIMIT :limit
                """)
                params = {
                    "embedding": embedding_str,
                    "owner_id": str(owner_id),
                    "threshold": similarity_threshold,
                    "limit": top_k,
                }
            else:
                query = text("""
                    SELECT
                        id, name, description, original_text, converted_text,
                        term_mappings, original_filename, converted_filename,
                        created_at, owner_id,
                        1 - (embedding <=> :embedding::vector) as similarity
                    FROM reference_examples
                    WHERE embedding IS NOT NULL
                      AND 1 - (embedding <=> :embedding::vector) >= :threshold
                    ORDER BY embedding <=> :embedding::vector
                    LIMIT :limit
                """)
                params = {
                    "embedding": embedding_str,
                    "threshold": similarity_threshold,
                    "limit": top_k,
                }

            result = await session.execute(query, params)
            rows = result.fetchall()

            return [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "description": row.description,
                    "original_text": row.original_text,
                    "converted_text": row.converted_text,
                    "term_mappings": row.term_mappings,
                    "original_filename": row.original_filename,
                    "converted_filename": row.converted_filename,
                    "created_at": row.created_at,
                    "owner_id": str(row.owner_id),
                    "similarity": float(row.similarity),
                }
                for row in rows
            ]

        except Exception as e:
            raise StorageError(f"Failed to search reference examples: {e}") from e

    async def get_relevant_examples(
        self,
        document_text: str,
        owner_id: uuid.UUID | None = None,
        top_k: int = 3,
    ) -> list[ReferenceExample]:
        """Find the most similar reference examples to guide document processing.

        This is the main retrieval function for the RAG system.

        Args:
            document_text: The document text to find examples for
            owner_id: Optional user ID to filter by
            top_k: Number of examples to retrieve

        Returns:
            List of ReferenceExample objects ordered by similarity
        """
        async with self.session_factory() as session:
            results = await self.search_similar_examples(
                session=session,
                query_text=document_text,
                owner_id=owner_id,
                top_k=top_k,
            )

            if not results:
                return []

            # Fetch full ReferenceExample objects
            example_ids = [uuid.UUID(r["id"]) for r in results]
            query = select(ReferenceExample).where(ReferenceExample.id.in_(example_ids))
            result = await session.execute(query)
            examples = {str(e.id): e for e in result.scalars().all()}

            # Return in similarity order
            return [examples[r["id"]] for r in results if r["id"] in examples]

    async def delete_reference_example(
        self,
        session: AsyncSession,
        example_id: uuid.UUID,
    ) -> bool:
        """Delete a reference example.

        Args:
            session: Database session
            example_id: ID of the example to delete

        Returns:
            True if deleted, False if not found
        """
        try:
            result = await session.execute(
                select(ReferenceExample).where(ReferenceExample.id == example_id)
            )
            example = result.scalar_one_or_none()

            if example is None:
                return False

            await session.delete(example)
            return True

        except Exception as e:
            raise StorageError(f"Failed to delete reference example: {e}") from e

    async def health_check(self) -> bool:
        """Check if pgvector is available and working."""
        try:
            async with self.session_factory() as session:
                result = await session.execute(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                )
                row = result.fetchone()
                return row is not None
        except Exception:
            return False


# Singleton instance
_pgvector_store_instance: PgVectorStore | None = None


def get_pgvector_store() -> PgVectorStore:
    """Get pgvector store singleton instance."""
    global _pgvector_store_instance
    if _pgvector_store_instance is None:
        _pgvector_store_instance = PgVectorStore()
    return _pgvector_store_instance
