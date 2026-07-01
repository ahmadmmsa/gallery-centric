from sqlalchemy import Column, String, Text, Boolean
from app.database import Base


class AppSetting(Base):
    """Key/value store for runtime configuration and generated secrets.

    Secret values (is_secret=True) are Fernet-encrypted at rest; see
    app.utils.crypto and app.services.runtime_config.
    """
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)
    is_secret = Column(Boolean, nullable=False, default=False)
