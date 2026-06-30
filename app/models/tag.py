from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

class TagType(Base):
    __tablename__ = "tag_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    color = Column(String, default="#6c757d")
    is_visible = Column(Boolean, default=True)

    tags = relationship("Tag", back_populates="tag_type", cascade="all, delete-orphan")

class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    slug = Column(String, unique=True, nullable=False, index=True)
    tag_type_id = Column(Integer, ForeignKey("tag_types.id", ondelete="CASCADE"), nullable=False)
    description = Column(String, nullable=True)
    gallery_count = Column(Integer, default=0)
    is_visible = Column(Boolean, default=True)

    tag_type = relationship("TagType", back_populates="tags")
    galleries = relationship("Gallery", secondary="gallery_tags", back_populates="tags")
