from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers import frontend, admin, auth
from app.config import settings
import os
from sqlalchemy import exc as sa_exc
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.utils.seo import get_default_seo

app = FastAPI(title=settings.SITE_NAME, debug=settings.DEBUG)

from starlette.middleware.base import BaseHTTPMiddleware
from app.database import AsyncSessionLocal
from jose import jwt
from app.utils.auth import SECRET_KEY, ALGORITHM
from sqlalchemy.future import select
from app.models.user import User

class UserAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        token = request.cookies.get("access_token")
        if token and token.startswith("Bearer "):
            token = token[7:]
        
        request.state.user = None
        if token:
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                username = payload.get("sub")
                if username:
                    async with AsyncSessionLocal() as db:
                        stmt = select(User).where(User.username == username)
                        result = await db.execute(stmt)
                        request.state.user = result.scalars().first()
            except Exception:
                pass
                
        response = await call_next(request)
        return response

app.add_middleware(UserAuthMiddleware)


# Ensure upload directory exists
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

# Mount static and upload files
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount(f"/{settings.UPLOAD_DIR}", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# Include routers
app.include_router(auth.router, prefix="/auth")
app.include_router(frontend.router)
app.include_router(admin.router)

templates = Jinja2Templates(directory="app/templates")
from app.config import settings
templates.env.globals["settings"] = settings

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
