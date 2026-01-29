"""Vector store service for semantic search using ChromaDB."""

import uuid
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.core.exceptions import StorageError

settings = get_settings()


class VectorStoreService:
    """Service for managing vector embeddings with ChromaDB."""

    def __init__(self) -> None:
        self.client = chromadb.PersistentClient(
            path=settings.chroma_persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._documents_collection = None
        self._references_collection = None

    @property
    def documents_collection(self):
        """Get or create documents collection."""
        if self._documents_collection is None:
            self._documents_collection = self.client.get_or_create_collection(
                name="documents",
                metadata={"hnsw:space": "cosine"},
            )
        return self._documents_collection

    @property
    def references_collection(self):
        """Get or create references collection."""
        if self._references_collection is None:
            self._references_collection = self.client.get_or_create_collection(
                name="references",
                metadata={"hnsw:space": "cosine"},
            )
        return self._references_collection

    async def add_document_chunks(
        self,
        document_id: str,
        chunks: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        """Add document chunks to the vector store."""
        try:
            ids = [f"{document_id}_{i}" for i in range(len(chunks))]
            chunk_metadatas = metadatas or [{}] * len(chunks)
            for metadata in chunk_metadatas:
                metadata["document_id"] = document_id

            self.documents_collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=chunks,
                metadatas=chunk_metadatas,
            )
            return ids
        except Exception as e:
            raise StorageError(f"Failed to add document chunks: {e}") from e

    async def search_documents(
        self,
        query_embedding: list[float],
        document_ids: list[str] | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search documents by query embedding."""
        try:
            where_filter = None
            if document_ids:
                where_filter = {"document_id": {"$in": document_ids}}

            results = self.documents_collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )

            search_results = []
            if results["ids"] and results["ids"][0]:
                for i, chunk_id in enumerate(results["ids"][0]):
                    search_results.append({
                        "id": chunk_id,
                        "document_id": results["metadatas"][0][i].get("document_id"),
                        "content": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "score": 1 - results["distances"][0][i],  # Convert distance to similarity
                    })
            return search_results
        except Exception as e:
            raise StorageError(f"Failed to search documents: {e}") from e

    async def delete_document_chunks(self, document_id: str) -> None:
        """Delete all chunks for a document."""
        try:
            self.documents_collection.delete(where={"document_id": document_id})
        except Exception as e:
            raise StorageError(f"Failed to delete document chunks: {e}") from e

    async def add_reference_item(
        self,
        item_id: str,
        content: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add a reference item to the vector store."""
        try:
            item_metadata = metadata or {}
            item_metadata["item_id"] = item_id

            self.references_collection.add(
                ids=[item_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[item_metadata],
            )
            return item_id
        except Exception as e:
            raise StorageError(f"Failed to add reference item: {e}") from e

    async def update_reference_item(
        self,
        item_id: str,
        content: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update a reference item in the vector store."""
        try:
            item_metadata = metadata or {}
            item_metadata["item_id"] = item_id

            self.references_collection.update(
                ids=[item_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[item_metadata],
            )
        except Exception as e:
            raise StorageError(f"Failed to update reference item: {e}") from e

    async def search_references(
        self,
        query_embedding: list[float],
        owner_id: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Search reference items by query embedding."""
        try:
            where_conditions = []
            if owner_id:
                where_conditions.append({"owner_id": owner_id})
            if category:
                where_conditions.append({"category": category})
            if tags:
                where_conditions.append({"tags": {"$contains": tags[0]}})  # ChromaDB limitation

            where_filter = None
            if len(where_conditions) == 1:
                where_filter = where_conditions[0]
            elif len(where_conditions) > 1:
                where_filter = {"$and": where_conditions}

            results = self.references_collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )

            search_results = []
            if results["ids"] and results["ids"][0]:
                for i, item_id in enumerate(results["ids"][0]):
                    search_results.append({
                        "id": item_id,
                        "content": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "score": 1 - results["distances"][0][i],
                    })
            return search_results
        except Exception as e:
            raise StorageError(f"Failed to search references: {e}") from e

    async def delete_reference_item(self, item_id: str) -> None:
        """Delete a reference item from the vector store."""
        try:
            self.references_collection.delete(ids=[item_id])
        except Exception as e:
            raise StorageError(f"Failed to delete reference item: {e}") from e

    async def health_check(self) -> bool:
        """Check if vector store is healthy."""
        try:
            self.client.heartbeat()
            return True
        except Exception:
            return False


_vector_store_instance: VectorStoreService | None = None


def get_vector_store_service() -> VectorStoreService:
    """Get vector store service singleton instance."""
    global _vector_store_instance
    if _vector_store_instance is None:
        _vector_store_instance = VectorStoreService()
    return _vector_store_instance
