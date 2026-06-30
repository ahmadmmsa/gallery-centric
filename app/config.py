from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7 # 1 week
    ADMIN_USERNAME: str
    ADMIN_PASSWORD: str
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 500
    SITE_NAME: str = "GalleryCentric"
    BASE_URL: str = "http://localhost:8008"
    DEBUG: bool = False
    ALTCHA_HMAC_KEY: str = "default-altcha-key"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
