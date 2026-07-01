"""Global request dependency: load the current user and enforce password reset.

This runs as a FastAPI dependency (in the endpoint's task), not in the
BaseHTTPMiddleware, so its DB work shares the request's cached get_db session
and never trips asyncpg's cross-task "another operation in progress".
"""
from fastapi import Request
from sqlalchemy.future import select
from jose import jwt

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.user import User
from app.services import runtime_config

# Paths a user who must reset their password is still allowed to reach.
PASSWORD_CHANGE_ALLOWED = ("/auth/change-password", "/auth/logout")


class PasswordChangeRequired(Exception):
    """Raised to force a logged-in user to the change-password page."""


class SetupRequired(Exception):
    """Raised on first launch to force everyone to the /setup page."""


async def load_current_user(request: Request) -> None:
    # First launch: no admin password has been set yet -> everybody is sent to
    # the /setup page to create one. Cheap in-memory flag, no DB hit.
    if runtime_config.setup_required():
        request.state.user = None
        if not request.url.path.startswith("/setup"):
            raise SetupRequired()
        return

    # Use a self-contained session (opened and closed here) rather than the
    # request's get_db session: sharing one session across the app-level
    # dependency and the route boundary corrupts SQLAlchemy's async greenlet
    # context. expire_on_commit=False keeps the loaded user usable after close.
    request.state.user = None

    token = request.cookies.get("access_token")
    if token and token.startswith("Bearer "):
        token = token[7:]
    if token:
        try:
            payload = jwt.decode(token, runtime_config.secret_key(), algorithms=[settings.ALGORITHM])
            username = payload.get("sub")
            if username:
                async with AsyncSessionLocal() as db:
                    request.state.user = (
                        await db.execute(select(User).where(User.username == username))
                    ).scalars().first()
        except Exception:
            pass

    user = request.state.user
    if user is not None and getattr(user, "must_change_password", False):
        if not any(request.url.path.startswith(p) for p in PASSWORD_CHANGE_ALLOWED):
            raise PasswordChangeRequired()
