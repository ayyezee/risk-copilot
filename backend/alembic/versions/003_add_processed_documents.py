"""Add processed_documents table for storing generated output files.

Revision ID: 003
Revises: 002
Create Date: 2025-01-29

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processed_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("source_document_id", sa.UUID(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("source_format", sa.String(length=50), nullable=False),
        sa.Column("total_replacements", sa.Integer(), default=0, nullable=False),
        sa.Column("replacement_details", sa.JSON(), nullable=True),
        sa.Column("warnings", sa.ARRAY(sa.String()), nullable=True),
        sa.Column("processing_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes
    op.create_index("ix_processed_documents_owner_id", "processed_documents", ["owner_id"])
    op.create_index("ix_processed_documents_source_document_id", "processed_documents", ["source_document_id"])


def downgrade() -> None:
    op.drop_index("ix_processed_documents_source_document_id", table_name="processed_documents")
    op.drop_index("ix_processed_documents_owner_id", table_name="processed_documents")
    op.drop_table("processed_documents")
