"""Add batch_jobs and batch_job_documents tables for batch processing.

Revision ID: 005
Revises: 004
Create Date: 2025-01-29

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create batch_jobs table
    op.create_table(
        "batch_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        # Status
        sa.Column("status", sa.String(length=50), default="pending", nullable=False),
        # Progress
        sa.Column("total_documents", sa.Integer(), default=0, nullable=False),
        sa.Column("processed_documents", sa.Integer(), default=0, nullable=False),
        sa.Column("failed_documents", sa.Integer(), default=0, nullable=False),
        # Configuration
        sa.Column("reference_example_ids", sa.ARRAY(sa.String()), nullable=True),
        sa.Column("protected_terms", sa.ARRAY(sa.String()), nullable=True),
        sa.Column("min_confidence", sa.Float(), default=0.7, nullable=False),
        sa.Column("highlight_changes", sa.Boolean(), default=True, nullable=False),
        sa.Column("generate_changes_report", sa.Boolean(), default=True, nullable=False),
        # Timing
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # Output
        sa.Column("output_zip_path", sa.String(length=500), nullable=True),
        # Error
        sa.Column("error_message", sa.Text(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        # Constraints
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for batch_jobs
    op.create_index("ix_batch_jobs_owner_id", "batch_jobs", ["owner_id"])
    op.create_index("ix_batch_jobs_status", "batch_jobs", ["status"])
    op.create_index("ix_batch_jobs_created_at", "batch_jobs", ["created_at"])

    # Create batch_job_documents table
    op.create_table(
        "batch_job_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("batch_job_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("processed_document_id", sa.UUID(), nullable=True),
        # Document info
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=50), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        # Status
        sa.Column("status", sa.String(length=50), default="pending", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Metrics
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("total_replacements", sa.Integer(), default=0, nullable=False),
        # Order
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        # Constraints
        sa.ForeignKeyConstraint(["batch_job_id"], ["batch_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["processed_document_id"], ["processed_documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for batch_job_documents
    op.create_index("ix_batch_job_documents_batch_job_id", "batch_job_documents", ["batch_job_id"])
    op.create_index("ix_batch_job_documents_status", "batch_job_documents", ["status"])


def downgrade() -> None:
    # Drop batch_job_documents indexes and table
    op.drop_index("ix_batch_job_documents_status", table_name="batch_job_documents")
    op.drop_index("ix_batch_job_documents_batch_job_id", table_name="batch_job_documents")
    op.drop_table("batch_job_documents")

    # Drop batch_jobs indexes and table
    op.drop_index("ix_batch_jobs_created_at", table_name="batch_jobs")
    op.drop_index("ix_batch_jobs_status", table_name="batch_jobs")
    op.drop_index("ix_batch_jobs_owner_id", table_name="batch_jobs")
    op.drop_table("batch_jobs")
