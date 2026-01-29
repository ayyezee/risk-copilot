"""Add reference_examples table with pgvector

Revision ID: 002
Revises: 001
Create Date: 2024-01-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # Create reference_examples table
    op.create_table(
        'reference_examples',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('original_text', sa.Text(), nullable=False),
        sa.Column('converted_text', sa.Text(), nullable=False),
        sa.Column('term_mappings', postgresql.JSON(), nullable=True),
        sa.Column('original_filename', sa.String(255), nullable=True),
        sa.Column('converted_filename', sa.String(255), nullable=True),
        sa.Column('original_file_type', sa.String(50), nullable=True),
        sa.Column('converted_file_type', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Add vector column for embeddings (1536 dimensions for OpenAI text-embedding-3-small)
    op.execute('ALTER TABLE reference_examples ADD COLUMN embedding vector(1536)')

    # Create indexes
    op.create_index('ix_reference_examples_owner_id', 'reference_examples', ['owner_id'])
    op.create_index('ix_reference_examples_name', 'reference_examples', ['name'])

    # Create HNSW index for fast approximate nearest neighbor search
    # Using cosine distance (vector_cosine_ops)
    op.execute('''
        CREATE INDEX ix_reference_examples_embedding
        ON reference_examples
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    ''')


def downgrade() -> None:
    op.drop_index('ix_reference_examples_embedding', 'reference_examples')
    op.drop_index('ix_reference_examples_name', 'reference_examples')
    op.drop_index('ix_reference_examples_owner_id', 'reference_examples')
    op.drop_table('reference_examples')
    # Note: We don't drop the vector extension as other tables might use it
