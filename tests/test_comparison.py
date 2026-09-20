"""Module M13 (comparison). Reuses the M8 simulation harness to build a
couple of completed runs, then exercises API-76/77/78 directly."""

from tests.conftest import TestSessionLocal
from tests.test_simulation import _make_ready_habitation
from app.workers.tasks_simulate import run_simulation


async def _make_completed_run(client, headers, habitation_id, horizon_years=2, label=None):
    payload = {"horizon_years": horizon_years}
    if label:
        payload["label"] = label
    resp = await client.post(f"/api/v1/habitations/{habitation_id}/simulations", json=payload, headers=headers)
    run_id = resp.json()["data"]["id"]
    await run_simulation(run_id, session_factory=TestSessionLocal)
    return run_id


async def test_comparison_requires_same_habitation(client, planner_headers):
    hab_a, _ = await _make_ready_habitation(client, planner_headers, "CompareA")
    hab_b, _ = await _make_ready_habitation(client, planner_headers, "CompareB")
    run_a = await _make_completed_run(client, planner_headers, hab_a)
    run_b = await _make_completed_run(client, planner_headers, hab_b)

    resp = await client.post(
        "/api/v1/comparisons", json={"run_ids": [run_a, run_b]}, headers=planner_headers
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "RUNS_NOT_COMPARABLE"


async def test_comparison_aligns_series_and_computes_deltas(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Compareville")
    run_1 = await _make_completed_run(client, planner_headers, habitation_id, horizon_years=2, label="Base")
    run_2 = await _make_completed_run(client, planner_headers, habitation_id, horizon_years=3, label="Longer")

    create_resp = await client.post(
        "/api/v1/comparisons",
        json={"run_ids": [run_1, run_2], "indicators": ["total_cost_inr", "landfilled_tpy"], "title": "T1 vs T2"},
        headers=planner_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    comparison_id = create_resp.json()["data"]["id"]

    series_resp = await client.get(f"/api/v1/comparisons/{comparison_id}", headers=planner_headers)
    series = series_resp.json()["data"]
    assert series["run_ids"] == [run_1, run_2]
    assert len(series["series"]["total_cost_inr"]) == 3  # aligned to the longer run's 3 years
    year1 = series["series"]["total_cost_inr"][0]
    assert year1["values"][run_1] is not None
    assert year1["values"][run_2] is not None
    year3 = series["series"]["total_cost_inr"][2]
    assert year3["values"][run_1] is None  # run_1 only has 2 years

    deltas_resp = await client.get(f"/api/v1/comparisons/{comparison_id}/deltas", headers=planner_headers)
    deltas = deltas_resp.json()["data"]
    assert deltas["base_run_id"] == run_1
    expected_delta = (
        series["series"]["total_cost_inr"][0]["values"][run_2] - series["series"]["total_cost_inr"][0]["values"][run_1]
    )
    assert deltas["deltas"]["total_cost_inr"][0][run_2] == expected_delta
    assert deltas["deltas"]["total_cost_inr"][2][run_2] is None  # run_1 has no year-3 value to diff against
