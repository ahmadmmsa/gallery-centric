#!/usr/bin/env python3
"""First-run setup for GalleryCentric.

Idempotent bootstrap that works the same whether PostgreSQL runs in a
docker-compose container or on a dedicated database host. Everything is
driven by ``DATABASE_URL`` from the environment / .env file.

Steps (all safe to re-run):
  1. Wait for the PostgreSQL server to accept connections.
  2. Create the target database if it does not exist.
  3. Create all tables from the SQLAlchemy models.
  4. Install the PostgreSQL full-text-search functions and triggers
     (these power search and are NOT part of the ORM models, so they
     must be applied explicitly).
  5. Stamp Alembic at ``head`` so future migrations apply cleanly.
  6. Create the admin user from ADMIN_USERNAME / ADMIN_PASSWORD.

Usage:
    python setup.py
"""
import asyncio
import subprocess
import sys

import asyncpg
from sqlalchemy.engine import make_url

from app.config import settings

# Connection attempts while the DB server is still coming up (e.g. a
# freshly started container). On a dedicated host this succeeds first try.
DB_CONNECT_RETRIES = 30
DB_CONNECT_DELAY_SECONDS = 2

# Full-text-search functions/triggers that power gallery search. Kept in
# sync with migrations/versions/..._add_search_vector.py. CREATE OR REPLACE
# and DROP ... IF EXISTS make this block idempotent.
FTS_SQL = """
CREATE OR REPLACE FUNCTION update_gallery_search_vector() RETURNS trigger AS $$
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
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tsvectorupdate ON galleries;
CREATE TRIGGER tsvectorupdate BEFORE INSERT OR UPDATE
ON galleries FOR EACH ROW EXECUTE FUNCTION update_gallery_search_vector();

CREATE OR REPLACE FUNCTION update_gallery_search_vector_from_tags() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    UPDATE galleries SET updated_at = NOW() WHERE id = OLD.gallery_id;
    RETURN OLD;
  ELSE
    UPDATE galleries SET updated_at = NOW() WHERE id = NEW.gallery_id;
    RETURN NEW;
  END IF;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tsvectorupdate_tags ON gallery_tags;
CREATE TRIGGER tsvectorupdate_tags AFTER INSERT OR UPDATE OR DELETE
ON gallery_tags FOR EACH ROW EXECUTE FUNCTION update_gallery_search_vector_from_tags();
"""


def _log(message: str) -> None:
    print(f"[setup] {message}", flush=True)


async def _connect_server(url, database: str):
    """Connect to a specific maintenance database on the server, with retries."""
    last_error = None
    for attempt in range(1, DB_CONNECT_RETRIES + 1):
        try:
            return await asyncpg.connect(
                user=url.username,
                password=url.password,
                host=url.host,
                port=url.port or 5432,
                database=database,
            )
        except (asyncpg.InvalidCatalogNameError,):
            # Maintenance database itself missing; let caller try another one.
            raise
        except (OSError, asyncpg.PostgresError) as exc:
            last_error = exc
            _log(
                f"PostgreSQL not ready ({database}) "
                f"[{attempt}/{DB_CONNECT_RETRIES}]: {exc}"
            )
            await asyncio.sleep(DB_CONNECT_DELAY_SECONDS)
    raise RuntimeError(f"Could not reach PostgreSQL server: {last_error}")


async def ensure_database_exists() -> None:
    """Create the target database if it is missing.

    Connects to a maintenance database on the same server (works for both a
    container, where only `postgres` exists by default, and a dedicated host).
    """
    url = make_url(settings.DATABASE_URL)
    target_db = url.database
    if not target_db:
        raise RuntimeError("DATABASE_URL has no database name")

    conn = None
    # Try common maintenance databases in order.
    for maintenance_db in ("postgres", "template1", url.username):
        if not maintenance_db:
            continue
        try:
            conn = await _connect_server(url, maintenance_db)
            break
        except asyncpg.InvalidCatalogNameError:
            continue
    if conn is None:
        raise RuntimeError(
            "Could not connect to any maintenance database "
            "(tried: postgres, template1, <user>)"
        )

    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", target_db
        )
        if exists:
            _log(f"Database '{target_db}' already exists.")
        else:
            # Identifier can't be parameterized; quote to be safe.
            await conn.execute(f'CREATE DATABASE "{target_db}"')
            _log(f"Created database '{target_db}'.")
    finally:
        await conn.close()


async def create_schema() -> None:
    """Create all tables/indexes from the models and install FTS triggers."""
    # Imported here so settings/database load after we know the DB exists.
    from app.database import engine, Base
    import app.models  # noqa: F401  (registers all models on Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _log("Tables created / verified.")

    # asyncpg sends text() statements via the extended query protocol
    # (prepared statements), which allows only ONE command each. FTS_SQL is a
    # multi-statement block, so run it on the raw asyncpg connection's
    # execute(), which uses the simple query protocol and accepts many commands.
    async with engine.begin() as conn:
        raw_conn = await conn.get_raw_connection()
        await raw_conn.driver_connection.execute(FTS_SQL)
    _log("Full-text-search functions and triggers installed.")

    await engine.dispose()


def stamp_alembic() -> None:
    """Mark the migration history as current so future upgrades apply cleanly."""
    try:
        subprocess.run(
            ["alembic", "stamp", "head"],
            check=True,
            capture_output=True,
            text=True,
        )
        _log("Alembic stamped at head.")
    except FileNotFoundError:
        _log("Alembic not found on PATH; skipping migration stamp.")
    except subprocess.CalledProcessError as exc:
        _log(f"Warning: 'alembic stamp head' failed (continuing): {exc.stderr.strip()}")


async def create_admin_user() -> None:
    """Create the admin user from ADMIN_USERNAME / ADMIN_PASSWORD if absent."""
    from sqlalchemy.future import select

    from app.database import AsyncSessionLocal, engine
    from app.models.user import User
    from app.utils.auth import get_password_hash

    async with AsyncSessionLocal() as db:
        username = settings.ADMIN_USERNAME
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalars().first()

        if user is None:
            db.add(
                User(
                    username=username,
                    email="admin@example.com",
                    hashed_password=get_password_hash(settings.ADMIN_PASSWORD),
                    is_admin=True,
                )
            )
            await db.commit()
            _log(f"Created admin user '{username}'.")
        elif not user.is_admin:
            user.is_admin = True
            await db.commit()
            _log(f"Promoted existing user '{username}' to admin.")
        else:
            _log(f"Admin user '{username}' already exists.")

    await engine.dispose()


async def main() -> None:
    _log("Starting first-run setup...")
    await ensure_database_exists()
    await create_schema()
    stamp_alembic()
    await create_admin_user()
    _log("Setup complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001 - surface a clear failure to the operator
        _log(f"ERROR: {exc}")
        sys.exit(1)
