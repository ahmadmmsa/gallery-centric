"""Bulk Import: turn folders dropped into media/imports/ into draft galleries.

Folder names are parsed for metadata: text in the first ``[...]`` or ``(...)``
group is the artist, every later bracket group becomes a ``misc:<text>`` tag,
and whatever sits outside brackets (stripped of special characters) is the
gallery title. Loose images at the imports root are appended to a gallery
titled "misc". Everything imports as an unpublished draft; source folders are
deleted only after their gallery was fully processed.

Runs as a BackgroundTask with its own sessions and reports progress through
``media/bulk_import_status.json`` (same pattern as maintenance/restore).
"""
import os
import re
import json
import uuid
import asyncio
import logging

import aiofiles
from sqlalchemy import select, func

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.gallery import Gallery, Page
from app.models.artist import Artist
from app.services import zip_service, image_service, manifest_service

STATUS_FILE = os.path.join(settings.UPLOAD_DIR, "bulk_import_status.json")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
BRACKET_RE = re.compile(r"\[([^\]]*)\]|\(([^)]*)\)")
MISC_GALLERY_TITLE = "misc"
MISC_TAG_TYPE = "misc"

# Special `target` values for run_bulk_import_task; anything else is a folder name.
ALL_TARGET = "__all__"
ROOT_TARGET = "__root__"


def _imports_dir() -> str:
    return os.path.join(settings.UPLOAD_DIR, "imports")


def _split_group(content: str) -> tuple[str, list[str]]:
    """Split one bracket group's content into (remainder, nested groups).

    ``Vincent-van-Gogh(Dark)`` -> ("Vincent-van-Gogh", ["Dark"]).
    """
    nested = [(a or b).strip() for a, b in BRACKET_RE.findall(content)]
    nested = [g for g in nested if g]
    remainder = BRACKET_RE.sub(" ", content)
    remainder = re.sub(r"\s+", " ", remainder).strip()
    return remainder, nested


def _normalize_name(text: str) -> str:
    """Collapse separator characters so "Vincent-van-Gogh" and
    "Vincent van Gogh" resolve to the same artist/tag."""
    return re.sub(r"\s+", " ", re.sub(r"[-_]+", " ", text)).strip()


def parse_folder_name(name: str) -> dict:
    """Split a folder name into title / artist / misc tags.

    The first ``[...]`` or ``(...)`` group is the artist; every later group is
    a tag. A group nested inside another ("[Artist(Dark)]") contributes its
    inner groups as tags. Text outside brackets, stripped of special
    characters, is the title.

    ``[Vincent van Gogh]The Starry Night (1889)`` ->
    title "The Starry Night", artist "Vincent van Gogh", tags ["1889"].
    ``The Potato Eaters [Vincent-van-Gogh(Dark)] (1885)`` ->
    title "The Potato Eaters", artist "Vincent van Gogh", tags ["Dark", "1885"].
    """
    groups = [(a or b).strip() for a, b in BRACKET_RE.findall(name)]
    groups = [g for g in groups if g]

    artist = None
    tags = []
    for index, group in enumerate(groups):
        remainder, nested = _split_group(group)
        if index == 0:
            artist = _normalize_name(remainder) or None
        elif remainder:
            tags.append(_normalize_name(remainder))
        tags.extend(_normalize_name(n) for n in nested)
    tags = list(dict.fromkeys(t for t in tags if t))

    title = BRACKET_RE.sub(" ", name)
    title = re.sub(r"[^\w\s'-]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return {
        "title": title or name.strip(),
        "artist": artist,
        "tags": tags,
    }


def validate_target(target: str) -> bool:
    """A target is a special value or the plain name of a direct subfolder."""
    if target in (ALL_TARGET, ROOT_TARGET):
        return True
    if not target or "/" in target or "\\" in target or target in (".", ".."):
        return False
    return os.path.isdir(os.path.join(_imports_dir(), target))


def _is_image(file_name: str) -> bool:
    return (
        file_name.lower().endswith(IMAGE_EXTENSIONS)
        and not file_name.startswith("._")
        and not file_name.startswith(".")
    )


async def scan() -> dict:
    """Preview what a bulk import would do: parsed folders + loose root images."""
    def _scan():
        imports_dir = _imports_dir()
        os.makedirs(imports_dir, exist_ok=True)
        folders = []
        root_images = 0
        for entry in sorted(os.scandir(imports_dir), key=lambda e: e.name.lower()):
            if entry.is_dir():
                image_count = sum(
                    1 for _, _, files in os.walk(entry.path)
                    for f in files if _is_image(f)
                )
                folders.append({
                    "folder": entry.name,
                    "image_count": image_count,
                    **parse_folder_name(entry.name),
                })
            elif entry.is_file() and _is_image(entry.name):
                root_images += 1
        return {"folders": folders, "root_images": root_images}

    return await asyncio.to_thread(_scan)


async def _write_status(status: str, summary: dict = None, error: str = None):
    data = {"status": status, "summary": summary or {}, "error": error}

    def _sync_write():
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        with open(STATUS_FILE, "w") as f:
            json.dump(data, f)

    await asyncio.to_thread(_sync_write)


async def get_bulk_import_status() -> dict:
    if not await asyncio.to_thread(os.path.exists, STATUS_FILE):
        return {"status": "idle"}
    try:
        def _read():
            with open(STATUS_FILE, "r") as f:
                return json.load(f)
        return await asyncio.to_thread(_read)
    except Exception:
        return {"status": "idle"}


async def run_bulk_import_task(target: str):
    """Entry point for BackgroundTasks which manages its own db sessions."""
    try:
        await _write_status("running")
        summary = {
            "imported_galleries": 0,
            "imported_pages": 0,
            "root_images_added": 0,
            "failed": [],
        }
        data = await scan()
        if target == ALL_TARGET:
            folders = [f["folder"] for f in data["folders"]]
            include_root = data["root_images"] > 0
        elif target == ROOT_TARGET:
            folders = []
            include_root = True
        else:
            folders = [target]
            include_root = False

        for folder in folders:
            try:
                page_count = await _import_folder(folder)
                summary["imported_galleries"] += 1
                summary["imported_pages"] += page_count
            except Exception as e:
                logging.exception(f"Bulk import failed for folder {folder}")
                summary["failed"].append({"folder": folder, "reason": str(e)})

        if include_root:
            try:
                summary["root_images_added"] = await _import_root_images()
            except Exception as e:
                logging.exception("Bulk import failed for loose root images")
                summary["failed"].append({"folder": "(loose images)", "reason": str(e)})

        await _write_status("completed", summary=summary)
    except Exception as e:
        logging.exception("Bulk import task failed")
        await _write_status("error", error=str(e))


async def _unique_slug(db) -> str:
    while True:
        slug = uuid.uuid4().hex[:8]
        exists = (
            await db.execute(select(Gallery.id).where(Gallery.slug == slug).limit(1))
        ).scalar_one_or_none()
        if not exists:
            return slug


async def _import_folder(folder_name: str) -> int:
    """Create a draft gallery from one imports subfolder. Returns page count."""
    folder_path = os.path.join(_imports_dir(), folder_name)
    if not await asyncio.to_thread(os.path.isdir, folder_path):
        raise ValueError("folder not found")
    parsed = parse_folder_name(folder_name)
    cache: dict = {}
    async with AsyncSessionLocal() as db:
        gallery = Gallery(
            title=parsed["title"],
            slug=await _unique_slug(db),
            is_published=False,
        )
        if parsed["artist"]:
            gallery.artists = [
                await manifest_service._get_or_create(db, Artist, parsed["artist"], cache)
            ]
        gallery.tags = [
            await manifest_service._get_or_create_tag(
                db, cache, {"name": f"{MISC_TAG_TYPE}:{tag}", "type": MISC_TAG_TYPE}
            )
            for tag in parsed["tags"]
        ]
        db.add(gallery)
        await db.flush()
        # Converts every image to a webp page, sets cover/thumbnail, then
        # deletes the source folder; raises without deleting when it fails.
        await zip_service.process_import_folder(folder_path, gallery, db, start_page=1)
        await db.commit()
        await manifest_service.write_manifest(db, gallery.id)
        return gallery.page_count or 0


async def _import_root_images() -> int:
    """Append loose images at the imports root to the "misc" draft gallery."""
    imports_dir = _imports_dir()

    def _list_images():
        return sorted(
            (
                f for f in os.listdir(imports_dir)
                if os.path.isfile(os.path.join(imports_dir, f)) and _is_image(f)
            ),
            key=zip_service.natural_sort_key,
        )

    file_names = await asyncio.to_thread(_list_images)
    if not file_names:
        return 0

    async with AsyncSessionLocal() as db:
        gallery = (
            await db.execute(
                select(Gallery).where(func.lower(Gallery.title) == MISC_GALLERY_TITLE)
            )
        ).scalars().first()
        if not gallery:
            gallery = Gallery(
                title=MISC_GALLERY_TITLE,
                slug=await _unique_slug(db),
                is_published=False,
            )
            db.add(gallery)
            await db.flush()

        start_page = (
            await db.execute(
                select(func.max(Page.page_number)).where(Page.gallery_id == gallery.id)
            )
        ).scalar() or 0

        added = 0
        for file_name in file_names:
            file_path = os.path.join(imports_dir, file_name)
            async with aiofiles.open(file_path, "rb") as fh:
                data = await fh.read()
            page_number = start_page + added + 1
            image_path, width, height = await image_service.process_page(
                data, gallery.slug, page_number
            )
            thumb_path = await image_service.generate_page_thumbnail(
                data, gallery.slug, page_number
            )
            db.add(Page(
                gallery_id=gallery.id,
                page_number=page_number,
                image_path=image_path,
                thumbnail_path=thumb_path,
                image_width=width,
                image_height=height,
            ))
            if not gallery.cover_path or not gallery.thumbnail_path:
                gallery.cover_path = await image_service.generate_cover(data, gallery.slug)
                gallery.thumbnail_path = await image_service.generate_thumbnail(data, gallery.slug)
            await asyncio.to_thread(os.remove, file_path)
            added += 1

        gallery.page_count = start_page + added
        await db.commit()
        await manifest_service.write_manifest(db, gallery.id)
        return added
