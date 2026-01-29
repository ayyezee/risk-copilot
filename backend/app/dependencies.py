"""Dependency injection setup for FastAPI."""

from typing import Annotated, AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import async_session_factory
from app.services.ai_service import AIService, get_ai_service
from app.services.document_processor import DocumentProcessor, get_document_processor
from app.services.file_storage import FileStorageService, get_file_storage_service
from app.services.vector_store import VectorStoreService, get_vector_store_service


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for dependency injection."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Type aliases for cleaner dependency injection
DBSession = Annotated[AsyncSession, Depends(get_db)]
Storage = Annotated[FileStorageService, Depends(get_file_storage_service)]
VectorStore = Annotated[VectorStoreService, Depends(get_vector_store_service)]
AI = Annotated[AIService, Depends(get_ai_service)]
DocProcessor = Annotated[DocumentProcessor, Depends(get_document_processor)]
