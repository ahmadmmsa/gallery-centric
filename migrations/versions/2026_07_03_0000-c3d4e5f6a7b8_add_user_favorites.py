"""add user_favorites table

Per-user favorite galleries (drives the favorite button and /favorites page).
Idempotent so it is safe on a database already built by create_all and
stamped at head.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'user_favorites' not in insp.get_table_names():
        op.create_table(
            'user_favorites',
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('gallery_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['gallery_id'], ['galleries.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('user_id', 'gallery_id'),
        )
        op.create_index('ix_user_favorites_user_id', 'user_favorites', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_user_favorites_user_id', table_name='user_favorites')
    op.drop_table('user_favorites')
