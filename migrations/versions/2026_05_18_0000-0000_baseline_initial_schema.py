"""baseline initial schema

Creates the core schema as it existed before the first incremental migration
(0001_add_pages_thumbnail). Previously the migration chain assumed these tables
already existed (built by setup.py's create_all), so `alembic upgrade head` on a
fresh database failed. This baseline makes a pure-Alembic provision work.

Later migrations layer on top exactly as before:
  0000 (this) -> 0001 (pages.thumbnail_path) -> d6045f12df88 (users)
  -> 52fb7fef9c8f (search_vector + FTS) -> a1b2c3d4e5f6 (image dims + sequence)

Idempotent guards (checkfirst) make it safe to run against a database that was
already created by create_all and stamped at head.

Revision ID: 0000_baseline
Revises:
Create Date: 2026-05-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0000_baseline'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())

    def has(name):
        return name in existing

    if not has('languages'):
        op.create_table(
            'languages',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('code', sa.String(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('code'),
        )
        op.create_index('ix_languages_id', 'languages', ['id'])

    if not has('tag_types'):
        op.create_table(
            'tag_types',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('slug', sa.String(), nullable=False),
            sa.Column('color', sa.String(), nullable=True),
            sa.Column('is_visible', sa.Boolean(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name'),
        )
        op.create_index('ix_tag_types_id', 'tag_types', ['id'])
        op.create_index('ix_tag_types_slug', 'tag_types', ['slug'], unique=True)

    if not has('tags'):
        op.create_table(
            'tags',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('slug', sa.String(), nullable=False),
            sa.Column('tag_type_id', sa.Integer(), nullable=False),
            sa.Column('description', sa.String(), nullable=True),
            sa.Column('gallery_count', sa.Integer(), nullable=True),
            sa.Column('is_visible', sa.Boolean(), nullable=True),
            sa.ForeignKeyConstraint(['tag_type_id'], ['tag_types.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_tags_id', 'tags', ['id'])
        op.create_index('ix_tags_name', 'tags', ['name'])
        op.create_index('ix_tags_slug', 'tags', ['slug'], unique=True)

    for tbl in ('artists', 'characters', 'parodies'):
        if has(tbl):
            continue
        cols = [
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('slug', sa.String(), nullable=False),
            sa.Column('gallery_count', sa.Integer(), nullable=True),
        ]
        if tbl == 'artists':
            cols.insert(3, sa.Column('bio', sa.Text(), nullable=True))
        op.create_table(tbl, *cols, sa.PrimaryKeyConstraint('id'))
        op.create_index(f'ix_{tbl}_id', tbl, ['id'])
        op.create_index(f'ix_{tbl}_name', tbl, ['name'])
        op.create_index(f'ix_{tbl}_slug', tbl, ['slug'], unique=True)

    if not has('galleries'):
        op.create_table(
            'galleries',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('slug', sa.String(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('thumbnail_path', sa.String(), nullable=True),
            sa.Column('cover_path', sa.String(), nullable=True),
            sa.Column('language_id', sa.Integer(), nullable=True),
            sa.Column('page_count', sa.Integer(), nullable=True),
            sa.Column('view_count', sa.Integer(), nullable=True),
            sa.Column('favorite_count', sa.Integer(), nullable=True),
            sa.Column('published_date', sa.DateTime(timezone=True), nullable=True),
            sa.Column('seo_title', sa.String(), nullable=True),
            sa.Column('seo_description', sa.String(), nullable=True),
            sa.Column('is_published', sa.Boolean(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.ForeignKeyConstraint(['language_id'], ['languages.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_galleries_id', 'galleries', ['id'])
        op.create_index('ix_galleries_title', 'galleries', ['title'])
        op.create_index('ix_galleries_slug', 'galleries', ['slug'], unique=True)
        op.create_index('ix_galleries_is_published', 'galleries', ['is_published'])
        op.create_index('ix_galleries_created_at', 'galleries', ['created_at'])

    if not has('pages'):
        op.create_table(
            'pages',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('gallery_id', sa.Integer(), nullable=False),
            sa.Column('page_number', sa.Integer(), nullable=False),
            sa.Column('image_path', sa.String(), nullable=False),
            sa.ForeignKeyConstraint(['gallery_id'], ['galleries.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_pages_id', 'pages', ['id'])
        op.create_index('ix_pages_gallery_id', 'pages', ['gallery_id'])

    assoc = {
        'gallery_tags': ('tag_id', 'tags'),
        'gallery_artists': ('artist_id', 'artists'),
        'gallery_characters': ('character_id', 'characters'),
        'gallery_parodies': ('parody_id', 'parodies'),
    }
    for table_name, (col, ref) in assoc.items():
        if has(table_name):
            continue
        op.create_table(
            table_name,
            sa.Column('gallery_id', sa.Integer(), nullable=False),
            sa.Column(col, sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['gallery_id'], ['galleries.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint([col], [f'{ref}.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('gallery_id', col),
        )


def downgrade() -> None:
    for table_name in (
        'gallery_parodies', 'gallery_characters', 'gallery_artists', 'gallery_tags',
        'pages', 'galleries', 'parodies', 'characters', 'artists', 'tags',
        'tag_types', 'languages',
    ):
        op.drop_table(table_name)
