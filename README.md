


Project Structure:
gallery-centric/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app entry point
│   ├── config.py                # Settings, env vars
│   ├── database.py              # SQLAlchemy engine + session
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── gallery.py           # Gallery, Page models
│   │   ├── tag.py               # Tag, TagType models
│   │   ├── artist.py
│   │   ├── character.py
│   │   ├── parody.py
│   │   ├── language.py
│   │   └── associations.py      # Many2many junction tables
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── gallery.py           # Pydantic schemas
│   │   ├── tag.py
│   │   └── search.py
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── frontend.py          # Public-facing HTML routes
│   │   ├── admin.py             # Admin routes
│   │   ├── api.py               # JSON API endpoints
│   │   └── search.py            # Search + filter routes
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── gallery_service.py   # Business logic
│   │   ├── search_service.py    # PostgreSQL full-text search
│   │   ├── image_service.py     # Upload, resize, WebP, thumbnails
│   │   └── zip_service.py       # ZIP bulk upload extraction
│   │
│   ├── templates/
│   │   ├── base.html            # Base layout
│   │   ├── partials/
│   │   │   ├── navbar.html
│   │   │   ├── footer.html
│   │   │   ├── gallery_card.html
│   │   │   ├── pagination.html
│   │   │   ├── tag_badge.html
│   │   │   ├── filter_sidebar.html
│   │   ├── pages/
│   │   │   ├── home.html
│   │   │   ├── gallery_detail.html
│   │   │   ├── reader.html
│   │   │   ├── search_results.html
│   │   │   ├── tag_page.html
│   │   │   ├── artist_page.html
│   │   │   └── 404.html
│   │   └── admin/
│   │       ├── dashboard.html
│   │       ├── gallery_form.html
│   │       ├── gallery_list.html
│   │       ├── tag_manager.html
│   │       └── upload.html
│   │
│   ├── static/
│   │   ├── css/
│   │   │   ├── main.css
│   │   │   ├── reader.css
│   │   │   └── admin.css
│   │   ├── js/
│   │   │   ├── reader.js        # Keyboard nav, progress, lazy load
│   │   │   ├── upload.js        # Drag and drop
│   │   │   └── filters.js       # Tag filter logic
│   │   └── img/
│   │       └── placeholder.webp
│   │
│   └── utils/
│       ├── __init__.py
│       ├── slugify.py
│       ├── pagination.py
│       └── seo.py
│
├── uploads/                     # Uploaded images (gitignored)
│   └── galleries/               # Organized by {gallery_slug}/
│
├── migrations/                  # Alembic migrations
│   └── versions/
│
├── tests/
│   ├── test_search.py
│   ├── test_upload.py
│   └── test_routes.py
│
├── .env                         # Environment variables
├── .env.example
├── alembic.ini
├── requirements.txt
├── docker-compose.yml
├── Dockerfile
└── README.md


====================================================
PROJECT NAME: gallery_centric
====================================================

a complete picture gallery web application using:

- FastAPI (async, Python 3.11+)
- HTMX 2.x (for dynamic UI without heavy JavaScript)
- Jinja2 (HTML templating)
- SQLAlchemy 2.x async ORM (PostgreSQL primary, SQLite fallback)
- Alembic (database migrations)
- PostgreSQL full-text search (tsvector/tsquery with tag-aware weighting)
- Pillow (image processing: resize, WebP conversion, thumbnail generation)
- Bootstrap 5.3 (responsive UI)
- python-multipart (file uploads)
- aiofiles (async file I/O)
- python-slugify (URL slug generation)
- python-jose + passlib (admin authentication)
- Docker + docker-compose (deployment)

====================================================
DATABASE MODELS (SQLAlchemy async)
====================================================

Use SQLAlchemy 2.x declarative_base with async sessions.

gallery_tags = Table(many2many junction)
gallery_artists = Table(many2many junction)
gallery_characters = Table(many2many junction)
gallery_parodies = Table(many2many junction)

class Gallery:
    id: int (primary key)
    title: str (indexed, not null)
    slug: str (unique, indexed)
    description: str (HTML, nullable)
    thumbnail_path: str
    cover_path: str
    language_id: int (FK)
    page_count: int (computed, stored)
    view_count: int (default 0)
    favorite_count: int (default 0)
    published_date: datetime
    seo_title: str
    seo_description: str
    is_published: bool (indexed, default False)
    sequence: int
    created_at: datetime (indexed)
    updated_at: datetime

    relationships:
    - pages: List[Page] (one2many)
    - tags: List[Tag] (many2many via gallery_tags)
    - artists: List[Artist] (many2many)
    - characters: List[Character] (many2many)
    - parodies: List[Parody] (many2many)
    - language: Language (many2one)

class Page:
    id: int
    gallery_id: int (FK, indexed)
    page_number: int
    image_path: str
    image_width: int
    image_height: int

class TagType:
    id: int
    name: str (unique)
    slug: str (unique)
    color: str (hex color for badges)
    is_visible: bool

class Tag:
    id: int
    name: str (indexed)
    slug: str (unique, indexed)
    tag_type_id: int (FK)
    description: str
    gallery_count: int (computed, cached)
    is_visible: bool

class Artist:
    id: int
    name: str (indexed)
    slug: str (unique)
    bio: str
    gallery_count: int

class Character:
    id: int
    name: str (indexed)
    slug: str (unique)
    gallery_count: int

class Parody:
    id: int
    name: str (indexed)
    slug: str (unique)
    gallery_count: int

class Language:
    id: int
    name: str
    code: str (e.g. "en", "ja", "ar")

Add PostgreSQL indexes on:

- gallery.title
- gallery.slug
- gallery.is_published
- gallery.created_at
- tag.name
- tag.slug

====================================================
IMAGE PROCESSING (image_service.py)
====================================================

On every image upload:

1. Convert to WebP format.
2. Generate thumbnail: 300x420px (cover ratio), quality 85.
3. Generate cover: 800x1100px, quality 90.
4. Store all assets in uploads/galleries/{gallery_slug}/
   - High-res cover: cover.webp
   - Card thumbnail: thumbnail.webp
   - Original pages: pages/{filename}.webp
   - Admin thumbnails: page_thumbs/{filename}_thumb.webp
5. Extract image dimensions using Pillow.
6. Save all paths relative to static root.

Thumbnail naming: {gallery_slug}_thumb.webp
Cover naming: {gallery_slug}_cover.webp
Page naming: {gallery_slug}_p{page_number:04d}.webp

====================================================
ZIP UPLOAD SERVICE (zip_service.py)
====================================================

Accept a .zip file upload containing images.

1. Extract to temp directory.
2. Filter only image files: jpg, jpeg, png, gif, webp.
3. Sort files by filename naturally (1.jpg, 2.jpg, 10.jpg not 1,10,2).
4. Convert each to WebP using image_service.
5. Create Page records sorted by filename.
6. Auto-generate thumbnail from first image.
7. Auto-generate cover from first image.
8. Update gallery page_count.
9. Clean up temp directory after processing.

====================================================
SEARCH SERVICE (search_service.py)
====================================================

Uses PostgreSQL native full-text search — no external search engine.

Search column: galleries.search_vector (tsvector, GIN-indexed)

The search_vector is maintained by database triggers (created by the
add_search_vector migration / setup.py) and weights:

- title -> weight A (highest)
- description -> weight B
- tag names -> weight C

Free-text queries use websearch_to_tsquery('english', ...) and rank with
ts_rank. Associations (tags/artists/characters/parodies), language, and
publish state are filtered directly via SQL joins/EXISTS.

Functions to implement:

- search(query, filters, sort, page, per_page) -> SearchResult

Note: there is no separate index to maintain — the triggers keep
search_vector in sync automatically on insert/update and on tag changes.

Search filters support:

- include_tags: List[str]
- exclude_tags: List[str]
- artists: List[str]
- characters: List[str]
- parodies: List[str]
- language: str

====================================================
FRONTEND ROUTES (frontend.py)
====================================================

GET /

- Query params: page, per_page (10/20/30/50), sort (latest/views/favorites/alpha)
- Load published galleries paginated
- HTMX: if HX-Request header, return only gallery grid partial
- Template: pages/home.html

GET /gallery/{slug}

- Load gallery with all relations eagerly
- Increment view_count (async, non-blocking)
- Load related galleries (shared tags, limit 8)
- Template: pages/gallery_detail.html

GET /read/{slug}

- Load gallery pages ordered by page_number
- Template: pages/reader.html

GET /search

- Query params: q, tags, artists, characters, parodies, language, page, per_page, sort
- Call search_service.search()
- HTMX: partial return for search results
- Template: pages/search_results.html

GET /tag/{slug}

- Load tag with galleries (paginated)
- Template: pages/tag_page.html

GET /artist/{slug}

- Load artist with galleries
- Template: pages/artist_page.html

GET /character/{slug}

- Load character with galleries
- Template: pages/character_page.html

GET /parody/{slug}

- Load parody with galleries
- Template: pages/parody_page.html

====================================================
ADMIN ROUTES (admin.py)
====================================================

All admin routes protected by HTTP Basic Auth or JWT.
Prefix: /admin

GET  /admin/                     -> dashboard with stats
GET  /admin/galleries            -> paginated gallery list
GET  /admin/galleries/new        -> new gallery form
POST /admin/galleries/new        -> create gallery
GET  /admin/galleries/{id}/edit  -> edit form
POST /admin/galleries/{id}/edit  -> update gallery
POST /admin/galleries/{id}/delete
POST /admin/galleries/{id}/publish
POST /admin/galleries/{id}/unpublish

POST /admin/galleries/{id}/upload-zip  -> ZIP bulk upload
POST /admin/galleries/{id}/upload-image -> single image upload
POST /admin/galleries/{id}/pages/reorder -> drag reorder pages
DELETE /admin/pages/{id}         -> delete single page

GET  /admin/tags                 -> tag manager
POST /admin/tags/new
POST /admin/tags/{id}/edit
POST /admin/tags/{id}/delete

GET  /admin/tag-types            -> tag type manager
POST /admin/tag-types/new
POST /admin/tag-types/{id}/edit
POST /admin/tag-types/{id}/delete

GET  /admin/artists
POST /admin/artists/new
POST /admin/artists/{id}/edit

GET  /admin/characters
GET  /admin/parodies
GET  /admin/languages

====================================================
HTMX BEHAVIOR
====================================================

Use HTMX for:

1. Search bar -> live search results (300ms debounce, hx-trigger="input changed delay:300ms")
2. Tag filter toggles -> update gallery grid without page reload
3. Pagination -> replace gallery grid only
4. Per-page selector -> update gallery grid
5. Sort selector -> update gallery grid
6. Admin: delete confirmations inline
7. Admin: publish/unpublish toggle

All HTMX responses return only the partial HTML fragment, not the full page.
Detect HTMX requests via HX-Request header.

====================================================
TEMPLATE STRUCTURE
====================================================

base.html:

- Bootstrap 5.3 CDN
- HTMX 2.x CDN
- Custom CSS link
- Dark mode toggle (localStorage)
- Navbar with search bar
- Main content block
- Footer

gallery_card.html (partial):

- Thumbnail image (lazy loading, aspect-ratio: 3/4)
- Title (truncated 2 lines)
- Tag badges (max 3 shown, +N more)
- Page count badge
- Hover: zoom + shadow

reader.html:

- Sticky top bar: title, page X of Y, back button
- Progress bar
- Long-strip vertical image list
- Each image: lazy loading with Intersection Observer
- Preload next 2 images
- Keyboard: ArrowRight/ArrowLeft or J/K for next/prev page
- Click right/left half for navigation (optional)
- Dark background default

filter_sidebar.html:

- Collapsible sections per tag type
- Checkboxes for include/exclude per tag
- Selected tags shown as removable badges
- "Clear all filters" button
- Apply button triggers HTMX search update

====================================================
SEO
====================================================

In base.html and each page template:

- <title>: seo_title or title + " | Site Name"
- <meta name="description">
- <meta property="og:title">
- <meta property="og:description">
- <meta property="og:image"> (thumbnail URL)
- <link rel="canonical">

Add route GET /sitemap.xml:

- List all published galleries
- Include lastmod from updated_at

Add route GET /robots.txt:

- Allow all, point to sitemap

====================================================
PERFORMANCE
====================================================

- Use async SQLAlchemy throughout (AsyncSession)
- Eager load relationships with selectinload() not lazy
- Add database connection pooling
- Use aiofiles for all file I/O
- Set Cache-Control headers on static files
- Compress responses with GZip middleware
- Use WebP for all images
- Lazy load images with loading="lazy" and Intersection Observer
- Thumbnail sizes kept small (under 30KB each)
- PostgreSQL GIN-indexed tsvector handles full-text search efficiently

====================================================
ENVIRONMENT VARIABLES (.env)
====================================================

DATABASE_URL=postgresql+asyncpg://user:pass@localhost/gallery_centric_db
SECRET_KEY=your_secret_key
ADMIN_USERNAME=admin
ADMIN_PASSWORD=changeme
UPLOAD_DIR=uploads
MAX_UPLOAD_SIZE_MB=500
SITE_NAME=GalleryCentric
BASE_URL=<https://yourdomain.com>
DEBUG=false

====================================================
DOCKER
====================================================

docker-compose.yml should include:

- app: FastAPI via uvicorn (port 8008)
- db: PostgreSQL (pgvector image, provides full-text search)
- nginx: reverse proxy, serve static files, gzip

====================================================
REQUIREMENTS.TXT
====================================================

fastapi>=0.111.0
uvicorn[standard]>=0.29.0
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.29.0
alembic>=1.13.0
jinja2>=3.1.0
python-multipart>=0.0.9
aiofiles>=23.2.0
pillow>=10.3.0
python-slugify>=8.0.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.0
python-dotenv>=1.0.0
httpx>=0.27.0

====================================================
DELIVERABLES
====================================================

Generate all files completely.
Do not use placeholder comments like # TODO or # implement this.
Every function must be fully implemented.
Every template must be complete HTML, not skeletons.
Include sample data seed script: seed.py
Include README.md with setup instructions.

Start with:

1. models/ (all models)
2. database.py
3. config.py
4. services/ (image, zip, search)
5. routers/ (frontend, admin, search)
6. templates/ (all pages and partials)
7. static/ (CSS and JS)
8. docker-compose.yml
9. alembic migration
10. seed.py
11. README.md
