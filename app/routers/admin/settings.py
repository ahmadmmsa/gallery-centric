"""Admin pages for DB-backed runtime configuration.

Two pages, both editing rows in ``app_settings`` via ``runtime_config``:

* ``/admin/settings`` -- Site Settings (site name, description).
* ``/admin/seo``      -- SEO / social meta tags (Open Graph, Twitter, etc.).
"""
from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.utils.auth import get_admin_user
from app.utils.templates import templates
from app.services import runtime_config
from app.routers.admin.helpers import redirect_to, _get_form_data

settings_router = APIRouter()

# Keys owned by each page. Every key must exist in runtime_config.DEFAULTS.
SITE_KEYS = ("SITE_NAME", "SITE_DESCRIPTION")
SEO_KEYS = (
    "SEO_KEYWORDS", "SEO_ROBOTS", "SEO_THEME_COLOR", "SEO_DEFAULT_IMAGE",
    "SEO_OG_SITE_NAME", "SEO_FB_APP_ID", "SEO_FB_PAGES",
    "SEO_TWITTER_CARD", "SEO_TWITTER_SITE", "SEO_TWITTER_CREATOR",
)


def _values(keys) -> dict:
    return {k: runtime_config.get(k, "") for k in keys}


@settings_router.get("/settings")
async def site_settings_page(request: Request, admin=Depends(get_admin_user)):
    return templates.TemplateResponse(request, "admin/site_settings.html", {
        "request": request,
        "admin": admin,
        "values": _values(SITE_KEYS),
        "saved": request.query_params.get("saved") == "1",
    })


@settings_router.post("/settings")
async def site_settings_save(request: Request, admin=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    form = await _get_form_data(request)
    await runtime_config.set_many(db, {k: form.get(k, "") for k in SITE_KEYS})
    return redirect_to(request, "/admin/settings?saved=1")


@settings_router.get("/seo")
async def seo_page(request: Request, admin=Depends(get_admin_user)):
    return templates.TemplateResponse(request, "admin/seo_manager.html", {
        "request": request,
        "admin": admin,
        "values": _values(SEO_KEYS),
        "saved": request.query_params.get("saved") == "1",
    })


@settings_router.post("/seo")
async def seo_save(request: Request, admin=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    form = await _get_form_data(request)
    await runtime_config.set_many(db, {k: form.get(k, "") for k in SEO_KEYS})
    return redirect_to(request, "/admin/seo?saved=1")
