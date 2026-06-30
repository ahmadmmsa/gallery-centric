from app.models.gallery import Gallery
from app.config import settings

def get_gallery_seo(gallery: Gallery) -> dict:
    title = gallery.seo_title or f"{gallery.title} | {settings.SITE_NAME}"
    description = gallery.seo_description or (gallery.description[:150] + "..." if gallery.description else f"Read {gallery.title} online.")
    image = f"{settings.BASE_URL}{gallery.thumbnail_path}" if gallery.thumbnail_path else None
    return {
        "title": title,
        "description": description,
        "image": image,
        "url": f"{settings.BASE_URL}/gallery/{gallery.slug}"
    }

def get_default_seo(title_suffix: str = "") -> dict:
    title = f"{title_suffix} | {settings.SITE_NAME}" if title_suffix else settings.SITE_NAME
    return {
        "title": title,
        "description": f"Welcome to {settings.SITE_NAME}",
        "image": None,
        "url": settings.BASE_URL
    }
