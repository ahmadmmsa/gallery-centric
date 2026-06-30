from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Query, Form, BackgroundTasks, HTTPException, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
import asyncio

from app.database import get_db
from app.utils.auth import get_admin_user, get_password_hash
from app.models.gallery import Gallery, Page
from app.models.user import User
from app.models.tag import Tag
from app.models.artist import Artist
from app.models.character import Character
from app.models.parody import Parody
from app.models.language import Language

from app.schemas.admin import AdminUserCreateRequest, AdminUserUpdateRequest
from app.services import maintenance_service
from app.utils.db_utils import safe_execute_all

from app.routers.admin.helpers import form_body, redirect_to
from app.routers.admin.gallery import gallery_router
from app.routers.admin.taxonomy import taxonomy_router

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")
from app.config import settings
templates.env.globals["settings"] = settings

router.include_router(gallery_router)
router.include_router(taxonomy_router)

async def safe_count(db, model, condition=None):
    stmt = select(func.count()).select_from(model)
    if condition is not None:
        stmt = stmt.where(condition)
    try:
        return await db.scalar(stmt) or 0
    except Exception:
        return 0

@router.get("/")
async def admin_dashboard(request: Request, admin = Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    (
        gallery_count, published_count, page_count,
        tag_count, artist_count, character_count, parody_count,
    ) = await asyncio.gather(
        safe_count(db, Gallery),
        safe_count(db, Gallery, Gallery.is_published == True),
        safe_count(db, Page),
        safe_count(db, Tag),
        safe_count(db, Artist),
        safe_count(db, Character),
        safe_count(db, Parody)
    )
    top_galleries_stmt = (
        select(Gallery).where(Gallery.is_published == True)
        .order_by(Gallery.page_count.desc()).limit(5).options(selectinload(Gallery.tags))
    )
    top_galleries = await safe_execute_all(db, top_galleries_stmt)
    recent_stmt = (select(Gallery).order_by(Gallery.created_at.desc()).limit(5).options(selectinload(Gallery.tags)))
    recent_galleries = await safe_execute_all(db, recent_stmt)
    empty_galleries_stmt = (select(Gallery).where(Gallery.page_count == 0).limit(5))
    empty_galleries = await safe_execute_all(db, empty_galleries_stmt)

    popular_tags_stmt = (
        select(Tag.name, func.count(Gallery.id).label('usage_count'))
        .join(Tag.galleries).group_by(Tag.id).order_by(desc('usage_count')).limit(10)
    )
    try:
        popular_tags_result = await db.execute(popular_tags_stmt)
        popular_tags = popular_tags_result.all() 
    except Exception as e:
        print(f"Error fetching popular tags: {e}")
        popular_tags = []
    context = {
        "request": request,
        "admin": admin,
        "stats": {
            "total_galleries": gallery_count,
            "published_galleries": published_count,
            "total_pages": page_count,
            "total_tags": tag_count,
            "total_artists": artist_count,
            "total_characters": character_count,
            "total_parodies": parody_count,
            "popular_tags": popular_tags,
        },
        "recent_galleries": recent_galleries,
        "top_galleries": top_galleries,
        "empty_galleries": empty_galleries
    }
    return templates.TemplateResponse(request, "admin/dashboard.html", context)


@router.get("/languages")
async def language_list(request: Request,admin = Depends(get_admin_user),db: AsyncSession = Depends(get_db)):
    stmt = select(Language).order_by(Language.name)
    result = await db.execute(stmt)
    languages = result.scalars().all()
    context = {"request": request,"admin": admin,"languages": languages}
    return templates.TemplateResponse(request, "admin/language_manager.html", context)

@router.get("/users")
async def user_list(request: Request, admin = Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    stmt = select(User).order_by(User.created_at.desc())
    result = await db.execute(stmt)
    users = result.scalars().all()
    context = {"request": request,"admin": admin,"users": users}
    return templates.TemplateResponse(request, "admin/user_manager.html", context)

@router.get("/users/check_username")
async def user_check_username(
    request: Request,
    username: str = Query(""),
    current_id: Optional[int] = Query(None),
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    if not username:
        return {"available": True, "message": ""}
    stmt = select(User).where(User.username == username)
    if current_id:
        stmt = stmt.where(User.id != current_id)
    existing = await db.execute(stmt)
    if existing.scalars().first():
        return {"available": False, "message": f'Username "{username}" is already taken.'}
    return {"available": True, "message": f'Username "{username}" is available.'}

@router.post("/users/new")
async def user_create(
    request: Request,
    data: AdminUserCreateRequest = form_body(AdminUserCreateRequest),
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where((User.username == data.username) | (User.email == data.email)))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Username or email already exists")
    user = User(
        username=data.username,
        email=data.email,
        hashed_password=get_password_hash(data.password),
        is_admin=data.is_admin,
        is_active=data.is_active
    )
    db.add(user)
    await db.commit()
    return redirect_to(request, "/admin/users")

@router.post("/users/{user_id}/edit")
async def user_update(
    request: Request,
    user_id: int,
    data: AdminUserUpdateRequest = form_body(AdminUserUpdateRequest),
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    existing = await db.execute(
        select(User).where(
            ((User.username == data.username) | (User.email == data.email)) & 
            (User.id != user_id)
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Username or email already taken by another user")
    user.username = data.username
    user.email = data.email
    user.is_admin = data.is_admin
    user.is_active = data.is_active
    if data.password:
        user.hashed_password = get_password_hash(data.password)
    await db.commit()
    return redirect_to(request, "/admin/users")

@router.post("/users/{user_id}/delete")
async def user_delete(
    request: Request,
    user_id: int,
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()
    return redirect_to(request, "/admin/users")

@router.post("/maintenance/cleanup")
async def run_system_cleanup(
    request: Request,
    background_tasks: BackgroundTasks,
    execute: bool = Query(False),
    admin = Depends(get_admin_user)):
    status_data = await maintenance_service.get_maintenance_status()
    if status_data.get("status") == "running":
        return Response(status_code=400, content="Task already running")
    background_tasks.add_task(maintenance_service.run_cleanup_task, execute)
    return templates.TemplateResponse(request, "admin/partials/maintenance_result.html", 
    {"status_data": {"status": "running", "execute": execute}})

@router.get("/maintenance/status")
async def get_system_cleanup_status(
    request: Request,
    admin = Depends(get_admin_user)):
    status_data = await maintenance_service.get_maintenance_status()
    return templates.TemplateResponse(request, "admin/partials/maintenance_result.html", {"status_data": status_data})
