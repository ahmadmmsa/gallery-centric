from typing import Optional, Type, Any, List
from pydantic import BaseModel
from fastapi import APIRouter, Request, Depends, Query, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, case
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.utils.auth import get_admin_user
from app.models.tag import Tag, TagType
from app.models.artist import Artist
from app.models.character import Character
from app.models.parody import Parody

from app.schemas.admin import (
    TagCreateRequest, TagUpdateRequest, TagTypeCreateRequest, TagTypeUpdateRequest,
    ArtistCreateRequest, ArtistUpdateRequest, CharacterCreateRequest, CharacterUpdateRequest,
    ParodyCreateRequest, ParodyUpdateRequest
)

from app.routers.admin.helpers import form_body, redirect_to, _gen_slug
from app.utils.templates import templates

taxonomy_router = APIRouter()

async def _resolve_tag_type(db: AsyncSession, type_name: str, fallback_to_misc: bool = False) -> TagType:
    sanitized_type_name = "".join(c for c in type_name if c.isalnum())
    if not sanitized_type_name:
        if fallback_to_misc:
            sanitized_type_name = "misc"
        else:
            raise HTTPException(status_code=400, detail="Tag type name must contain at least one alphanumeric character")
    type_stmt = select(TagType).where(TagType.slug == sanitized_type_name)
    tag_type = (await db.execute(type_stmt)).scalars().first()
    if not tag_type:
        tag_type = TagType(
            name=sanitized_type_name,
            slug=sanitized_type_name,
            color="#6c757d",
            is_visible=True
        )
        db.add(tag_type)
        await db.flush()
    return tag_type

def _validate_tag_type_name(name: str) -> str:
    sanitized = "".join(c for c in name if c.isalnum())
    if not sanitized:
        raise HTTPException(status_code=400, detail="Tag type name must contain at least one alphanumeric character")
    return sanitized

def register_crud_routes(
    router: APIRouter,
    prefix: str,
    model_class,
    create_schema: Type[BaseModel],
    update_schema: Type[BaseModel],
    template_name: str,
    context_key: str,
    item_name: str,
    check_name_handler = None,
    create_handler = None,
    update_handler = None,
    query_options = None,
    list_context_hook = None,):
    
    async def list_items(
        request: Request,
        admin = Depends(get_admin_user),
        db: AsyncSession = Depends(get_db)
    ):
        stmt = select(model_class).order_by(model_class.name)
        if query_options:
            stmt = stmt.options(*query_options)
        result = await db.execute(stmt)
        items = result.scalars().all()
        context = {
            "request": request,
            "admin": admin,
            context_key: items
        }
        if list_context_hook:
            await list_context_hook(db, context)
        return templates.TemplateResponse(request, template_name, context)

    async def check_name(
        request: Request,
        name: str = Query(""),
        current_id: Optional[int] = Query(None),
        admin = Depends(get_admin_user),
        db: AsyncSession = Depends(get_db)
    ):
        if check_name_handler:
            return await check_name_handler(db, name, current_id, request)
            
        if not name:
            return {"available": True, "message": ""}
            
        stmt = select(model_class).where(model_class.name == name)
        if current_id:
            stmt = stmt.where(model_class.id != current_id)
            
        existing = await db.execute(stmt)
        if existing.scalars().first():
            return {"available": False, "message": f'{item_name.capitalize()} name "{name}" is already taken.'}
        return {"available": True, "message": f'{item_name.capitalize()} name "{name}" is available.'}

    async def create_item(
        request: Request,
        data = form_body(create_schema),
        admin = Depends(get_admin_user),
        db: AsyncSession = Depends(get_db)
    ):
        if create_handler:
            await create_handler(db, data)
        else:
            slug = _gen_slug()
            attrs = {
                "name": data.name,
                "slug": slug,
            }
            if hasattr(data, "bio"):
                attrs["bio"] = data.bio
                
            item = model_class(**attrs)
            db.add(item)
            await db.commit()
            
        return RedirectResponse(url=f"/admin/{prefix}", status_code=302)

    async def update_item(
        request: Request,
        item_id: int,
        data = form_body(update_schema),
        admin = Depends(get_admin_user),
        db: AsyncSession = Depends(get_db)
    ):
        item = await db.get(model_class, item_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"{item_name.capitalize()} not found")
            
        if update_handler:
            await update_handler(db, item, data)
        else:
            if item.name != data.name or not item.slug:
                item.slug = _gen_slug()
                
            item.name = data.name
            if hasattr(data, "bio"):
                item.bio = data.bio
                
            await db.commit()
            
        return RedirectResponse(url=f"/admin/{prefix}", status_code=302)

    async def delete_item(
        request: Request,
        item_id: int,
        admin = Depends(get_admin_user),
        db: AsyncSession = Depends(get_db)
    ):
        item = await db.get(model_class, item_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"{item_name.capitalize()} not found")
            
        await db.delete(item)
        await db.commit()
        return redirect_to(request, f"/admin/{prefix}")

    router.add_api_route(f"/{prefix}", list_items, methods=["GET"])
    router.add_api_route(f"/{prefix}/check_name", check_name, methods=["GET"])
    router.add_api_route(f"/{prefix}/new", create_item, methods=["POST"])
    router.add_api_route(f"/{prefix}/{{item_id}}/edit", update_item, methods=["POST"])
    router.add_api_route(f"/{prefix}/{{item_id}}/delete", delete_item, methods=["POST"])

async def _check_tag_name_handler(db: AsyncSession, name: str, current_id: Optional[int], request: Request):
    if not name:
        return {"available": True, "message": ""}
    parts = name.split(":")
    base_name = parts[-1].strip()
    tag_type = request.query_params.get("tag_type")
    if len(parts) > 1:
        full_name = name
    elif tag_type:
        sanitized_type_name = "".join(c for c in tag_type if c.isalnum())
        full_name = f"{sanitized_type_name}:{base_name}"
    else:
        full_name = base_name
    stmt = select(Tag).where(Tag.name == full_name)
    if current_id:
        stmt = stmt.where(Tag.id != current_id)
    existing = await db.execute(stmt)
    if existing.scalars().first():
        return {"available": False, "message": f'Tag name "{full_name}" is already taken.'}
    return {"available": True, "message": f'Tag name "{full_name}" is available.'}

async def _create_tag_handler(db: AsyncSession, data: TagCreateRequest):
    tag_type = await _resolve_tag_type(db, data.tag_type, fallback_to_misc=False)
    parts = data.name.split(":")
    base_name = parts[-1].strip()
    name = f"{tag_type.name}:{base_name}"
    slug = _gen_slug()
    tag = Tag(
        name=name,
        slug=slug,
        tag_type_id=tag_type.id,
        description=data.description,
        is_visible=data.is_visible
    )
    db.add(tag)
    await db.commit()

async def _update_tag_handler(db: AsyncSession, tag: Tag, data: TagUpdateRequest):
    tag_type = await _resolve_tag_type(db, data.tag_type, fallback_to_misc=False)
    parts = data.name.split(":")
    base_name = parts[-1].strip()
    name = f"{tag_type.name}:{base_name}"
    if tag.name != name or not tag.slug:
        tag.slug = _gen_slug()
    tag.name = name
    tag.tag_type_id = tag_type.id
    tag.description = data.description
    tag.is_visible = data.is_visible
    await db.commit()

async def _tag_list_context_hook(db: AsyncSession, context: dict):
    tag_types_result = await db.execute(select(TagType).order_by(TagType.name))
    context["tag_types"] = tag_types_result.scalars().all()

register_crud_routes(
    router=taxonomy_router,
    prefix="tags",
    model_class=Tag,
    create_schema=TagCreateRequest,
    update_schema=TagUpdateRequest,
    template_name="admin/tag_manager.html",
    context_key="tags",
    item_name="tag",
    check_name_handler=_check_tag_name_handler,
    create_handler=_create_tag_handler,
    update_handler=_update_tag_handler,
    query_options=[selectinload(Tag.tag_type)],
    list_context_hook=_tag_list_context_hook,
)
register_crud_routes(
    router=taxonomy_router,
    prefix="artists",
    model_class=Artist,
    create_schema=ArtistCreateRequest,
    update_schema=ArtistUpdateRequest,
    template_name="admin/artist_manager.html",
    context_key="artists",
    item_name="artist",
)
register_crud_routes(
    router=taxonomy_router,
    prefix="characters",
    model_class=Character,
    create_schema=CharacterCreateRequest,
    update_schema=CharacterUpdateRequest,
    template_name="admin/character_manager.html",
    context_key="characters",
    item_name="character",
)
register_crud_routes(
    router=taxonomy_router,
    prefix="parodies",
    model_class=Parody,
    create_schema=ParodyCreateRequest,
    update_schema=ParodyUpdateRequest,
    template_name="admin/parody_manager.html",
    context_key="parodies",
    item_name="parody",
)

@taxonomy_router.get("/tag-types")
async def tag_type_list(request: Request, admin = Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    """List all tag types"""
    stmt = select(TagType).order_by(TagType.name)
    result = await db.execute(stmt)
    tag_types = result.scalars().all()
    context = {"request": request,"admin": admin,"tag_types": tag_types}
    return templates.TemplateResponse(request, "admin/tag_type_manager.html", context)

@taxonomy_router.post("/tag-types/new")
async def tag_type_create(
    request: Request,
    data: TagTypeCreateRequest = form_body(TagTypeCreateRequest),
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    sanitized_name = _validate_tag_type_name(data.name)
    tag_type = TagType(
        name=sanitized_name,
        slug=sanitized_name.lower().replace(" ", "-"),
        color=data.color,
        is_visible=data.is_visible
    )
    db.add(tag_type)
    await db.commit()
    return RedirectResponse(url="/admin/tag-types", status_code=302)

@taxonomy_router.post("/tag-types/{tag_type_id}/edit")
async def tag_type_update(
    request: Request,
    tag_type_id: int,
    data: TagTypeUpdateRequest = form_body(TagTypeUpdateRequest),
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    tag_type = await db.get(TagType, tag_type_id)
    if not tag_type:
        raise HTTPException(status_code=404, detail="Tag type not found")
    sanitized_name = _validate_tag_type_name(data.name)
    tag_type.name = sanitized_name
    tag_type.color = data.color
    tag_type.is_visible = data.is_visible
    await db.commit()
    return RedirectResponse(url="/admin/tag-types", status_code=302)

@taxonomy_router.post("/tag-types/{tag_type_id}/delete")
async def tag_type_delete(
    request: Request,
    tag_type_id: int,
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)):
    tag_type = await db.get(TagType, tag_type_id)
    if not tag_type:
        raise HTTPException(status_code=404, detail="Tag type not found")
    await db.delete(tag_type)
    await db.commit()
    return redirect_to(request, "/admin/tag-types")

MODEL_MAP = {
    "tag": { "model": Tag, "field": "tag_ids", },
    "artist": { "model": Artist, "field": "artist_ids",},
    "character": { "model": Character, "field": "character_ids", },
    "parody": { "model": Parody, "field": "parody_ids", },
}

@taxonomy_router.get("/taxonomy/search")
async def taxonomy_search(
    request: Request,
    q: str = Query(""),
    type: str = Query("tag"),
    tag_type: Optional[str] = Query(None),
    admin = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),):
    config = MODEL_MAP.get(type)
    if not config or not q.strip():
        return templates.TemplateResponse(request,"admin/components/tag_results.html",{"request": request,"results": [],"query": q,"type": type,"tag_type": tag_type})
    model = config["model"]
    
    if type == "tag" and tag_type:
        search_q = f"{tag_type}:{q}"
        stmt = select(model).where(model.name.ilike(f"{search_q}%")).order_by(case((model.name.ilike(search_q), 0), else_=1),model.name).limit(8)
    else:
        stmt = select(model).where(model.name.ilike(f"{q}%")).order_by(case((model.name.ilike(q), 0), else_=1),model.name).limit(8)
        
    results = (await db.execute(stmt)).scalars().all()
    return templates.TemplateResponse(request,"admin/components/tag_results.html",
    {"request": request,"results": results,"query": q,"type": type,"tag_type": tag_type})

@taxonomy_router.post("/taxonomy/create")
async def taxonomy_create(request: Request,name: str = Form(...),type: str = Form(...),tag_type: Optional[str] = Form(None),admin = Depends(get_admin_user),db: AsyncSession = Depends(get_db),):
    config = MODEL_MAP.get(type)
    if not config:
        return templates.TemplateResponse(request, "admin/components/error_chip.html", {"request": request, "msg": "Invalid taxonomy type"})
    model = config["model"]
    if model == Tag:
        parts = name.split(":")
        base_name = parts[-1].strip()
        type_name = parts[0].strip() if len(parts) > 1 else (tag_type or "misc")
        tag_type = await _resolve_tag_type(db, type_name, fallback_to_misc=True)
        full_name = f"{tag_type.name}:{base_name}"
        obj = Tag(
            name=full_name,
            slug=full_name.lower().replace(" ", "-"),
            tag_type_id=tag_type.id,
            is_visible=True
        )
    else:
        obj = model(
            name=name,
            slug=name.lower().replace(" ", "-")
        )
    db.add(obj)
    
    try:
        await db.commit()
        await db.refresh(obj)
    except IntegrityError:
        await db.rollback()
        stmt = select(model).where(model.name == obj.name)
        obj = (await db.execute(stmt)).scalars().first()

    response = templates.TemplateResponse(request,"admin/components/tag_chip.html",{"request": request,"item": obj,"field_name": config["field"],"type": type,"clear_input": True,})
    response.headers["HX-Trigger"] = f"clear-{type}-input"
    return response



@taxonomy_router.get("/taxonomy/chip")
async def taxonomy_chip(request: Request,id: int,type: str,admin = Depends(get_admin_user),db: AsyncSession = Depends(get_db),):
    config = MODEL_MAP.get(type)
    if not config:
        raise HTTPException(status_code=400, detail="Invalid taxonomy type")
    obj = await db.get(config["model"], id)
    return templates.TemplateResponse(request,
        "admin/components/tag_chip.html", {"request": request,"item": obj,"field_name": config["field"],"type": type,"clear_input": True,},
    )
