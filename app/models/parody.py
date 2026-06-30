from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from app.database import Base

class Parody(Base):
    __tablename__ = "parodies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    slug = Column(String, unique=True, nullable=False, index=True)
    gallery_count = Column(Integer, default=0)

    galleries = relationship("Gallery", secondary="gallery_parodies", back_populates="parodies")
