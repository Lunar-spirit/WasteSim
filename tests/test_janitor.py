"""BG-08 (BR-32): a run stuck in RUNNING past its timeout is marked FAILED
by the janitor sweep, never left hanging."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from tests.conftest import TestSessionLocal
from tests.test_simulation import _make_ready_habitation
from app.simulation.models import RunStatus, SimulationRun
from app.workers.beat import run_janitor_sweep


async def test_janitor_marks_a_stuck_run_failed(client, planner_headers, db_session):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Stuckville")
    create_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations", json={"horizon_years": 1}, headers=planner_headers
    )
    run_id = create_resp.json()["data"]["id"]

    # Simulate a worker that started the run and then died: RUNNING, with
    # started_at far enough in the past to be past SIMULATION_TIMEOUT.
    await db_session.execute(
        update(SimulationRun)
        .where(SimulationRun.id == run_id)
        .values(status=RunStatus.RUNNING, started_at=datetime.now(timezone.utc) - timedelta(hours=1))
    )
    await db_session.commit()

    swept = await run_janitor_sweep(session_factory=TestSessionLocal)
    assert swept["simulation_runs"] == 1

    status_resp = await client.get(f"/api/v1/simulations/{run_id}", headers=planner_headers)
    data = status_resp.json()["data"]
    assert data["status"] == "FAILED"
    assert "BR-32" in data["error_detail"]


async def test_janitor_leaves_a_fresh_running_run_alone(client, planner_headers, db_session):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Freshville")
    create_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations", json={"horizon_years": 1}, headers=planner_headers
    )
    run_id = create_resp.json()["data"]["id"]

    await db_session.execute(
        update(SimulationRun)
        .where(SimulationRun.id == run_id)
        .values(status=RunStatus.RUNNING, started_at=datetime.now(timezone.utc))
    )
    await db_session.commit()

    swept = await run_janitor_sweep(session_factory=TestSessionLocal)
    assert swept["simulation_runs"] == 0

    status_resp = await client.get(f"/api/v1/simulations/{run_id}", headers=planner_headers)
    assert status_resp.json()["data"]["status"] == "RUNNING"
