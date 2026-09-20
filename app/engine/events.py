"""Which events are in force this month, and how strongly.

Only the generic mechanics live here: a window, a severity-scaled magnitude,
and a linear recovery ramp back to baseline (design section 5.5's "without
this, resilience is unmeasurable" requirement). *Deriving* an event's
impact_params from GIS geometry (BR-23 — intersecting a flood polygon with
the ROAD layer) is module M9's job, built on top of this in a later session;
by the time a list of events reaches the engine, impact_params is already a
plain {"collection_coverage_pct": -35, "road_accessibility_loss": 0.4} dict,
however it was derived.

An event dict has the shape:
    {
        "event_type": "FLOOD",
        "start_month": 14, "duration_months": 3, "recovery_months": 3,
        "severity": "SEVERE",              # LOW / MODERATE / SEVERE
        "impact_params": {"collection_coverage_pct": -35, "road_accessibility_loss": 0.4},
    }
"""

from __future__ import annotations

from typing import Any

SEVERITY_MULTIPLIER = {"LOW": 0.5, "MODERATE": 1.0, "SEVERE": 1.6}


def active_in(events: list[dict[str, Any]], month: int) -> list[dict[str, Any]]:
    """Every event covering `month`, either at full strength (still within
    its window) or ramping down afterwards (design 5.5's recovery ramp),
    each annotated with `_ramp` in (0, 1] — how much of its declared impact
    still applies this month."""
    active = []
    for event in events:
        start = event["start_month"]
        window_end = start + event["duration_months"] - 1
        recovery_months = event.get("recovery_months", 0)
        recovery_end = window_end + recovery_months

        if month < start or month > recovery_end:
            continue

        if month <= window_end:
            ramp = 1.0
        elif recovery_months > 0:
            months_into_recovery = month - window_end
            ramp = max(0.0, 1.0 - months_into_recovery / recovery_months)
        else:
            ramp = 0.0

        if ramp <= 0.0:
            continue

        severity_mult = SEVERITY_MULTIPLIER.get(event.get("severity", "MODERATE"), 1.0)
        active.append({**event, "_ramp": ramp * severity_mult})
    return active


def coverage_delta_pct(active_events: list[dict[str, Any]]) -> float:
    """Additive change to collection_coverage_pct from every active event —
    events stack additively (two events both cutting coverage compound)."""
    return sum(
        event.get("impact_params", {}).get("collection_coverage_pct", 0.0) * event["_ramp"]
        for event in active_events
    )


def accessibility_multiplier(active_events: list[dict[str, Any]]) -> float:
    """Multiplicative accessibility loss from road damage — multiple events
    compose multiplicatively (design 5.4.6: "event_factor = product of
    (1 - road_accessibility_loss) over active events")."""
    factor = 1.0
    for event in active_events:
        loss = event.get("impact_params", {}).get("road_accessibility_loss", 0.0) * event["_ramp"]
        factor *= max(0.0, 1.0 - loss)
    return factor


def capacity_delta_tpd(active_events: list[dict[str, Any]]) -> float:
    """A TREATMENT_PLANT_OUTAGE-style event reduces usable capacity."""
    return sum(
        event.get("impact_params", {}).get("treatment_capacity_tpd", 0.0) * event["_ramp"]
        for event in active_events
    )


def population_surge_multiplier(active_events: list[dict[str, Any]]) -> float:
    """A POPULATION_SURGE event multiplies P_eff for its window (design
    5.5's table: "P_eff multiplied for the window"). Multiple surges
    compose multiplicatively, same as accessibility_multiplier."""
    factor = 1.0
    for event in active_events:
        surge_pct = event.get("impact_params", {}).get("population_surge_pct", 0.0) * event["_ramp"]
        factor *= 1.0 + surge_pct / 100.0
    return factor


def active_event_codes(active_events: list[dict[str, Any]]) -> list[str]:
    return [event["event_type"] for event in active_events]
