import os
import shutil
import time
import json
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from app.models.gallery import Gallery, Page
from app.config import settings
from app.database import AsyncSessionLocal

STATUS_FILE = os.path.join(settings.UPLOAD_DIR, "maintenance_status.json")
# 15 minutes buffer
TIME_BUFFER_SECONDS = 900

async def _write_status(status: str, summary: dict = None, error: str = None, execute: bool = False):
    data = {"status": status, "execute": execute, "summary": summary or {}, "error": error}
    await asyncio.to_thread(_sync_write_status, data)

def _sync_write_status(data):
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    with open(STATUS_FILE, "w") as f:
        json.dump(data, f)

async def get_maintenance_status() -> dict:
    if not await asyncio.to_thread(os.path.exists, STATUS_FILE):
        return {"status": "idle"}
    try:
        def _read():
            with open(STATUS_FILE, "r") as f:
                return json.load(f)
        return await asyncio.to_thread(_read)
    except Exception:
        return {"status": "idle"}

async def run_cleanup_task(execute: bool):
    """Entry point for BackgroundTasks which manages its own db session."""
    try:
        await _write_status("running", execute=execute)
        async with AsyncSessionLocal() as db:
            summary = await run_cleanup(db, execute)
            final_status = "completed_execution" if execute else "completed_dry_run"
            await _write_status(final_status, summary=summary, execute=execute)
    except Exception as e:
        await _write_status("error", error=str(e), execute=execute)

async def run_cleanup(db: AsyncSession, execute: bool) -> dict:
    """Run system maintenance to clean orphaned files and records. If execute is False, perform dry run."""
    summary = {
        "deleted_gallery_folders": 0,
        "deleted_orphaned_files": 0,
        "deleted_broken_page_records": 0,
        "updated_gallery_counts": 0,
    }
    
    galleries_dir = os.path.join(settings.UPLOAD_DIR, "galleries")
    if not await asyncio.to_thread(os.path.exists, galleries_dir):
        return summary
        
    current_time = time.time()

    # 1. Fetch all valid gallery slugs from the database
    valid_galleries = set()
    result = await db.execute(select(Gallery))
    all_galleries = result.scalars().all()
    
    for gallery in all_galleries:
        if gallery.slug:
            valid_galleries.add(gallery.slug)
            
    # 2. Scan uploads/galleries for directories that are not in valid_galleries
    def _scan_dirs():
        return os.listdir(galleries_dir)
    
    folder_names = await asyncio.to_thread(_scan_dirs)
    
    for folder_name in folder_names:
        folder_path = os.path.join(galleries_dir, folder_name)
        
        def _check_dir_and_age(p):
            if not os.path.isdir(p):
                return False, False
            mtime = os.path.getmtime(p)
            return True, (current_time - mtime) > TIME_BUFFER_SECONDS
            
        is_dir, is_old_enough = await asyncio.to_thread(_check_dir_and_age, folder_path)
        
        if is_dir and folder_name not in valid_galleries and is_old_enough:
            summary["deleted_gallery_folders"] += 1
            if execute:
                try:
                    await asyncio.to_thread(shutil.rmtree, folder_path)
                except Exception:
                    pass

    # 3. Process existing valid galleries one by one to save memory
    for gallery in all_galleries:
        if not gallery.slug:
            continue
            
        gallery_dir = os.path.join(galleries_dir, gallery.slug)
        if not await asyncio.to_thread(os.path.exists, gallery_dir):
            continue
            
        valid_files = set()
        if gallery.thumbnail_path:
            valid_files.add(gallery.thumbnail_path.lstrip('/').replace('\\', '/'))
        if gallery.cover_path:
            valid_files.add(gallery.cover_path.lstrip('/').replace('\\', '/'))
            
        # Refetch gallery with pages
        gal_result = await db.execute(select(Gallery).where(Gallery.id == gallery.id).options(selectinload(Gallery.pages)))
        gal_with_pages = gal_result.scalars().first()
        
        if not gal_with_pages:
            continue
            
        # 4. Check for broken Page records
        pages_to_delete = []
        for page in gal_with_pages.pages:
            broken = False
            
            def _check_file(path_str):
                if not path_str:
                    return False, False, None
                local_p = path_str.lstrip('/').replace('\\', '/')
                exists = os.path.exists(local_p)
                return True, exists, local_p
                
            has_img, img_exists, local_img = await asyncio.to_thread(_check_file, page.image_path)
            
            if has_img:
                if not img_exists:
                    broken = True
                else:
                    valid_files.add(local_img)
            else:
                broken = True # No image path = broken
            
            has_thumb, thumb_exists, local_thumb = await asyncio.to_thread(_check_file, page.thumbnail_path)
            if has_thumb and thumb_exists:
                valid_files.add(local_thumb)
                    
            if broken:
                pages_to_delete.append(page)
                
        # Delete broken pages
        if pages_to_delete:
            summary["deleted_broken_page_records"] += len(pages_to_delete)
            if execute:
                for page in pages_to_delete:
                    await db.delete(page)
                await db.commit()
            
        # Recalculate page count
        if pages_to_delete:
            summary["updated_gallery_counts"] += 1
            if execute:
                new_count_res = await db.execute(select(func.count()).select_from(Page).where(Page.gallery_id == gallery.id))
                gallery.page_count = new_count_res.scalar() or 0
                await db.commit()
            
        # 5. Clean orphaned files in the gallery folder
        def _get_files_to_remove(g_dir, v_files):
            to_remove = []
            for root_dir, _, files in os.walk(g_dir):
                for file_name in files:
                    file_path = os.path.join(root_dir, file_name)
                    file_path_clean = file_path.replace('\\', '/')
                    if file_path_clean not in v_files:
                        mtime = os.path.getmtime(file_path)
                        if (current_time - mtime) > TIME_BUFFER_SECONDS:
                            to_remove.append(file_path)
            return to_remove
            
        orphans = await asyncio.to_thread(_get_files_to_remove, gallery_dir, valid_files)
        
        for file_path in orphans:
            summary["deleted_orphaned_files"] += 1
            if execute:
                try:
                    await asyncio.to_thread(os.remove, file_path)
                except Exception:
                    pass
                        
    return summary
