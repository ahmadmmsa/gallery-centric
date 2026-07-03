"""Admin pages for DB-backed runtime configuration.

Two pages, both editing rows in ``app_settings`` via ``runtime_config``:

* ``/admin/settings`` -- Site Settings (site name, description).
* ``/admin/seo``      -- SEO / social meta tags (Open Graph, Twitter, etc.).
"""
import os
import time
from typing import Optional

import aiofiles
from fastapi import APIRouter, Request, Depends
from starlette.datastructures import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
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
    "SEO_FAVICON",
    "SEO_OG_SITE_NAME", "SEO_FB_APP_ID", "SEO_FB_PAGES",
    "SEO_TWITTER_CARD", "SEO_TWITTER_SITE", "SEO_TWITTER_CREATOR",
)

FAVICON_EXTENSIONS = {".ico", ".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp"}
FAVICON_MAX_BYTES = 1024 * 1024  # favicons are tiny; 1 MB is already generous


async def _save_favicon(upload: UploadFile) -> Optional[str]:
    """Store the uploaded favicon under uploads/site/ and return its URL.

    Returns None if the file type or size is not acceptable. The URL carries a
    version query string so browsers pick up a replacement immediately.
    """
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in FAVICON_EXTENSIONS:
        return None
    data = await upload.read()
    if not data or len(data) > FAVICON_MAX_BYTES:
        return None

    site_dir = os.path.join(app_settings.UPLOAD_DIR, "site")
    os.makedirs(site_dir, exist_ok=True)
    # Drop any previous favicon so a replacement with a new extension can't
    # leave a stale file behind.
    for name in os.listdir(site_dir):
        if name.startswith("favicon."):
            os.remove(os.path.join(site_dir, name))
    async with aiofiles.open(os.path.join(site_dir, f"favicon{ext}"), "wb") as fh:
        await fh.write(data)
    return f"/{app_settings.UPLOAD_DIR}/site/favicon{ext}?v={int(time.time())}"


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
        "favicon_error": request.query_params.get("error") == "favicon",
    })


@settings_router.post("/seo")
async def seo_save(request: Request, admin=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    form = await _get_form_data(request)
    # SEO_FAVICON is file-backed, not a text field: leave the stored value
    # alone unless a new file is uploaded or removal is requested.
    values = {k: form.get(k, "") for k in SEO_KEYS if k != "SEO_FAVICON"}

    upload = form.get("favicon")
    if isinstance(upload, UploadFile) and upload.filename:
        favicon_url = await _save_favicon(upload)
        if favicon_url is None:
            return redirect_to(request, "/admin/seo?error=favicon")
        values["SEO_FAVICON"] = favicon_url
    elif form.get("remove_favicon"):
        values["SEO_FAVICON"] = ""
        site_dir = os.path.join(app_settings.UPLOAD_DIR, "site")
        if os.path.isdir(site_dir):
            for name in os.listdir(site_dir):
                if name.startswith("favicon."):
                    os.remove(os.path.join(site_dir, name))

    await runtime_config.set_many(db, values)
    return redirect_to(request, "/admin/seo?saved=1")
