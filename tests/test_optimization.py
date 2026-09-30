"""Module M11 (optimization). Same harness pattern as test_simulation.py /
test_scenario.py: `run_optimization` is called directly with the test
suite's own NullPool session maker, no live Celery worker needed. Base runs
use a short 2-year horizon so a 20-30 candidate search stays fast.
"""

import json

import app.optimization.service as optimization_service
from tests.conftest import TestSessionLocal
from tests.test_gis_ingestion import _upload_gis_file, _run_worker as _run_gis_worker
from tests.test_simulation import _make_ready_habitation, _run_worker as _run_sim_worker
from app.habitation.models import Habitation
from app.parameters.models import ParameterSet, ParameterSetStatus
from app.optimization.service import format_worker_failure, get_optimization_readiness
from app.workers.tasks_simulate import run_simulation
from app.workers.tasks_optimize import run_optimization

ECO_SENSITIVE_GEOJSON = json.dumps(
    {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Mangrove buffer"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[74.795, 13.345], [74.805, 13.345], [74.805, 13.355], [74.795, 13.355], [74.795, 13.345]]],
                },
            }
        ],
    }
).encode()

HABITATION_BOUNDARY = {
    "type": "MultiPolygon",
    "coordinates": [[[[74.79, 13.34], [74.81, 13.34], [74.81, 13.36], [74.79, 13.36], [74.79, 13.34]]]],
}

DEFAULT_OBJECTIVES = {"MIN_COST": 0.4, "MIN_LANDFILL": 0.3, "MAX_COVERAGE": 0.2, "MIN_GHG": 0.1}


async def _make_completed_base_run(client, headers, habitation_id, horizon_years=2):
    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations", json={"horizon_years": horizon_years}, headers=headers
    )
    run_id = resp.json()["data"]["id"]
    await run_simulation(run_id, session_factory=TestSessionLocal)
    return run_id


async def test_optimization_weights_must_sum_to_one(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Badweightville")
    base_run_id = await _make_completed_base_run(client, planner_headers, habitation_id)

    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/optimizations",
        json={"base_run_id": base_run_id, "objectives": {"MIN_COST": 0.5, "MIN_LANDFILL": 0.4}},  # sums to 0.9
        headers=planner_headers,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "INVALID_OBJECTIVE_WEIGHTS"


async def test_optimization_rejects_unknown_objective(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Badobjville")
    base_run_id = await _make_completed_base_run(client, planner_headers, habitation_id)

    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/optimizations",
        json={"base_run_id": base_run_id, "objectives": {"MAX_PROFIT": 1.0}},
        headers=planner_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNKNOWN_OBJECTIVE"


async def test_optimization_requires_a_completed_base_run(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Notdonevile")
    create_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations", json={"horizon_years": 1}, headers=planner_headers
    )
    queued_run_id = create_resp.json()["data"]["id"]  # never executed -> stays QUEUED

    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/optimizations",
        json={"base_run_id": queued_run_id, "objectives": DEFAULT_OBJECTIVES},
        headers=planner_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BASE_RUN_NOT_COMPLETED"


async def test_eco_sensitive_zone_forces_landfill_expansion_to_zero(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Ecoville", boundary_geojson=HABITATION_BOUNDARY)
    upload_resp = await _upload_gis_file(
        client, planner_headers, habitation_id, ECO_SENSITIVE_GEOJSON, "eco.geojson", "Ecoville eco-sensitive zone",
        layer_type="ECO_SENSITIVE",
    )
    assert upload_resp.status_code == 202, upload_resp.text
    await _run_gis_worker(upload_resp.json()["data"]["upload_id"])

    base_run_id = await _make_completed_base_run(client, planner_headers, habitation_id)

    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/optimizations",
        json={"base_run_id": base_run_id, "objectives": DEFAULT_OBJECTIVES, "max_evaluations": 5},
        headers=planner_headers,
    )
    assert resp.status_code == 202, resp.text
    data = resp.json()["data"]
    assert data["decision_space"]["landfill_expansion_tonnes"] == [0.0, 0.0]
    assert any("BR-26" in note for note in data["notes"])


async def test_infeasible_constraints_yield_no_best_plan(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Impossibleville")
    base_run_id = await _make_completed_base_run(client, planner_headers, habitation_id)

    create_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/optimizations",
        json={
            "base_run_id": base_run_id,
            "objectives": DEFAULT_OBJECTIVES,
            # No capex at all can possibly satisfy 100% coverage inside a
            # zero-rupee budget alongside a 100% minimum coverage floor.
            "constraints": {"capex_budget_inr": 0, "min_coverage_pct": 100},
            "max_evaluations": 15,
        },
        headers=planner_headers,
    )
    optimization_id = create_resp.json()["data"]["optimization_id"]
    await run_optimization(optimization_id, session_factory=TestSessionLocal)

    status_resp = await client.get(f"/api/v1/optimizations/{optimization_id}", headers=planner_headers)
    data = status_resp.json()["data"]
    assert data["status"] == "FAILED"
    assert data["best_candidate_id"] is None
    assert data["infeasible_reason"] is not None
    assert "BR-25" in data["infeasible_reason"]
    # Two-line contract: a planner-facing headline on the first line (used as
    # the collapsed banner text), the exact BR-25 wording (asserted above)
    # on the second (used inside the [View Details] accordion).
    headline, _, detail = data["infeasible_reason"].partition("\n")
    assert headline.startswith("Infeasible optimization constraints:")
    assert "BR-25" in detail


async def test_normal_search_finds_a_plan_at_least_as_good_as_do_nothing(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Searchville")
    base_run_id = await _make_completed_base_run(client, planner_headers, habitation_id)

    create_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/optimizations",
        json={"base_run_id": base_run_id, "objectives": DEFAULT_OBJECTIVES, "max_evaluations": 25},
        headers=planner_headers,
    )
    assert create_resp.status_code == 202, create_resp.text
    optimization_id = create_resp.json()["data"]["optimization_id"]
    await run_optimization(optimization_id, session_factory=TestSessionLocal)

    status_resp = await client.get(f"/api/v1/optimizations/{optimization_id}", headers=planner_headers)
    data = status_resp.json()["data"]
    assert data["status"] == "COMPLETED", data
    assert data["candidates_evaluated"] == 25
    assert data["best_candidate_id"] is not None

    candidates_resp = await client.get(
        f"/api/v1/optimizations/{optimization_id}/candidates", headers=planner_headers
    )
    candidates = candidates_resp.json()["data"]
    best = next(c for c in candidates if c["id"] == data["best_candidate_id"])
    # The do-nothing plan is always evaluated and normalises to a score of
    # ~1.0 against itself (the base run) — the best candidate found can
    # never score meaningfully below that (a small tolerance covers the
    # float/Decimal rounding between the persisted base run and a freshly
    # recomputed one).
    assert best["score"] >= 0.99
    assert best["feasible"] is True

    pareto_resp = await client.get(f"/api/v1/optimizations/{optimization_id}/pareto", headers=planner_headers)
    pareto = pareto_resp.json()["data"]
    assert len(pareto) >= 1
    assert all(c["is_pareto"] for c in pareto)

    explanation_resp = await client.get(
        f"/api/v1/optimizations/{optimization_id}/explanation", headers=planner_headers
    )
    explanation = explanation_resp.json()["data"]
    assert explanation["candidate_id"] == data["best_candidate_id"]
    assert "disclaimer" in explanation

    promote_resp = await client.post(
        f"/api/v1/optimizations/{optimization_id}/promote", json={}, headers=planner_headers
    )
    assert promote_resp.status_code == 202, promote_resp.text
    optimized_run_id = promote_resp.json()["data"]["id"]
    assert promote_resp.json()["data"]["run_type"] == "OPTIMIZED"

    await _run_sim_worker(optimized_run_id)
    run_status = await client.get(f"/api/v1/simulations/{optimized_run_id}", headers=planner_headers)
    assert run_status.json()["data"]["status"] == "COMPLETED"


async def _async(value):
    return value


async def test_readiness_blocks_without_base_simulation(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Nobaserunville")

    resp = await client.get(
        f"/api/v1/habitations/{habitation_id}/optimization/readiness", headers=planner_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["can_run"] is False
    assert data["checks"]["base_simulation_exists"] is False
    assert data["action_label"] == "Go to Simulations"
    assert data["action_tab"] == "simulations"
    assert "baseline simulation" in data["blocking_reason"]


async def test_readiness_blocks_when_worker_offline(client, planner_headers, monkeypatch):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Workeroffline")
    await _make_completed_base_run(client, planner_headers, habitation_id)

    monkeypatch.setattr(optimization_service, "_worker_available", lambda: _async(False))

    resp = await client.get(
        f"/api/v1/habitations/{habitation_id}/optimization/readiness", headers=planner_headers
    )
    data = resp.json()["data"]
    assert data["can_run"] is False
    assert data["checks"]["base_simulation_exists"] is True
    assert data["checks"]["parameters_validated"] is True
    assert data["checks"]["worker_available"] is False
    assert "offline" in data["blocking_reason"]


async def test_readiness_can_run_true_ignores_missing_gis_roads(client, planner_headers, monkeypatch):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Readyville")
    await _make_completed_base_run(client, planner_headers, habitation_id)

    monkeypatch.setattr(optimization_service, "_worker_available", lambda: _async(True))

    resp = await client.get(
        f"/api/v1/habitations/{habitation_id}/optimization/readiness", headers=planner_headers
    )
    data = resp.json()["data"]
    # No ROAD layer was ever uploaded for this habitation, but that's only
    # advisory (design decision documented in service.py) — it must not
    # block the run.
    assert data["checks"]["gis_roads_ready"] is False
    assert data["can_run"] is True
    assert data["blocking_reason"] is None


async def test_readiness_blocks_when_parameters_not_validated(client, planner_headers):
    """DRAFT-with-a-completed-base-run is not reachable through the real
    API (committing is what sets active_parameter_set_id in the first
    place, and nothing un-validates it afterward without also pointing at a
    freshly VALIDATED set) — so this exercises the branch directly against
    a hand-built DB state, the same way a unit test would."""
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Draftregressville")
    await _make_completed_base_run(client, planner_headers, habitation_id)

    async with TestSessionLocal() as db:
        habitation = await db.get(Habitation, habitation_id)
        active = await db.get(ParameterSet, habitation.active_parameter_set_id)
        draft = ParameterSet(
            habitation_id=habitation_id,
            version_no=99,
            status=ParameterSetStatus.DRAFT,
            created_by=active.created_by,
        )
        db.add(draft)
        await db.flush()
        habitation.active_parameter_set_id = draft.id
        await db.commit()

        readiness = await get_optimization_readiness(db, habitation_id)

    assert readiness["can_run"] is False
    assert readiness["checks"]["base_simulation_exists"] is True
    assert readiness["checks"]["parameters_validated"] is False
    assert readiness["action_label"] == "Review Parameters"
    assert readiness["action_tab"] == "parameters"
    assert "VALIDATED" in readiness["blocking_reason"]


def test_format_worker_failure_maps_known_exception_types():
    reason = format_worker_failure(RuntimeError("column simulation_yearly.foo does not exist"))
    headline, _, detail = reason.partition("\n")
    assert headline == "Optimization run failed unexpectedly"
    assert "RuntimeError" in detail

    class ProgrammingError(Exception):
        pass

    reason = format_worker_failure(ProgrammingError("column x does not exist"))
    headline, _, detail = reason.partition("\n")
    assert headline == "Database schema out of date"
    assert "ProgrammingError" in detail
