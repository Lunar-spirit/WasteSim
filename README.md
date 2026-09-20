# SWMS Backend — Drop 1 (Evaluation 1)

FastAPI + SQLAlchemy 2.0 async + PostGIS backend implementing the five Drop 1
features: auth/RBAC, habitation registry, immutable parameter versioning, the
6-stage validation pipeline, and GIS layer/feature storage.

## Setup

```bash
docker compose up -d db
```

Wait for the healthcheck to pass, then run migrations:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Or run everything in Docker:

```bash
docker compose up --build
```

Open http://localhost:8000/docs for the interactive Swagger UI.

## Demo script

Drop 1 has no user-management endpoint (an ADMIN would be needed to create
the first ADMIN — a chicken-and-egg problem), so the very first
PLANNER/ADMIN account is bootstrapped directly against the database:

```bash
# 1. Register normally via the API (or let seed_demo.py do it) — always lands as RESEARCHER
curl -X POST localhost:8000/api/v1/auth/register -H "Content-Type: application/json" \
  -d '{"email":"planner.shirva@example.com","password":"SecurePass123!","full_name":"Shirva Planner"}'

# 2. Promote that account directly in the DB (dev-only escape hatch)
python scripts/bootstrap_admin.py planner.shirva@example.com PLANNER

# 3. Run the full judge-facing flow end to end
python scripts/seed_demo.py
```

`seed_demo.py` registers/logs in, creates the "Shirva" habitation, opens a
DRAFT parameter set, deliberately sets `annual_growth_rate_pct = 14` (outside
the seeded `[-5, 10]` range), shows the resulting `FAIL` validation report,
fixes it, validates again (`PASS`), commits (habitation flips to `READY`),
then uploads a GeoJSON road feature and confirms it lands inside the
habitation boundary.

## Tests

```bash
createdb -h localhost -U swms swms_test   # or: docker exec -it <db container> createdb -U swms swms_test
pytest
```

`tests/conftest.py` creates the schema fresh (via `Base.metadata.create_all`,
not Alembic) against `swms_test` and drops it after the session.

## What was deliberately left out of this Drop 1 scaffold

- **User management endpoints** (promote/deactivate a user) — not in the
  requested scope; `scripts/bootstrap_admin.py` is a dev-only stand-in.
- **Async ingestion pipeline for shapefiles/CRS-declared uploads** (M5) — the
  spec asked specifically for a direct GeoJSON `POST .../layers` endpoint,
  which is synchronous; the 202-job-id pattern in `SWMS_BACKEND_MAP.md` Loop 2
  applies to the M5 shapefile/dataset upload flow, which is a separate,
  larger piece of Drop 1 not in the five requested features.
- **Refresh token revoke-on-logout endpoint** — `RefreshToken` rows and
  rotation exist (`POST /auth/refresh`), but there's no explicit
  `POST /auth/logout` since it wasn't requested.
- **PARAMETER_SET state machine's `VALIDATING` transient state** — simplified
  to DRAFT ⇄ INVALID ⇆ (edit) with the same net effect (edits after a failed
  validation reopen the set), since the transient in-flight status isn't
  observable over a synchronous request/response cycle.
- **Native PostgreSQL ENUM types** — all enums are stored as
  `VARCHAR` (`native_enum=False`) to avoid `ALTER TYPE ... ADD VALUE`
  migration ceremony during a hackathon; values are still validated at the
  Python/Pydantic layer.

## Verification performed in this environment

No Docker/Postgres was available in the sandbox this was built in, so:
- ✅ Every module imports cleanly, the FastAPI app builds, and all 19 routes
  registered as expected (checked via `python -c "from app.main import app"`).
- ✅ `ruff check` passes clean.
- ❌ Migrations and the pytest suite were **not** run against a live
  PostGIS instance — do that first via `docker compose up -d db && alembic
  upgrade head && pytest`, and treat this as unverified until it's green.
# NoMoreWaste
