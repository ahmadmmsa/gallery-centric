import os
import re
import zipfile
import tempfile
import asyncio
import aiofiles
import shutil
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.gallery import Gallery, Page
from app.services import image_service

def natural_sort_key(s):
    """Sort strings with numbers naturally (1.jpg, 2.jpg, 10.jpg)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

async def process_directory_upload(directory_path: str, gallery: Gallery, db: AsyncSession, start_page: int = 1):
    valid_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    
    # Find all valid image files
    image_files = []
    for root, _, files in os.walk(directory_path):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in valid_extensions:
                # Filter out hidden files like macOS ._ files
                if not file.startswith("._") and not file.startswith(".DS_Store"):
                    image_files.append(os.path.join(root, file))
    
    if not image_files:
        raise ValueError("No valid image files found in the directory.")
        
    # Sort naturally based on the filename
    image_files.sort(key=lambda x: natural_sort_key(os.path.basename(x)))
    
    # Only overwrite cover/thumbnail when this is the first upload (start_page == 1)
    if start_page == 1:
        first_image_path = image_files[0]
        async with aiofiles.open(first_image_path, "rb") as f:
            first_image_data = await f.read()
            
        gallery.cover_path = await image_service.generate_cover(first_image_data, gallery.slug)
        gallery.thumbnail_path = await image_service.generate_thumbnail(first_image_data, gallery.slug)
    
    # Process all pages concurrently with a semaphore limit to prevent resource exhaustion
    sem = asyncio.Semaphore(10)
    
    async def process_single_page(index, img_path):
        async with sem:
            async with aiofiles.open(img_path, "rb") as f:
                img_data = await f.read()
                
            page_path, width, height = await image_service.process_page(
                img_data, gallery.slug, index
            )
            
            thumb_path = await image_service.generate_page_thumbnail(
                img_data, gallery.slug, index
            )
            
            return Page(
                gallery_id=gallery.id,
                page_number=index,
                image_path=page_path,
                thumbnail_path=thumb_path,
                image_width=width,
                image_height=height
            )

    tasks = [
        process_single_page(start_page + i, img_path)
        for i, img_path in enumerate(image_files)
    ]
    pages = await asyncio.gather(*tasks)
        
    db.add_all(pages)
    # Update page_count to reflect the total after appending
    gallery.page_count = (start_page - 1) + len(pages)

async def process_zip_upload(zip_path: str, gallery: Gallery, db: AsyncSession, start_page: int = 1):
    def extract_zip(zpath, dest):
        with zipfile.ZipFile(zpath, 'r') as zip_ref:
            zip_ref.extractall(dest)

    with tempfile.TemporaryDirectory() as temp_dir:
        await asyncio.to_thread(extract_zip, zip_path, temp_dir)
        await process_directory_upload(temp_dir, gallery, db, start_page)

async def process_import_folder(folder_path: str, gallery: Gallery, db: AsyncSession, start_page: int = 1):
    """Process an existing server directory, then delete it."""
    await process_directory_upload(folder_path, gallery, db, start_page)
    # Delete the folder after successful processing
    await asyncio.to_thread(shutil.rmtree, folder_path)
