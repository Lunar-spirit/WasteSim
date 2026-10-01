"""Sensitive-data masking and write restrictions for the default VIEWER
role — everything a fresh self-registered account can and can't see/do
before an admin approves their RESEARCHER application.
"""

from tests.conftest import TestSessionLocal
from tests.test_simulation import _make_ready_habitation, _run_worker
from app.habitation.models import AccessLevel, HabitationMember


async def _grant_membership(habitation_id: str, user_and_password, access_level=AccessLevel.VIEWER) -> None:
    """GET /parameter-sets/{psid} checks habitation membership directly
    (not the READY-habitation-is-open-to-all carve-out check_habitation_access
    gives everything else), so any non-ADMIN test user — VIEWER role or
    not — needs an explicit habitation_members row to reach it at all."""
    user, _password = user_and_password
    async with TestSessionLocal() as db:
        db.add(HabitationMember(habitation_id=habitation_id, user_id=user.id, access_level=access_level))
        await db.commit()


async def _make_completed_run(client, headers, habitation_id, horizon_years=2):
    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations", json={"horizon_years": horizon_years}, headers=headers
    )
    run_id = resp.json()["data"]["id"]
    await _run_worker(run_id)
    return run_id


async def test_viewer_sees_masked_economic_fields(client, planner_headers, viewer_headers, viewer_user):
    habitation_id, psid = await _make_ready_habitation(client, planner_headers, "Maskedville")
    await _grant_membership(habitation_id, viewer_user)

    resp = await client.get(f"/api/v1/parameter-sets/{psid}", headers=viewer_headers)
    assert resp.status_code == 200, resp.text
    economic = resp.json()["data"]["categories"]["economic_conditions"]
    assert economic["swm_annual_budget"] is None

    demography = resp.json()["data"]["categories"]["demography"]
    assert demography["population"] == 22500  # non-sensitive field untouched


async def test_researcher_sees_unmasked_economic_fields(client, planner_headers, researcher_headers, researcher_user):
    habitation_id, psid = await _make_ready_habitation(client, planner_headers, "Unmaskedville")
    await _grant_membership(habitation_id, researcher_user)
    resp = await client.get(f"/api/v1/parameter-sets/{psid}", headers=researcher_headers)
    assert resp.status_code == 200, resp.text
    economic = resp.json()["data"]["categories"]["economic_conditions"]
    assert float(economic["swm_annual_budget"]) == 2_500_000.0


async def test_viewer_cannot_see_draft_parameter_set(client, planner_headers, viewer_headers, viewer_user):
    habitation_resp = await client.post(
        "/api/v1/habitations",
        json={"name": "Draftonly", "habitation_type": "VILLAGE", "state": "Karnataka", "district": "Udupi"},
        headers=planner_headers,
    )
    habitation_id = habitation_resp.json()["data"]["id"]
    ps_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/parameter-sets", json={}, headers=planner_headers
    )
    psid = ps_resp.json()["data"]["id"]
    await _grant_membership(habitation_id, viewer_user)

    resp = await client.get(f"/api/v1/parameter-sets/{psid}", headers=viewer_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN_ROLE"


async def test_viewer_budget_lines_forbidden(client, planner_headers, viewer_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Budgetlockville")
    run_id = await _make_completed_run(client, planner_headers, habitation_id)

    resp = await client.get(f"/api/v1/simulations/{run_id}/budget/lines", headers=viewer_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN_ROLE"


async def test_researcher_budget_lines_allowed(client, planner_headers, researcher_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Budgetokville")
    run_id = await _make_completed_run(client, planner_headers, habitation_id)

    resp = await client.get(f"/api/v1/simulations/{run_id}/budget/lines", headers=researcher_headers)
    assert resp.status_code == 200
    assert len(resp.json()["data"]) > 0


async def test_viewer_budget_summary_masked(client, planner_headers, viewer_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Summaryville")
    run_id = await _make_completed_run(client, planner_headers, habitation_id)

    resp = await client.get(f"/api/v1/simulations/{run_id}/budget/summary", headers=viewer_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["run_id"] == run_id  # non-sensitive identifier untouched
    assert data["total_opex_inr"] is None
    assert data["total_capex_inr"] is None
    assert data["total_cost_inr"] is None
    assert data["npv_total_cost_inr"] is None
    assert data["by_category"] is None


async def test_researcher_budget_summary_unmasked(client, planner_headers, researcher_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Summaryokville")
    run_id = await _make_completed_run(client, planner_headers, habitation_id)

    resp = await client.get(f"/api/v1/simulations/{run_id}/budget/summary", headers=researcher_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_cost_inr"] is not None


async def test_viewer_cannot_create_scenario(client, planner_headers, viewer_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Scenarioblockville")
    run_id = await _make_completed_run(client, planner_headers, habitation_id)

    resp = await client.post(
        f"/api/v1/simulations/{run_id}/scenarios",
        json={"events": [{"event_type": "FLOOD", "start_month": 6, "duration_months": 2, "severity": "MODERATE"}]},
        headers=viewer_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN_ROLE"


async def test_viewer_gets_masked_findings_without_error(client, planner_headers, viewer_headers):
    """Non-cost summary data (findings, incl. landfill exhaustion year) stays
    fully visible to VIEWER — only the Economics/Labor bucket is masked."""
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Findingsville")
    run_id = await _make_completed_run(client, planner_headers, habitation_id)

    resp = await client.get(f"/api/v1/simulations/{run_id}/findings", headers=viewer_headers)
    assert resp.status_code == 200
