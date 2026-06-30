from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import relationship
from app.database import Base

class Artist(Base):
    __tablename__ = "artists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    slug = Column(String, unique=True, nullable=False, index=True)
    bio = Column(Text, nullable=True)
    gallery_count = Column(Integer, default=0)

    galleries = relationship("Gallery", secondary="gallery_artists", back_populates="artists")
