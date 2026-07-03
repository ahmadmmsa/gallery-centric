"""Runtime configuration stored in the database.

Two kinds of settings live in the ``app_settings`` table:

* **Secrets** (``SECRET_KEY``, ``ALTCHA_HMAC_KEY``) -- auto-generated on first
  launch and persisted *encrypted*. Never read from .env.
* **Editable settings** (site name, SEO/social meta tags) -- plain-text values
  the admin changes from the Site Settings / SEO admin pages. Their factory
  defaults live in ``DEFAULTS`` and are used until a row is saved.

``load()`` reads everything into an in-memory cache (secrets decrypted, defaults
overlaid); ``bootstrap()`` generates any missing secrets; ``set_many()`` writes
editable settings and refreshes the cache.
"""
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.utils import crypto

# Secret config keys that are auto-generated and stored encrypted.
SECRET_KEYS = ("SECRET_KEY", "ALTCHA_HMAC_KEY")

# Editable (non-secret) settings and their factory defaults. A row is created
# the first time the admin saves; until then the default here is served.
DEFAULTS = {
    # --- Site identity ---
    "SITE_NAME": "Gallery Centric",
    "SITE_DESCRIPTION": "",
    # --- SEO: general ---
    "SEO_KEYWORDS": "",
    "SEO_ROBOTS": "index, follow",
    "SEO_THEME_COLOR": "",
    "SEO_DEFAULT_IMAGE": "",
    "SEO_FAVICON": "",
    # --- SEO: Open Graph (Facebook, Snapchat, WhatsApp, LinkedIn) ---
    "SEO_OG_SITE_NAME": "",
    "SEO_FB_APP_ID": "",
    "SEO_FB_PAGES": "",
    # --- SEO: Twitter / X ---
    "SEO_TWITTER_CARD": "summary_large_image",
    "SEO_TWITTER_SITE": "",
    "SEO_TWITTER_CREATOR": "",
}

_cache: dict = {}

# First-run flag: True while the admin still has an unset (auto-generated)
# password, i.e. before anyone has completed the /setup page. Kept in memory
# (refreshed at startup) so we don't hit the DB on every anonymous request.
_setup_required: bool = False


async def _get_row(db: AsyncSession, key: str):
    return (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalars().first()


async def bootstrap(db: AsyncSession) -> None:
    """Generate any missing secrets and persist them (encrypted). Idempotent."""
    created = False
    for key in SECRET_KEYS:
        if await _get_row(db, key) is None:
            db.add(AppSetting(key=key, value=crypto.encrypt(secrets.token_hex(32)), is_secret=True))
            created = True
    if created:
        await db.commit()


async def load(db: AsyncSession) -> None:
    """Load all settings into the in-memory cache, decrypting secrets.

    Editable-setting defaults are overlaid first so ``get()`` always returns a
    sensible value even before the admin has saved anything.
    """
    rows = (await db.execute(select(AppSetting))).scalars().all()
    data = dict(DEFAULTS)
    for row in rows:
        data[row.key] = crypto.decrypt(row.value) if row.is_secret else row.value
    _cache.clear()
    _cache.update(data)


async def ensure_loaded(db: AsyncSession) -> None:
    """Bootstrap (if needed) then load. Safe to call at every app startup."""
    await bootstrap(db)
    await load(db)
    await refresh_setup_state(db)


async def refresh_setup_state(db: AsyncSession) -> None:
    """Recompute whether first-run setup is still pending (admin has no password)."""
    global _setup_required
    from app.models.user import User

    admin = (
        await db.execute(
            select(User).where(User.is_admin == True, User.must_change_password == True)  # noqa: E712
        )
    ).scalars().first()
    _setup_required = admin is not None


def setup_required() -> bool:
    return _setup_required


def mark_setup_complete() -> None:
    global _setup_required
    _setup_required = False


async def set_many(db: AsyncSession, values: dict) -> None:
    """Persist editable settings then refresh the cache.

    Only keys declared in ``DEFAULTS`` are accepted, so this can never touch or
    overwrite an encrypted secret.
    """
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        value = value or ""
        row = await _get_row(db, key)
        if row is None:
            db.add(AppSetting(key=key, value=value, is_secret=False))
        else:
            row.value = value
    await db.commit()
    await load(db)


def get(key: str, default=None):
    return _cache.get(key, default)


def secret_key() -> str:
    return _cache.get("SECRET_KEY", "")


def altcha_hmac_key() -> str:
    return _cache.get("ALTCHA_HMAC_KEY", "")
