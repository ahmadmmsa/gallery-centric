import os
import asyncio
import shutil
from io import BytesIO
from PIL import Image, ImageFile, ImageOps

ImageFile.LOAD_TRUNCATED_IMAGES = True
from app.config import settings

def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def _convert_to_webp(input_data: bytes, output_path: str, quality: int = 90, size: tuple = None) -> tuple[int, int]:
    """Blocking Pillow operations, should be run in a thread pool."""
    with Image.open(BytesIO(input_data)) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        if size:
            img = ImageOps.fit(img, size, Image.Resampling.LANCZOS)
        img.save(output_path, "WEBP", quality=quality)
        return img.width, img.height

async def process_page(file_data: bytes, gallery_slug: str, page_number: int) -> tuple[str, int, int]:
    """Convert and save a gallery page."""
    rel_dir = os.path.join(settings.UPLOAD_DIR, "galleries", gallery_slug, "pages")
    _ensure_dir(rel_dir)
    filename = f"{gallery_slug}_p{page_number:04d}.webp"
    file_path = os.path.join(rel_dir, filename)
    width, height = await asyncio.to_thread(
        _convert_to_webp, file_data, file_path, 90, None
    )
    return f"/{settings.UPLOAD_DIR}/galleries/{gallery_slug}/pages/{filename}", width, height

async def generate_thumbnail(file_data: bytes, gallery_slug: str) -> str:
    """Generate a 300x420 thumbnail."""
    rel_dir = os.path.join(settings.UPLOAD_DIR, "galleries", gallery_slug)
    _ensure_dir(rel_dir)
    filename = "thumbnail.webp"
    file_path = os.path.join(rel_dir, filename)
    await asyncio.to_thread(
        _convert_to_webp, file_data, file_path, 85, (300, 420)
    )
    return f"/{settings.UPLOAD_DIR}/galleries/{gallery_slug}/{filename}"

async def generate_cover(file_data: bytes, gallery_slug: str) -> str:
    """Generate an 800x1100 cover."""
    rel_dir = os.path.join(settings.UPLOAD_DIR, "galleries", gallery_slug)
    _ensure_dir(rel_dir)
    filename = "cover.webp"
    file_path = os.path.join(rel_dir, filename)
    await asyncio.to_thread(
        _convert_to_webp, file_data, file_path, 90, (800, 1100)
    )
    return f"/{settings.UPLOAD_DIR}/galleries/{gallery_slug}/{filename}"

async def generate_page_thumbnail(file_data: bytes, gallery_slug: str, page_number: int) -> str:
    """Generate a small 200x280 thumbnail for an individual page (used in gallery detail grid)."""
    rel_dir = os.path.join(settings.UPLOAD_DIR, "galleries", gallery_slug, "page_thumbs")
    _ensure_dir(rel_dir)
    filename = f"{gallery_slug}_p{page_number:04d}_thumb.webp"
    file_path = os.path.join(rel_dir, filename)
    await asyncio.to_thread(
        _convert_to_webp, file_data, file_path, 80, (200, 280)
    )
    return f"/{settings.UPLOAD_DIR}/galleries/{gallery_slug}/page_thumbs/{filename}"

def delete_gallery_files(gallery) -> None:
    """Physically remove the entire gallery directory and all its assets."""
    if gallery.slug:
        gallery_dir = os.path.join(settings.UPLOAD_DIR, "galleries", gallery.slug)
        if os.path.isdir(gallery_dir):
            try:
                shutil.rmtree(gallery_dir)
            except Exception as e:
                import logging
                logging.error(f"Failed to delete gallery directory {gallery_dir}: {str(e)}")

def scan_gallery_duplicates(gallery_pages: list) -> list[dict]:
    """Scan a list of Page objects for duplicates by size and MD5 hash."""
    import hashlib
    from collections import defaultdict
    size_groups = defaultdict(list)
    for page in gallery_pages:
        if not page.image_path:
            continue
        path = page.image_path.lstrip('/')
        if os.path.exists(path):
            try:
                size = os.path.getsize(path)
                size_groups[size].append(page)
            except Exception:
                continue
    duplicate_groups = []
    for size, pages in size_groups.items():
        if len(pages) > 1:
            hash_groups = defaultdict(list)
            for page in pages:
                path = page.image_path.lstrip('/')
                md5_hash = hashlib.md5()
                try:
                    with open(path, "rb") as f:
                        for chunk in iter(lambda: f.read(4096), b""):
                            md5_hash.update(chunk)
                    hash_groups[md5_hash.hexdigest()].append(page)
                except Exception:
                    continue
            for h, hash_pages in hash_groups.items():
                if len(hash_pages) > 1:
                    hash_pages.sort(key=lambda p: p.page_number)
                    duplicate_groups.append({
                        "original": hash_pages[0],
                        "duplicates": hash_pages[1:]
                    })
    duplicate_groups.sort(key=lambda g: g["original"].page_number)
    return duplicate_groups