"""Module M9 (scenario/calamity). Reuses the M8 simulation test harness
(run_simulation called directly, no live Celery worker in pytest) plus the
M4 GIS ingestion harness (a real ROAD layer, loaded through BG-01) to
exercise BR-23's spatial derivation for real, not with a stubbed ratio.
"""

import json

import pytest

from tests.conftest import TestSessionLocal
from tests.test_gis_ingestion import _upload_gis_file, _run_worker as _run_gis_worker
from tests.test_simulation import _make_ready_habitation, _run_worker as _run_sim_worker
from app.workers.tasks_simulate import run_simulation

# A straight 0.01-degree road (~1.1km near the equator) so a flood polygon
# covering a known fraction of its longitude span covers ~that same fraction
# of its length — the road is (deliberately) a plain LineString, so length
# and longitude-span are proportional.
ROAD_GEOJSON = json.dumps(
    {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Test Road"},
                "geometry": {"type": "LineString", "coordinates": [[74.80, 13.35], [74.81, 13.35]]},
            }
        ],
    }
).encode()

# Covers lon 74.80-74.804 of the road's 74.80-74.81 span: 40%.
FLOOD_POLYGON_40PCT = {
    "type": "MultiPolygon",
    "coordinates": [[[[74.80, 13.34], [74.804, 13.34], [74.804, 13.36], [74.80, 13.36], [74.80, 13.34]]]],
}

# Wide enough to contain the whole road (74.80-74.81, lat 13.35) — a GIS
# layer upload needs a habitation boundary to validate against (BR-06).
HABITATION_BOUNDARY = {
    "type": "MultiPolygon",
    "coordinates": [[[[74.79, 13.34], [74.82, 13.34], [74.82, 13.36], [74.79, 13.36], [74.79, 13.34]]]],
}


async def _make_ready_habitation_with_road(client, headers, name):
    habitation_id, psid = await _make_ready_habitation(client, headers, name, boundary_geojson=HABITATION_BOUNDARY)
    upload_resp = await _upload_gis_file(client, headers, habitation_id, ROAD_GEOJSON, "road.geojson", f"{name} road")
    await _run_gis_worker(upload_resp.json()["data"]["upload_id"])
    return habitation_id, psid


async def _make_completed_base_run(client, headers, habitation_id, horizon_years=5):
    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations", json={"horizon_years": horizon_years}, headers=headers
    )
    run_id = resp.json()["data"]["id"]
    await run_simulation(run_id, session_factory=TestSessionLocal)
    return run_id


async def test_event_catalogue_lists_all_nine_event_types(client, planner_headers):
    resp = await client.get("/api/v1/event-types", headers=planner_headers)
    assert resp.status_code == 200
    types = {row["event_type"] for row in resp.json()["data"]}
    assert types == {
        "FLOOD", "LANDSLIDE", "HEAVY_MONSOON", "ROAD_BLOCKAGE", "POPULATION_SURGE",
        "VEHICLE_BREAKDOWN", "TREATMENT_PLANT_OUTAGE", "FESTIVAL", "STRIKE",
    }


async def test_scenario_run_created_and_base_run_untouched(client, planner_headers, db_session):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Scenariobase")
    base_run_id = await _make_completed_base_run(client, planner_headers, habitation_id)

    before = await client.get(f"/api/v1/simulations/{base_run_id}", headers=planner_headers)
    before_data = before.json()["data"]

    scenario_resp = await client.post(
        f"/api/v1/simulations/{base_run_id}/scenarios",
        json={
            "label": "Flood test",
            "events": [
                {
                    "event_type": "FLOOD",
                    "start_month": 14,
                    "duration_months": 3,
                    "recovery_months": 3,
                    "severity": "SEVERE",
                    "impact_params": {"collection_coverage_pct": -35, "road_accessibility_loss": 0.4},
                }
            ],
        },
        headers=planner_headers,
    )
    assert scenario_resp.status_code == 202, scenario_resp.text
    scenario_data = scenario_resp.json()["data"]
    scenario_run_id = scenario_data["id"]
    assert scenario_data["run_type"] == "SCENARIO"
    assert scenario_data["parent_run_id"] == base_run_id
    assert scenario_data["parameter_set_id"] == before_data["parameter_set_id"]

    await _run_sim_worker(scenario_run_id)

    after = await client.get(f"/api/v1/simulations/{base_run_id}", headers=planner_headers)
    assert after.json()["data"] == before_data  # BR-22: base run byte-identical afterwards

    scenario_status = await client.get(f"/api/v1/simulations/{scenario_run_id}", headers=planner_headers)
    assert scenario_status.json()["data"]["status"] == "COMPLETED"


async def test_scenario_requires_a_completed_base_run(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Notcompletedville")
    create_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations", json={"horizon_years": 1}, headers=planner_headers
    )
    queued_run_id = create_resp.json()["data"]["id"]  # never executed -> stays QUEUED

    scenario_resp = await client.post(
        f"/api/v1/simulations/{queued_run_id}/scenarios",
        json={"events": [{"event_type": "STRIKE", "start_month": 1, "duration_months": 1}]},
        headers=planner_headers,
    )
    assert scenario_resp.status_code == 409
    assert scenario_resp.json()["error"]["code"] == "BASE_RUN_NOT_COMPLETED"


async def test_event_window_exceeding_horizon_is_rejected(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Toolongville")
    base_run_id = await _make_completed_base_run(client, planner_headers, habitation_id, horizon_years=1)

    scenario_resp = await client.post(
        f"/api/v1/simulations/{base_run_id}/scenarios",
        json={"events": [{"event_type": "STRIKE", "start_month": 11, "duration_months": 5}]},  # ends month 15 > 12
        headers=planner_headers,
    )
    assert scenario_resp.status_code == 400
    assert scenario_resp.json()["error"]["code"] == "EVENT_WINDOW_OUT_OF_RANGE"


async def test_flood_polygon_derives_road_accessibility_loss_from_gis(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation_with_road(client, planner_headers, "Roadflood")
    base_run_id = await _make_completed_base_run(client, planner_headers, habitation_id)

    preview_resp = await client.post(
        f"/api/v1/simulations/{base_run_id}/events/preview",
        json={"event_type": "FLOOD", "affected_area": FLOOD_POLYGON_40PCT},
        headers=planner_headers,
    )
    assert preview_resp.status_code == 200, preview_resp.text
    data = preview_resp.json()["data"]
    assert data["derived"] is True
    assert data["derived_impacts"]["road_accessibility_loss"] == pytest.approx(0.4, abs=0.02)


async def test_scenario_event_stores_derived_impact_overriding_declared(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation_with_road(client, planner_headers, "Roadflood2")
    base_run_id = await _make_completed_base_run(client, planner_headers, habitation_id)

    scenario_resp = await client.post(
        f"/api/v1/simulations/{base_run_id}/scenarios",
        json={
            "events": [
                {
                    "event_type": "FLOOD",
                    "start_month": 1,
                    "duration_months": 2,
                    "affected_area": FLOOD_POLYGON_40PCT,
                    # Deliberately a very different declared value, so we can
                    # tell whether the derived one actually won (BR-23).
                    "impact_params": {"road_accessibility_loss": 0.99},
                }
            ]
        },
        headers=planner_headers,
    )
    scenario_run_id = scenario_resp.json()["data"]["id"]

    events_resp = await client.get(f"/api/v1/simulations/{scenario_run_id}/events", headers=planner_headers)
    events = events_resp.json()["data"]
    assert len(events) == 1
    assert events[0]["impact_params"]["road_accessibility_loss"] == 0.99
    assert events[0]["derived_impacts"]["road_accessibility_loss"] == pytest.approx(0.4, abs=0.02)


async def test_recovery_ramp_is_gradual_not_instant(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Rampville")
    base_run_id = await _make_completed_base_run(client, planner_headers, habitation_id, horizon_years=2)

    scenario_resp = await client.post(
        f"/api/v1/simulations/{base_run_id}/scenarios",
        json={
            "events": [
                {
                    "event_type": "STRIKE",
                    "start_month": 5,
                    "duration_months": 2,
                    "recovery_months": 3,
                    "impact_params": {"collection_coverage_pct": -40},
                }
            ]
        },
        headers=planner_headers,
    )
    scenario_run_id = scenario_resp.json()["data"]["id"]
    await _run_sim_worker(scenario_run_id)

    monthly_resp = await client.get(
        f"/api/v1/simulations/{scenario_run_id}/results?aggregate=monthly", headers=planner_headers
    )
    series = {row["month_index"]: row["collection_coverage_pct"] for row in monthly_resp.json()["data"]["series"]}
    # months 5-6 fully hit, 7-8 recovering (strictly increasing), 9+ back to baseline
    assert series[5] < series[4]
    assert series[6] < series[4]
    assert series[7] > series[6]
    assert series[8] > series[7]
    assert series[9] == series[4]
