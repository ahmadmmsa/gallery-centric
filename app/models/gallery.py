from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, DateTime, Index
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.associations import gallery_tags, gallery_artists, gallery_characters, gallery_parodies

class Gallery(Base):
    __tablename__ = "galleries"
    __table_args__ = (
        Index('ix_gallery_search_vector', 'search_vector', postgresql_using='gin'),
    )

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, index=True)
    slug = Column(String, unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    thumbnail_path = Column(String, nullable=True)
    cover_path = Column(String, nullable=True)
    language_id = Column(Integer, ForeignKey("languages.id", ondelete="SET NULL"), nullable=True)
    page_count = Column(Integer, default=0)
    view_count = Column(Integer, default=0)
    favorite_count = Column(Integer, default=0)
    published_date = Column(DateTime(timezone=True), nullable=True)
    seo_title = Column(String, nullable=True)
    seo_description = Column(String, nullable=True)
    is_published = Column(Boolean, default=False, index=True)
    sequence = Column(Integer, default=0)
    search_vector = Column(TSVECTOR)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    language = relationship("Language", back_populates="galleries")
    pages = relationship("Page", back_populates="gallery", cascade="all, delete-orphan", order_by="Page.page_number")
    
    tags = relationship("Tag", secondary=gallery_tags, back_populates="galleries")
    artists = relationship("Artist", secondary=gallery_artists, back_populates="galleries")
    characters = relationship("Character", secondary=gallery_characters, back_populates="galleries")
    parodies = relationship("Parody", secondary=gallery_parodies, back_populates="galleries")


class Page(Base):
    __tablename__ = "pages"

    id = Column(Integer, primary_key=True, index=True)
    gallery_id = Column(Integer, ForeignKey("galleries.id", ondelete="CASCADE"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False)
    image_path = Column(String, nullable=False)
    thumbnail_path = Column(String, nullable=True)
    image_width = Column(Integer, nullable=True)
    image_height = Column(Integer, nullable=True)

    gallery = relationship("Gallery", back_populates="pages")
