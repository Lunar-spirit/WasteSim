import json
import uuid
from typing import Any

from geoalchemy2.functions import ST_GeomFromGeoJSON, ST_SetSRID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.deps import check_habitation_access
from app.core.errors import AppError
from app.engine.run import ENGINE_VERSION
from app.engine.run import run as engine_run
from app.habitation.models import AccessLevel, Habitation
from app.habitation.service import get_habitation_or_404
from app.parameters.service import get_parameter_set_full
from app.scenario.models import EventType, ScenarioEvent
from app.scenario.schemas import ComparativePreviewIn, EventIn, ScenarioCreateIn
from app.scenario.spatial_impact import derive_impacts
from app.simulation.models import CoefficientSet, RunStatus, RunType, SimulationRun
from app.simulation.service import materialize_params

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

# Baseline (MODERATE-severity) impact_params per event type, for the
# one-click comparative preview (app/scenario/schemas.py's
# ComparativePreviewIn), which asks for only an event type + severity +
# duration — not the full declared impact_params a manually-built
# ScenarioCreateIn event requires. The engine itself only understands four
# levers (app/engine/events.py: collection_coverage_pct, road_accessibility_
# loss, treatment_capacity_tpd, population_surge_pct); each entry below
# picks the one or two that best match that event type's design-5.5
# "effect" description in EVENT_CATALOGUE above. LOW/SEVERE scaling comes
# for free from the engine's own SEVERITY_MULTIPLIER (app/engine/events.py)
# — these are the MODERATE baseline only.
#
# VEHICLE_BREAKDOWN has no direct "fewer trucks" lever, so it's modelled as
# a coverage reduction (fewer trucks -> less area actually serviced) — a
# documented approximation, not a precise fleet-capacity simulation.
#
# FESTIVAL is deliberately absent: it's already modelled natively by the
# engine every festival month (coeffs["festival_waste_multiplier"], scaled
# by cultural_context.festival_days_count) — a second, scenario-event
# "festival" would double-count the same real-world effect rather than
# model a distinct one, so preview_comparative_impact rejects it outright.
DEFAULT_IMPACT_PARAMS: dict[str, dict[str, float]] = {
    "FLOOD": {"road_accessibility_loss": 0.4, "collection_coverage_pct": -30.0, "treatment_capacity_tpd": 1.0},
    "LANDSLIDE": {"road_accessibility_loss": 0.35},
    "HEAVY_MONSOON": {"road_accessibility_loss": 0.10},
    "ROAD_BLOCKAGE": {"road_accessibility_loss": 0.5},
    "POPULATION_SURGE": {"population_surge_pct": 25.0},
    "VEHICLE_BREAKDOWN": {"collection_coverage_pct": -20.0},
    "TREATMENT_PLANT_OUTAGE": {"treatment_capacity_tpd": 1000.0},  # clamped to 0 by step.py's own max(0.0, ...)
    "STRIKE": {"collection_coverage_pct": -60.0},
}


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


async def _habitation_boundary_geojson(db: AsyncSession, habitation_id: uuid.UUID) -> dict[str, Any] | None:
    """Same ST_AsGeoJSON idiom app/automation/service.py's own
    _get_habitation_geometry and app/gis/service.py's get_map_overlay
    already use — kept local rather than imported across modules for a
    five-line query."""
    geom_json = await db.scalar(
        select(func.ST_AsGeoJSON(Habitation.boundary)).where(Habitation.id == habitation_id)
    )
    return json.loads(geom_json) if geom_json else None


_RECOVERY_TOLERANCE_FRACTION = 0.02  # "back to baseline" = within 2% of the base run's own collected tonnage


async def preview_comparative_impact(
    db: AsyncSession, payload: ComparativePreviewIn, user: User
) -> dict[str, Any]:
    """POST /api/v1/scenarios/preview — an instant base-vs-shocked
    comparison computed synchronously in this one request: the pure engine
    (app/engine/run.py) is fast enough (<50ms for a full 240-month run,
    per tests/test_engine.py) to just call twice here rather than queue a
    real SCENARIO SimulationRun and poll for it. Nothing is persisted —
    simulation_results/simulation_yearly are insert-only, real-run tables
    (rule #2); this never writes to them, matching how preview_impact()
    above already previews without a run.
    """
    await check_habitation_access(db, user, payload.habitation_id, AccessLevel.VIEWER)
    habitation = await get_habitation_or_404(db, payload.habitation_id)

    if payload.event_type == EventType.FESTIVAL:
        raise AppError(
            "EVENT_TYPE_NOT_PREVIEWABLE",
            "FESTIVAL is already modelled natively every festival month (cultural_context."
            "festival_days_count) — a scenario event of this type would double-count the same effect, "
            "not model a distinct one.",
            422,
        )

    base_run = await db.get(SimulationRun, payload.base_run_id)
    if base_run is None:
        raise AppError("RUN_NOT_FOUND", "Base run not found", 404)
    if base_run.habitation_id != payload.habitation_id:
        raise AppError("RUN_NOT_FOUND", "Base run does not belong to this habitation", 404)
    if base_run.status != RunStatus.COMPLETED:
        raise AppError("BASE_RUN_NOT_COMPLETED", f"Base run must be COMPLETED, is {base_run.status.value}", 409)

    horizon_months = base_run.horizon_years * 12
    # Overpass/GIS-style month granularity from a week-based UI input: the
    # engine's whole event model (app/engine/events.py) only understands
    # whole months, there is no week-level resolution anywhere in it.
    duration_months = max(1, round(payload.duration_weeks / 4.345))
    window_end = payload.start_month + duration_months - 1
    if window_end > horizon_months:
        raise AppError(
            "EVENT_WINDOW_OUT_OF_RANGE",
            f"Event window (months {payload.start_month}-{window_end}) exceeds the base run's "
            f"{horizon_months}-month horizon",
            400,
        )

    coeff_set = await db.get(CoefficientSet, base_run.coefficient_set_id)
    params = await materialize_params(
        db, base_run.parameter_set_id, habitation.habitation_type.value, base_run.param_overrides
    )

    notes: list[str] = []
    affected_area = payload.custom_polygon_geojson
    if affected_area is None and payload.apply_full_boundary:
        affected_area = await _habitation_boundary_geojson(db, payload.habitation_id)
        if affected_area is None:
            notes.append("apply_full_boundary was set, but this habitation has no boundary geometry to use.")

    impact_params = dict(DEFAULT_IMPACT_PARAMS[payload.event_type.value])
    if affected_area is not None:
        derived = await derive_impacts(db, payload.habitation_id, payload.event_type.value, affected_area)
        if derived:
            # Only road_accessibility_loss is one of the four keys the engine
            # actually reads (app/engine/events.py) — derive_impacts() also
            # returns population_affected_pct, an informational figure with
            # no engine lever, so filtering to keys this event already
            # declares a default for is what keeps that one out.
            impact_params.update({k: v for k, v in derived.items() if k in impact_params})
            notes.append("road_accessibility_loss derived from this habitation's own ROAD layer, not a static guess.")

    vulnerability = await _vulnerability_multiplier(db, base_run.parameter_set_id, payload.event_type.value)
    impact_params = {k: v * vulnerability for k, v in impact_params.items()}

    event = {
        "event_type": payload.event_type.value,
        "start_month": payload.start_month,
        "duration_months": duration_months,
        # No recovery input in the request shape asked for — half the
        # disruption's own duration is this endpoint's own default ramp,
        # documented rather than silently picked, same as coefficients.py's
        # own undeclared-default convention.
        "recovery_months": max(1, duration_months // 2),
        "severity": payload.severity_intensity.value,
        "impact_params": impact_params,
    }

    coeffs_raw = coeff_set.coefficients
    base_result = engine_run(params, events=[], coeffs_raw=coeffs_raw, months=horizon_months, config=base_run.config)
    scenario_result = engine_run(
        params, events=[event], coeffs_raw=coeffs_raw, months=horizon_months, config=base_run.config
    )

    series: list[dict[str, Any]] = []
    running_backlog = 0.0
    peak_backlog = 0.0
    net_penalty = 0.0
    recovery_month: int | None = None
    base_month1_collected = base_result["monthly"][0]["waste_collected_tpd"] or 1.0

    for base_snapshot, scenario_snapshot in zip(base_result["monthly"], scenario_result["monthly"], strict=True):
        days = base_snapshot["days_in_month"]
        extra_uncollected_tonnes = max(
            0.0, (scenario_snapshot["waste_uncollected_tpd"] - base_snapshot["waste_uncollected_tpd"]) * days
        )
        # Honest, not fabricated: the engine has no "fleet works through a
        # backlog once conditions normalise" mechanic (each month's
        # uncollected tonnage is independent, app/engine/step.py Part 5) —
        # this plateaus once the event's ramp reaches zero rather than
        # declining, and the frontend says so rather than implying a
        # cleanup mechanic that isn't actually being simulated.
        running_backlog = max(0.0, running_backlog + extra_uncollected_tonnes)
        peak_backlog = max(peak_backlog, running_backlog)
        net_penalty += scenario_snapshot["opex_inr"] + scenario_snapshot["capex_inr"] - base_snapshot["opex_inr"] - base_snapshot["capex_inr"]

        if (
            recovery_month is None
            and base_snapshot["month_index"] >= payload.start_month
            and abs(scenario_snapshot["waste_collected_tpd"] - base_snapshot["waste_collected_tpd"])
            < _RECOVERY_TOLERANCE_FRACTION * base_month1_collected
        ):
            recovery_month = base_snapshot["month_index"]

        series.append(
            {
                "month": base_snapshot["month_index"],
                "base_collected_tpd": base_snapshot["waste_collected_tpd"],
                "scenario_collected_tpd": scenario_snapshot["waste_collected_tpd"],
                "base_opex_inr": base_snapshot["opex_inr"],
                "scenario_opex_inr": scenario_snapshot["opex_inr"],
                "uncollected_backlog_tonnes": round(running_backlog, 3),
            }
        )

    recovery_time_weeks = (recovery_month - payload.start_month) * 4.345 if recovery_month is not None else None
    if recovery_month is None:
        notes.append("Scenario collection never returns within 2% of baseline inside this run's own horizon.")
    notes.append(
        "uncollected_backlog is the cumulative extra tonnage left uncollected by the shock, relative to the "
        "base run — it plateaus once the event's own ramp fully recovers rather than declining, since the "
        "engine doesn't model a fleet working through a backlog once conditions return to normal."
    )
    if net_penalty < 0:
        # Genuinely possible, not a bug: an event that only cuts
        # collection_coverage_pct (STRIKE, VEHICLE_BREAKDOWN) means less
        # material moves through the whole collection->treatment->disposal
        # chain, so measured opex actually drops — there is no modelled
        # "overtime to clear the backlog" cost to offset it with. The real
        # cost of the uncollected tonnage is the backlog itself
        # (peak_backlog_tonnes), not a fabricated cleanup line item.
        notes.append(
            "Net financial penalty is negative: this event only reduces collection coverage, so less waste "
            "moves through the paid collection/treatment/disposal chain — the real cost of the disruption is "
            "the uncollected backlog above, not a modelled cleanup-overtime expense."
        )

    return {
        "event_type": payload.event_type,
        "severity_intensity": payload.severity_intensity,
        "duration_months": duration_months,
        "start_month": payload.start_month,
        "horizon_months": horizon_months,
        "series": series,
        "peak_backlog_tonnes": round(peak_backlog, 3),
        "net_financial_penalty_inr": round(net_penalty, 2),
        "recovery_time_weeks": round(recovery_time_weeks, 1) if recovery_time_weeks is not None else None,
        "notes": notes,
    }


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
