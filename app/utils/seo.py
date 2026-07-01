from app.models.gallery import Gallery
from app.config import settings
from app.services import runtime_config


def _site_name() -> str:
    # DB-backed, admin-editable (Site Settings page); falls back to the default.
    return runtime_config.get("SITE_NAME", "Gallery Centric")


def get_gallery_seo(gallery: Gallery) -> dict:
    site_name = _site_name()
    title = gallery.seo_title or f"{gallery.title} | {site_name}"
    description = gallery.seo_description or (gallery.description[:150] + "..." if gallery.description else f"Read {gallery.title} online.")
    image = f"{settings.BASE_URL}{gallery.thumbnail_path}" if gallery.thumbnail_path else None
    return {
        "title": title,
        "description": description,
        "image": image,
        "url": f"{settings.BASE_URL}/gallery/{gallery.slug}"
    }

def get_default_seo(title_suffix: str = "") -> dict:
    site_name = _site_name()
    title = f"{title_suffix} | {site_name}" if title_suffix else site_name
    return {
        "title": title,
        "description": runtime_config.get("SITE_DESCRIPTION") or f"Welcome to {site_name}",
        "image": None,
        "url": settings.BASE_URL
    }
