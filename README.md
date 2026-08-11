# SBK TaskManager API — FastAPI Port

A Python port of the [`pedmjm/sbk_laravel_app`](https://github.com/pedmjm/sbk_laravel_app)
Laravel task manager. Same domain (tareas, comentarios, técnicos, clientes,
sucursales, herramientas, polymorphic evidence photos), same Flet-friendly
endpoints, but rebuilt on **FastAPI + SQLAlchemy 2.0 (async) + JWT + OneSignal**.

The port also fixes every bug flagged in the Laravel review:

| Laravel bug | Fixed here |
|---|---|
| `ContactoController` used but never imported → API fatal at boot | N/A (Python) |
| Duplicate `tareas` / `pasos_tarea` migrations | Single source of truth per table in `models.py` |
| `imagenes.imageable_id` was BIGINT (numericMorphs) → truncated Tarea UUIDs | `String(36)` column, holds UUIDs from any parent |
| `comentarios.autor_id` FK type mismatch (UUID column → BIGINT users.id) | Consistently UUID FK → `users.id` |
| `AuthController::register` double-hashed the password | `hash_password()` called exactly once |
| `TareaController::update` validated `cliente` instead of `cliente_id` | Validates `cliente_id` |
| `TareaController::destroy` left orphan comment image files on disk | Deletes every comment's image files too |
| `LogApiRequests` middleware logged bearer tokens + passwords in plaintext | `log_requests` middleware redacts Authorization + password fields |
| Two unauthenticated web routes ran `migrate --force` / `storage:link` | Removed — use `python seed.py` and `mkdir storage` instead |
| No authorization anywhere | `require_nivel(min_level)` RBAC dependency on every mutating endpoint |
| `Cliente::$appends = ['total_sucursales']` caused N+1 queries | Counted via `outerjoin` subquery in a single statement |
| `HerramientaController` enum validation only allowed 4 of 8 enum values | All 8 enum values accepted consistently |
| Passport installed but never registered (5 unused tables + migrations) | Not ported — JWT + Sanctum-equivalent via `OAuth2PasswordBearer` |
| Stray `Comentario::find(10);` dump file committed to repo root | N/A |
| Default Laravel README | This file |

---

## Stack

| | |
|---|---|
| Web framework | FastAPI 0.115 |
| ASGI server | uvicorn 0.34 |
| ORM | SQLAlchemy 2.0 (async) |
| DB driver | `aiosqlite` (default) — swap to `asyncpg` for Postgres |
| Auth | `bcrypt` + `pyjwt` (stateless JWT, no DB session store needed) |
| Push notifications | OneSignal REST API via `httpx` |
| Validation | Pydantic v2 |
| File uploads | FastAPI `UploadFile` + `StaticFiles` mount at `/storage` |

---

## Project layout

```
sbk_fastapi/
├── .env.example
├── requirements.txt
├── database.py            # async engine + Base + get_db + create_all
├── models.py              # 10 SQLAlchemy 2.0 models + 2 M:N pivots
├── schemas.py             # Pydantic v2 schemas (Create/Update/Out per entity)
├── auth.py                # JWT + bcrypt + RBAC (require_nivel)
├── notifications.py       # OneSignal client + notify_users helper
├── storage_helpers.py     # save_upload / build_public_url / delete_rel_path
├── seed.py                # port of PersonalSeeder + HerramientaSeeder + ClienteSeeder
├── main.py                # FastAPI app + lifespan + router wiring + middleware
├── routers/
│   ├── __init__.py
│   ├── auth.py            # /auth/register | /auth/login | /auth/logout | /auth/me
│   ├── personal.py        # /tecnicos CRUD
│   ├── herramientas.py    # /herramientas CRUD
│   ├── clientes.py        # /clientes CRUD (with total_sucursales)
│   ├── sucursales.py      # /sucursales CRUD
│   ├── contactos.py       # /contactos CRUD
│   ├── tareas.py          # /tareas CRUD + pasos + image upload
│   ├── comentarios.py     # /tareas/{id}/comentarios + /comentarios/{id}
│   └── notifications.py   # /notifications/send + /notifications/test/{id}
└── storage/               # created at runtime; served at /storage/*
```

---

## Quick start

```bash
cd sbk_fastapi/

# 1. Create a virtualenv
python3 -m venv .venv
source .venv/bin/activate

# 2. Install deps
pip install -r requirements.txt

# 3. Configure env
cp .env.example .env
# Generate a SECRET_KEY:
python -c "import secrets; print(secrets.token_urlsafe(48))"  >> .env
# Edit .env and replace the SECRET_KEY line with the generated value.

# 4. Create tables + seed (Personal, Herramientas, Clientes+Sucursales+Contactos)
python seed.py

# 5. Run the dev server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000/docs for the Swagger UI.

---

## Auth flow

The Laravel app's "Personal whitelist" gate is preserved:

1. An admin creates a row in `personals` (via `POST /tecnicos`).
2. The technician registers via `POST /auth/register` with their cédula +
   email + password. Registration only succeeds if the cédula already
   exists in `personals`.
3. The technician logs in via `POST /auth/login` (OAuth2 password flow,
   accepts `username` = email + `password` as form-data) or
   `POST /auth/login/json` (JSON body).
4. The returned `access_token` is sent as `Authorization: Bearer <token>`
   on all protected endpoints.
5. `POST /auth/logout` is a no-op (JWT is stateless — the client just
   discards the token).

### Role levels (mapped from Laravel's `tipo_usuario`)

| `nivel` | Role | What they can do |
|---|---|---|
| 0 | Técnico | Read everything; create tareas & comentarios; delete own comentarios |
| 1 | Moderador | Same as Técnico |
| 2 | Admin | Also: create/update/delete personales, herramientas, clientes, sucursales, contactos |
| 5 | Super Admin | Same as Admin (reserved for future) |

---

## Endpoint reference

All endpoints except `/auth/*` require `Authorization: Bearer <jwt>`.

### Auth
| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | JSON body; cédula must exist in `personals` |
| POST | `/auth/login` | OAuth2 form-data (`username` + `password`) |
| POST | `/auth/login/json` | JSON body (`{email, password}`) |
| POST | `/auth/logout` | Stateless — client discards token |
| GET  | `/auth/me` | Returns the current user |

### Técnicos (Personal)
| Method | Path | RBAC |
|---|---|---|
| GET | `/tecnicos` | any auth user |
| GET | `/tecnicos/{id}` | any auth user |
| POST | `/tecnicos` | admin+ |
| PUT | `/tecnicos/{id}` | admin+ |
| DELETE | `/tecnicos/{id}` | admin+ |

### Herramientas
| Method | Path | RBAC |
|---|---|---|
| GET | `/herramientas` | any auth user |
| GET | `/herramientas/{id}` | any auth user |
| POST | `/herramientas` | admin+ |
| PUT | `/herramientas/{id}` | admin+ |
| DELETE | `/herramientas/{id}` | admin+ |

### Clientes / Sucursales / Contactos
| Method | Path | RBAC |
|---|---|---|
| GET | `/clientes` | any auth user (includes `total_sucursales` aggregate) |
| GET | `/clientes/{id}` | any auth user (eager-loads sucursales + contactos) |
| POST/PUT/DELETE | `/clientes/{id}` | admin+ |
| POST/PUT/DELETE | `/sucursales/{id}` | admin+ |
| POST/PUT/DELETE | `/contactos/{id}` | admin+ |

### Tareas
| Method | Path | Notes |
|---|---|---|
| GET | `/tareas` | Lists all with 6 eager-loaded relations |
| POST | `/tareas` | `multipart/form-data` — see below |
| GET | `/tareas/{id}` | Full detail incl. comentarios |
| PUT | `/tareas/{id}` | JSON body; `personal_ids` / `herramienta_ids` use `sync()` semantics |
| DELETE | `/tareas/{id}` | Cleans up tarea's + every comentario's image files |
| POST | `/tareas/{id}/pasos` | Add a checklist step |
| PUT | `/tareas/{id}/pasos/{paso_id}` | Toggle completado / edit fields |
| DELETE | `/tareas/{id}/pasos/{paso_id}` | Remove a step |
| POST | `/tareas/{id}/imagenes` | Attach evidence photos |

#### `POST /tareas` body (multipart/form-data)

Mirrors the Laravel endpoint shape so the existing Flet client keeps working
without changes:

```
cliente_id:        <uuid>
sucursal_id:       <uuid>
titulo:            <str>
descripcion:       <str, optional>
prioridad:         Baja|Media|Alta|Urgente   (default: Media)
fecha_programada:  YYYY-MM-DD, optional
fecha_limite:      YYYY-MM-DD, optional
personal_ids:      ["<uuid>", "<uuid>"]       (JSON-encoded list)
herramienta_ids:   ["<uuid>", "<uuid>"]       (JSON-encoded list)
pasos:             [{"actividad":"...","metodo":"...","requerimiento":"..."}]  (JSON-encoded list)
imagenes:          <file>                      (repeat for multiple)
```

### Comentarios
| Method | Path | Notes |
|---|---|---|
| GET | `/tareas/{tarea_id}/comentarios` | Newest first |
| POST | `/tareas/{tarea_id}/comentarios` | Multipart: `texto` (optional) + `imagenes[]` (optional). Must have at least one. |
| DELETE | `/comentarios/{comentario_id}` | Author or admin |

### Notifications
| Method | Path | Notes |
|---|---|---|
| POST | `/notifications/send` | Manual push to a single user. Self or admin. |
| GET | `/notifications/test/{user_id}` | Send a fixed test message |

Automatic notifications are also fired:
- When a `Tarea` is created with `personal_ids`, push goes to every User
  whose `cedula` matches an assigned Personal.
- When a `Comentario` is created, push goes to the tarea's creator + every
  assigned Personal's linked User — minus the comment's author.

To enable actual OneSignal calls (vs. just logging the payload), set
`ONESIGNAL_ENABLED=1` in `.env`. Default is `0` for local dev.

---

## Storage

Uploaded evidence photos are stored under `./storage/{subdir}/{parent_id}/`
where `subdir` is `tareas` or `comentarios`, and `parent_id` is the
owning entity's UUID. Files are served at `/storage/{subdir}/{parent_id}/{filename}`
via FastAPI's `StaticFiles` mount.

The DB stores only the **relative path** (`tareas/abc-123/xyz.png`); the
public URL is derived on read via `storage_helpers.build_public_url()`,
which reads `APP_URL` from the environment. This fixes the Laravel bug
where the full URL (including host) was persisted at write time, so
changing `APP_URL` later broke every existing image.

---

## Migrating from the Laravel app

### Data migration

If you have data in the Laravel SQLite/MySQL DB that you need to bring
over, dump each table to JSON and write a one-off Python script that
inserts via the SQLAlchemy models. The schema is intentionally close
(field names match exactly), with two exceptions:

1. `tareas.creador_id` is now always a UUID FK → `users.id` (the Laravel
   first migration had it pointing at `personals`).
2. `imagenes.imageable_id` is now `String(36)` (was BIGINT in Laravel).
   If you have existing Tarea image rows in Laravel where `imageable_id`
   was somehow stored as a truncated int, those rows are unrecoverable —
   re-upload the photos.

### Client (Flet app) changes

The Flet client only needs three changes:

1. **Auth header**: Sanctum uses `Bearer <token>` — JWT also uses
   `Bearer <token>`. No change needed.
2. **Endpoint URLs**: identical path shapes (`/api/tareas`, `/api/tecnicos`,
   etc.). You can either mount this FastAPI app under `/api` (via a proxy
   or `app.include_router(..., prefix="/api")`) or update the Flet client's
   base URL.
3. **Login endpoint**: Laravel's was `POST /api/login` with JSON body
   `{email, password}`. FastAPI's `/auth/login` uses OAuth2 form-data
   by default (for Swagger UI compatibility), but `/auth/login/json`
   accepts the exact same JSON body as Laravel — point the Flet client
   there.

---

## Production notes

- Set `APP_ENV=production`, `APP_DEBUG=false`, `LOG_LEVEL=warning`.
- Generate a strong `SECRET_KEY` (≥ 48 chars).
- Switch `DATABASE_URL` to Postgres: `postgresql+asyncpg://...`
  (also swap `aiosqlite` for `asyncpg` in `requirements.txt`).
- Set `ONESIGNAL_ENABLED=1` and fill in your real OneSignal credentials.
- Run behind `uvicorn` (or `gunicorn -k uvicorn.workers.UvicornWorker`)
  with multiple workers — JWT auth is stateless so horizontal scaling is fine.
- Replace `create_db_and_tables()` in the lifespan with Alembic migrations
  for schema evolution.
- Put `/storage` behind a CDN or S3 for real traffic — the local
  `StaticFiles` mount is fine for dev / single-node deployments.
