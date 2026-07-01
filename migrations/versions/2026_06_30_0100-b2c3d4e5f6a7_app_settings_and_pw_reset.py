"""add app_settings table and users.must_change_password

Adds the key/value app_settings store (runtime-generated secrets, encrypted at
rest) and the forced-password-change flag. Idempotent so it is safe on a
database already built by create_all and stamped at head.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-30 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'app_settings' not in insp.get_table_names():
        op.create_table(
            'app_settings',
            sa.Column('key', sa.String(), nullable=False),
            sa.Column('value', sa.Text(), nullable=False),
            sa.Column('is_secret', sa.Boolean(), nullable=False, server_default='false'),
            sa.PrimaryKeyConstraint('key'),
        )

    user_cols = {c['name'] for c in insp.get_columns('users')}
    if 'must_change_password' not in user_cols:
        op.add_column(
            'users',
            sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default='false'),
        )


def downgrade() -> None:
    op.drop_column('users', 'must_change_password')
    op.drop_table('app_settings')
