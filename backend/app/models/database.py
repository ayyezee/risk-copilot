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


class BatchStatus(StrEnum):
    """Status of a batch processing job."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"  # Some documents failed
    CANCELLED = "cancelled"


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
    processed_documents: Mapped[list["ProcessedDocument"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
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


class ProcessedDocument(Base, TimestampMixin):
    """Processed/generated document output.

    Stores the output of document processing pipelines, including
    DOCX files with applied replacements and changes reports.
    """

    __tablename__ = "processed_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    # File metadata
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)

    # Processing metadata
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "processed", "changes_report"
    source_format: Mapped[str] = mapped_column(String(50), nullable=False)  # "docx", "pdf"
    total_replacements: Mapped[int] = mapped_column(Integer, default=0)

    # Details stored as JSON
    replacement_details: Mapped[dict | None] = mapped_column(JSON)  # List of ReplacementMatchDetail
    warnings: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    processing_summary: Mapped[str | None] = mapped_column(Text)

    # Relationships
    owner: Mapped["User"] = relationship(back_populates="processed_documents")
    source_document: Mapped["Document"] = relationship()

    __table_args__ = (
        Index("ix_processed_documents_owner_id", "owner_id"),
        Index("ix_processed_documents_source_document_id", "source_document_id"),
    )


class ProcessingLog(Base, TimestampMixin):
    """Log of document processing operations for analytics and learning.

    Tracks metrics, replacements made, and serves as the foundation
    for the learning system that improves over time.
    """

    __tablename__ = "processing_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    processed_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processed_documents.id", ondelete="SET NULL"), nullable=True
    )

    # Processing metrics
    total_replacements: Mapped[int] = mapped_column(Integer, default=0)
    processing_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cache_hits: Mapped[int] = mapped_column(Integer, default=0)
    cache_misses: Mapped[int] = mapped_column(Integer, default=0)

    # Document info
    document_word_count: Mapped[int | None] = mapped_column(Integer)
    document_type: Mapped[str | None] = mapped_column(String(50))  # "docx", "pdf", etc.
    chunks_processed: Mapped[int] = mapped_column(Integer, default=1)

    # For learning - full details stored as JSON
    replacements_made: Mapped[dict | None] = mapped_column(JSON)  # List of replacement details
    warnings: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    reference_examples_used: Mapped[list[str] | None] = mapped_column(ARRAY(String))  # UUIDs

    # Status
    status: Mapped[str] = mapped_column(String(50), default="completed")  # completed, failed, partial
    error_message: Mapped[str | None] = mapped_column(Text)

    # Relationships
    owner: Mapped["User"] = relationship()
    document: Mapped["Document"] = relationship()
    processed_document: Mapped["ProcessedDocument"] = relationship()

    __table_args__ = (
        Index("ix_processing_logs_owner_id", "owner_id"),
        Index("ix_processing_logs_document_id", "document_id"),
        Index("ix_processing_logs_created_at", "created_at"),
    )


class UserCorrection(Base, TimestampMixin):
    """User corrections to AI-suggested replacements for learning.

    When users mark a replacement as incorrect or modify it,
    this feedback is stored to improve future suggestions.
    """

    __tablename__ = "user_corrections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    processing_log_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processing_logs.id", ondelete="SET NULL"), nullable=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    # The original AI suggestion
    original_term: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_replacement: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_confidence: Mapped[float] = mapped_column(nullable=False)

    # User's correction
    correction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Types: "rejected" (don't replace), "modified" (different replacement), "accepted" (confirmed correct)
    user_replacement: Mapped[str | None] = mapped_column(Text)  # For "modified" type
    user_reason: Mapped[str | None] = mapped_column(Text)  # Optional explanation

    # Context for learning
    context_before: Mapped[str | None] = mapped_column(Text)  # Text before the term
    context_after: Mapped[str | None] = mapped_column(Text)  # Text after the term

    # Whether this correction has been processed by the learning system
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    owner: Mapped["User"] = relationship()

    __table_args__ = (
        Index("ix_user_corrections_owner_id", "owner_id"),
        Index("ix_user_corrections_original_term", "original_term"),
        Index("ix_user_corrections_processed", "processed"),
    )


class BatchJob(Base, TimestampMixin):
    """Batch processing job for multiple documents.

    Tracks overall progress and status of a batch of documents
    being processed together.
    """

    __tablename__ = "batch_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Job status
    status: Mapped[str] = mapped_column(String(50), default=BatchStatus.PENDING, nullable=False)

    # Progress tracking
    total_documents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_documents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_documents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Processing configuration
    reference_example_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    protected_terms: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    min_confidence: Mapped[float] = mapped_column(default=0.7, nullable=False)
    highlight_changes: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    generate_changes_report: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Output
    output_zip_path: Mapped[str | None] = mapped_column(String(500))  # Path to ZIP file when complete

    # Error info
    error_message: Mapped[str | None] = mapped_column(Text)

    # Relationships
    owner: Mapped["User"] = relationship()
    documents: Mapped[list["BatchJobDocument"]] = relationship(
        back_populates="batch_job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_batch_jobs_owner_id", "owner_id"),
        Index("ix_batch_jobs_status", "status"),
        Index("ix_batch_jobs_created_at", "created_at"),
    )


class BatchJobDocument(Base, TimestampMixin):
    """Individual document within a batch job.

    Tracks the processing status and results for each document
    in a batch.
    """

    __tablename__ = "batch_job_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batch_jobs.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    processed_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processed_documents.id", ondelete="SET NULL"), nullable=True
    )

    # Document info
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)

    # Processing status
    status: Mapped[str] = mapped_column(String(50), default=DocumentStatus.PENDING, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    # Processing metrics
    processing_time_ms: Mapped[int | None] = mapped_column(Integer)
    total_replacements: Mapped[int] = mapped_column(Integer, default=0)

    # Order in batch (for consistent ordering)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    batch_job: Mapped["BatchJob"] = relationship(back_populates="documents")
    document: Mapped["Document"] = relationship()
    processed_document: Mapped["ProcessedDocument"] = relationship()

    __table_args__ = (
        Index("ix_batch_job_documents_batch_job_id", "batch_job_id"),
        Index("ix_batch_job_documents_status", "status"),
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


def get_async_session():
    """Get an async session context manager for use outside of FastAPI dependency injection.

    Usage:
        async with get_async_session() as session:
            # use session
            await session.commit()
    """
    return get_async_session_factory()()
