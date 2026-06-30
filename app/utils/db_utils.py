from typing import Optional, Any
from sqlalchemy import exc
from sqlalchemy.ext.asyncio import AsyncSession


essential_exceptions = (
    exc.SQLAlchemyError,
)


async def safe_execute_first(db: AsyncSession, stmt) -> Optional[Any]:
    try:
        result = await db.execute(stmt)
        return result.scalars().first()
    except essential_exceptions:
        return None


async def safe_execute_all(db: AsyncSession, stmt) -> list:
    try:
        result = await db.execute(stmt)
        return list(result.scalars().all())
    except essential_exceptions:
        return []
