import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.errors import AppError
from app.habitation.models import Habitation
from app.parameters.models import (
    CATEGORY_MODELS,
    ParameterDefinition,
    ParameterSet,
    ParameterSetStatus,
    WasteBaseline,
)
from app.parameters.schemas import ParameterSetCreate
from app.validation.normalization import NormalizationError, normalize_value


async def _get_habitation_or_404(db: AsyncSession, habitation_id: uuid.UUID) -> Habitation:
    habitation = await db.get(Habitation, habitation_id)
    if habitation is None or habitation.deleted_at is not None:
        raise AppError("HABITATION_NOT_FOUND", "Habitation not found", 404)
    return habitation


async def get_parameter_set_or_404(db: AsyncSession, psid: uuid.UUID) -> ParameterSet:
    ps = await db.get(ParameterSet, psid)
    if ps is None:
        raise AppError("PARAMETER_SET_NOT_FOUND", "Parameter set not found", 404)
    return ps


def _assert_editable(ps: ParameterSet) -> None:
    if ps.status in (ParameterSetStatus.VALIDATED, ParameterSetStatus.ARCHIVED):
        raise AppError(
            "PARAMETER_SET_IMMUTABLE",
            f"Parameter set is {ps.status.value} and cannot be modified",
            409,
        )
    # Editing an INVALID set re-opens it for another validate/commit cycle.
    if ps.status == ParameterSetStatus.INVALID:
        ps.status = ParameterSetStatus.DRAFT


async def create_parameter_set(
    db: AsyncSession, habitation_id: uuid.UUID, payload: ParameterSetCreate, user: User
) -> ParameterSet:
    await _get_habitation_or_404(db, habitation_id)

    max_version = await db.scalar(
        select(ParameterSet.version_no)
        .where(ParameterSet.habitation_id == habitation_id)
        .order_by(ParameterSet.version_no.desc())
        .limit(1)
    )
    next_version = (max_version or 0) + 1

    new_set = ParameterSet(
        habitation_id=habitation_id,
        version_no=next_version,
        status=ParameterSetStatus.DRAFT,
        change_note=payload.change_note,
        created_by=user.id,
    )

    if payload.clone_from_version is not None:
        source = await db.scalar(
            select(ParameterSet).where(
                ParameterSet.habitation_id == habitation_id,
                ParameterSet.version_no == payload.clone_from_version,
            )
        )
        if source is None:
            raise AppError(
                "PARAMETER_SET_NOT_FOUND",
                f"No version {payload.clone_from_version} exists to clone from",
                404,
            )
        new_set.cloned_from_id = source.id

    db.add(new_set)
    await db.flush()

    if payload.clone_from_version is not None:
        await _clone_category_data(db, source.id, new_set.id)

    return new_set


async def _clone_category_data(db: AsyncSession, source_id: uuid.UUID, target_id: uuid.UUID) -> None:
    for model in CATEGORY_MODELS.values():
        row = await db.get(model, source_id)
        if row is not None:
            clone = model(parameter_set_id=target_id)
            for column in model.__table__.columns.keys():
                if column != "parameter_set_id":
                    setattr(clone, column, getattr(row, column))
            db.add(clone)

    baseline = await db.get(WasteBaseline, source_id)
    if baseline is not None:
        clone = WasteBaseline(
            parameter_set_id=target_id,
            per_capita_generation_kg_day=baseline.per_capita_generation_kg_day,
            total_generation_tpd=baseline.total_generation_tpd,
            composition=baseline.composition,
        )
        db.add(clone)

    await db.flush()


async def upsert_category(
    db: AsyncSession, psid: uuid.UUID, category: str, raw_payload: dict[str, Any]
) -> Any:
    if category not in CATEGORY_MODELS:
        raise AppError(
            "CATEGORY_UNKNOWN", f"Unknown category '{category}'", 404
        )

    ps = await get_parameter_set_or_404(db, psid)
    _assert_editable(ps)

    model = CATEGORY_MODELS[category]
    definitions = await db.scalars(
        select(ParameterDefinition).where(ParameterDefinition.category == category)
    )
    definitions_by_key = {d.param_key: d for d in definitions}

    row = await db.get(model, psid)
    if row is None:
        row = model(parameter_set_id=psid)
        db.add(row)

    columns = set(model.__table__.columns.keys()) - {"parameter_set_id"}
    for key, raw_value in raw_payload.items():
        if key not in columns:
            continue
        definition = definitions_by_key.get(key)
        if definition is not None:
            try:
                value = normalize_value(raw_value, definition.data_type, definition.normalization_rule)
            except NormalizationError as exc:
                raise AppError(
                    "NORMALIZATION_FAILED", f"{category}.{key}: {exc.message}", 400
                ) from exc
        else:
            value = raw_value
        setattr(row, key, value)

    await db.flush()
    return row


async def upsert_waste_baseline(db: AsyncSession, psid: uuid.UUID, payload: dict[str, Any]) -> WasteBaseline:
    ps = await get_parameter_set_or_404(db, psid)
    _assert_editable(ps)

    definitions = await db.scalars(
        select(ParameterDefinition).where(ParameterDefinition.category == "waste_baseline")
    )
    definitions_by_key = {d.param_key: d for d in definitions}

    row = await db.get(WasteBaseline, psid)
    if row is None:
        row = WasteBaseline(parameter_set_id=psid)
        db.add(row)

    for key in ("per_capita_generation_kg_day", "total_generation_tpd"):
        if key in payload and payload[key] is not None:
            definition = definitions_by_key.get(key)
            data_type = definition.data_type if definition else None
            try:
                value = (
                    normalize_value(payload[key], data_type, definition.normalization_rule)
                    if definition
                    else float(payload[key])
                )
            except NormalizationError as exc:
                raise AppError(
                    "NORMALIZATION_FAILED", f"waste_baseline.{key}: {exc.message}", 400
                ) from exc
            setattr(row, key, value)

    if "composition" in payload and payload["composition"] is not None:
        row.composition = payload["composition"]

    await db.flush()
    return row


async def derive_semi_automated_fields(db: AsyncSession, psid: uuid.UUID) -> list[str]:
    """Semi-automated formulations (automation module): fills in a target
    field from ones already present, but ONLY when the target is still
    missing — never overwrites a value a planner or an upload explicitly
    supplied. Called from two places: app/ingestion/service.py's
    ingest_accepted_rows (API-37 — "seamlessly on ingest") and
    app/automation/service.py's auto_populate, so the same two formulas
    apply consistently regardless of which path a habitation's data came
    in through. Writes through upsert_category/upsert_waste_baseline like
    every other mutation, so the 409 PARAMETER_SET_IMMUTABLE guard and the
    immutability trigger both still apply."""
    full = await get_parameter_set_full(db, psid)
    demography = full["categories"].get("demography") or {}
    industrial = full["categories"].get("industrial_activities") or {}
    baseline = full["waste_baseline"] or {}

    derived: list[str] = []

    population = demography.get("population")
    household_size_avg = demography.get("household_size_avg")
    if population and household_size_avg and not demography.get("household_count"):
        household_count = round(float(population) / float(household_size_avg))
        await upsert_category(db, psid, "demography", {"household_count": household_count})
        derived.append("demography.household_count")

    per_capita = baseline.get("per_capita_generation_kg_day")
    if population and per_capita and not baseline.get("total_generation_tpd"):
        industrial_waste_tpd = industrial.get("industrial_waste_tpd") or 0.0
        total_generation_tpd = round((float(population) * float(per_capita)) / 1000.0 + float(industrial_waste_tpd), 3)
        await upsert_waste_baseline(db, psid, {"total_generation_tpd": total_generation_tpd})
        derived.append("waste_baseline.total_generation_tpd")

    return derived


async def get_parameter_set_full(db: AsyncSession, psid: uuid.UUID) -> dict[str, Any]:
    ps = await get_parameter_set_or_404(db, psid)

    categories: dict[str, dict[str, Any]] = {}
    for name, model in CATEGORY_MODELS.items():
        row = await db.get(model, psid)
        categories[name] = _row_to_dict(row, model) if row else {}

    baseline_row = await db.get(WasteBaseline, psid)
    baseline = _row_to_dict(baseline_row, WasteBaseline) if baseline_row else None

    return {"parameter_set": ps, "categories": categories, "waste_baseline": baseline}


async def get_parameter_set_summary(db: AsyncSession, psid: uuid.UUID) -> dict[str, Any] | None:
    ps = await db.get(ParameterSet, psid)
    if ps is None:
        return None
    return {"id": str(ps.id), "version_no": ps.version_no, "status": ps.status.value}


def _row_to_dict(row: Any, model: type) -> dict[str, Any]:
    return {
        column: getattr(row, column)
        for column in model.__table__.columns.keys()
        if column != "parameter_set_id"
    }
