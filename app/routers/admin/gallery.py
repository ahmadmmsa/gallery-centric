from typing import Optional, List, Any, Type
from fastapi import APIRouter, Request, Depends, Query, Form, Header, UploadFile, File, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
import os
import logging
import tempfile
import asyncio
import aiofiles

from app.database import get_db
from app.utils.auth import get_admin_user
from app.models.gallery import Gallery, Page
from app.models.tag import Tag
from app.models.artist import Artist
from app.models.character import Character
from app.models.parody import Parody
from app.models.language import Language

from app.schemas.admin import (
    GalleryCreateRequest, GalleryUpdateRequest, PageDeleteRequest,
    PageReorderRequest,
)
from app.services import image_service, zip_service, runtime_config, manifest_service, merge_service
from app.utils.pagination import Pagination
from app.utils.db_utils import safe_execute_all, safe_execute_first

from app.routers.admin.helpers import form_body, redirect_to, _gen_slug
from app.utils.templates import templates

gallery_router = APIRouter()

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

def _remove_files(paths) -> None:
    """Best-effort deletion of a collection of local file paths (sync; run in a thread)."""
    for path in paths:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


async def _delete_gallery_pages(
    db: AsyncSession,
    gallery_id: int,
    page_ids: set[int],
) -> tuple[int, int]:
    """Delete and renumber pages atomically while serializing gallery edits."""
    if not page_ids:
        raise HTTPException(status_code=400, detail="No pages selected")

    gallery = (
        await db.execute(
            select(Gallery).where(Gallery.id == gallery_id).with_for_update()
        )
    ).scalars().first()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")

    pages = list(
        (
            await db.execute(
                select(Page).where(
                    Page.gallery_id == gallery_id,
                    Page.id.in_(page_ids),
                )
            )
        ).scalars().all()
    )
    if len(pages) != len(page_ids):
        raise HTTPException(
            status_code=404,
            detail="One or more selected pages were not found in this gallery",
        )

    # A path is removable only if no surviving Page record references it in
    # either the full-image or thumbnail column.
    candidate_paths = {
        path
        for page in pages
        for path in (page.image_path, page.thumbnail_path)
        if path
    }
    surviving_paths: set[str] = set()
    if candidate_paths:
        path_rows = (
            await db.execute(
                select(Page.image_path, Page.thumbnail_path).where(
                    ~Page.id.in_(page_ids),
                    or_(
                        Page.image_path.in_(candidate_paths),
                        Page.thumbnail_path.in_(candidate_paths),
                    ),
                )
            )
        ).all()
        surviving_paths = {
            path
            for row in path_rows
            for path in row
            if path
        }

    for page in pages:
        await db.delete(page)
    await db.flush()

    remaining_pages = list(
        (
            await db.execute(
                select(Page)
                .where(Page.gallery_id == gallery_id)
                .order_by(Page.page_number, Page.id)
            )
        ).scalars().all()
    )
    for page_number, page in enumerate(remaining_pages, start=1):
        page.page_number = page_number
    gallery.page_count = len(remaining_pages)
    await db.commit()
    await manifest_service.write_manifest(db, gallery_id)

    paths_to_remove = {
        path.lstrip("/")
        for path in candidate_paths - surviving_paths
        if path.lstrip("/")
    }
    await asyncio.to_thread(_remove_files, paths_to_remove)
    return len(pages), len(remaining_pages)

async def _get_gallery_or_404(db: AsyncSession, gallery_id: int, options: list = None) -> Gallery:
    stmt = select(Gallery).where(Gallery.id == gallery_id)
    if options:
        stmt = stmt.options(*options)
    gallery = (await db.execute(stmt)).scalars().first()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")
    return gallery

async def _get_languages(db: AsyncSession):
    # Taxonomy pickers are htmx-driven; the form only needs the language list.
    return await safe_execute_all(db, select(Language).order_by(Language.name))

async def _fetch_relations(db: AsyncSession, model_class: Type[Any], ids: List[int]) -> List[Any]:
    if not ids:
        return []
    result = await db.execute(select(model_class).where(model_class.id.in_(ids)))
    return list(result.scalars().all())

async def _fetch_gallery_relations(db: AsyncSession, data):
    # Keep every ORM object attached to the gallery's request session.
    tags = await _fetch_relations(db, Tag, data.tag_ids)
    artists = await _fetch_relations(db, Artist, data.artist_ids)
    characters = await _fetch_relations(db, Character, data.character_ids)
    parodies = await _fetch_relations(db, Parody, data.parody_ids)
    return tags, artists, characters, parodies

@gallery_router.get("/galleries")
async def gallery_list(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=10, le=50),
    q: Optional[str] = Query(None),
    hx_request: Optional[str] = Header(None),
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    stmt = select(Gallery).order_by(Gallery.created_at.desc())
    count_stmt = select(func.count()).select_from(Gallery)
    if q:
        search_filter = Gallery.title.ilike(f"%{q}%")
        stmt = stmt.where(search_filter)
        count_stmt = count_stmt.where(search_filter)
    try:
        total_count = await db.scalar(count_stmt)
    except Exception:
        total_count = 0
    pagination = Pagination(page, per_page, total_count)
    stmt = stmt.offset((pagination.page - 1) * per_page).limit(per_page).options(
        selectinload(Gallery.tags),
        selectinload(Gallery.language),
        selectinload(Gallery.artists),
        selectinload(Gallery.characters),
        selectinload(Gallery.parodies)
    )
    galleries = await safe_execute_all(db, stmt)
    context = {
        "request": request,
        "admin": admin,
        "galleries": galleries,
        "pagination": pagination,
        "q": q,
        "per_page": per_page,
    }
    if hx_request:
        push_url = f"/admin/galleries?page={pagination.page}"
        if q:
            push_url += f"&q={q}"
        return templates.TemplateResponse(
            request, "admin/partials/gallery_results.html", context,
            headers={"HX-Push-Url": push_url},
        )
    return templates.TemplateResponse(request, "admin/gallery_list.html", context)

@gallery_router.get("/galleries/new")
async def gallery_new(
    request: Request,
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    languages = await _get_languages(db)
    context = {
        "request": request,
        "admin": admin,
        "languages": languages,
    }
    return templates.TemplateResponse(request, "admin/gallery_form.html", context)

@gallery_router.post("/galleries/new")
async def gallery_create(
    request: Request,
    data: GalleryCreateRequest = form_body(GalleryCreateRequest),
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    while True:
        slug = _gen_slug()
        stmt = select(Gallery.id).where(Gallery.slug == slug).limit(1)
        result = await db.execute(stmt)
        if not result.scalar_one_or_none():
            break
    tag_objs, artist_objs, character_objs, parody_objs = await _fetch_gallery_relations(db, data)

    gallery = Gallery(
        title=data.title,
        slug=slug,
        description=data.description,
        language_id=data.language_id,
        seo_title=data.seo_title or data.title,
        seo_description=data.seo_description,
        tags=tag_objs,
        artists=artist_objs,
        characters=character_objs,
        parodies=parody_objs
    )
    db.add(gallery)
    await db.commit()
    await db.refresh(gallery)
    await manifest_service.write_manifest(db, gallery.id)
    return RedirectResponse(url=f"/admin/galleries/{gallery.id}/edit", status_code=302)

@gallery_router.get("/galleries/{gallery_id}/edit")
async def gallery_edit(
    request: Request,
    gallery_id: int,
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    stmt = select(Gallery).where(Gallery.id == gallery_id).options(
        selectinload(Gallery.tags),
        selectinload(Gallery.artists),
        selectinload(Gallery.characters),
        selectinload(Gallery.parodies),
        selectinload(Gallery.pages),
        selectinload(Gallery.language)
    )
    result = await db.execute(stmt)
    gallery = result.scalars().first()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")
    languages = await _get_languages(db)
    context = {
        "request": request,
        "admin": admin,
        "gallery": gallery,
        "languages": languages,
    }
    return templates.TemplateResponse(request, "admin/gallery_form.html", context)

@gallery_router.post("/galleries/{gallery_id}/edit")
async def gallery_update(
    request: Request,
    gallery_id: int,
    data: GalleryUpdateRequest = form_body(GalleryUpdateRequest),
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    gallery = await _get_gallery_or_404(db, gallery_id, options=[
        selectinload(Gallery.tags),
        selectinload(Gallery.artists),
        selectinload(Gallery.characters),
        selectinload(Gallery.parodies)
    ])
    gallery.title = data.title
    gallery.description = data.description
    gallery.language_id = data.language_id
    gallery.seo_title = data.seo_title or data.title
    gallery.seo_description = data.seo_description
    gallery.tags, gallery.artists, gallery.characters, gallery.parodies = await _fetch_gallery_relations(db, data)
    await db.commit()
    await manifest_service.write_manifest(db, gallery.id)
    return RedirectResponse(url=f"/admin/galleries/{gallery.id}/edit", status_code=302)

@gallery_router.post("/galleries/{gallery_id}/delete")
async def gallery_delete(request: Request,gallery_id: int,admin = Depends(get_admin_user),db: AsyncSession = Depends(get_db)):
    gallery = await _get_gallery_or_404(db, gallery_id, options=[
        selectinload(Gallery.pages),
        selectinload(Gallery.tags),
        selectinload(Gallery.artists),
        selectinload(Gallery.characters),
        selectinload(Gallery.parodies)
    ])
    gallery_slug = gallery.slug

    await db.delete(gallery)
    await db.commit()
    if gallery_slug:
        from types import SimpleNamespace
        import logging
        try:
            await asyncio.to_thread(image_service.delete_gallery_files, SimpleNamespace(slug=gallery_slug))
            logging.info(f"Successfully deleted files for gallery: {gallery_slug}")
        except Exception as e:
            logging.error(f"Failed to delete files for gallery {gallery_slug}: {str(e)}")
    return redirect_to(request, "/admin/galleries")

@gallery_router.post("/galleries/{gallery_id}/publish")
async def gallery_publish(request: Request,gallery_id: int,admin = Depends(get_admin_user),db: AsyncSession = Depends(get_db)):
    gallery = await _get_gallery_or_404(db, gallery_id, options=[
        selectinload(Gallery.tags),
        selectinload(Gallery.artists),
        selectinload(Gallery.characters),
        selectinload(Gallery.parodies),
        selectinload(Gallery.language),
    ])
    gallery.is_published = True
    await db.commit()
    await manifest_service.write_manifest(db, gallery.id)

    if "hx-request" in request.headers:
        return templates.TemplateResponse(request, "admin/partials/publish_toggle.html", {"gallery": gallery})
    return RedirectResponse(url=f"/admin/galleries/{gallery.id}/edit", status_code=302)

@gallery_router.post("/galleries/{gallery_id}/unpublish")
async def gallery_unpublish(request: Request,gallery_id: int,admin = Depends(get_admin_user),db: AsyncSession = Depends(get_db)):
    gallery = await _get_gallery_or_404(db, gallery_id)
    gallery.is_published = False
    await db.commit()
    await manifest_service.write_manifest(db, gallery.id)

    if "hx-request" in request.headers:
        return templates.TemplateResponse(request, "admin/partials/publish_toggle.html", {"gallery": gallery})
    return RedirectResponse(url=f"/admin/galleries/{gallery.id}/edit", status_code=302)

@gallery_router.get("/galleries/{gallery_id}/upload")
async def gallery_upload_form(request: Request,gallery_id: int,admin = Depends(get_admin_user),db: AsyncSession = Depends(get_db)):
    gallery = await _get_gallery_or_404(db, gallery_id, options=[
        selectinload(Gallery.pages),
        selectinload(Gallery.language)
    ])
    context = {
        "request": request,
        "admin": admin,
        "gallery": gallery,
        "pages": gallery.pages
    }
    return templates.TemplateResponse(request, "admin/upload.html", context)

@gallery_router.post("/galleries/{gallery_id}/upload-zip")
async def gallery_upload_zip(
    request: Request,
    gallery_id: int,
    file: UploadFile = File(...),
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    gallery = await _get_gallery_or_404(db, gallery_id)
    max_page_result = await db.execute(
        select(func.max(Page.page_number)).where(Page.gallery_id == gallery_id)
    )
    start_page = (max_page_result.scalar() or 0) + 1
    CHUNK_SIZE = 1024 * 1024
    max_mb = runtime_config.max_upload_mb()
    max_bytes = max_mb * 1024 * 1024
    temp_zip_path = None
    try:
        # Create the temp path without holding a sync file handle, then stream
        # the upload to disk with aiofiles so writes don't block the event loop.
        fd, temp_zip_path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        total = 0
        async with aiofiles.open(temp_zip_path, "wb") as temp_zip:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail=f"Upload exceeds {max_mb} MB limit")
                await temp_zip.write(chunk)
        await zip_service.process_zip_upload(temp_zip_path, gallery, db, start_page=start_page)
        await db.commit()
        await manifest_service.write_manifest(db, gallery_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if temp_zip_path and await asyncio.to_thread(os.path.exists, temp_zip_path):
            await asyncio.to_thread(os.remove, temp_zip_path)
    return {"status": "success"}

@gallery_router.post("/galleries/{gallery_id}/upload-image")
async def gallery_upload_image(
    request: Request,
    gallery_id: int,
    file: UploadFile = File(...),
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    gallery = await db.get(Gallery, gallery_id)
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")
    max_page_result = await db.execute(select(func.max(Page.page_number)).where(Page.gallery_id == gallery_id))
    max_page = max_page_result.scalar() or 0
    page_number = max_page + 1
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported file type. Allowed: JPEG, PNG, WebP, GIF.")
    try:
        file.file.seek(0)
        file_data = await file.read()
        max_mb = runtime_config.max_upload_mb()
        if len(file_data) > max_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"Upload exceeds {max_mb} MB limit")
        image_path, width, height = await image_service.process_page(
            file_data, gallery.slug, page_number
        )
        thumb_path = await image_service.generate_page_thumbnail(
            file_data, gallery.slug, page_number
        )
        page = Page(
            gallery_id=gallery_id,
            page_number=page_number,
            image_path=image_path,
            thumbnail_path=thumb_path,
            image_width=width,
            image_height=height
        )
        db.add(page)
        gallery.page_count = page_number
        if page_number == 1 or not gallery.thumbnail_path or not gallery.cover_path:
            gallery.cover_path = await image_service.generate_cover(file_data, gallery.slug)
            gallery.thumbnail_path = await image_service.generate_thumbnail(file_data, gallery.slug)
        await db.commit()
        await manifest_service.write_manifest(db, gallery_id)
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logging.error(f"Upload Image Error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "page_number": page_number}

@gallery_router.get("/galleries/merge-search")
async def gallery_merge_search(
    request: Request,
    q: str = Query(""),
    exclude: int = Query(0),
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    results = []
    if q.strip():
        stmt = (
            select(Gallery)
            .where(Gallery.title.ilike(f"%{q}%"), Gallery.id != exclude)
            .order_by(Gallery.title)
            .limit(8)
        )
        results = await safe_execute_all(db, stmt)
    return templates.TemplateResponse(
        request, "admin/partials/merge_search_results.html",
        {"request": request, "results": results},
    )

@gallery_router.post("/galleries/{gallery_id}/merge")
async def gallery_merge(
    request: Request,
    gallery_id: int,
    source_id: int = Form(...),
    merge_metadata: Optional[str] = Form(None),
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    await merge_service.merge_galleries(
        db, gallery_id, source_id, merge_metadata=bool(merge_metadata)
    )
    return redirect_to(request, f"/admin/galleries/{gallery_id}/edit")

@gallery_router.post("/galleries/{gallery_id}/pages/reorder")
async def pages_reorder(
    request: Request,
    gallery_id: int,
    data: PageReorderRequest,
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    stmt = select(Page).where(Page.gallery_id == gallery_id).order_by(Page.page_number)
    result = await db.execute(stmt)
    pages = list(result.scalars().all())
    target_page = await db.get(Page, data.page_id)
    if not target_page or target_page.gallery_id != gallery_id:
        raise HTTPException(status_code=404, detail="Page not found")
    pages = [p for p in pages if p.id != target_page.id]
    new_idx = max(0, min(data.new_page_number - 1, len(pages)))
    pages.insert(new_idx, target_page)
    for index, p in enumerate(pages, start=1):
        p.page_number = index
    await db.commit()
    await manifest_service.write_manifest(db, gallery_id)
    return {"status": "success"}

@gallery_router.delete("/pages/{page_id}")
async def page_delete(
    request: Request,
    page_id: int,
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    gallery_id = await db.scalar(select(Page.gallery_id).where(Page.id == page_id))
    if gallery_id is None:
        raise HTTPException(status_code=404, detail="Page not found")
    deleted_count, page_count = await _delete_gallery_pages(
        db, gallery_id, {page_id}
    )
    return {
        "status": "success",
        "deleted_count": deleted_count,
        "page_count": page_count,
    }


@gallery_router.delete("/galleries/{gallery_id}/pages")
async def pages_delete(
    request: Request,
    gallery_id: int,
    data: PageDeleteRequest,
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    deleted_count, page_count = await _delete_gallery_pages(
        db, gallery_id, set(data.page_ids)
    )
    return {
        "status": "success",
        "deleted_count": deleted_count,
        "page_count": page_count,
    }

@gallery_router.get("/galleries/{gallery_id}/deduplicate/scan")
async def scan_gallery_duplicates_route(
    request: Request,
    gallery_id: int,
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    stmt = select(Gallery).where(Gallery.id == gallery_id).options(selectinload(Gallery.pages))
    result = await db.execute(stmt)
    gallery = result.scalars().first()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")
    duplicate_groups = await asyncio.to_thread(image_service.scan_gallery_duplicates, gallery.pages)
    total_duplicates = sum(len(g["duplicates"]) for g in duplicate_groups)
    return templates.TemplateResponse(
        request,
        "admin/partials/duplicate_results.html",
        {
            "gallery": gallery,
            "duplicate_groups": duplicate_groups,
            "total_duplicates": total_duplicates
        }
    )

@gallery_router.post("/galleries/{gallery_id}/deduplicate/remove")
async def remove_gallery_duplicates_route(
    request: Request, gallery_id: int, 
    admin = Depends(get_admin_user), 
    db: AsyncSession = Depends(get_db)
    ):
    stmt = select(Gallery).where(Gallery.id == gallery_id).options(selectinload(Gallery.pages))
    result = await db.execute(stmt)
    gallery = result.scalars().first()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")
    duplicate_groups = await asyncio.to_thread(image_service.scan_gallery_duplicates, gallery.pages)
    if not duplicate_groups:
        return Response(headers={"HX-Refresh": "true"})
    pages_to_delete = []
    for group in duplicate_groups:
        pages_to_delete.extend(group["duplicates"])
    surviving_pages = [p for p in gallery.pages if p not in pages_to_delete]
    surviving_image_paths = {p.image_path for p in surviving_pages if p.image_path}
    surviving_thumb_paths = {p.thumbnail_path for p in surviving_pages if p.thumbnail_path}
    paths_to_remove = set()
    for page in pages_to_delete:
        if page.image_path:
            local_img_path = page.image_path.lstrip('/')
            if local_img_path and page.image_path not in surviving_image_paths:
                paths_to_remove.add(local_img_path)
        if page.thumbnail_path:
            local_thumb_path = page.thumbnail_path.lstrip('/')
            if local_thumb_path and page.thumbnail_path not in surviving_thumb_paths:
                paths_to_remove.add(local_thumb_path)
        await db.delete(page)
    await db.commit()
    stmt = select(Page).where(Page.gallery_id == gallery_id).order_by(Page.page_number)
    result = await db.execute(stmt)
    remaining_pages = list(result.scalars().all())
    for index, p in enumerate(remaining_pages, start=1):
        p.page_number = index
    gallery.page_count = len(remaining_pages)
    await db.commit()
    await manifest_service.write_manifest(db, gallery_id)
    await asyncio.to_thread(_remove_files, paths_to_remove)
    return Response(headers={"HX-Refresh": "true"})
