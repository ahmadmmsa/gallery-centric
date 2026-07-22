from typing import Optional, Any
from fastapi import APIRouter, Request, Depends, Query, Header
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload
from urllib.parse import unquote, urlencode
from app.database import get_db
from app.models.gallery import Gallery, Page
from app.models.tag import Tag, TagType
from app.models.artist import Artist
from app.models.character import Character
from app.models.parody import Parody
from app.routers.favorites import get_user_fav_ids
from app.services import search_service
from app.utils.pagination import Pagination
from app.utils.seo import get_gallery_seo, get_default_seo
from app.utils.db_utils import safe_execute_all, safe_execute_first
from app.utils.templates import templates

router = APIRouter()

def _render_404(request: Request) -> templates.TemplateResponse:
    return templates.TemplateResponse(request, "pages/404.html", {"request": request, "seo": get_default_seo("Not Found")}, status_code=404)

def _apply_gallery_sort(stmt, sort: str):
    if sort == "views": return stmt.order_by(Gallery.view_count.desc())
    if sort == "favorites": return stmt.order_by(Gallery.favorite_count.desc())
    if sort == "alpha": return stmt.order_by(Gallery.title.asc())
    return stmt.order_by(Gallery.created_at.desc())

async def _handle_taxonomy_redirect(request: Request, db: AsyncSession, model: Any, slug: str, prefix: str = ""):
    item = await safe_execute_first(db, select(model).where(model.slug == slug))
    if not item: return _render_404(request)
    formatted = item.name.replace(" ", "_")
    url = f"/tags/?{prefix}:{formatted}" if prefix else f"/tags/?{formatted}"
    return RedirectResponse(url=url, status_code=301)

@router.get("/")
async def home(request: Request, page: int = Query(1, ge=1), per_page: int = Query(20, ge=10, le=50), sort: str = Query("latest"), hx_request: Optional[str] = Header(None), db: AsyncSession = Depends(get_db)):
    stmt = _apply_gallery_sort(select(Gallery).where(Gallery.is_published == True), sort)
    total_count = await db.scalar(select(func.count()).select_from(Gallery).where(Gallery.is_published == True)) or 0
    pagination = Pagination(page, per_page, total_count)
    galleries = await safe_execute_all(db, stmt.offset((pagination.page - 1) * per_page).limit(per_page).options(selectinload(Gallery.tags)))
    context = {"request": request, "galleries": galleries, "pagination": pagination, "sort": sort, "per_page": per_page, "user_fav_ids": await get_user_fav_ids(db, request.state.user, [g.id for g in galleries]), "seo": get_default_seo("Home")}
    if hx_request: return templates.TemplateResponse(request, "partials/gallery_results.html", context, headers={"HX-Push-Url": f"/?page={page}&per_page={per_page}&sort={sort}"}, status_code=200)
    return templates.TemplateResponse(request, "pages/home.html", context, status_code=200)

@router.get("/gallery/{slug}")
async def gallery_detail(request: Request, slug: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Gallery).where(Gallery.slug == slug, Gallery.is_published == True).options(selectinload(Gallery.tags).selectinload(Tag.tag_type), selectinload(Gallery.artists), selectinload(Gallery.characters), selectinload(Gallery.parodies), selectinload(Gallery.language), selectinload(Gallery.pages))
    gallery = await safe_execute_first(db, stmt)
    if not gallery: return _render_404(request)
    # Atomic increment to avoid lost updates under concurrent views.
    await db.execute(update(Gallery).where(Gallery.id == gallery.id).values(view_count=Gallery.view_count + 1))
    await db.commit()
    gallery.view_count += 1  # reflect the increment for rendering (raw UPDATE bypasses the ORM)
    related = []
    if gallery.tags:
        tag_ids = [t.id for t in gallery.tags]
        related = await safe_execute_all(db, select(Gallery).where(Gallery.is_published == True, Gallery.id != gallery.id, Gallery.tags.any(Tag.id.in_(tag_ids))).order_by(Gallery.created_at.desc()).limit(8).options(selectinload(Gallery.tags)))
    context = {"request": request, "gallery": gallery, "pages": sorted(gallery.pages, key=lambda p: p.page_number), "related_galleries": related, "is_favorited": gallery.id in await get_user_fav_ids(db, request.state.user, [gallery.id]), "seo": get_gallery_seo(gallery)}
    return templates.TemplateResponse(request, "pages/gallery_detail.html", context)

@router.get("/read/{slug}")
async def reader(request: Request, slug: str, db: AsyncSession = Depends(get_db)):
    gallery = await safe_execute_first(db, select(Gallery).where(Gallery.slug == slug, Gallery.is_published == True).options(selectinload(Gallery.pages)))
    if not gallery: return _render_404(request)
    context = {"request": request, "gallery": gallery, "pages": gallery.pages, "seo": get_gallery_seo(gallery)}
    return templates.TemplateResponse(request, "pages/reader.html", context)

@router.get("/search")
async def search_results(request: Request, q: str = Query(""), tags: Optional[str] = Query(None), artists: Optional[str] = Query(None), characters: Optional[str] = Query(None), parodies: Optional[str] = Query(None), language: Optional[str] = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=10, le=50), sort: str = Query("created_at:desc"), hx_request: Optional[str] = Header(None), db: AsyncSession = Depends(get_db)):
    include_tags = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    artist_list = [a.strip() for a in artists.split(",") if a.strip()] if artists else None
    char_list = [c.strip() for c in characters.split(",") if c.strip()] if characters else None
    parody_list = [p.strip() for p in parodies.split(",") if p.strip()] if parodies else None
    sort_map = {'latest': 'created_at:desc', 'views': 'view_count:desc', 'favorites': 'favorite_count:desc', 'alpha': 'title:asc'}
    results = await search_service.search(db=db, query=q, include_tags=include_tags, artists=artist_list, characters=char_list, parodies=parody_list, language=language, sort=sort_map.get(sort, sort), page=page, per_page=per_page)
    pagination = Pagination(page, per_page, results.total_hits)
    context = {"request": request, "results": results, "galleries": results.hits, "pagination": pagination, "q": q, "sort": sort, "per_page": per_page, "tags": tags, "artists": artists, "characters": characters, "parodies": parodies, "language": language, "user_fav_ids": await get_user_fav_ids(db, request.state.user, [hit["id"] for hit in results.hits]), "seo": get_default_seo("Search Results")}
    if hx_request:
        query_params = {"page": page}
        for k, v in [("q", q), ("tags", tags), ("artists", artists), ("characters", characters), ("parodies", parodies), ("language", language)]:
            if v: query_params[k] = v
        if sort and sort != "latest": query_params["sort"] = sort
        if per_page and per_page != 20: query_params["per_page"] = per_page
        return templates.TemplateResponse(request, "partials/gallery_results.html", context, headers={"HX-Push-Url": f"/search?{urlencode(query_params)}"})
    return templates.TemplateResponse(request, "pages/search_results.html", context)

@router.get("/tag/{slug}")
async def tag_page(request: Request, slug: str, db: AsyncSession = Depends(get_db)):
    return await _handle_taxonomy_redirect(request, db, Tag, slug)

@router.get("/artist/{slug}")
async def artist_page(request: Request, slug: str, db: AsyncSession = Depends(get_db)):
    return await _handle_taxonomy_redirect(request, db, Artist, slug, "artist")

@router.get("/character/{slug}")
async def character_page(request: Request, slug: str, db: AsyncSession = Depends(get_db)):
    return await _handle_taxonomy_redirect(request, db, Character, slug, "character")

@router.get("/parody/{slug}")
async def parody_page(request: Request, slug: str, db: AsyncSession = Depends(get_db)):
    return await _handle_taxonomy_redirect(request, db, Parody, slug, "parody")

@router.get("/tags")
@router.get("/tags/")
async def tags_search(request: Request, page: int = Query(1, ge=1), per_page: int = Query(20, ge=10, le=50), sort: str = Query("latest"), hx_request: Optional[str] = Header(None), db: AsyncSession = Depends(get_db)):
    query_str = unquote(request.url.query)
    tag_queries = []
    for part in [p.strip() for p in query_str.split("&") if p.strip()]:
        if "=" in part:
            k, v = part.split("=", 1)
            if k == "sort": sort = v
            elif k == "page": page = int(v) if v.isdigit() else page
            elif k == "per_page": per_page = int(v) if v.isdigit() else per_page
            elif k == "tags": tag_queries.extend([t.strip() for t in v.split(" ") if t.strip()])
        else: tag_queries.extend([t.strip() for t in part.split(" ") if t.strip()])
    active_tags = []
    for tag_q in tag_queries:
        tag_q_norm = tag_q.replace("_", " ")
        found_tag = (await db.execute(select(Tag).where(Tag.name == tag_q_norm).options(selectinload(Tag.tag_type)))).scalars().first()
        if found_tag: active_tags.append(found_tag)
        else:
            if ":" in tag_q_norm:
                t_type, _ = tag_q_norm.split(":", 1)
                color = {"artist": "#6f42c1", "character": "#198754", "parody": "#dc3545"}.get(t_type, "#6c757d")
                dt = Tag(name=tag_q_norm, slug=tag_q.replace(':', '-'), description=None, gallery_count=0)
                dt.tag_type = TagType(name=t_type, slug=t_type, color=color)
                active_tags.append(dt)
            else: active_tags.append(Tag(name=tag_q_norm, slug=tag_q, description=None, gallery_count=0))
    stmt = select(Gallery).where(Gallery.is_published == True)
    count_stmt = select(func.count()).select_from(Gallery).where(Gallery.is_published == True)
    for tag_q in tag_queries:
        tag_q_norm = tag_q.replace("_", " ")
        if ":" in tag_q_norm:
            t_type, t_val = tag_q_norm.split(":", 1)
            if t_type == "artist":
                stmt, count_stmt = stmt.where(Gallery.artists.any(Artist.name == t_val)), count_stmt.where(Gallery.artists.any(Artist.name == t_val))
            elif t_type == "character":
                stmt, count_stmt = stmt.where(Gallery.characters.any(Character.name == t_val)), count_stmt.where(Gallery.characters.any(Character.name == t_val))
            elif t_type == "parody":
                stmt, count_stmt = stmt.where(Gallery.parodies.any(Parody.name == t_val)), count_stmt.where(Gallery.parodies.any(Parody.name == t_val))
            else:
                stmt, count_stmt = stmt.where(Gallery.tags.any(Tag.name == tag_q_norm)), count_stmt.where(Gallery.tags.any(Tag.name == tag_q_norm))
        else:
            stmt, count_stmt = stmt.where(Gallery.tags.any(Tag.name.ilike(f"%{tag_q_norm}%"))), count_stmt.where(Gallery.tags.any(Tag.name.ilike(f"%{tag_q_norm}%")))
    stmt = _apply_gallery_sort(stmt, sort)
    total_count = await db.scalar(count_stmt) or 0
    pagination = Pagination(page, per_page, total_count)
    galleries = await safe_execute_all(db, stmt.offset((pagination.page - 1) * per_page).limit(per_page).options(selectinload(Gallery.tags).selectinload(Tag.tag_type)))
    import urllib.parse
    active_tags_data = [{"tag": t, "remove_url": f"/tags/?{urllib.parse.quote(' '.join([q for q in tag_queries if q.replace('_', ' ').lower() != t.name.lower()]))}" if [q for q in tag_queries if q.replace("_", " ").lower() != t.name.lower()] else "/tags/"} for t in active_tags]
    tags_query_val = " ".join(tag_queries)
    context = {"request": request, "active_tags_data": active_tags_data, "tags_query_val": tags_query_val, "tags": tags_query_val, "galleries": galleries, "pagination": pagination, "sort": sort, "per_page": per_page, "user_fav_ids": await get_user_fav_ids(db, request.state.user, [g.id for g in galleries]), "seo": get_default_seo("Search by Tags")}
    if hx_request: return templates.TemplateResponse(request, "partials/gallery_results.html", context, headers={"HX-Push-Url": f"/tags/?{query_str}"})
    return templates.TemplateResponse(request, "pages/tags_search.html", context)

@router.get("/api/tags/autocomplete")
async def tags_autocomplete(q: str = Query(""), type: Optional[str] = Query(None), db: AsyncSession = Depends(get_db)):
    if not q: return []
    q_norm = q.replace("_", " ")
    model_map = {"artist": Artist, "character": Character, "parody": Parody}
    if type in model_map:
        model = model_map[type]
        items = (await db.execute(select(model).where(model.name.ilike(f"{q_norm}%")).limit(10))).scalars().all()
        return [{"name": f"{type}:{i.name}", "value": i.name, "formatted": f"{type}:{i.name.replace(' ', '_')}"} for i in items]
    if type == "tag-type":
        items = (await db.execute(select(TagType).where(TagType.name.ilike(f"{q_norm}%")).limit(10))).scalars().all()
        return [{"name": i.name, "value": i.name, "formatted": i.name} for i in items]
    tags = (await db.execute(select(Tag).where(Tag.name.ilike(f"%{q_norm}%")).limit(10))).scalars().all()
    return [{"name": t.name, "value": t.name.split(":", 1)[-1], "formatted": t.name.replace(" ", "_")} for t in tags]
