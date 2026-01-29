"""Add processing_logs and user_corrections tables for analytics and learning.

Revision ID: 004
Revises: 003
Create Date: 2025-01-29

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create processing_logs table
    op.create_table(
        "processing_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("processed_document_id", sa.UUID(), nullable=True),
        # Processing metrics
        sa.Column("total_replacements", sa.Integer(), default=0, nullable=False),
        sa.Column("processing_time_ms", sa.Integer(), default=0, nullable=False),
        sa.Column("tokens_used", sa.Integer(), default=0, nullable=False),
        sa.Column("cache_hits", sa.Integer(), default=0, nullable=False),
        sa.Column("cache_misses", sa.Integer(), default=0, nullable=False),
        # Document info
        sa.Column("document_word_count", sa.Integer(), nullable=True),
        sa.Column("document_type", sa.String(length=50), nullable=True),
        sa.Column("chunks_processed", sa.Integer(), default=1, nullable=False),
        # Learning data
        sa.Column("replacements_made", sa.JSON(), nullable=True),
        sa.Column("warnings", sa.ARRAY(sa.String()), nullable=True),
        sa.Column("reference_examples_used", sa.ARRAY(sa.String()), nullable=True),
        # Status
        sa.Column("status", sa.String(length=50), default="completed", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        # Constraints
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["processed_document_id"], ["processed_documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for processing_logs
    op.create_index("ix_processing_logs_owner_id", "processing_logs", ["owner_id"])
    op.create_index("ix_processing_logs_document_id", "processing_logs", ["document_id"])
    op.create_index("ix_processing_logs_created_at", "processing_logs", ["created_at"])

    # Create user_corrections table
    op.create_table(
        "user_corrections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("processing_log_id", sa.UUID(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        # Original AI suggestion
        sa.Column("original_term", sa.Text(), nullable=False),
        sa.Column("suggested_replacement", sa.Text(), nullable=False),
        sa.Column("suggested_confidence", sa.Float(), nullable=False),
        # User's correction
        sa.Column("correction_type", sa.String(length=50), nullable=False),
        sa.Column("user_replacement", sa.Text(), nullable=True),
        sa.Column("user_reason", sa.Text(), nullable=True),
        # Context
        sa.Column("context_before", sa.Text(), nullable=True),
        sa.Column("context_after", sa.Text(), nullable=True),
        # Processing status
        sa.Column("processed", sa.Boolean(), default=False, nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        # Constraints
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["processing_log_id"], ["processing_logs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for user_corrections
    op.create_index("ix_user_corrections_owner_id", "user_corrections", ["owner_id"])
    op.create_index("ix_user_corrections_original_term", "user_corrections", ["original_term"])
    op.create_index("ix_user_corrections_processed", "user_corrections", ["processed"])


def downgrade() -> None:
    # Drop user_corrections indexes and table
    op.drop_index("ix_user_corrections_processed", table_name="user_corrections")
    op.drop_index("ix_user_corrections_original_term", table_name="user_corrections")
    op.drop_index("ix_user_corrections_owner_id", table_name="user_corrections")
    op.drop_table("user_corrections")

    # Drop processing_logs indexes and table
    op.drop_index("ix_processing_logs_created_at", table_name="processing_logs")
    op.drop_index("ix_processing_logs_document_id", table_name="processing_logs")
    op.drop_index("ix_processing_logs_owner_id", table_name="processing_logs")
    op.drop_table("processing_logs")
