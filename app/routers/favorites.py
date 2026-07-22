"""Per-user gallery favorites.

The toggle endpoint returns the favorite-button partial for HTMX to swap in
place. Anonymous users are sent to the login page (HX-Redirect for HTMX
requests, a plain 302 otherwise) with ``next`` pointing back to where they
clicked.
"""
from typing import Iterable, Optional
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Query, Header, HTTPException
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import get_db
from app.models.gallery import Gallery
from app.models.associations import user_favorites
from app.utils.pagination import Pagination
from app.utils.seo import get_default_seo
from app.utils.templates import templates
from app.utils.db_utils import safe_execute_all

router = APIRouter()

BUTTON_VARIANTS = {"badge", "button"}


async def get_user_fav_ids(
    db: AsyncSession,
    user,
    gallery_ids: Iterable[int],
) -> set[int]:
    """Return the supplied gallery IDs favorited by ``user``."""
    if user is None:
        return set()
    gallery_ids = list(gallery_ids)
    if not gallery_ids:
        return set()
    rows = await db.execute(
        select(user_favorites.c.gallery_id).where(
            user_favorites.c.user_id == user.id,
            user_favorites.c.gallery_id.in_(gallery_ids),
        )
    )
    return set(rows.scalars().all())


def _login_redirect(request: Request) -> Response:
    next_url = request.headers.get("referer") or "/"
    login_url = f"/auth/login?next={quote(next_url, safe='')}"
    if request.headers.get("hx-request"):
        # htmx ignores Location on 302 for a swap; HX-Redirect does a full navigation.
        return Response(status_code=200, headers={"HX-Redirect": login_url})
    return RedirectResponse(login_url, status_code=302)


@router.post("/favorites/{gallery_id}/toggle")
async def toggle_favorite(
    request: Request,
    gallery_id: int,
    variant: str = Query("badge"),
    db: AsyncSession = Depends(get_db),
):
    user = request.state.user
    if user is None:
        return _login_redirect(request)

    gallery_exists = await db.scalar(
        select(Gallery.id).where(Gallery.id == gallery_id, Gallery.is_published == True)
    )
    if not gallery_exists:
        raise HTTPException(status_code=404, detail="Gallery not found")

    # Race-safe toggle: ON CONFLICT DO NOTHING tells us whether the row was
    # new, so concurrent double-clicks can't skew favorite_count.
    inserted = await db.execute(
        pg_insert(user_favorites)
        .values(user_id=user.id, gallery_id=gallery_id)
        .on_conflict_do_nothing()
    )
    if inserted.rowcount:
        is_favorited = True
        await db.execute(
            update(Gallery).where(Gallery.id == gallery_id)
            .values(favorite_count=Gallery.favorite_count + 1)
        )
    else:
        is_favorited = False
        deleted = await db.execute(
            delete(user_favorites).where(
                user_favorites.c.user_id == user.id,
                user_favorites.c.gallery_id == gallery_id,
            )
        )
        if deleted.rowcount:
            await db.execute(
                update(Gallery).where(Gallery.id == gallery_id)
                .values(favorite_count=func.greatest(Gallery.favorite_count - 1, 0))
            )
    await db.commit()

    favorite_count = await db.scalar(select(Gallery.favorite_count).where(Gallery.id == gallery_id)) or 0
    return templates.TemplateResponse(request, "partials/favorite_button.html", {
        "request": request,
        "gallery_id": gallery_id,
        "favorite_count": favorite_count,
        "is_favorited": is_favorited,
        "variant": variant if variant in BUTTON_VARIANTS else "badge",
    })


@router.get("/favorites")
async def favorites_page(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=10, le=50),
    hx_request: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    user = request.state.user
    if user is None:
        return RedirectResponse("/auth/login?next=/favorites", status_code=302)

    base_where = (
        (user_favorites.c.user_id == user.id)
        & (Gallery.is_published == True)
    )
    total_count = await db.scalar(
        select(func.count()).select_from(
            user_favorites.join(Gallery, user_favorites.c.gallery_id == Gallery.id)
        ).where(base_where)
    ) or 0
    pagination = Pagination(page, per_page, total_count)
    galleries = await safe_execute_all(
        db,
        select(Gallery)
        .join(user_favorites, user_favorites.c.gallery_id == Gallery.id)
        .where(base_where)
        .order_by(user_favorites.c.created_at.desc())
        .offset((pagination.page - 1) * per_page)
        .limit(per_page),
    )
    context = {
        "request": request,
        "galleries": galleries,
        "pagination": pagination,
        "per_page": per_page,
        "user_fav_ids": {g.id for g in galleries},
        "seo": get_default_seo("My Favorites"),
    }
    if hx_request:
        return templates.TemplateResponse(
            request, "partials/gallery_results.html", context,
            headers={"HX-Push-Url": f"/favorites?page={page}&per_page={per_page}"},
        )
    return templates.TemplateResponse(request, "pages/favorites.html", context)
