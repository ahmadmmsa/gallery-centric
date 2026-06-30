from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

# Gallery Schemas
class GalleryCreateRequest(BaseModel):
    title: str
    slug: Optional[str] = None
    description: Optional[str] = None
    language_id: Optional[int] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    tag_ids: List[int] = []
    artist_ids: List[int] = []
    character_ids: List[int] = []
    parody_ids: List[int] = []

class GalleryUpdateRequest(BaseModel):
    title: str
    slug: Optional[str] = None
    description: Optional[str] = None
    language_id: Optional[int] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    tag_ids: List[int] = []
    artist_ids: List[int] = []
    character_ids: List[int] = []
    parody_ids: List[int] = []

class PageReorderRequest(BaseModel):
    page_id: int
    new_page_number: int

# Tag Schemas
class TagCreateRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    tag_type: str
    description: Optional[str] = None
    is_visible: bool = True

class TagUpdateRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    tag_type: str
    description: Optional[str] = None
    is_visible: bool = True

# TagType Schemas
class TagTypeCreateRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    color: str = "#6c757d"
    is_visible: bool = True

class TagTypeUpdateRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    color: str = "#6c757d"
    is_visible: bool = True

# Artist Schemas
class ArtistCreateRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    bio: Optional[str] = None

class ArtistUpdateRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    bio: Optional[str] = None

# Character Schemas
class CharacterCreateRequest(BaseModel):
    name: str
    slug: Optional[str] = None

class CharacterUpdateRequest(BaseModel):
    name: str
    slug: Optional[str] = None

# Parody Schemas
class ParodyCreateRequest(BaseModel):
    name: str
    slug: Optional[str] = None

class ParodyUpdateRequest(BaseModel):
    name: str
    slug: Optional[str] = None

# Language Schemas
class LanguageResponse(BaseModel):
    id: int
    name: str
    code: str

    class Config:
        from_attributes = True

# Stats Schemas
class AdminStats(BaseModel):
    total_galleries: int
    published_galleries: int
    total_pages: int
    total_tags: int
    total_artists: int
    total_characters: int
    total_parodies: int
    recent_galleries: list

# User Schemas
class AdminUserCreateRequest(BaseModel):
    username: str
    email: str
    password: str
    is_admin: bool = False
    is_active: bool = True

class AdminUserUpdateRequest(BaseModel):
    username: str
    email: str
    password: Optional[str] = None
    is_admin: bool = False
    is_active: bool = True
