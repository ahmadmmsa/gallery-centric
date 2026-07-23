"""Merge one gallery into another.

The source gallery's pages are physically moved into the target's folder
(pure renames, no re-encoding), renumbered after the target's last page and
re-pointed in the database; taxonomies are optionally unioned. The source
gallery row and its leftover folder are then deleted.

Failure model: file moves happen before the DB commit. A crash mid-move
leaves the DB untouched with some files already relocated -- exactly the
orphaned-file / broken-page states the System Cleanup task already detects
and repairs, so no separate recovery mechanism exists here.
"""
import os
import shutil
import asyncio
import logging

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.gallery import Gallery, Page
from app.services import manifest_service


def _dedupe(items: list) -> list:
    return list(dict.fromkeys(items))


def _local(path: str | None) -> str | None:
    return path.lstrip("/") if path else None


async def _load_gallery(db: AsyncSession, gallery_id: int) -> Gallery:
    stmt = select(Gallery).where(Gallery.id == gallery_id).options(
        selectinload(Gallery.tags),
        selectinload(Gallery.artists),
        selectinload(Gallery.characters),
        selectinload(Gallery.parodies),
        selectinload(Gallery.pages),
    )
    gallery = (await db.execute(stmt)).scalars().first()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")
    return gallery


async def merge_galleries(
    db: AsyncSession, target_id: int, source_id: int, merge_metadata: bool = True
) -> dict:
    if target_id == source_id:
        raise HTTPException(status_code=400, detail="Cannot merge a gallery into itself")

    # Lock both rows in id order so concurrent merges/page edits serialize
    # without deadlocking (page deletion locks the gallery row the same way).
    for gallery_id in sorted((target_id, source_id)):
        locked = (
            await db.execute(
                select(Gallery.id).where(Gallery.id == gallery_id).with_for_update()
            )
        ).scalar_one_or_none()
        if locked is None:
            raise HTTPException(status_code=404, detail="Gallery not found")

    target = await _load_gallery(db, target_id)
    source = await _load_gallery(db, source_id)

    galleries_dir = os.path.join(settings.UPLOAD_DIR, "galleries")
    target_pages_dir = os.path.join(galleries_dir, target.slug, "pages")
    target_thumbs_dir = os.path.join(galleries_dir, target.slug, "page_thumbs")

    max_page = (
        await db.execute(
            select(func.max(Page.page_number)).where(Page.gallery_id == target_id)
        )
    ).scalar() or 0

    source_pages = sorted(source.pages, key=lambda p: p.page_number)

    def _plan_moves():
        """Resolve every source page to its new number and file destinations.
        Pages whose image file is missing on disk get None destinations and
        consume no page number, so the merged numbering stays gapless."""
        planned = []
        number = max_page
        for page in source_pages:
            old_image = _local(page.image_path)
            if not old_image or not os.path.exists(old_image):
                planned.append((page, None, None, None, None, None))
                continue
            number += 1
            ext = os.path.splitext(old_image)[1] or ".webp"
            new_image = os.path.join(
                target_pages_dir, f"{target.slug}_p{number:04d}{ext}"
            )
            old_thumb = _local(page.thumbnail_path)
            new_thumb = None
            if old_thumb and os.path.exists(old_thumb):
                thumb_ext = os.path.splitext(old_thumb)[1] or ".webp"
                new_thumb = os.path.join(
                    target_thumbs_dir, f"{target.slug}_p{number:04d}_thumb{thumb_ext}"
                )
            else:
                old_thumb = None
            planned.append((page, number, old_image, new_image, old_thumb, new_thumb))
        return planned

    planned = await asyncio.to_thread(_plan_moves)

    def _execute_moves():
        os.makedirs(target_pages_dir, exist_ok=True)
        os.makedirs(target_thumbs_dir, exist_ok=True)
        for _, _, old_image, new_image, old_thumb, new_thumb in planned:
            if old_image:
                shutil.move(old_image, new_image)
            if old_thumb:
                shutil.move(old_thumb, new_thumb)

    await asyncio.to_thread(_execute_moves)

    moved = 0
    skipped = 0
    for page, number, old_image, new_image, old_thumb, new_thumb in planned:
        if not old_image:
            # The source file is gone; dropping the record keeps the merged
            # gallery free of broken pages.
            await db.delete(page)
            skipped += 1
            continue
        page.gallery = target
        page.page_number = number
        page.image_path = "/" + new_image.replace(os.sep, "/")
        page.thumbnail_path = "/" + new_thumb.replace(os.sep, "/") if new_thumb else None
        moved += 1

    if merge_metadata:
        target.tags = _dedupe(list(target.tags) + list(source.tags))
        target.artists = _dedupe(list(target.artists) + list(source.artists))
        target.characters = _dedupe(list(target.characters) + list(source.characters))
        target.parodies = _dedupe(list(target.parodies) + list(source.parodies))
        if not target.description:
            target.description = source.description
        if not target.language_id:
            target.language_id = source.language_id
    target.view_count = (target.view_count or 0) + (source.view_count or 0)
    target.favorite_count = (target.favorite_count or 0) + (source.favorite_count or 0)
    target.page_count = max_page + moved

    source_slug = source.slug
    await db.flush()
    await db.delete(source)
    await db.commit()

    await manifest_service.write_manifest(db, target_id)

    source_dir = os.path.join(galleries_dir, source_slug)

    def _remove_source_dir():
        if os.path.isdir(source_dir):
            shutil.rmtree(source_dir, ignore_errors=True)

    await asyncio.to_thread(_remove_source_dir)

    logging.info(
        f"Merged gallery {source_id} into {target_id}: "
        f"{moved} pages moved, {skipped} skipped (missing files)"
    )
    return {
        "moved_pages": moved,
        "skipped_missing": skipped,
        "page_count": target.page_count,
    }
