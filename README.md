# Gallery Centric

A self-hosted image gallery web application. Upload galleries as ZIP archives or single images, organize them with tags, artists, characters, parodies, and languages, and browse them through a fast, HTMX-driven frontend with full-text search and a long-strip reader.

## Features

- **Gallery browsing** — paginated grid with sorting (latest, views, favorites, alphabetical), per-page selection, and lazy-loaded WebP thumbnails
- **Long-strip reader** — vertical reader with progress bar, keyboard navigation, and image preloading
- **Full-text search** — PostgreSQL native `tsvector` search (GIN-indexed, trigger-maintained) with weighted ranking: title > description > tag names; no external search engine
- **Tag filtering** — include/exclude filters for tags, artists, characters, parodies, and language, plus a tag browser and autocomplete
- **Admin panel** — gallery CRUD, publish/unpublish, ZIP bulk upload, single-image upload, page reordering, taxonomy management (tags, tag types, artists, characters, parodies, languages), and site/SEO settings
- **Image pipeline** — every upload is converted to WebP with generated cover, card thumbnail, and page thumbnails (Pillow)
- **Auth & security** — cookie-based auth (JWT), user registration with ALTCHA proof-of-work CAPTCHA, CSRF double-submit protection on all state-changing routes
- **Runtime configuration** — site name, SEO defaults, and secrets live in the database and are managed from the admin panel, not config files
- **Graceful degradation** — friendly 503 pages (HTML, HTMX partial, or JSON) when the database is unreachable

## Tech stack

- [FastAPI](https://fastapi.tiangolo.com/) (async, Python 3.11+) + Uvicorn
- SQLAlchemy 2.x async ORM + asyncpg + Alembic migrations
- PostgreSQL (full-text search via `tsvector`/`websearch_to_tsquery`)
- Jinja2 templates + HTMX 2.x + Bootstrap 5.3
- Pillow for image processing (WebP conversion, thumbnails)
- Docker + docker-compose (optional nginx reverse proxy for production)

## Quick start (Docker)

```bash
docker compose up -d
```

Then open <http://localhost:8008>. On first launch you are redirected to `/setup` to choose the admin password — after that the site is live and you land in the admin panel.

The `app` container's entrypoint runs `setup.py` automatically on every start. It is idempotent: it waits for PostgreSQL, creates the database and tables if missing, installs the full-text-search triggers, stamps Alembic at `head`, and creates the admin user. Set `SKIP_SETUP=1` to bypass it for one-off commands.

### Production (with nginx)

An nginx reverse proxy (static file serving, ports 80/443) is defined behind a compose profile:

```bash
docker compose --profile production up -d
```

Configuration lives in [nginx.conf](nginx.conf).

## Running without Docker

You need a reachable PostgreSQL server.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # point DATABASE_URL at your PostgreSQL server
python setup.py           # one-time bootstrap (safe to re-run)
uvicorn app.main:app --host 0.0.0.0 --port 8008 --reload
```

## Configuration

All configuration is via `.env` (see [.env.example](.env.example)):

| Variable | Purpose |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Credentials for the compose PostgreSQL container |
| `DATABASE_URL` | Async SQLAlchemy URL, e.g. `postgresql+asyncpg://user:pass@gallerydb/gallery_centric` |
| `BASE_URL` | Public base URL (enables `Secure` cookies when `https`) |
| `UPLOAD_DIR` | Where uploaded images are stored (default `uploads`) |
| `MAX_UPLOAD_SIZE_MB` | Upload size limit |
| `ADMIN_USERNAME` | Admin account username (created by `setup.py`) |
| `DEBUG` | Verbose error detail in 503 pages |

**Secrets are not set in `.env`.** `SECRET_KEY` and `ALTCHA_HMAC_KEY` are generated on first launch and stored (encrypted) in the database. The admin password is set interactively at `/setup` on first visit. Site name and SEO/social tags are configured in the admin panel (Settings) and stored in the database.

## Database migrations

Alembic migrations live in [migrations/versions/](migrations/versions/). After changing models:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

Inside Docker, prefix with `docker compose exec app`. Note the full-text-search functions and triggers are plain SQL (not ORM state) — they are defined both in the `add_search_vector` migration and in `setup.py`, and must be kept in sync if changed.

## Project structure

```
app/
├── main.py              # FastAPI app, CSRF middleware, error handlers
├── config.py            # .env-backed settings
├── database.py          # Async engine + session
├── models/              # SQLAlchemy models (gallery, page, tag, taxonomy, user, app_setting)
├── schemas/             # Pydantic schemas
├── routers/
│   ├── frontend.py      # Public pages: home, gallery, reader, search, tag/artist/... pages
│   ├── auth.py          # Login, register (ALTCHA), logout, change password
│   ├── setup.py         # First-run admin password setup
│   └── admin/           # Admin panel: galleries, taxonomy, settings
├── services/            # Image pipeline, ZIP extraction, search, runtime config, maintenance
├── templates/           # Jinja2: base, pages/, partials/, admin/, auth/
├── static/              # CSS + JS (reader, upload, filters)
└── utils/               # Auth, CSRF, deps, pagination, SEO, slugify, templates
migrations/              # Alembic environment + versions
uploads/                 # Uploaded images, organized per gallery slug (gitignored)
setup.py                 # Idempotent first-run bootstrap
entrypoint.sh            # Container entrypoint: setup.py then uvicorn
```
