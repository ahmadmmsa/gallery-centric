import os

DB_USER = "gallery"
DB_NAME = "gallery"
DB_PASSWORD_FILE = os.path.join("data", "db_password")

def _database_url() -> str:
    override = os.environ.get("DATABASE_URL")
    if override:
        return override

    try:
        with open(DB_PASSWORD_FILE, encoding="utf-8") as fh:
            password = fh.read().strip()
    except FileNotFoundError:
        raise RuntimeError(
            f"Database password file '{DB_PASSWORD_FILE}' not found. "
            "Start the stack with 'docker compose up' (the db-init service "
            "generates it on first boot), or set the DATABASE_URL environment "
            "variable to use an external database."
        ) from None

    host = os.environ.get("DB_HOST", "gallerydb")
    return f"postgresql+asyncpg://{DB_USER}:{password}@{host}:5432/{DB_NAME}"

class Settings:
    DATABASE_URL: str = _database_url()
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 1 week
    UPLOAD_DIR: str = "media"
    # Developer override only (DEBUG=1); production always runs with False.
    DEBUG: bool = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")

settings = Settings()
