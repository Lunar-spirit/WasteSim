import os
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://swms:swms@localhost:5432/swms_test"
)

from app.audit import models as _audit_models  # noqa: E402,F401
from app.auth import models as _auth_models  # noqa: E402,F401
from app.auth.models import User, UserRole  # noqa: E402
from app.budget import models as _budget_models  # noqa: E402,F401
from app.core.config import settings  # noqa: E402
from app.core.db import Base, get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.gis import models as _gis_models  # noqa: E402,F401
from app.habitation import models as _habitation_models  # noqa: E402,F401
from app.ingestion import models as _ingestion_models  # noqa: E402,F401
from app.main import app  # noqa: E402
from app.optimization import models as _optimization_models  # noqa: E402,F401
from app.parameters import models as _parameters_models  # noqa: E402,F401
from app.parameters.models import DataType, ParameterDefinition  # noqa: E402
from app.scenario import models as _scenario_models  # noqa: E402,F401
from app.simulation import models as _simulation_models  # noqa: E402,F401
from app.validation import models as _validation_models  # noqa: E402,F401
from sqlalchemy import select  # noqa: E402

# NullPool: every checkout opens a brand-new asyncpg connection and closes it
# on checkin instead of pooling. Each test runs in its own function-scoped
# asyncio event loop (pytest-asyncio's default), but asyncpg connections are
# bound to the loop that created them — a pooled connection handed from one
# test's loop to the next test's loop raises "Future attached to a different
# loop". NullPool sidesteps this entirely by never reusing a connection
# across checkouts, which is exactly what a test suite needs (correctness
# over pool efficiency); the app's real engine in app/core/db.py keeps normal
# pooling since a running server has one event loop for its whole lifetime.
test_engine = create_async_engine(settings.database_url, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


# loop_scope="session" here, but "function" (see pytest.ini) for every other
# fixture and every test: this fixture only ever runs once (scope="session")
# and never hands a live connection out past its own `yield`, so giving it
# its own dedicated session-long loop is safe and doesn't fight the
# function-scoped loop every test runs in. NullPool (above) is what actually
# keeps the two loop worlds from colliding.
@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def _create_schema():
    async with test_engine.begin() as conn:
        await conn.execute(__import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS postgis"))
        # drop_all before create_all: if a previous run crashed before its
        # own teardown ran, swms_test is left holding a stale schema (and
        # stale rows, which then cause spurious HABITATION_DUPLICATE-style
        # failures). Starting every session with a clean slate makes the
        # suite self-healing instead of depending on the last run having
        # exited cleanly.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # The real FastAPI app creates this bucket in its lifespan startup hook
    # (app/main.py), but httpx.ASGITransport never runs lifespan events, so
    # the test suite has to do it itself against the same real MinIO the
    # dev stack uses.
    from app.core import storage

    storage.ensure_bucket()
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session():
    async with TestSessionLocal() as session:
        yield session


# Minimal catalogue covering the fields the parameter/validation tests
# exercise: one required numeric field per relevant category, plus the
# demography.annual_growth_rate_pct range used in the design doc's example.
TEST_DEFINITIONS = [
    ("demography", "population", "Population", "INTEGER", 1, 10_000_000, True),
    ("demography", "annual_growth_rate_pct", "Annual growth rate", "NUMERIC", -5, 10, True),
    ("waste_baseline", "per_capita_generation_kg_day", "Per-capita generation", "NUMERIC", 0.05, 5, True),
]


@pytest_asyncio.fixture(autouse=True)
async def seed_parameter_definitions(db_session):
    existing = await db_session.scalar(select(ParameterDefinition).limit(1))
    if existing is not None:
        return
    for category, key, label, data_type, lo, hi, required in TEST_DEFINITIONS:
        db_session.add(
            ParameterDefinition(
                category=category,
                param_key=key,
                display_label=label,
                data_type=DataType(data_type),
                min_value=lo,
                max_value=hi,
                is_required=required,
            )
        )
    await db_session.commit()


@pytest_asyncio.fixture
async def client(db_session):
    # A FRESH session per simulated request, exactly like the real get_db —
    # NOT the shared db_session fixture. Reusing one open session across every
    # request in a test means a request that errors out (raises before its
    # router calls db.commit()) leaves its flushed-but-uncommitted rows sitting
    # in that same open transaction, visible to the *next* simulated request
    # in the same test even though a real server would have rolled them back
    # when that request's session closed (verified: closing an AsyncSession
    # with no commit does roll back). Without this, tests can't trust
    # rejection paths to actually discard what they wrote (BR-14, ERR-10).
    async def override_get_db():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _make_user(db_session, role: UserRole) -> tuple[User, str]:
    email = f"{role.value.lower()}.{uuid.uuid4().hex[:8]}@example.com"
    password = "TestPass123!"
    user = User(email=email, hashed_password=hash_password(password), full_name="Test User", role=role)
    db_session.add(user)
    await db_session.commit()
    return user, password


@pytest_asyncio.fixture
async def planner_user(db_session):
    return await _make_user(db_session, UserRole.PLANNER)


@pytest_asyncio.fixture
async def researcher_user(db_session):
    return await _make_user(db_session, UserRole.RESEARCHER)


@pytest_asyncio.fixture
async def admin_user(db_session):
    return await _make_user(db_session, UserRole.ADMIN)


async def _login(client, email: str, password: str) -> str:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


@pytest_asyncio.fixture
async def planner_headers(client, planner_user):
    user, password = planner_user
    token = await _login(client, user.email, password)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def researcher_headers(client, researcher_user):
    user, password = researcher_user
    token = await _login(client, user.email, password)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin_headers(client, admin_user):
    user, password = admin_user
    token = await _login(client, user.email, password)
    return {"Authorization": f"Bearer {token}"}
