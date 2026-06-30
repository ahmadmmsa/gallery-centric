"""add pages.thumbnail_path

Revision ID: 0001_add_pages_thumbnail
Revises: 
Create Date: 2026-05-18

"""

from alembic import op
import sqlalchemy as sa

revision = '0001_add_pages_thumbnail'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('pages', sa.Column('thumbnail_path', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('pages', 'thumbnail_path')

