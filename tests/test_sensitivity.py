"""Module M10 (sensitivity/elasticity). Same harness pattern as
test_optimization.py: `run_sweep_task` is called directly with the test
suite's own NullPool session maker. Short 2-year horizons keep 5-point
sweeps fast.
"""

from tests.conftest import TestSessionLocal
from tests.test_simulation import _make_ready_habitation
from app.workers.tasks_simulate import run_simulation
from app.workers.tasks_sensitivity import run_sweep_task


async def _make_completed_base_run(client, headers, habitation_id, horizon_years=2):
    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations", json={"horizon_years": horizon_years}, headers=headers
    )
    run_id = resp.json()["data"]["id"]
    await run_simulation(run_id, session_factory=TestSessionLocal)
    return run_id


async def test_sweep_rejects_non_sweepable_parameter(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Notsweptville")
    base_run_id = await _make_completed_base_run(client, planner_headers, habitation_id)

    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/sensitivity",
        json={"base_run_id": base_run_id, "param_path": "demography.household_size_avg", "values": [3.0, 4.0]},
        headers=planner_headers,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "PARAM_NOT_SWEEPABLE"


async def test_sweep_rejects_value_outside_catalogue_range(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Outofrangeville")
    base_run_id = await _make_completed_base_run(client, planner_headers, habitation_id)

    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/sensitivity",
        json={
            "base_run_id": base_run_id,
            "param_path": "demography.annual_growth_rate_pct",
            "values": [1.0, 500.0],
        },
        headers=planner_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALUE_OUT_OF_RANGE"


async def test_sweep_computes_elasticity_and_monotonic_exhaustion(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Sweepville")
    base_run_id = await _make_completed_base_run(client, planner_headers, habitation_id, horizon_years=3)

    create_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/sensitivity",
        json={
            "base_run_id": base_run_id,
            "param_path": "demography.annual_growth_rate_pct",
            "values": [0.0, 2.0, 4.0, 6.0, 8.0],
            "indicators": ["NPV_TOTAL_COST", "LANDFILL_EXHAUSTION_YEAR"],
        },
        headers=planner_headers,
    )
    assert create_resp.status_code == 202, create_resp.text
    analysis_id = create_resp.json()["data"]["id"]
    await run_sweep_task(analysis_id, session_factory=TestSessionLocal)

    status_resp = await client.get(f"/api/v1/sensitivity/{analysis_id}", headers=planner_headers)
    data = status_resp.json()["data"]
    assert data["status"] == "COMPLETED", data
    points = data["points"]
    assert len(points) == 5
    assert all(p["child_run_id"] is not None for p in points)

    # Higher growth -> more waste -> landfill exhausts no later than at a
    # lower growth rate (monotonically non-increasing exhaustion year).
    exhaustion_years = [p["indicator_values"].get("LANDFILL_EXHAUSTION_YEAR") for p in points]
    known = [y for y in exhaustion_years if y is not None]
    assert known == sorted(known, reverse=True) or len(known) <= 1

    # NPV should rise as growth rises (more waste to handle costs more).
    npvs = [p["indicator_values"]["NPV_TOTAL_COST"] for p in points]
    assert npvs == sorted(npvs)

    tornado_resp = await client.get(f"/api/v1/sensitivity/{analysis_id}/tornado", headers=planner_headers)
    tornado = tornado_resp.json()["data"]
    assert {row["indicator"] for row in tornado} <= {"NPV_TOTAL_COST", "LANDFILL_EXHAUSTION_YEAR"}

    list_resp = await client.get(f"/api/v1/habitations/{habitation_id}/sensitivity", headers=planner_headers)
    assert len(list_resp.json()["data"]) == 1
