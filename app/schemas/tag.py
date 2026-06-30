from typing import Optional
from pydantic import BaseModel

class TagTypeSchema(BaseModel):
    id: int
    name: str
    slug: str
    color: Optional[str] = None

    class Config:
        from_attributes = True

class TagBadgeResponse(BaseModel):
    id: int
    name: str
    slug: str
    color: Optional[str] = None

    class Config:
        from_attributes = True

class TagDetailResponse(BaseModel):
    id: int
    name: str
    slug: str
    tag_type_id: int
    description: Optional[str] = None
    gallery_count: int
    is_visible: bool

    class Config:
        from_attributes = True
