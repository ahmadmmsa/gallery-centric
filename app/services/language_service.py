"""Cached public language choices backed by the system language table."""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.language import Language


@dataclass(frozen=True)
class PublicLanguage:
    code: str
    name: str


# Startup normally replaces this fallback with the migration-seeded DB rows.
_DEFAULT_LANGUAGES = (
    PublicLanguage(code="en", name="English"),
    PublicLanguage(code="ja", name="Japanese"),
    PublicLanguage(code="zh", name="Chinese"),
    PublicLanguage(code="es", name="Spanish"),
    PublicLanguage(code="ar", name="Arabic"),
)
_cache: tuple[PublicLanguage, ...] = _DEFAULT_LANGUAGES


async def refresh(db: AsyncSession) -> None:
    """Refresh the process-local list used by public templates."""
    global _cache
    rows = (
        await db.execute(select(Language).order_by(Language.name, Language.code))
    ).scalars().all()
    _cache = tuple(PublicLanguage(code=row.code, name=row.name) for row in rows)


def all_languages() -> tuple[PublicLanguage, ...]:
    return _cache
