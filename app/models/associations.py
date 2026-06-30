from sqlalchemy import Table, Column, Integer, ForeignKey
from app.database import Base

gallery_tags = Table(
    "gallery_tags",
    Base.metadata,
    Column("gallery_id", Integer, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
)

gallery_artists = Table(
    "gallery_artists",
    Base.metadata,
    Column("gallery_id", Integer, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True),
    Column("artist_id", Integer, ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True)
)

gallery_characters = Table(
    "gallery_characters",
    Base.metadata,
    Column("gallery_id", Integer, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True),
    Column("character_id", Integer, ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
)

gallery_parodies = Table(
    "gallery_parodies",
    Base.metadata,
    Column("gallery_id", Integer, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True),
    Column("parody_id", Integer, ForeignKey("parodies.id", ondelete="CASCADE"), primary_key=True)
)
