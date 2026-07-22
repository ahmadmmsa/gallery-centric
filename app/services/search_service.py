import math
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, func, desc, asc

from app.models.gallery import Gallery
from app.models.tag import Tag
from app.models.artist import Artist
from app.models.character import Character
from app.models.parody import Parody
from app.models.language import Language
from app.schemas.search import SearchResult
from app.utils.db_utils import safe_execute_all

async def search(
    db: AsyncSession,
    query: str = "",
    include_tags: Optional[List[str]] = None,
    exclude_tags: Optional[List[str]] = None,
    artists: Optional[List[str]] = None,
    characters: Optional[List[str]] = None,
    parodies: Optional[List[str]] = None,
    language: Optional[str] = None,
    sort: str = "created_at:desc", # e.g. "view_count:desc"
    page: int = 1,
    per_page: int = 20
) -> SearchResult:
    """Execute a search query against PostgreSQL Full-Text Search with complex filtering."""
    
    stmt = select(Gallery).where(Gallery.is_published == True)
    count_stmt = select(func.count()).select_from(Gallery).where(Gallery.is_published == True)
    
    tsquery = None
    if query:
        # Use websearch_to_tsquery for user-friendly query parsing
        tsquery = func.websearch_to_tsquery('english', query)
        stmt = stmt.where(Gallery.search_vector.op('@@')(tsquery))
        count_stmt = count_stmt.where(Gallery.search_vector.op('@@')(tsquery))
        
    if language:
        stmt = stmt.join(Gallery.language).where(Language.code == language)
        count_stmt = count_stmt.join(Gallery.language).where(Language.code == language)

    # Helper to build associations filters
    if include_tags:
        for t in include_tags:
            stmt = stmt.where(Gallery.tags.any(Tag.name == t))
            count_stmt = count_stmt.where(Gallery.tags.any(Tag.name == t))
            
    if exclude_tags:
        for t in exclude_tags:
            stmt = stmt.where(~Gallery.tags.any(Tag.name == t))
            count_stmt = count_stmt.where(~Gallery.tags.any(Tag.name == t))

    if artists:
        for a in artists:
            stmt = stmt.where(Gallery.artists.any(Artist.name == a))
            count_stmt = count_stmt.where(Gallery.artists.any(Artist.name == a))
            
    if characters:
        for c in characters:
            stmt = stmt.where(Gallery.characters.any(Character.name == c))
            count_stmt = count_stmt.where(Gallery.characters.any(Character.name == c))
            
    if parodies:
        for p in parodies:
            stmt = stmt.where(Gallery.parodies.any(Parody.name == p))
            count_stmt = count_stmt.where(Gallery.parodies.any(Parody.name == p))

    # Apply sorting
    if query and sort == "relevance":
        stmt = stmt.order_by(func.ts_rank(Gallery.search_vector, tsquery).desc())
    else:
        # default sorting
        if sort == "created_at:desc": stmt = stmt.order_by(Gallery.created_at.desc())
        elif sort == "created_at:asc": stmt = stmt.order_by(Gallery.created_at.asc())
        elif sort == "view_count:desc": stmt = stmt.order_by(Gallery.view_count.desc())
        elif sort == "favorite_count:desc": stmt = stmt.order_by(Gallery.favorite_count.desc())
        elif sort == "title:asc": stmt = stmt.order_by(Gallery.title.asc())
        elif sort == "title:desc": stmt = stmt.order_by(Gallery.title.desc())
        else: stmt = stmt.order_by(Gallery.created_at.desc()) # fallback

    # Pagination
    offset = (page - 1) * per_page
    stmt = stmt.offset(offset).limit(per_page)
    
    # Eager load relationships for hits
    stmt = stmt.options(
        selectinload(Gallery.tags),
        selectinload(Gallery.artists),
        selectinload(Gallery.characters),
        selectinload(Gallery.parodies),
        selectinload(Gallery.language)
    )

    total_hits = await db.scalar(count_stmt) or 0
    galleries = await safe_execute_all(db, stmt)
    
    total_pages = math.ceil(total_hits / per_page) if per_page > 0 else 0
    
    # Convert SQLAlchemy model hits to dictionary layout expected by SearchResult
    def _gallery_to_document(gallery: Gallery) -> Dict[str, Any]:
        return {
            'id': gallery.id,
            'title': gallery.title,
            'slug': gallery.slug,
            'description': gallery.description or "",
            'thumbnail_path': gallery.thumbnail_path or "",
            'language': gallery.language.name if gallery.language else None,
            'is_published': gallery.is_published,
            'page_count': gallery.page_count,
            'view_count': gallery.view_count,
            'favorite_count': gallery.favorite_count,
            'created_at': int(gallery.created_at.timestamp()) if gallery.created_at else 0,
            
            # Flattened relationships
            'tag_names': [tag.name for tag in gallery.tags],
            'artist_names': [artist.name for artist in gallery.artists],
            'character_names': [character.name for character in gallery.characters],
            'parody_names': [parody.name for parody in gallery.parodies],
        }

    hits = [_gallery_to_document(g) for g in galleries]
    
    return SearchResult(
        hits=hits,
        total_hits=total_hits,
        page=page,
        total_pages=total_pages,
        processing_time_ms=0,
        facets={}
    )
