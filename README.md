# Gallery Centric

A self-hosted image gallery web application. Upload galleries as ZIP archives or single images, organize them with tags, artists, characters, parodies, and languages, and browse them through a fast, HTMX-driven frontend with full-text search and a long-strip reader.

## Features

- **Gallery browsing** — paginated grid with sorting (latest, views, favorites, alphabetical), per-page selection, and lazy-loaded WebP thumbnails
- **Long-strip reader** — vertical reader with progress bar, keyboard navigation, and image preloading
- **Full-text search** — PostgreSQL native `tsvector` search (GIN-indexed, trigger-maintained) with weighted ranking: title > description > tag names; no external search engine
- **Tag filtering** — include/exclude filters for tags, artists, characters, parodies, and language, plus a tag browser and autocomplete
- **Admin panel** — gallery CRUD, publish/unpublish, ZIP bulk upload, single-image upload, page reordering, taxonomy management (tags, tag types, artists, characters, parodies, languages), and site/SEO settings
- **Image pipeline** — every upload is converted to WebP with generated cover, card thumbnail, and page thumbnails (Pillow)
- **Favorites** — logged-in users can favorite galleries from the card grid or the gallery page (HTMX toggle) and browse them at `/favorites`
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

Then open <http://localhost:8008>. On first launch you are redirected to `/setup` to choose the admin username and password (and optionally the site name and public base URL) — after that the site is live and you land in the admin panel.

There is no `.env` file and nothing to configure up front: the database password is generated automatically on first boot (`data/db_password`, created by the `db-init` compose service and shared with PostgreSQL), and everything else lives in the database.

The `app` container's entrypoint runs `setup.py` automatically on every start. It is idempotent: it waits for PostgreSQL, creates the database if missing, applies all Alembic migrations, generates runtime secrets, and creates the placeholder admin user when needed. Set `SKIP_SETUP=1` to bypass it for one-off commands.

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
export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/gallery
python setup.py           # one-time bootstrap (safe to re-run)
uvicorn app.main:app --host 0.0.0.0 --port 8008 --reload
```

## Configuration

There is no `.env` file. Configuration lives in three places:

| Where | What | Set how |
|---|---|---|
| `data/db_password` | Generated database password (the only pre-database secret) | Auto-generated on first `docker compose up`; chmod 600, gitignored |
| `app_settings` table | Base URL, upload size limit, site name/description, SEO/social tags, generated secrets (`SECRET_KEY`, `ALTCHA_HMAC_KEY`, stored encrypted) | First-run `/setup` wizard, then the admin panel (Settings / SEO) |
| [app/config.py](app/config.py) | Structural constants: upload directory, JWT algorithm, token lifetime | Edit the code |

Environment variables are honoured only as developer overrides for running outside compose: `DATABASE_URL` (external database), `DB_HOST`, and `DEBUG=1` (verbose error detail in 503 pages). None are required.

The admin account is created as a placeholder by `setup.py`; its username and password are chosen interactively at `/setup` on first visit, and the password is stored bcrypt-hashed.

## Database migrations

Alembic migrations live in [migrations/versions/](migrations/versions/). After changing models:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

Inside Docker, prefix with `docker compose exec app`. The container entrypoint runs `alembic upgrade head` before starting the application, so pending migrations are applied automatically. Full-text-search functions and triggers are migration-owned SQL and must be updated through a new Alembic revision when their behavior changes.

## Project structure

```
app/
├── main.py              # FastAPI app, CSRF middleware, error handlers
├── config.py            # Structural constants + DATABASE_URL from data/db_password
├── database.py          # Async engine + session
├── models/              # SQLAlchemy models (gallery, page, tag, taxonomy, user, app_setting)
├── schemas/             # Pydantic schemas
├── routers/
│   ├── frontend.py      # Public pages: home, gallery, reader, search, tag/artist/... pages
│   ├── auth.py          # Login, register (ALTCHA), logout, change password
│   ├── setup.py         # First-run setup wizard (admin account, site basics)
│   └── admin/           # Admin panel: galleries, taxonomy, settings
├── services/            # Image pipeline, ZIP extraction, search, runtime config, maintenance
├── templates/           # Jinja2: base, pages/, partials/, admin/, auth/
├── static/              # CSS + JS (reader, upload, filters)
└── utils/               # Auth, CSRF, deps, pagination, SEO, slugify, templates
migrations/              # Alembic environment + versions
media/                   # Uploaded images, organized per gallery slug (gitignored)
setup.py                 # Idempotent first-run bootstrap
entrypoint.sh            # Container entrypoint: setup.py then uvicorn
```
