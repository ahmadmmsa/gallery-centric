"""repair stamped schemas and seed system languages

Older setup code built tables with ``create_all`` and then stamped Alembic at
``head``. ``create_all`` cannot add columns to existing tables, so an upgraded
database could claim to be current while still missing later model fields.
This forward-only repair revision makes those installations whole before
normal Alembic upgrades become the only schema bootstrap path.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-22 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SYSTEM_LANGUAGES = (
    ("en", "English"),
    ("ja", "Japanese"),
    ("zh", "Chinese"),
    ("es", "Spanish"),
    ("ar", "Arabic"),
)


def _require_tables(table_names: set[str], *required: str) -> None:
    missing = sorted(set(required) - table_names)
    if missing:
        raise RuntimeError(
            "Cannot repair the Gallery Centric schema; missing core tables: "
            + ", ".join(missing)
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    _require_tables(
        table_names,
        "galleries",
        "pages",
        "users",
        "languages",
        "gallery_tags",
        "tags",
    )

    # Repair columns that create_all could not add to existing tables.
    op.execute("ALTER TABLE pages ADD COLUMN IF NOT EXISTS thumbnail_path VARCHAR")
    op.execute("ALTER TABLE pages ADD COLUMN IF NOT EXISTS image_width INTEGER")
    op.execute("ALTER TABLE pages ADD COLUMN IF NOT EXISTS image_height INTEGER")
    op.execute("ALTER TABLE galleries ADD COLUMN IF NOT EXISTS sequence INTEGER DEFAULT 0")
    op.execute("ALTER TABLE galleries ADD COLUMN IF NOT EXISTS search_vector TSVECTOR")
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password "
        "BOOLEAN NOT NULL DEFAULT FALSE"
    )

    # Repair whole tables introduced after the original schema.
    if "app_settings" not in table_names:
        op.create_table(
            "app_settings",
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column(
                "is_secret",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.PrimaryKeyConstraint("key"),
        )

    if "user_favorites" not in table_names:
        op.create_table(
            "user_favorites",
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("gallery_id", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["gallery_id"], ["galleries.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("user_id", "gallery_id"),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_favorites_user_id "
        "ON user_favorites (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_gallery_search_vector "
        "ON galleries USING gin (search_vector)"
    )

    # The language list is system-managed. Codes are stable public filter values.
    values = ", ".join(
        f"('{code}', '{name}')" for code, name in SYSTEM_LANGUAGES
    )
    op.execute(
        "INSERT INTO languages (code, name) VALUES "
        f"{values} ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name"
    )

    # Recreate FTS state in case a stamped database never ran the historical
    # search-vector migration.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_gallery_search_vector()
        RETURNS trigger AS $$
        BEGIN
          NEW.search_vector :=
             setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
             setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B') ||
             setweight(to_tsvector('english', coalesce((
                 SELECT string_agg(t.name, ' ')
                 FROM gallery_tags gt
                 JOIN tags t ON gt.tag_id = t.id
                 WHERE gt.gallery_id = NEW.id
             ), '')), 'C');
          RETURN NEW;
        END
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS tsvectorupdate ON galleries")
    op.execute(
        """
        CREATE TRIGGER tsvectorupdate BEFORE INSERT OR UPDATE
        ON galleries FOR EACH ROW EXECUTE FUNCTION update_gallery_search_vector()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_gallery_search_vector_from_tags()
        RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            UPDATE galleries SET updated_at = NOW() WHERE id = OLD.gallery_id;
            RETURN OLD;
          ELSE
            UPDATE galleries SET updated_at = NOW() WHERE id = NEW.gallery_id;
            RETURN NEW;
          END IF;
        END
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS tsvectorupdate_tags ON gallery_tags")
    op.execute(
        """
        CREATE TRIGGER tsvectorupdate_tags AFTER INSERT OR UPDATE OR DELETE
        ON gallery_tags FOR EACH ROW
        EXECUTE FUNCTION update_gallery_search_vector_from_tags()
        """
    )
    op.execute("UPDATE galleries SET updated_at = NOW()")


def downgrade() -> None:
    # This revision repairs state owned by earlier migrations. Removing repaired
    # columns or seeded rows would risk data loss and would not recreate the
    # previously broken schema, so the repair is intentionally irreversible.
    pass
