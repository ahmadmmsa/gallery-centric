from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

class TagBadgeSchema(BaseModel):
    name: str
    slug: str
    color: Optional[str] = None
    tag_type_name: Optional[str] = None

class LanguageSchema(BaseModel):
    id: int
    name: str
    code: str

    class Config:
        from_attributes = True

class ArtistSchema(BaseModel):
    id: int
    name: str
    slug: str

    class Config:
        from_attributes = True

class CharacterSchema(BaseModel):
    id: int
    name: str
    slug: str

    class Config:
        from_attributes = True

class ParodySchema(BaseModel):
    id: int
    name: str
    slug: str

    class Config:
        from_attributes = True

class PageResponse(BaseModel):
    id: int
    gallery_id: int
    page_number: int
    image_path: str
    thumbnail_path: Optional[str] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None

    class Config:
        from_attributes = True

class GalleryCardResponse(BaseModel):
    id: int
    title: str
    slug: str
    thumbnail_path: Optional[str] = None
    cover_path: Optional[str] = None
    page_count: int
    view_count: int
    favorite_count: int
    tags: List[TagBadgeSchema] = []

    class Config:
        from_attributes = True

class GalleryDetailResponse(BaseModel):
    id: int
    title: str
    slug: str
    description: Optional[str] = None
    thumbnail_path: Optional[str] = None
    cover_path: Optional[str] = None
    page_count: int
    view_count: int
    favorite_count: int
    published_date: Optional[datetime] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    is_published: bool
    created_at: datetime
    updated_at: datetime
    
    language: Optional[LanguageSchema] = None
    pages: List[PageResponse] = []
    tags: List[TagBadgeSchema] = []
    artists: List[ArtistSchema] = []
    characters: List[CharacterSchema] = []
    parodies: List[ParodySchema] = []

    class Config:
        from_attributes = True
