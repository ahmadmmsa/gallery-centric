"""At-rest encryption for secrets stored in the database.

Encryption needs one key that cannot live in the database it protects, so we
keep a Fernet master key in a file on the persistent media volume. It is
generated on first use and is never written to .env or committed to git.
"""
import os

from cryptography.fernet import Fernet

from app.config import settings

MASTER_KEY_PATH = os.path.join(settings.UPLOAD_DIR, ".appkey")

_fernet = None


def _load_or_create_master_key() -> bytes:
    if os.path.exists(MASTER_KEY_PATH):
        with open(MASTER_KEY_PATH, "rb") as f:
            return f.read().strip()

    os.makedirs(os.path.dirname(MASTER_KEY_PATH) or ".", exist_ok=True)
    key = Fernet.generate_key()
    try:
        # O_EXCL so concurrent starters don't clobber each other.
        fd = os.open(MASTER_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        return key
    except FileExistsError:
        with open(MASTER_KEY_PATH, "rb") as f:
            return f.read().strip()


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_master_key())
    return _fernet


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()
