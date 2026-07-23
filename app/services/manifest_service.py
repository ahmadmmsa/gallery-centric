"""Per-gallery sidecar manifests and disk -> database restore.

Every gallery folder under ``media/galleries/{slug}/`` carries a
``gallery.json`` sidecar holding the metadata that otherwise lives only in
Postgres (title, taxonomy names, page list, ...). The manifest is rewritten on
every admin save, so a gallery folder copied to another installation is
self-describing: the restore task scans ``media/galleries``, skips folders
whose slug already exists in the database, and recreates Gallery/Page rows
from each folder's manifest (taxonomies are matched by name, created when
missing). Folders without a manifest are adopted as unpublished drafts named
after the folder.

Restore runs as a BackgroundTask with its own session and reports progress
through ``media/restore_status.json`` (same pattern as maintenance_service).
"""
import os
import re
import json
import uuid
import asyncio
import logging
import datetime

from PIL import Image
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.gallery import Gallery, Page
from app.models.tag import Tag, TagType
from app.models.artist import Artist
from app.models.character import Character
from app.models.parody import Parody
from app.models.language import Language

MANIFEST_NAME = "gallery.json"
MANIFEST_VERSION = 1
STATUS_FILE = os.path.join(settings.UPLOAD_DIR, "restore_status.json")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
DEFAULT_TAG_TYPE = "General"


def _gen_slug(length: int = 8) -> str:
    return uuid.uuid4().hex[:length]


def _galleries_dir() -> str:
    return os.path.join(settings.UPLOAD_DIR, "galleries")


def _url(*parts: str) -> str:
    return "/" + "/".join([settings.UPLOAD_DIR, "galleries", *parts])


def _isoformat(value) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value) -> datetime.datetime | None:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


# ---------------------------------------------------------------------------
# Writing manifests
# ---------------------------------------------------------------------------

def _build_manifest(gallery: Gallery) -> dict:
    """Serialize a fully-loaded Gallery into the sidecar dict.

    File references are stored as basenames only: the folder layout
    (pages/, page_thumbs/, cover.webp at the root) is fixed, and basenames
    keep the manifest valid even if the whole tree is copied elsewhere.
    """
    return {
        "manifest_version": MANIFEST_VERSION,
        "slug": gallery.slug,
        "title": gallery.title,
        "description": gallery.description,
        "language": (
            {"name": gallery.language.name, "code": gallery.language.code}
            if gallery.language else None
        ),
        "tags": [
            {"name": t.name, "type": t.tag_type.name if t.tag_type else None}
            for t in gallery.tags
        ],
        "artists": [a.name for a in gallery.artists],
        "characters": [c.name for c in gallery.characters],
        "parodies": [p.name for p in gallery.parodies],
        "is_published": bool(gallery.is_published),
        "sequence": gallery.sequence or 0,
        "view_count": gallery.view_count or 0,
        "favorite_count": gallery.favorite_count or 0,
        "published_date": _isoformat(gallery.published_date),
        "created_at": _isoformat(gallery.created_at),
        "seo_title": gallery.seo_title,
        "seo_description": gallery.seo_description,
        "cover": os.path.basename(gallery.cover_path) if gallery.cover_path else None,
        "thumbnail": os.path.basename(gallery.thumbnail_path) if gallery.thumbnail_path else None,
        "pages": [
            {
                "number": p.page_number,
                "file": os.path.basename(p.image_path) if p.image_path else None,
                "thumb": os.path.basename(p.thumbnail_path) if p.thumbnail_path else None,
                "width": p.image_width,
                "height": p.image_height,
            }
            for p in gallery.pages
        ],
    }


async def write_manifest(db: AsyncSession, gallery_id: int) -> None:
    """Write/refresh the sidecar manifest for one gallery. Never raises."""
    try:
        stmt = select(Gallery).where(Gallery.id == gallery_id).options(
            selectinload(Gallery.tags).selectinload(Tag.tag_type),
            selectinload(Gallery.artists),
            selectinload(Gallery.characters),
            selectinload(Gallery.parodies),
            selectinload(Gallery.language),
            selectinload(Gallery.pages),
        )
        gallery = (await db.execute(stmt)).scalars().first()
        if not gallery or not gallery.slug:
            return
        data = _build_manifest(gallery)
        folder = os.path.join(_galleries_dir(), gallery.slug)

        def _write():
            os.makedirs(folder, exist_ok=True)
            tmp_path = os.path.join(folder, MANIFEST_NAME + ".tmp")
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, os.path.join(folder, MANIFEST_NAME))

        await asyncio.to_thread(_write)
    except Exception:
        logging.exception(f"Failed to write manifest for gallery {gallery_id}")


# ---------------------------------------------------------------------------
# Status file (mirrors maintenance_service)
# ---------------------------------------------------------------------------

async def _write_status(status: str, task: str = None, summary: dict = None, error: str = None):
    data = {"status": status, "task": task, "summary": summary or {}, "error": error}

    def _sync_write():
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        with open(STATUS_FILE, "w") as f:
            json.dump(data, f)

    await asyncio.to_thread(_sync_write)


async def get_restore_status() -> dict:
    if not await asyncio.to_thread(os.path.exists, STATUS_FILE):
        return {"status": "idle"}
    try:
        def _read():
            with open(STATUS_FILE, "r") as f:
                return json.load(f)
        return await asyncio.to_thread(_read)
    except Exception:
        return {"status": "idle"}


# ---------------------------------------------------------------------------
# Restore: disk -> database
# ---------------------------------------------------------------------------

async def run_restore_task():
    """Entry point for BackgroundTasks which manages its own db session."""
    try:
        await _write_status("running", task="restore")
        async with AsyncSessionLocal() as db:
            summary = await restore_from_disk(db)
        await _write_status("completed_restore", task="restore", summary=summary)
    except Exception as e:
        logging.exception("Gallery restore failed")
        await _write_status("error", task="restore", error=str(e))


async def run_rebuild_manifests_task():
    """Write a fresh sidecar manifest for every gallery in the database."""
    try:
        await _write_status("running", task="manifests")
        async with AsyncSessionLocal() as db:
            gallery_ids = (await db.execute(select(Gallery.id))).scalars().all()
            for gallery_id in gallery_ids:
                await write_manifest(db, gallery_id)
        await _write_status(
            "completed_manifests", task="manifests",
            summary={"manifests_written": len(gallery_ids)},
        )
    except Exception as e:
        logging.exception("Manifest rebuild failed")
        await _write_status("error", task="manifests", error=str(e))


async def restore_from_disk(db: AsyncSession) -> dict:
    summary = {
        "restored": 0,
        "restored_without_manifest": 0,
        "skipped_existing": 0,
        "warnings": [],
        "failed": [],
    }
    galleries_dir = _galleries_dir()
    if not await asyncio.to_thread(os.path.isdir, galleries_dir):
        return summary

    existing_slugs = set((await db.execute(select(Gallery.slug))).scalars().all())

    def _list_folders():
        return sorted(
            entry.name for entry in os.scandir(galleries_dir) if entry.is_dir()
        )

    folders = await asyncio.to_thread(_list_folders)
    cache: dict = {}

    for folder in folders:
        if folder in existing_slugs:
            summary["skipped_existing"] += 1
            continue
        folder_path = os.path.join(galleries_dir, folder)
        try:
            manifest = await asyncio.to_thread(_read_manifest, folder_path)
            if manifest is not None:
                await _restore_with_manifest(db, folder, folder_path, manifest, cache, summary)
                summary["restored"] += 1
            elif await _restore_without_manifest(db, folder, folder_path):
                summary["restored_without_manifest"] += 1
            else:
                summary["failed"].append(
                    {"folder": folder, "reason": "no manifest and no images found"}
                )
        except Exception as e:
            logging.exception(f"Failed to restore gallery folder {folder}")
            await db.rollback()
            summary["failed"].append({"folder": folder, "reason": str(e)})
    return summary


def _read_manifest(folder_path: str) -> dict | None:
    manifest_path = os.path.join(folder_path, MANIFEST_NAME)
    if not os.path.isfile(manifest_path):
        return None
    with open(manifest_path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{MANIFEST_NAME} is not a JSON object")
    return data


async def _get_or_create(db: AsyncSession, model, name: str, cache: dict, **extra):
    """Find a taxonomy row by name (case-insensitive) or create it."""
    name = (name or "").strip()
    key = (model.__name__, name.lower())
    if key in cache:
        return cache[key]
    obj = (
        await db.execute(select(model).where(func.lower(model.name) == name.lower()))
    ).scalars().first()
    if not obj:
        obj = model(name=name, slug=_gen_slug(), **extra)
        db.add(obj)
        await db.flush()
    cache[key] = obj
    return obj


async def _get_or_create_language(db: AsyncSession, cache: dict, lang) -> Language | None:
    if not isinstance(lang, dict):
        return None
    code = (lang.get("code") or "").strip()
    if not code:
        return None
    key = ("Language", code.lower())
    if key in cache:
        return cache[key]
    obj = (
        await db.execute(select(Language).where(func.lower(Language.code) == code.lower()))
    ).scalars().first()
    if not obj:
        obj = Language(name=(lang.get("name") or code).strip(), code=code)
        db.add(obj)
        await db.flush()
    cache[key] = obj
    return obj


async def _get_or_create_tag(db: AsyncSession, cache: dict, entry: dict) -> Tag:
    tag_type = await _get_or_create(
        db, TagType, entry.get("type") or DEFAULT_TAG_TYPE, cache
    )
    return await _get_or_create(
        db, Tag, entry["name"], cache, tag_type_id=tag_type.id
    )


def _dedupe(objs: list) -> list:
    return list(dict.fromkeys(objs))


async def _restore_with_manifest(
    db: AsyncSession, folder: str, folder_path: str,
    manifest: dict, cache: dict, summary: dict,
) -> None:
    manifest_slug = manifest.get("slug")
    if manifest_slug and manifest_slug != folder:
        summary["warnings"].append(
            f"{folder}: manifest slug is '{manifest_slug}' but the folder was "
            f"renamed; restored under '{folder}'"
        )

    def _list_files():
        def _ls(sub):
            p = os.path.join(folder_path, sub)
            return set(os.listdir(p)) if os.path.isdir(p) else set()
        return {"root": _ls(""), "pages": _ls("pages"), "page_thumbs": _ls("page_thumbs")}

    files = await asyncio.to_thread(_list_files)

    pages = []
    for entry in manifest.get("pages") or []:
        if not isinstance(entry, dict):
            continue
        file_name = entry.get("file")
        if not file_name or file_name not in files["pages"]:
            continue
        thumb_name = entry.get("thumb")
        pages.append(Page(
            page_number=len(pages) + 1,
            image_path=_url(folder, "pages", file_name),
            thumbnail_path=(
                _url(folder, "page_thumbs", thumb_name)
                if thumb_name and thumb_name in files["page_thumbs"] else None
            ),
            image_width=entry.get("width"),
            image_height=entry.get("height"),
        ))
    if len(pages) != len(manifest.get("pages") or []):
        summary["warnings"].append(
            f"{folder}: {len(manifest.get('pages') or []) - len(pages)} page(s) "
            f"listed in the manifest are missing on disk and were skipped"
        )

    tags = [
        await _get_or_create_tag(db, cache, entry)
        for entry in manifest.get("tags") or []
        if isinstance(entry, dict) and (entry.get("name") or "").strip()
    ]

    async def _named(model, names):
        return _dedupe([
            await _get_or_create(db, model, name, cache)
            for name in names or [] if isinstance(name, str) and name.strip()
        ])

    language = await _get_or_create_language(db, cache, manifest.get("language"))
    cover_name = manifest.get("cover") or "cover.webp"
    thumb_name = manifest.get("thumbnail") or "thumbnail.webp"

    fields = {
        "title": (manifest.get("title") or folder).strip() or folder,
        "slug": folder,
        "description": manifest.get("description"),
        "seo_title": manifest.get("seo_title"),
        "seo_description": manifest.get("seo_description"),
        "is_published": bool(manifest.get("is_published")),
        "sequence": int(manifest.get("sequence") or 0),
        "view_count": int(manifest.get("view_count") or 0),
        "favorite_count": int(manifest.get("favorite_count") or 0),
        "page_count": len(pages),
        "cover_path": _url(folder, cover_name) if cover_name in files["root"] else None,
        "thumbnail_path": _url(folder, thumb_name) if thumb_name in files["root"] else None,
        "language_id": language.id if language else None,
        "tags": _dedupe(tags),
        "artists": await _named(Artist, manifest.get("artists")),
        "characters": await _named(Character, manifest.get("characters")),
        "parodies": await _named(Parody, manifest.get("parodies")),
        "pages": pages,
    }
    published_date = _parse_dt(manifest.get("published_date"))
    if published_date:
        fields["published_date"] = published_date
    created_at = _parse_dt(manifest.get("created_at"))
    if created_at:
        fields["created_at"] = created_at

    gallery = Gallery(**fields)
    db.add(gallery)
    await db.commit()
    # Refresh the sidecar so it reflects what was actually restored (renamed
    # folder, pages skipped because their files were missing, ...).
    await write_manifest(db, gallery.id)


async def _restore_without_manifest(db: AsyncSession, folder: str, folder_path: str) -> bool:
    """Adopt a manifest-less folder as an unpublished draft named after it.

    Returns False when the folder contains no images at all.
    """
    def _scan():
        pages_dir = os.path.join(folder_path, "pages")
        in_pages = os.path.isdir(pages_dir)
        target = pages_dir if in_pages else folder_path
        names = sorted(
            (
                f for f in os.listdir(target)
                if f.lower().endswith(IMAGE_EXTENSIONS)
                and not f.startswith("._")
                and f not in ("cover.webp", "thumbnail.webp")
            ),
            key=_natural_key,
        )
        return in_pages, names, set(os.listdir(folder_path))

    in_pages, names, root_files = await asyncio.to_thread(_scan)
    if not names:
        return False

    def _dimensions(rel_path):
        try:
            with Image.open(os.path.join(folder_path, rel_path)) as img:
                return img.width, img.height
        except Exception:
            return None, None

    pages = []
    for number, file_name in enumerate(names, start=1):
        rel_path = os.path.join("pages", file_name) if in_pages else file_name
        width, height = await asyncio.to_thread(_dimensions, rel_path)
        pages.append(Page(
            page_number=number,
            image_path=_url(folder, *rel_path.split(os.sep)),
            thumbnail_path=None,
            image_width=width,
            image_height=height,
        ))

    cover_path = _url(folder, "cover.webp") if "cover.webp" in root_files else None
    thumbnail_path = _url(folder, "thumbnail.webp") if "thumbnail.webp" in root_files else None
    if not cover_path or not thumbnail_path:
        # Derive presentation images from the first page so the draft is
        # browsable immediately; failures just leave them blank.
        try:
            from app.services import image_service
            first_rel = os.path.join("pages", names[0]) if in_pages else names[0]

            def _read_first():
                with open(os.path.join(folder_path, first_rel), "rb") as fh:
                    return fh.read()

            first_bytes = await asyncio.to_thread(_read_first)
            cover_path = cover_path or await image_service.generate_cover(first_bytes, folder)
            thumbnail_path = thumbnail_path or await image_service.generate_thumbnail(first_bytes, folder)
        except Exception:
            logging.exception(f"Could not generate cover/thumbnail for {folder}")

    gallery = Gallery(
        title=folder,
        slug=folder,
        is_published=False,
        page_count=len(pages),
        cover_path=cover_path,
        thumbnail_path=thumbnail_path,
        pages=pages,
    )
    db.add(gallery)
    await db.commit()
    await write_manifest(db, gallery.id)
    return True
