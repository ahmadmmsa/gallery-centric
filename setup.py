#!/usr/bin/env python3
"""First-run setup for GalleryCentric.

Idempotent bootstrap that works the same whether PostgreSQL runs in a
docker-compose container or on a dedicated database host. Everything is
driven by ``DATABASE_URL`` from the environment / .env file.

Steps (all safe to re-run):
  1. Wait for the PostgreSQL server to accept connections.
  2. Create the target database if it does not exist.
  3. Upgrade the schema to the latest Alembic revision.
  4. Generate application secrets if they do not exist.
  5. Create the placeholder admin user for browser-based first-run setup.

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


def upgrade_schema() -> None:
    """Apply every pending schema migration and fail startup on any error."""
    try:
        subprocess.run(
            ["alembic", "upgrade", "head"],
            check=True,
            capture_output=True,
            text=True,
        )
        _log("Database schema upgraded to Alembic head.")
    except FileNotFoundError as exc:
        raise RuntimeError("Alembic is not installed or is not on PATH") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"'alembic upgrade head' failed: {detail}") from exc


async def generate_secrets() -> None:
    """Generate SECRET_KEY / ALTCHA_HMAC_KEY (encrypted) in the DB if missing."""
    from app.database import AsyncSessionLocal, engine
    from app.services import runtime_config

    async with AsyncSessionLocal() as db:
        await runtime_config.bootstrap(db)
    await engine.dispose()
    _log("Application secrets generated/verified (stored encrypted in the database).")


def _announce_setup_needed(username: str) -> None:
    _log("=" * 64)
    _log("FIRST-RUN SETUP REQUIRED")
    _log(f"    Open {settings.BASE_URL} in your browser to set the password")
    _log(f"    for the administrator account '{username}'.")
    _log("=" * 64)


async def create_admin_user() -> None:
    """Final setup step: ensure an admin placeholder exists for first-run setup.

    The admin is created with an unusable random password and
    ``must_change_password=True``. Nobody logs in with it -- the user sets the
    real password from the web /setup page on first launch.
    """
    import secrets as _secrets
    from sqlalchemy.future import select

    from app.database import AsyncSessionLocal, engine
    from app.models.user import User
    from app.utils.auth import get_password_hash

    async with AsyncSessionLocal() as db:
        username = settings.ADMIN_USERNAME
        user = (await db.execute(select(User).where(User.username == username))).scalars().first()

        if user is None:
            db.add(
                User(
                    username=username,
                    email="admin@example.com",
                    # Unusable placeholder; replaced via the web /setup page.
                    hashed_password=get_password_hash(_secrets.token_urlsafe(32)),
                    is_admin=True,
                    must_change_password=True,
                )
            )
            await db.commit()
            _announce_setup_needed(username)
        elif user.must_change_password:
            # Setup not completed yet -> keep it as an admin and re-announce.
            user.is_admin = True
            await db.commit()
            _announce_setup_needed(username)
        else:
            _log(f"Admin user '{username}' already configured (password set by user).")

    await engine.dispose()


async def main() -> None:
    _log("Starting first-run setup...")
    await ensure_database_exists()
    upgrade_schema()
    await generate_secrets()
    # Admin creation runs last so the schema and secrets are fully in place.
    await create_admin_user()
    _log("Setup complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001 - surface a clear failure to the operator
        _log(f"ERROR: {exc}")
        sys.exit(1)
