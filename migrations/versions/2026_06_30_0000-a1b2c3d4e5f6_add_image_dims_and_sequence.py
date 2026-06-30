"""add pages.image_width/image_height and galleries.sequence

These columns exist on the SQLAlchemy models (and are written by the page
upload code) but were never added by a migration -- fresh installs get them
via setup.py's create_all, while databases upgraded purely through Alembic
were left without them. Added idempotently so it is safe to run regardless of
how the schema was originally created.

Revision ID: a1b2c3d4e5f6
Revises: 52fb7fef9c8f
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '52fb7fef9c8f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS keeps this safe on databases that already have the columns
    # (e.g. created via setup.py's Base.metadata.create_all).
    op.execute("ALTER TABLE pages ADD COLUMN IF NOT EXISTS image_width INTEGER")
    op.execute("ALTER TABLE pages ADD COLUMN IF NOT EXISTS image_height INTEGER")
    op.execute("ALTER TABLE galleries ADD COLUMN IF NOT EXISTS sequence INTEGER DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE galleries DROP COLUMN IF EXISTS sequence")
    op.execute("ALTER TABLE pages DROP COLUMN IF EXISTS image_height")
    op.execute("ALTER TABLE pages DROP COLUMN IF EXISTS image_width")
