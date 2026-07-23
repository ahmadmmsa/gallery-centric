from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import timedelta
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import parse_qs

from app.database import get_db
from app.models.user import User
from app.utils.auth import (
    create_access_token, 
    get_password_hash, 
    ACCESS_TOKEN_EXPIRE_MINUTES,
    verify_password
)
from app.utils.seo import get_default_seo
from app.utils.templates import templates
from app.services import runtime_config
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
        samesite="lax",
        secure=runtime_config.base_url().startswith("https"),
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return response

router = APIRouter(tags=["auth"])

ALTCHA_CHALLENGE_TTL_SECONDS = 300

@router.get("/altcha-challenge")
def get_challenge():
    """Generates a PoW challenge for the client."""
    # Embed an expiry in the salt (ALTCHA convention) so a solved challenge
    # cannot be replayed indefinitely. The salt is bound into the signed
    # challenge hash, so a client cannot extend it without invalidating the signature.
    expires = int(time.time()) + ALTCHA_CHALLENGE_TTL_SECONDS
    salt = f"{secrets.token_hex(12)}?expires={expires}"
    secret_number = secrets.randbelow(100000)
    challenge = hashlib.sha256(f"{salt}{secret_number}".encode()).hexdigest()
    signature = hmac.new(runtime_config.altcha_hmac_key().encode(), challenge.encode(), hashlib.sha256).hexdigest()
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
        expected_sig = hmac.new(runtime_config.altcha_hmac_key().encode(), data['challenge'].encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, data['signature']):
            raise ValueError("Invalid signature")
        hash_check = hashlib.sha256(f"{data['salt']}{data['number']}".encode()).hexdigest()
        if hash_check != data['challenge']:
            raise ValueError("Invalid proof of work")
        # Reject expired/replayed challenges.
        salt_params = parse_qs(data['salt'].split('?', 1)[1]) if '?' in data['salt'] else {}
        expires_vals = salt_params.get('expires')
        if not expires_vals or int(expires_vals[0]) < time.time():
            raise ValueError("Challenge expired")
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
    res.delete_cookie("access_token", samesite="lax", secure=runtime_config.base_url().startswith("https"))
    return res


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request):
    if not request.state.user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request, "auth/change_password.html", {
        "request": request,
        "seo": get_default_seo("Change Password"),
        "settings": settings,
        "forced": bool(getattr(request.state.user, "must_change_password", False)),
    })


@router.post("/change-password")
async def change_password(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not request.state.user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)

    ctx = {
        "request": request,
        "seo": get_default_seo("Change Password"),
        "settings": settings,
        "forced": bool(getattr(request.state.user, "must_change_password", False)),
    }
    error = None
    if len(new_password) < 8:
        error = "Password must be at least 8 characters."
    elif new_password != confirm_password:
        error = "Passwords do not match."
    if error:
        ctx["error"] = error
        return templates.TemplateResponse(request, "auth/change_password.html", ctx, status_code=status.HTTP_400_BAD_REQUEST)

    # Re-fetch the user in this session (request.state.user is detached).
    user = (await db.execute(select(User).where(User.username == request.state.user.username))).scalars().first()
    if not user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    user.hashed_password = get_password_hash(new_password)
    user.must_change_password = False
    await db.commit()

    res = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return _set_auth_cookie(res, user.username)
