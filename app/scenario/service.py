import json
import uuid
from typing import Any

from geoalchemy2.functions import ST_GeomFromGeoJSON, ST_SetSRID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.errors import AppError
from app.engine.run import ENGINE_VERSION
from app.parameters.service import get_parameter_set_full
from app.scenario.models import EventType, ScenarioEvent
from app.scenario.schemas import EventIn, ScenarioCreateIn
from app.scenario.spatial_impact import derive_impacts
from app.simulation.models import RunStatus, RunType, SimulationRun

# design 5.5's table, condensed to what API-59 (the event catalogue) needs to
# show a planner picking an event type: what it affects and where its
# magnitude typically comes from.
EVENT_CATALOGUE: list[dict[str, str]] = [
    {
        "event_type": "FLOOD",
        "effect": "Road accessibility loss (derived from GIS when an affected_area is given); "
        "treatment capacity reduced.",
        "magnitude_source": "Spatial, scaled by the habitation's own flood_risk_level",
    },
    {
        "event_type": "LANDSLIDE",
        "effect": "Road segments cut in a hilly habitation; localised access loss.",
        "magnitude_source": "Spatial, scaled by the habitation's own landslide_risk_level",
    },
    {
        "event_type": "HEAVY_MONSOON",
        "effect": "Waste mass uplift through moisture; mild accessibility reduction habitation-wide.",
        "magnitude_source": "Declared, informed by annual_rainfall_mm",
    },
    {"event_type": "ROAD_BLOCKAGE", "effect": "Fixed accessibility reduction for a stated window.", "magnitude_source": "Declared"},
    {"event_type": "POPULATION_SURGE", "effect": "Effective population multiplied for the window.", "magnitude_source": "Declared"},
    {"event_type": "VEHICLE_BREAKDOWN", "effect": "Available fleet reduced.", "magnitude_source": "Declared"},
    {
        "event_type": "TREATMENT_PLANT_OUTAGE",
        "effect": "Treatment capacity reduced toward zero; organic diverted to landfill.",
        "magnitude_source": "Declared",
    },
    {"event_type": "FESTIVAL", "effect": "Generation multiplier.", "magnitude_source": "From parameters (cultural_context)"},
    {"event_type": "STRIKE", "effect": "Coverage sharply reduced for a short window.", "magnitude_source": "Declared"},
]

# design 5.5: "further scaled by the habitation's own vulnerability — the
# same flood is worse in a HIGH flood-vulnerability, hilly habitation than
# on a plain." Applied only to FLOOD (via terrain.flood_risk_level) and
# LANDSLIDE (via terrain.landslide_risk_level) — the two event types the
# design explicitly ties to a habitation vulnerability field.
VULNERABILITY_MULTIPLIER = {"LOW": 0.8, "MODERATE": 1.0, "HIGH": 1.3}
_VULNERABILITY_FIELD_BY_EVENT = {"FLOOD": "flood_risk_level", "LANDSLIDE": "landslide_risk_level"}


def list_event_catalogue() -> list[dict[str, str]]:
    return EVENT_CATALOGUE


async def _vulnerability_multiplier(db: AsyncSession, parameter_set_id: uuid.UUID, event_type: str) -> float:
    field = _VULNERABILITY_FIELD_BY_EVENT.get(event_type)
    if field is None:
        return 1.0
    full = await get_parameter_set_full(db, parameter_set_id)
    level = (full["categories"].get("terrain") or {}).get(field)
    return VULNERABILITY_MULTIPLIER.get(level, 1.0) if isinstance(level, str) else 1.0


async def preview_impact(
    db: AsyncSession, habitation_id: uuid.UUID, event_type: EventType, affected_area: dict[str, Any]
) -> dict[str, Any]:
    """API-62: what would this event do, without running a simulation."""
    derived = await derive_impacts(db, habitation_id, event_type.value, affected_area)
    if not derived:
        return {
            "derived": False,
            "message": "No READY ROAD/SETTLEMENT layer to measure against yet, or this event type has no "
            "spatial derivation (design 5.5) — impact would fall back to whatever impact_params is declared.",
        }
    return {"derived": True, "derived_impacts": derived}


async def create_scenario_run(
    db: AsyncSession, base_run_id: uuid.UUID, payload: ScenarioCreateIn, user: User
) -> SimulationRun:
    base_run = await db.get(SimulationRun, base_run_id)
    if base_run is None:
        raise AppError("RUN_NOT_FOUND", "Base run not found", 404)
    if base_run.status != RunStatus.COMPLETED:
        raise AppError(
            "BASE_RUN_NOT_COMPLETED", f"Base run must be COMPLETED, is {base_run.status.value}", 409
        )

    horizon_months = base_run.horizon_years * 12
    for event in payload.events:
        window_end = event.start_month + event.duration_months - 1
        if window_end > horizon_months:
            raise AppError(
                "EVENT_WINDOW_OUT_OF_RANGE",
                f"Event window (months {event.start_month}-{window_end}) exceeds the base run's "
                f"{horizon_months}-month horizon",
                400,
            )

    # BR-22: a scenario run never modifies its parent — it copies the
    # parent's parameter_set_id and attaches its own events. Same
    # coefficient_set_id too, so only the events differ from the base run.
    scenario_run = SimulationRun(
        habitation_id=base_run.habitation_id,
        parameter_set_id=base_run.parameter_set_id,
        coefficient_set_id=base_run.coefficient_set_id,
        engine_version=ENGINE_VERSION,
        run_type=RunType.SCENARIO,
        parent_run_id=base_run.id,
        label=payload.label,
        horizon_years=base_run.horizon_years,
        param_overrides=base_run.param_overrides,
        config=payload.config,
        status=RunStatus.QUEUED,
        created_by=user.id,
    )
    db.add(scenario_run)
    await db.flush()

    for event in payload.events:
        await _add_event(db, scenario_run, base_run, event)

    await db.flush()
    return scenario_run


async def _add_event(
    db: AsyncSession, scenario_run: SimulationRun, base_run: SimulationRun, event: EventIn
) -> ScenarioEvent:
    derived_impacts: dict[str, Any] = {}
    if event.affected_area is not None:
        derived_impacts = await derive_impacts(
            db, scenario_run.habitation_id, event.event_type.value, event.affected_area
        )

    vulnerability = await _vulnerability_multiplier(db, base_run.parameter_set_id, event.event_type.value)
    impact_params = {k: v * vulnerability for k, v in event.impact_params.items()}
    derived_impacts = {k: v * vulnerability for k, v in derived_impacts.items()}

    row = ScenarioEvent(
        simulation_run_id=scenario_run.id,
        event_type=event.event_type,
        start_month=event.start_month,
        duration_months=event.duration_months,
        recovery_months=event.recovery_months,
        severity=event.severity,
        impact_params=impact_params,
        derived_impacts=derived_impacts,
    )
    if event.affected_area is not None:
        row.affected_area = ST_SetSRID(ST_GeomFromGeoJSON(json.dumps(event.affected_area)), 4326)
    db.add(row)
    await db.flush()
    return row


async def get_events_for_run(db: AsyncSession, run_id: uuid.UUID) -> list[ScenarioEvent]:
    return list(
        await db.scalars(
            select(ScenarioEvent).where(ScenarioEvent.simulation_run_id == run_id).order_by(ScenarioEvent.start_month)
        )
    )


def events_to_engine_format(events: list[ScenarioEvent]) -> list[dict[str, Any]]:
    """Plain dicts, exactly what app.engine.events.active_in() expects —
    BR-21 applies here too, the engine never sees a ScenarioEvent ORM row."""
    return [
        {
            "event_type": e.event_type.value,
            "start_month": e.start_month,
            "duration_months": e.duration_months,
            "recovery_months": e.recovery_months,
            "severity": e.severity.value,
            "impact_params": e.effective_impact_params(),
        }
        for e in events
    ]
