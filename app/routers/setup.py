"""First-run setup wizard: configure the site by opening it.

On the very first launch the admin account exists but has an unusable,
auto-generated password (``must_change_password=True``). Until someone
completes this page every request is redirected here (see
``deps.load_current_user``). The wizard collects the admin username (default
"admin"), the password, and optional site name / base URL. Once submitted the
flag clears and this page redirects to login.
"""
import re

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

router = APIRouter()

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


async def _pending_admin(db: AsyncSession) -> User | None:
    return (
        await db.execute(
            select(User).where(User.is_admin == True, User.must_change_password == True)  # noqa: E712
        )
    ).scalars().first()


def _ctx(request: Request, **extra) -> dict:
    ctx = {
        "request": request,
        "seo": get_default_seo("Welcome"),
        # Prefills; overridden with the submitted values on a validation error.
        "admin_username": "admin",
        "site_name": runtime_config.get("SITE_NAME", ""),
        "base_url": str(request.base_url).rstrip("/"),
    }
    ctx.update(extra)
    return ctx


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, db: AsyncSession = Depends(get_db)):
    if not runtime_config.setup_required():
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    admin = await _pending_admin(db)
    extra = {"admin_username": admin.username} if admin else {}
    return templates.TemplateResponse(request, "auth/setup.html", _ctx(request, **extra))


@router.post("/setup")
async def setup_submit(
    request: Request,
    admin_username: str = Form("admin"),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    site_name: str = Form(""),
    base_url: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not runtime_config.setup_required():
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)

    admin_username = admin_username.strip() or "admin"
    site_name = site_name.strip()
    base_url = base_url.strip().rstrip("/")

    error = None
    if not USERNAME_RE.match(admin_username):
        error = "Username must be 3-32 characters: letters, digits, . _ - only."
    elif len(new_password) < 8:
        error = "Password must be at least 8 characters."
    elif new_password != confirm_password:
        error = "Passwords do not match."
    elif base_url and not re.match(r"^https?://", base_url):
        error = "Base URL must start with http:// or https://."
    if error:
        return templates.TemplateResponse(
            request, "auth/setup.html",
            _ctx(request, error=error, admin_username=admin_username,
                 site_name=site_name, base_url=base_url),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    admin = await _pending_admin(db)
    if admin is None:
        # Setup was completed by a concurrent request between the guard and here.
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)

    # The chosen name must not collide with another (registered) account.
    taken = (
        await db.execute(
            select(User).where(User.username == admin_username, User.id != admin.id)
        )
    ).scalars().first()
    if taken:
        return templates.TemplateResponse(
            request, "auth/setup.html",
            _ctx(request, error="That username is already taken.",
                 admin_username=admin_username, site_name=site_name, base_url=base_url),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    admin.username = admin_username
    admin.hashed_password = get_password_hash(new_password)
    admin.must_change_password = False
    await db.commit()

    values = {}
    if site_name:
        values["SITE_NAME"] = site_name
    if base_url:
        values["BASE_URL"] = base_url
    if values:
        await runtime_config.set_many(db, values)

    runtime_config.mark_setup_complete()

    res = RedirectResponse(url="/admin/", status_code=status.HTTP_302_FOUND)
    return _set_auth_cookie(res, admin.username)
