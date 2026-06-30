from typing import Type
from pydantic import BaseModel
from fastapi import Request, Response, Depends
from fastapi.responses import RedirectResponse
import uuid

def _gen_slug(length: int = 8) -> str:
    return uuid.uuid4().hex[:length]

def redirect_to(request: Request, url: str) -> Response:
    if "hx-request" in request.headers:
        return Response(headers={"HX-Redirect": url})
    return RedirectResponse(url=url, status_code=302)

async def _get_form_data(request: Request) -> dict:
    form = await request.form()
    data = {}
    for key, value in form.multi_items():
        if key in data:
            if not isinstance(data[key], list):
                data[key] = [data[key]]
            data[key].append(value)
        else:
            data[key] = value
    return data

def form_body(model_class: Type[BaseModel]):
    async def dependency(request: Request):
        from typing import get_args, get_origin
        raw_data = await _get_form_data(request)
        normalized = {}
        
        for key, field in model_class.model_fields.items():
            annotation = field.annotation
            is_bool = (annotation is bool) or (bool in get_args(annotation))
            is_str = (annotation is str) or (str in get_args(annotation))
            is_list = (get_origin(annotation) is list) or (annotation is list)
            
            if key not in raw_data:
                if is_bool:
                    normalized[key] = False
                continue
                
            value = raw_data[key]
            if is_list:
                if not isinstance(value, list):
                    if value is None or value == "":
                        normalized[key] = []
                    else:
                        normalized[key] = [value]
                else:
                    normalized[key] = [v for v in value if v != ""]
            elif isinstance(value, str) and value == "" and not is_str:
                normalized[key] = None
            elif is_bool:
                if isinstance(value, str):
                    normalized[key] = value.lower() in ("true", "on", "1", "yes")
                else:
                    normalized[key] = bool(value)
            else:
                normalized[key] = value
                
        return model_class(**normalized)
    return Depends(dependency)
