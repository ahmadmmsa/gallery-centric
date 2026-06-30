from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import timedelta
import base64
import hashlib
import hmac
import json
import secrets

from app.database import get_db
from app.models.user import User
from app.utils.auth import (
    create_access_token, 
    get_password_hash, 
    ACCESS_TOKEN_EXPIRE_MINUTES,
    verify_password
)
from app.utils.seo import get_default_seo
from app.config import settings

def _set_auth_cookie(response: Response, username: str) -> Response:
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": username}, expires_delta=access_token_expires
    )
    response.set_cookie(
        key="access_token", 
        value=f"Bearer {access_token}", 
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return response

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")
from app.config import settings
templates.env.globals["settings"] = settings

@router.get("/altcha-challenge")
def get_challenge():
    """Generates a PoW challenge for the client."""
    salt = secrets.token_hex(12)
    secret_number = secrets.randbelow(100000)
    challenge = hashlib.sha256(f"{salt}{secret_number}".encode()).hexdigest()
    signature = hmac.new(settings.ALTCHA_HMAC_KEY.encode(), challenge.encode(), hashlib.sha256).hexdigest()
    return {
        "algorithm": "SHA-256",
        "challenge": challenge,
        "salt": salt,
        "signature": signature
    }

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "auth/login.html", {
        "request": request,
        "seo": get_default_seo("Login"),
        "settings": settings
    })

@router.post("/login")
async def login(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(User).where(User.username == username)
    result = await db.execute(stmt)
    user = result.scalars().first()
    
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(request, "auth/login.html", {
            "request": request,
            "seo": get_default_seo("Login"),
            "settings": settings,
            "error": "Incorrect username or password"
        }, status_code=status.HTTP_401_UNAUTHORIZED)
        
    redirect_url = request.query_params.get("next", "/")
    res = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    return _set_auth_cookie(res, user.username)

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request, "auth/register.html", {
        "request": request,
        "seo": get_default_seo("Register"),
        "settings": settings
    })

@router.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    altcha: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    if not altcha:
        return templates.TemplateResponse(request, "auth/register.html", {
            "request": request,
            "seo": get_default_seo("Register"),
            "settings": settings,
            "error": "CAPTCHA missing"
        }, status_code=status.HTTP_400_BAD_REQUEST)
        
    try:
        decoded = base64.b64decode(altcha).decode('utf-8')
        data = json.loads(decoded)
        expected_sig = hmac.new(settings.ALTCHA_HMAC_KEY.encode(), data['challenge'].encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, data['signature']):
            raise ValueError("Invalid signature")
        hash_check = hashlib.sha256(f"{data['salt']}{data['number']}".encode()).hexdigest()
        if hash_check != data['challenge']:
            raise ValueError("Invalid proof of work")
    except (ValueError, KeyError, json.JSONDecodeError):
        return templates.TemplateResponse(request, "auth/register.html", {
            "request": request,
            "seo": get_default_seo("Register"),
            "settings": settings,
            "error": "CAPTCHA validation failed"
        }, status_code=status.HTTP_400_BAD_REQUEST)
        
    # Check existing user
    stmt = select(User).where((User.username == username) | (User.email == email))
    result = await db.execute(stmt)
    existing_user = result.scalars().first()
    
    if existing_user:
        return templates.TemplateResponse(request, "auth/register.html", {
            "request": request,
            "seo": get_default_seo("Register"),
            "settings": settings,
            "error": "Username or email already registered"
        }, status_code=status.HTTP_400_BAD_REQUEST)
        
    hashed_password = get_password_hash(password)
    new_user = User(
        username=username,
        email=email,
        hashed_password=hashed_password
    )
    db.add(new_user)
    await db.commit()
    
    res = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return _set_auth_cookie(res, new_user.username)

@router.get("/logout")
async def logout():
    res = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    res.delete_cookie("access_token")
    return res
