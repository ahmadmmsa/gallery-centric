"""Stateless double-submit-cookie CSRF protection.

A non-HttpOnly ``csrf_token`` cookie is issued by the auth middleware. Unsafe
requests must echo that token back, either in the ``X-CSRF-Token`` header
(AJAX / HTMX) or a ``csrf_token`` form field (plain HTML forms). The two are
compared; a mismatch is rejected.
"""
import hmac
import secrets

from fastapi import Request, HTTPException, status

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


async def verify_csrf(request: Request) -> None:
    """Router-level dependency: enforce CSRF on unsafe methods."""
    if request.method in SAFE_METHODS:
        return

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    submitted = request.headers.get(CSRF_HEADER_NAME)

    if not submitted:
        # Only parse urlencoded bodies here -- never multipart, so we don't
        # buffer large file uploads (those carry the token in the header).
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("application/x-www-form-urlencoded"):
            form = await request.form()
            submitted = form.get(CSRF_FORM_FIELD)

    if not cookie_token or not submitted or not hmac.compare_digest(cookie_token, submitted):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
