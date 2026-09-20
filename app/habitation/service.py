import json
import uuid

from geoalchemy2 import Geography
from sqlalchemy import cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserRole
from app.core.deps import check_habitation_access
from app.core.errors import AppError
from app.habitation.models import AccessLevel, Habitation, HabitationMember, HabitationStatus
from app.habitation.schemas import HabitationCreate


def _valid_geography_expr(geojson: dict, geometry_type: str, srid: int = 4326):
    geojson_str = json.dumps(geojson)
    raw = func.ST_SetSRID(func.ST_GeomFromGeoJSON(geojson_str), srid)
    valid = func.ST_MakeValid(raw)
    # A plain Polygon is a valid GeoJSON input for a MultiPolygon column; the
    # geography(MultiPolygon,4326) typmod otherwise rejects it outright.
    if geometry_type == "MULTIPOLYGON":
        valid = func.ST_Multi(valid)
    return cast(valid, Geography(geometry_type=geometry_type, srid=srid))


async def create_habitation(
    db: AsyncSession, payload: HabitationCreate, creator: User
) -> Habitation:
    duplicate = await db.scalar(
        select(Habitation).where(
            Habitation.name == payload.name,
            Habitation.district == payload.district,
            Habitation.state == payload.state,
            Habitation.deleted_at.is_(None),
        )
    )
    if duplicate is not None:
        raise AppError(
            "HABITATION_DUPLICATE",
            "A habitation with this name already exists in this district/state",
            409,
        )

    boundary_expr = (
        _valid_geography_expr(payload.boundary_geojson, "MULTIPOLYGON")
        if payload.boundary_geojson
        else None
    )
    if payload.centroid_geojson:
        centroid_expr = _valid_geography_expr(payload.centroid_geojson, "POINT")
    elif boundary_expr is not None:
        centroid_expr = cast(func.ST_Centroid(boundary_expr), Geography(geometry_type="POINT", srid=4326))
    else:
        centroid_expr = None

    habitation = Habitation(
        name=payload.name,
        habitation_type=payload.habitation_type,
        state=payload.state,
        district=payload.district,
        country=payload.country,
        boundary=boundary_expr,
        centroid=centroid_expr,
        area_sqkm=payload.area_sqkm,
        created_by=creator.id,
    )
    db.add(habitation)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise AppError(
            "HABITATION_DUPLICATE",
            "A habitation with this name already exists in this district/state",
            409,
        ) from exc

    if payload.area_sqkm is None and boundary_expr is not None:
        computed = await db.scalar(select(func.ST_Area(Habitation.boundary) / 1_000_000).where(
            Habitation.id == habitation.id
        ))
        habitation.area_sqkm = computed

    db.add(HabitationMember(habitation_id=habitation.id, user_id=creator.id, access_level=AccessLevel.OWNER))
    await db.flush()
    return habitation


async def list_habitations(db: AsyncSession, user: User) -> list[Habitation]:
    if user.role == UserRole.ADMIN:
        stmt = select(Habitation).where(Habitation.deleted_at.is_(None))
    else:
        member_ids = select(HabitationMember.habitation_id).where(HabitationMember.user_id == user.id)
        stmt = select(Habitation).where(
            Habitation.deleted_at.is_(None),
            or_(Habitation.status == HabitationStatus.READY, Habitation.id.in_(member_ids)),
        )
    result = await db.scalars(stmt.order_by(Habitation.created_at.desc()))
    return list(result)


async def get_habitation_or_404(db: AsyncSession, habitation_id: uuid.UUID) -> Habitation:
    habitation = await db.get(Habitation, habitation_id)
    if habitation is None or habitation.deleted_at is not None:
        raise AppError("HABITATION_NOT_FOUND", "Habitation not found", 404)
    return habitation


async def get_habitation(db: AsyncSession, habitation_id: uuid.UUID, user: User) -> Habitation:
    habitation = await get_habitation_or_404(db, habitation_id)
    await ensure_read_access(db, user, habitation)
    return habitation


async def ensure_read_access(db: AsyncSession, user: User, habitation: Habitation) -> None:
    """A READY habitation is readable by any authenticated role (per the RBAC
    matrix); a DRAFT/ARCHIVED one needs at least VIEWER membership."""
    if habitation.status != HabitationStatus.READY:
        await check_habitation_access(db, user, habitation.id, AccessLevel.VIEWER)
