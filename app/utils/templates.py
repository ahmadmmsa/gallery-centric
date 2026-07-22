"""Shared Jinja2Templates instance used by all routers.

Centralises the template directory and the `settings` global so each router
doesn't re-create its own environment.
"""
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.services import language_service, runtime_config

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["settings"] = settings
# `setting('SITE_NAME')` etc. -- DB-backed, admin-editable runtime config.
templates.env.globals["setting"] = runtime_config.get
templates.env.globals["public_languages"] = language_service.all_languages
