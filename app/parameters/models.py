import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import DDL

from app.core.db import Base


# --- DB-level immutability backstop (rule #1: VALIDATED/ARCHIVED parameter
# sets are read-only forever) -------------------------------------------
#
# app/parameters/service.py already refuses an edit with a friendly 409
# PARAMETER_SET_IMMUTABLE before touching the database. This trigger is the
# second, physical layer underneath it: even a raw `UPDATE demography ...`
# run directly against the database (a bad migration, a bug in a future
# module, a stray admin script) cannot silently corrupt a committed run's
# inputs. Two independent mechanisms are attached to Base.metadata so BOTH
# `alembic upgrade head` (real deployments — see migrations/versions/0003_*)
# and `Base.metadata.create_all()` (the test suite, in tests/conftest.py)
# end up with the identical function + triggers.
# Every literal "%" below is doubled to "%%": sqlalchemy.schema.DDL runs
# `text % context` on this whole string before Postgres ever sees it (that's
# how it substitutes %(table)s for table-level DDL events), so an
# un-doubled "%" — even one meant only for Postgres's own RAISE EXCEPTION
# placeholders — gets misread as a Python format spec and raises ValueError.
_CREATE_IMMUTABILITY_TRIGGER_FUNCTION = DDL(
    """
    CREATE OR REPLACE FUNCTION swms_block_locked_parameter_set_edit() RETURNS trigger AS $$
    DECLARE
        ps_status varchar;
    BEGIN
        SELECT status::text INTO ps_status FROM parameter_sets WHERE id = NEW.parameter_set_id;
        IF ps_status IN ('VALIDATED', 'ARCHIVED') THEN
            RAISE EXCEPTION
                'parameter_set %% is %% and is read-only (VALIDATED/ARCHIVED sets are immutable)',
                NEW.parameter_set_id, ps_status
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
)

# Waste composition is stored as a JSONB map, e.g. {"organic": 55, "plastic":
# 12, ...}. A plain column CHECK can't sum JSONB values by itself, so the
# CHECK below (on WasteBaseline) delegates to this tiny SQL function. This is
# the hard backstop for the same "sums to 100 +/- 0.5" rule Stage 3 of the
# validation pipeline already reports nicely, with a field_path, to the API.
_CREATE_COMPOSITION_CHECK_FUNCTION = DDL(
    """
    CREATE OR REPLACE FUNCTION swms_composition_sums_to_100(comp jsonb) RETURNS boolean AS $$
        SELECT comp IS NULL OR (
            SELECT abs(sum((value)::numeric) - 100) <= 0.5
            FROM jsonb_each_text(comp)
        );
    $$ LANGUAGE sql IMMUTABLE;
    """
)

# before_create on the *metadata* (not a single table) fires once, before
# create_all touches any table — exactly when a function referenced by a
# CHECK constraint or a trigger on some later table needs to already exist.
event.listen(Base.metadata, "before_create", _CREATE_IMMUTABILITY_TRIGGER_FUNCTION)
event.listen(Base.metadata, "before_create", _CREATE_COMPOSITION_CHECK_FUNCTION)


def _attach_immutability_trigger(model: Any) -> None:
    """Wire the BEFORE UPDATE trigger onto one category table's own
    after_create event, so it appears the moment that table does.

    Typed `Any`, not `type[Base]`: mypy has no static knowledge that a
    DeclarativeBase subclass carries `__tablename__`/`__table__` (those are
    supplied dynamically by the declarative metaclass), so `type[Base]`
    would still fail the same attribute check.
    """
    table_name = model.__tablename__
    ddl = DDL(
        f"""
        CREATE TRIGGER trg_block_locked_edit_{table_name}
        BEFORE UPDATE ON {table_name}
        FOR EACH ROW EXECUTE FUNCTION swms_block_locked_parameter_set_edit();
        """
    )
    event.listen(model.__table__, "after_create", ddl)


class ParameterSetStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    INVALID = "INVALID"
    ARCHIVED = "ARCHIVED"


class DataType(str, enum.Enum):
    INTEGER = "INTEGER"
    NUMERIC = "NUMERIC"
    STRING = "STRING"
    BOOLEAN = "BOOLEAN"
    JSON = "JSON"


CATEGORY_NAMES = (
    "demography",
    "community_infrastructure",
    "industrial_activities",
    "natural_resources",
    "terrain",
    "economic_conditions",
    "cultural_context",
)


class ParameterSet(Base):
    __tablename__ = "parameter_sets"
    __table_args__ = (
        UniqueConstraint("habitation_id", "version_no", name="uq_parameter_set_version"),
        # Partial unique index, not a plain UNIQUE: "at most one VALIDATED
        # set per habitation" is only a constraint on rows where
        # status='VALIDATED' — DRAFT/INVALID/ARCHIVED rows are unrestricted.
        # This is what makes the commit() race genuinely safe: two concurrent
        # commits both trying to become "the" VALIDATED version can't both
        # succeed, even if the row-lock in commit() were ever bypassed.
        Index(
            "uq_one_validated_parameter_set_per_habitation",
            "habitation_id",
            unique=True,
            postgresql_where=text("status = 'VALIDATED'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("habitations.id", ondelete="CASCADE")
    )
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[ParameterSetStatus] = mapped_column(
        Enum(ParameterSetStatus, name="parameter_set_status"),
        default=ParameterSetStatus.DRAFT,
    )
    cloned_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parameter_sets.id", ondelete="SET NULL"), nullable=True
    )
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def _category_pk():
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("parameter_sets.id", ondelete="CASCADE"), primary_key=True
    )


class Demography(Base):
    __tablename__ = "demography"
    __table_args__ = (
        # Hard physical bounds, enforced no matter what wrote the row — but
        # deliberately much WIDER than the -5..10 business range a planner
        # sees. The validation loop's entire point (design Loop 1) is that a
        # planner can PUT an out-of-range value like 14 and get a graceful
        # `FAIL` with a field_path from /validate; a DB CHECK matching the
        # catalogue's tight range exactly would instead 500 on the PUT
        # itself, before validation ever runs. So the two bounds are
        # deliberately different: this CHECK only rejects values no real
        # habitation could ever have (a typo like 1400 instead of 14), while
        # parameter_definitions + Stage 2 of the pipeline enforce the real,
        # adjustable -5..10 business rule (rule #4) and report it nicely.
        CheckConstraint("population IS NULL OR population > 0", name="ck_demography_population_positive"),
        CheckConstraint(
            "annual_growth_rate_pct IS NULL OR annual_growth_rate_pct BETWEEN -100 AND 1000",
            name="ck_demography_growth_rate_sane",
        ),
    )

    parameter_set_id: Mapped[uuid.UUID] = _category_pk()
    population: Mapped[int | None] = mapped_column(Integer, nullable=True)
    annual_growth_rate_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    household_size_avg: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    floating_population_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)


class CommunityInfrastructure(Base):
    __tablename__ = "community_infrastructure"
    __table_args__ = (
        CheckConstraint(
            "landfill_remaining_tonnes IS NULL OR landfill_capacity_tonnes IS NULL "
            "OR landfill_remaining_tonnes <= landfill_capacity_tonnes",
            name="ck_community_infra_landfill_remaining_le_capacity",
        ),
    )

    parameter_set_id: Mapped[uuid.UUID] = _category_pk()
    road_network_km: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    collection_vehicles_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    collection_coverage_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    treatment_capacity_tpd: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    landfill_capacity_tonnes: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    landfill_remaining_tonnes: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)


class IndustrialActivities(Base):
    __tablename__ = "industrial_activities"

    parameter_set_id: Mapped[uuid.UUID] = _category_pk()
    industrial_units_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    industrial_waste_tpd: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    hazardous_waste_present: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class NaturalResources(Base):
    __tablename__ = "natural_resources"

    parameter_set_id: Mapped[uuid.UUID] = _category_pk()
    annual_rainfall_mm: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    water_bodies_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forest_cover_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)


class Terrain(Base):
    __tablename__ = "terrain"

    parameter_set_id: Mapped[uuid.UUID] = _category_pk()
    avg_slope_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    soil_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    flood_risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    landslide_risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)


class EconomicConditions(Base):
    __tablename__ = "economic_conditions"

    parameter_set_id: Mapped[uuid.UUID] = _category_pk()
    avg_household_income_monthly: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    swm_annual_budget: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    unemployment_rate_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)


class CulturalContext(Base):
    __tablename__ = "cultural_context"

    parameter_set_id: Mapped[uuid.UUID] = _category_pk()
    segregation_practice_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    festival_days_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dietary_organic_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)


class WasteBaseline(Base):
    __tablename__ = "waste_baseline"
    __table_args__ = (
        CheckConstraint(
            "per_capita_generation_kg_day IS NOT NULL OR total_generation_tpd IS NOT NULL",
            name="ck_waste_baseline_generation_present",
        ),
        CheckConstraint(
            "swms_composition_sums_to_100(composition)",
            name="ck_waste_baseline_composition_sum",
        ),
    )

    parameter_set_id: Mapped[uuid.UUID] = _category_pk()
    per_capita_generation_kg_day: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    total_generation_tpd: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    # {"organic": 55.0, "plastic": 12.0, "paper": 10.0, "glass": 3.0, "metal": 2.0, "other": 18.0}
    composition: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


CATEGORY_MODELS: dict[str, type] = {
    "demography": Demography,
    "community_infrastructure": CommunityInfrastructure,
    "industrial_activities": IndustrialActivities,
    "natural_resources": NaturalResources,
    "terrain": Terrain,
    "economic_conditions": EconomicConditions,
    "cultural_context": CulturalContext,
}

# The immutability trigger applies to every category table AND waste_baseline
# (all eight are 1:1 children of a parameter_set, keyed by parameter_set_id).
for _model in (*CATEGORY_MODELS.values(), WasteBaseline):
    _attach_immutability_trigger(_model)


class ParameterDefinition(Base):
    __tablename__ = "parameter_definitions"
    __table_args__ = (
        UniqueConstraint("category", "param_key", name="uq_parameter_definition"),
        CheckConstraint(
            "severity_on_fail IN ('ERROR', 'WARNING')", name="ck_parameter_definitions_severity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(64))
    param_key: Mapped[str] = mapped_column(String(64))
    display_label: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    data_type: Mapped[DataType] = mapped_column(Enum(DataType, name="parameter_data_type"))
    min_value: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    max_value: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    # Soft bounds: outside [warn_min, warn_max] but still inside
    # [min_value, max_value] produces a WARNING issue instead of an ERROR —
    # e.g. a 9% growth rate is legal but worth a planner double-checking.
    warn_min: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    warn_max: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    normalization_rule: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # For STRING fields validated against a fixed vocabulary (e.g.
    # terrain.soil_type) instead of a numeric range, e.g. ["SANDY", "CLAY",
    # "LOAMY", "ROCKY"]. Deliberately catalogue data rather than a Postgres
    # enum column, so adding a new allowed soil type is a seed row, not a
    # migration (rule #4).
    allowed_values: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Read by sensitivity sweeps (Drop 2/3) to decide which parameters may be
    # varied in a "what if growth rate were X" analysis.
    is_sweepable: Mapped[bool] = mapped_column(Boolean, default=False)
    # Plain string, not app.validation.models.Severity: importing that enum
    # here would make app.parameters depend on app.validation, which already
    # depends on app.parameters (CATEGORY_MODELS) — a cycle. The CHECK
    # constraint above keeps the same two values in sync at the DB level.
    severity_on_fail: Mapped[str] = mapped_column(String(8), default="ERROR")
    help_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    rules_version: Mapped[str] = mapped_column(String(8), default="v1")
