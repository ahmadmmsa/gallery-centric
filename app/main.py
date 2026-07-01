from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from app.routers import frontend, admin, auth, setup
from app.config import settings
import os
from sqlalchemy import exc as sa_exc
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from app.utils.templates import templates
from app.utils.seo import get_default_seo
from app.utils.csrf import verify_csrf, generate_csrf_token, CSRF_COOKIE_NAME
from app.utils.deps import load_current_user, PasswordChangeRequired, SetupRequired
from app.services import runtime_config

# The current user is loaded (and password-reset enforced) by load_current_user,
# applied to every route. It runs in the request task so its DB access is safe.
# The OpenAPI/docs title is fixed at construction (before the DB is loaded); the
# live, user-facing site name is DB-backed (see runtime_config / setting()).
app = FastAPI(
    title=runtime_config.DEFAULTS["SITE_NAME"],
    debug=settings.DEBUG,
    dependencies=[Depends(load_current_user)],
)

from starlette.datastructures import MutableHeaders
from app.database import AsyncSessionLocal


@app.on_event("startup")
async def _load_runtime_secrets():
    # Generate (if missing) and load SECRET_KEY / ALTCHA_HMAC_KEY from the DB.
    async with AsyncSessionLocal() as db:
        await runtime_config.ensure_loaded(db)


@app.exception_handler(PasswordChangeRequired)
async def _password_change_required_handler(request: Request, exc: PasswordChangeRequired):
    return RedirectResponse("/auth/change-password", status_code=302)


@app.exception_handler(SetupRequired)
async def _setup_required_handler(request: Request, exc: SetupRequired):
    return RedirectResponse("/setup", status_code=302)


class CsrfMiddleware:
    """Pure-ASGI middleware that issues/propagates the CSRF double-submit token.

    Implemented as raw ASGI (not BaseHTTPMiddleware) so it does not run the
    endpoint in a child task -- that child-task behaviour corrupts SQLAlchemy's
    async (greenlet) DB context and triggers asyncpg "another operation in
    progress" errors. Does no DB work itself.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        state["user"] = None  # default; load_current_user sets the real value

        path = scope.get("path", "")
        if path.startswith("/static/") or path.startswith(f"/{settings.UPLOAD_DIR}/"):
            await self.app(scope, receive, send)
            return

        csrf_token = Request(scope).cookies.get(CSRF_COOKIE_NAME)
        if csrf_token:
            state["csrf_token"] = csrf_token
            await self.app(scope, receive, send)
            return

        # Issue a new token (readable by JS for the X-CSRF-Token header).
        csrf_token = generate_csrf_token()
        state["csrf_token"] = csrf_token
        cookie = f"{CSRF_COOKIE_NAME}={csrf_token}; Path=/; Max-Age={60 * 60 * 24 * 7}; SameSite=lax"
        if settings.BASE_URL.startswith("https"):
            cookie += "; Secure"

        async def send_with_cookie(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("set-cookie", cookie)
            await send(message)

        await self.app(scope, receive, send_with_cookie)

app.add_middleware(CsrfMiddleware)


# Ensure upload directory exists
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

# Mount static and upload files
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount(f"/{settings.UPLOAD_DIR}", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# Include routers
app.include_router(setup.router, dependencies=[Depends(verify_csrf)])
app.include_router(auth.router, prefix="/auth", dependencies=[Depends(verify_csrf)])
app.include_router(frontend.router)
app.include_router(admin.router, dependencies=[Depends(verify_csrf)])

async def render_connection_error(request: Request, error_message: str):
    # Check if this is a JSON request
    accept = request.headers.get("accept", "")
    if "application/json" in accept or request.url.path.startswith("/api/"):
        return JSONResponse(
            {"detail": "Service temporarily unavailable. Database connection failed.", "error": error_message},
            status_code=503
        )
        
    # Check if this is an HTMX request
    hx_request = request.headers.get("hx-request")
    if hx_request:
        return templates.TemplateResponse(
            request,
            "partials/error_card.html",
            {
                "request": request,
                "message": "Service temporarily unavailable. The database connection was lost.",
                "error_detail": error_message,
                "debug": settings.DEBUG
            },
            status_code=503
        )
        
    # Standard HTML page request
    return templates.TemplateResponse(
        request,
        "pages/503.html",
        {
            "request": request,
            "seo": get_default_seo("Service Unavailable"),
            "error_detail": error_message,
            "debug": settings.DEBUG
        },
        status_code=503
    )

@app.exception_handler(sa_exc.SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: sa_exc.SQLAlchemyError):
    return await render_connection_error(request, str(exc))

@app.exception_handler(OSError)
async def os_exception_handler(request: Request, exc: OSError):
    return await render_connection_error(request, f"OSError: {exc}")
