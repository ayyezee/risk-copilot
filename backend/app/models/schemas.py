"""Pydantic schemas for request/response validation."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# Base schemas
class BaseSchema(BaseModel):
    """Base schema with common configuration."""

    model_config = ConfigDict(from_attributes=True)


class TimestampSchema(BaseSchema):
    """Schema with timestamp fields."""

    created_at: datetime
    updated_at: datetime


# Auth schemas
class UserCreate(BaseModel):
    """Schema for user registration."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(None, max_length=255)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserLogin(BaseModel):
    """Schema for user login."""

    email: EmailStr
    password: str
    totp_code: str | None = None


class UserResponse(TimestampSchema):
    """Schema for user response."""

    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    is_verified: bool
    totp_enabled: bool


class TokenResponse(BaseModel):
    """Schema for token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    """Schema for token refresh request."""

    refresh_token: str


class PasswordChange(BaseModel):
    """Schema for password change."""

    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


# 2FA schemas
class TwoFactorSetupResponse(BaseModel):
    """Schema for 2FA setup response."""

    secret: str
    qr_code_base64: str
    backup_codes: list[str]


class TwoFactorVerify(BaseModel):
    """Schema for 2FA verification."""

    code: str = Field(min_length=6, max_length=6)


class TwoFactorBackupCode(BaseModel):
    """Schema for using a backup code."""

    backup_code: str


# Document schemas
class DocumentUploadResponse(BaseSchema):
    """Schema for document upload response."""

    id: uuid.UUID
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    status: str


class DocumentResponse(TimestampSchema):
    """Schema for document response."""

    id: uuid.UUID
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    mime_type: str
    status: str
    error_message: str | None
    summary: str | None
    page_count: int | None
    metadata: dict[str, Any] | None = Field(None, validation_alias="doc_metadata")


class DocumentListResponse(BaseModel):
    """Schema for paginated document list."""

    items: list[DocumentResponse]
    total: int
    page: int
    page_size: int
    pages: int


class DocumentProcessRequest(BaseModel):
    """Schema for document processing request."""

    generate_summary: bool = True
    extract_metadata: bool = True
    index_for_search: bool = True


class DocumentQueryRequest(BaseModel):
    """Schema for semantic document query."""

    query: str = Field(min_length=1, max_length=1000)
    document_ids: list[uuid.UUID] | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class DocumentQueryResult(BaseModel):
    """Schema for document query result."""

    document_id: uuid.UUID
    filename: str
    content: str
    score: float
    metadata: dict[str, Any] | None


class DocumentQueryResponse(BaseModel):
    """Schema for document query response."""

    query: str
    results: list[DocumentQueryResult]
    answer: str | None = None


class DocumentSectionResponse(BaseModel):
    """Schema for a parsed document section."""

    element_type: str
    content: str
    page_number: int | None = None
    metadata: dict[str, Any] = {}


class DocumentParseResponse(BaseModel):
    """Schema for document parsing response."""

    id: uuid.UUID
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    status: str
    title: str | None = None
    full_text: str
    sections: list[DocumentSectionResponse]
    page_count: int | None = None
    word_count: int = 0
    headers: list[str] = []
    tables: list[dict[str, Any]] = []
    footnotes: list[str] = []
    metadata: dict[str, Any] = {}
    warnings: list[str] = []


# Reference Library schemas
class ReferenceItemCreate(BaseModel):
    """Schema for creating a reference item."""

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    category: str | None = Field(None, max_length=100)
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class ReferenceItemUpdate(BaseModel):
    """Schema for updating a reference item."""

    title: str | None = Field(None, min_length=1, max_length=255)
    content: str | None = Field(None, min_length=1)
    category: str | None = Field(None, max_length=100)
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class ReferenceItemResponse(TimestampSchema):
    """Schema for reference item response."""

    id: uuid.UUID
    title: str
    content: str
    category: str | None
    tags: list[str] | None
    metadata: dict[str, Any] | None = Field(None, validation_alias="item_metadata")


class ReferenceItemListResponse(BaseModel):
    """Schema for paginated reference item list."""

    items: list[ReferenceItemResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ReferenceSearchRequest(BaseModel):
    """Schema for semantic reference search."""

    query: str = Field(min_length=1, max_length=500)
    category: str | None = None
    tags: list[str] | None = None
    top_k: int = Field(default=10, ge=1, le=50)


class ReferenceSearchResult(BaseModel):
    """Schema for reference search result."""

    item: ReferenceItemResponse
    score: float


class ReferenceSearchResponse(BaseModel):
    """Schema for reference search response."""

    query: str
    results: list[ReferenceSearchResult]


# Reference Example schemas (for pgvector-based semantic search)
class ReferenceExampleCreate(BaseModel):
    """Schema for creating a reference example with before/after document pair."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    original_text: str = Field(min_length=1)
    converted_text: str = Field(min_length=1)
    original_filename: str | None = Field(None, max_length=255)
    converted_filename: str | None = Field(None, max_length=255)


class ReferenceExampleResponse(TimestampSchema):
    """Schema for reference example response."""

    id: uuid.UUID
    name: str
    description: str | None
    original_text: str
    converted_text: str
    term_mappings: dict[str, Any] | None
    original_filename: str | None
    converted_filename: str | None
    original_file_type: str | None
    converted_file_type: str | None


class ReferenceExampleListResponse(BaseModel):
    """Schema for paginated reference example list."""

    items: list[ReferenceExampleResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ReferenceExampleSearchRequest(BaseModel):
    """Schema for semantic search of reference examples."""

    query: str = Field(min_length=1, max_length=10000)
    top_k: int = Field(default=3, ge=1, le=20)
    similarity_threshold: float = Field(default=0.0, ge=0.0, le=1.0)


class ReferenceExampleSearchResult(BaseModel):
    """Schema for a single search result with similarity score."""

    example: ReferenceExampleResponse
    similarity: float


class ReferenceExampleSearchResponse(BaseModel):
    """Schema for reference example search response."""

    query: str
    results: list[ReferenceExampleSearchResult]


class TermMapping(BaseModel):
    """Schema for a single term mapping."""

    original_term: str
    converted_term: str
    context: str | None = None
    category: str | None = None  # e.g., "legal", "financial", "technical"


class TermMappingsResponse(BaseModel):
    """Schema for term mappings extracted from a reference example."""

    example_id: uuid.UUID
    mappings: list[TermMapping]
    summary: str | None = None


# Document AI Processing schemas
class TermReplacementItem(BaseModel):
    """Schema for a single term replacement identified by AI."""

    original_term: str
    replacement_term: str
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
    category: str | None = None


class DocumentAnalysisRequest(BaseModel):
    """Schema for document analysis request."""

    document_id: uuid.UUID | None = None  # Use existing document
    document_text: str | None = None  # Or provide text directly
    reference_example_ids: list[uuid.UUID] | None = None  # Specific examples to use
    top_k_examples: int = Field(default=3, ge=1, le=10)  # Or find top-k similar
    protected_terms: list[str] = Field(default_factory=list)
    min_confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class DocumentAnalysisResponse(BaseModel):
    """Schema for document analysis response."""

    replacements: list[TermReplacementItem]
    warnings: list[str]
    summary: str | None = None
    chunks_processed: int
    total_chunks: int
    document_id: uuid.UUID | None = None


class ApplyReplacementsRequest(BaseModel):
    """Schema for applying replacements to a document."""

    document_id: uuid.UUID | None = None
    document_text: str | None = None
    replacements: list[TermReplacementItem]
    min_confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class ApplyReplacementsResponse(BaseModel):
    """Schema for the result of applying replacements."""

    original_text: str
    modified_text: str
    changes_applied: list[dict[str, Any]]
    total_replacements: int


# Section Detection schemas
class DetectedSection(BaseModel):
    """Schema for a detected document section."""

    id: str  # Generated UUID for selection tracking
    title: str
    description: str | None = None
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)
    section_type: str | None = None  # e.g., "definitions", "risk_disclosures", "terms"
    confidence: float = Field(ge=0.0, le=1.0)


class SectionDetectionResponse(BaseModel):
    """Schema for section detection response."""

    document_id: uuid.UUID
    sections: list[DetectedSection]
    page_count: int | None = None
    warnings: list[str] = Field(default_factory=list)


class PageRange(BaseModel):
    """Schema for a page range selection."""

    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)
    label: str | None = None  # Optional user-provided label


# Document Processing Pipeline schemas
class ProcessDocumentRequest(BaseModel):
    """Schema for triggering the full document processing pipeline."""

    reference_example_ids: list[uuid.UUID] | None = None  # Specific examples to use
    top_k_examples: int = Field(default=3, ge=1, le=10)  # Or find top-k similar
    protected_terms: list[str] = Field(default_factory=list)
    min_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    highlight_changes: bool = True
    generate_changes_report: bool = True
    # Section selection options
    selected_page_ranges: list[PageRange] | None = None  # Process only these page ranges
    use_full_document_for_context: bool = True  # Use full doc for definition lookups


class ProcessingJobStatus(BaseModel):
    """Schema for processing job status."""

    job_id: uuid.UUID
    document_id: uuid.UUID
    status: str  # "pending", "analyzing", "generating", "completed", "failed"
    progress: int = Field(ge=0, le=100)  # Percentage complete
    message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class ProcessDocumentResponse(BaseModel):
    """Schema for document processing response (when processing completes)."""

    document_id: uuid.UUID
    status: str
    total_replacements: int
    replacements: list[TermReplacementItem]
    warnings: list[str]
    summary: str | None = None
    output_file_id: uuid.UUID | None = None  # ID of the generated DOCX
    changes_report_id: uuid.UUID | None = None  # ID of the changes report


class ReplacementMatchDetail(BaseModel):
    """Schema for detailed replacement match information."""

    original_term: str
    replacement_term: str
    paragraph_index: int
    location_description: str
    reasoning: str
    confidence: float


class GeneratedDocumentResponse(BaseModel):
    """Schema for generated document information."""

    id: uuid.UUID
    filename: str
    content_type: str
    file_size: int
    total_replacements_applied: int
    source_format: str  # "docx" or "pdf"
    replacement_details: list[ReplacementMatchDetail]
    warnings: list[str]
    created_at: datetime


# Analytics schemas
class ProcessingMetricsResponse(BaseModel):
    """Aggregated processing metrics."""

    total_documents: int
    total_replacements: int
    total_processing_time_ms: int
    total_tokens_used: int
    total_cache_hits: int
    total_cache_misses: int
    avg_processing_time_ms: float
    avg_replacements_per_doc: float
    cache_hit_rate: float
    estimated_cost_usd: float


class DailyMetricsResponse(BaseModel):
    """Metrics for a single day."""

    date: datetime
    documents_processed: int
    total_replacements: int
    tokens_used: int
    avg_processing_time_ms: float


class TopReplacementResponse(BaseModel):
    """A frequently occurring replacement."""

    original_term: str
    replacement_term: str
    occurrence_count: int
    avg_confidence: float
    category: str | None = None


class TermPatternResponse(BaseModel):
    """A term replacement pattern from cache."""

    original_term: str
    replacement_term: str
    total_uses: int
    avg_confidence: float
    category: str | None = None
    is_high_confidence: bool


class AmbiguousTermResponse(BaseModel):
    """A term with multiple/inconsistent replacements."""

    term: str
    occurrence_count: int
    unique_replacements: int
    avg_confidence: float
    replacements: list[str]


class CacheStatsResponse(BaseModel):
    """Cache performance statistics."""

    total_hits: int
    total_misses: int
    hit_rate: float
    api_calls_saved: int


class AnalyticsDashboardResponse(BaseModel):
    """Complete analytics dashboard."""

    daily_metrics: list[DailyMetricsResponse]
    weekly_total: ProcessingMetricsResponse
    monthly_total: ProcessingMetricsResponse
    all_time_total: ProcessingMetricsResponse
    top_replacements: list[TopReplacementResponse]
    high_confidence_patterns: list[TermPatternResponse]
    ambiguous_terms: list[AmbiguousTermResponse]
    cache_stats: CacheStatsResponse
    total_corrections: int
    correction_rate: float
    estimated_monthly_cost_usd: float


# User Correction schemas
class CorrectionCreate(BaseModel):
    """Schema for creating a user correction."""

    original_term: str
    suggested_replacement: str
    suggested_confidence: float = Field(ge=0.0, le=1.0)
    correction_type: str = Field(pattern="^(rejected|modified|accepted)$")
    user_replacement: str | None = None
    user_reason: str | None = None
    context_before: str | None = None
    context_after: str | None = None
    processing_log_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None


class CorrectionResponse(TimestampSchema):
    """Schema for a user correction."""

    id: uuid.UUID
    original_term: str
    suggested_replacement: str
    suggested_confidence: float
    correction_type: str
    user_replacement: str | None
    user_reason: str | None
    context_before: str | None
    context_after: str | None
    processing_log_id: uuid.UUID | None
    document_id: uuid.UUID | None
    processed: bool


class CorrectionListResponse(BaseModel):
    """Schema for paginated correction list."""

    items: list[CorrectionResponse]
    total: int
    page: int
    page_size: int


# Processing Log schemas
class ProcessingLogResponse(TimestampSchema):
    """Schema for a processing log entry."""

    id: uuid.UUID
    document_id: uuid.UUID | None
    total_replacements: int
    processing_time_ms: int
    tokens_used: int
    cache_hits: int
    cache_misses: int
    document_word_count: int | None
    document_type: str | None
    chunks_processed: int
    status: str
    error_message: str | None


class ProcessingLogListResponse(BaseModel):
    """Schema for paginated processing log list."""

    items: list[ProcessingLogResponse]
    total: int
    page: int
    page_size: int


# Batch Processing schemas
class BatchCreateRequest(BaseModel):
    """Schema for creating a batch processing job."""

    reference_example_ids: list[uuid.UUID] | None = None
    protected_terms: list[str] = Field(default_factory=list)
    min_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    highlight_changes: bool = True
    generate_changes_report: bool = True


class BatchDocumentStatus(BaseModel):
    """Schema for a single document's status in a batch."""

    id: uuid.UUID
    original_filename: str
    file_type: str
    file_size: int
    status: str
    error_message: str | None = None
    processing_time_ms: int | None = None
    total_replacements: int = 0
    sequence_number: int


class BatchJobResponse(TimestampSchema):
    """Schema for batch job response."""

    id: uuid.UUID
    status: str
    total_documents: int
    processed_documents: int
    failed_documents: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    has_output_zip: bool = False


class BatchJobDetailResponse(BatchJobResponse):
    """Schema for detailed batch job response with documents."""

    documents: list[BatchDocumentStatus]
    min_confidence: float
    highlight_changes: bool
    generate_changes_report: bool


class BatchProgressResponse(BaseModel):
    """Schema for real-time batch progress updates."""

    batch_id: uuid.UUID
    status: str
    total_documents: int
    processed_documents: int
    failed_documents: int
    current_document: str | None = None
    percentage: float
    estimated_remaining_seconds: int | None = None


class BatchListResponse(BaseModel):
    """Schema for paginated batch job list."""

    items: list[BatchJobResponse]
    total: int
    page: int
    page_size: int


# Health check schemas
class HealthResponse(BaseModel):
    """Schema for health check response."""

    status: str
    version: str
    environment: str


class DetailedHealthResponse(HealthResponse):
    """Schema for detailed health check response."""

    database: str
    redis: str
    vector_store: str
    storage: str


# Error schemas
class ErrorResponse(BaseModel):
    """Schema for error response."""

    error_code: str
    message: str
    details: dict[str, Any] | None = None


class ValidationErrorDetail(BaseModel):
    """Schema for validation error detail."""

    loc: list[str | int]
    msg: str
    type: str


class ValidationErrorResponse(BaseModel):
    """Schema for validation error response."""

    error_code: str = "ValidationError"
    message: str = "Validation failed"
    details: list[ValidationErrorDetail]
