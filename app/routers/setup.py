"""First-run setup: create the admin password by opening the site.

On the very first launch the admin account exists but has an unusable,
auto-generated password (``must_change_password=True``). Until someone completes
this page every request is redirected here (see ``deps.load_current_user``).
Once the password is set the flag clears and this page 404s / redirects to login.
"""
from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models.user import User
from app.utils.auth import get_password_hash
from app.utils.templates import templates
from app.utils.seo import get_default_seo
from app.services import runtime_config
from app.routers.auth import _set_auth_cookie
from app.config import settings

router = APIRouter()


def _ctx(request: Request, **extra) -> dict:
    ctx = {
        "request": request,
        "seo": get_default_seo("Welcome"),
        "settings": settings,
        "admin_username": settings.ADMIN_USERNAME,
    }
    ctx.update(extra)
    return ctx


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    if not runtime_config.setup_required():
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request, "auth/setup.html", _ctx(request))


@router.post("/setup")
async def setup_submit(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not runtime_config.setup_required():
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)

    error = None
    if len(new_password) < 8:
        error = "Password must be at least 8 characters."
    elif new_password != confirm_password:
        error = "Passwords do not match."
    if error:
        return templates.TemplateResponse(
            request, "auth/setup.html", _ctx(request, error=error),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    admin = (
        await db.execute(
            select(User).where(User.is_admin == True, User.must_change_password == True)  # noqa: E712
        )
    ).scalars().first()
    if admin is None:
        # Setup was completed by a concurrent request between the guard and here.
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)

    admin.hashed_password = get_password_hash(new_password)
    admin.must_change_password = False
    await db.commit()
    runtime_config.mark_setup_complete()

    res = RedirectResponse(url="/admin/", status_code=status.HTTP_302_FOUND)
    return _set_auth_cookie(res, admin.username)
