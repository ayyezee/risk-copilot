"""SQLAlchemy database models."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

try:
    from pgvector.sqlalchemy import Vector
    PGVECTOR_AVAILABLE = True
except ImportError:
    PGVECTOR_AVAILABLE = False
    Vector = None  # type: ignore

from app.config import get_settings

if TYPE_CHECKING:
    pass

settings = get_settings()


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all database models."""

    pass


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DocumentStatus(StrEnum):
    """Status of document processing."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentType(StrEnum):
    """Type of document."""

    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MARKDOWN = "markdown"


class User(Base, TimestampMixin):
    """User account model."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 2FA fields
    totp_secret: Mapped[str | None] = mapped_column(String(255))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    backup_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String))

    # Relationships
    documents: Mapped[list["Document"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    reference_items: Mapped[list["ReferenceItem"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    reference_examples: Mapped[list["ReferenceExample"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base, TimestampMixin):
    """Refresh token for JWT authentication."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class Document(Base, TimestampMixin):
    """Document model for uploaded files."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # File metadata
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)

    # Processing
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    # Content
    extracted_text: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    doc_metadata: Mapped[dict | None] = mapped_column(JSON)
    page_count: Mapped[int | None] = mapped_column(Integer)

    # Vector store
    vector_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String))

    # Relationships
    owner: Mapped["User"] = relationship(back_populates="documents")

    __table_args__ = (
        Index("ix_documents_owner_status", "owner_id", "status"),
        Index("ix_documents_created_at", "created_at"),
    )


class ReferenceItem(Base, TimestampMixin):
    """Reference library item for storing reusable content."""

    __tablename__ = "reference_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    item_metadata: Mapped[dict | None] = mapped_column(JSON)

    # Vector store
    vector_id: Mapped[str | None] = mapped_column(String(255))

    # Relationships
    owner: Mapped["User"] = relationship(back_populates="reference_items")

    __table_args__ = (
        Index("ix_reference_items_owner_category", "owner_id", "category"),
        Index("ix_reference_items_tags", "tags", postgresql_using="gin"),
    )


class ReferenceExample(Base, TimestampMixin):
    """Reference example for document transformation with before/after pairs.

    Used for semantic search to find relevant examples for guiding document processing.
    Embeddings are stored in pgvector for efficient similarity search.
    """

    __tablename__ = "reference_examples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Identifiers
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # e.g., "Subadvisor X PPM - 2024"
    description: Mapped[str | None] = mapped_column(Text)

    # Document pair
    original_text: Mapped[str] = mapped_column(Text, nullable=False)  # Before text
    converted_text: Mapped[str] = mapped_column(Text, nullable=False)  # After text

    # Extracted mappings (JSON)
    term_mappings: Mapped[dict | None] = mapped_column(JSON)  # What changed and why

    # File metadata
    original_filename: Mapped[str | None] = mapped_column(String(255))
    converted_filename: Mapped[str | None] = mapped_column(String(255))
    original_file_type: Mapped[str | None] = mapped_column(String(50))
    converted_file_type: Mapped[str | None] = mapped_column(String(50))

    # Embedding vector for semantic search (1536 dimensions for OpenAI text-embedding-3-small)
    # Note: This column is nullable to allow creation without immediate embedding
    # The actual Vector type is added in migration if pgvector is available

    # Relationships
    owner: Mapped["User"] = relationship(back_populates="reference_examples")

    __table_args__ = (
        Index("ix_reference_examples_owner_id", "owner_id"),
        Index("ix_reference_examples_name", "name"),
    )


# Database engine and session factory (lazy initialization)
_engine = None
_async_session_factory = None


def get_engine():
    """Get or create the async database engine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            str(settings.database_url),
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            echo=settings.debug,
        )
    return _engine


def get_async_session_factory():
    """Get or create the async session factory."""
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _async_session_factory


async def get_db_session():
    """Get a database session for dependency injection."""
    async with get_async_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
