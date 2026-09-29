from datetime import date, timedelta

import pytest

from tests.test_simulation import _make_ready_habitation, _run_worker


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


async def _log_day(client, headers, habitation_id, log_date, **overrides):
    payload = {
        "log_date": log_date,
        "total_collected_tonnes": 12.0,
        "organic_tonnes": 7.0,
        "dry_recyclable_tonnes": 4.0,
        "vehicles_deployed": 4,
        "trips_completed": 8,
        "anomaly_flag": "NORMAL",
    }
    payload.update(overrides)
    resp = await client.post(f"/api/v1/habitations/{habitation_id}/daily-logs", headers=headers, json=payload)
    assert resp.status_code == 200, resp.text


async def test_recalibration_report_computes_real_variance(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "RecalVille")
    # 6 days in the last 30 — clears MIN_DAYS_FOR_AVERAGE (5).
    for day in range(1, 7):
        await _log_day(client, planner_headers, habitation_id, _days_ago(day))

    resp = await client.get(f"/api/v1/habitations/{habitation_id}/recalibration-report", headers=planner_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["moving_average_30d"]["sample_days"] == 6
    assert data["moving_average_30d"]["avg_total_collected_tpd"] == pytest.approx(12.0)

    # population=22500, baseline per_capita=0.45 -> theoretical 10.125 t/day;
    # empirical is the 30-day average, 12.0 t/day.
    total_gen = data["total_generation_variance"]
    assert total_gen["theoretical"] == pytest.approx(22500 * 0.45 / 1000)
    assert total_gen["empirical"] == pytest.approx(12.0)

    # population=22500, per_capita baseline=0.45 (tests/test_simulation.py's
    # _make_ready_habitation). Empirical: 12.0 * 1000 / 22500 = 0.5333...
    per_capita = data["per_capita_variance"]
    assert per_capita["theoretical"] == pytest.approx(0.45)
    assert per_capita["empirical"] == pytest.approx(12.0 * 1000 / 22500, rel=1e-3)
    assert per_capita["variance_pct"] == pytest.approx(18.52, abs=0.5)

    # stated segregation_practice_pct=35.0; realized = (7+4)/12*100 = 91.67%
    segregation = data["segregation_variance"]
    assert segregation["theoretical"] == pytest.approx(35.0)
    assert segregation["empirical"] == pytest.approx((7.0 + 4.0) / 12.0 * 100, rel=1e-3)

    # theoretical fleet efficiency = 5.0 * 2.0 * 0.85 = 8.5 t/vehicle/day (engine defaults);
    # empirical = 12.0 / 4 = 3.0
    fleet = data["fleet_efficiency_variance"]
    assert fleet["theoretical"] == pytest.approx(8.5)
    assert fleet["empirical"] == pytest.approx(3.0)
    assert fleet["variance_pct"] < 0


async def test_recalibration_report_falls_back_gracefully_with_sparse_data(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "SparseDataVille")
    # Only 2 days logged — below MIN_DAYS_FOR_AVERAGE (5).
    await _log_day(client, planner_headers, habitation_id, _days_ago(1))
    await _log_day(client, planner_headers, habitation_id, _days_ago(2))

    resp = await client.get(f"/api/v1/habitations/{habitation_id}/recalibration-report", headers=planner_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["moving_average_90d"]["avg_total_collected_tpd"] is None
    assert data["per_capita_variance"]["empirical"] is None
    assert any("day(s) logged" in note for note in data["notes"])


async def test_recalibration_report_requires_ready_habitation(client, planner_headers):
    from tests.test_parameters import _create_habitation

    habitation_id = await _create_habitation(client, planner_headers, "NotReadyVille")
    resp = await client.get(f"/api/v1/habitations/{habitation_id}/recalibration-report", headers=planner_headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "HABITATION_NOT_READY"


async def test_hybrid_run_starts_from_empirical_per_capita(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "HybridVille")
    for day in range(1, 7):
        await _log_day(client, planner_headers, habitation_id, _days_ago(day), total_collected_tonnes=15.0)

    theoretical_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations",
        json={"run_type": "BASE", "horizon_years": 1, "engine_mode": "THEORETICAL", "label": "theoretical"},
        headers=planner_headers,
    )
    theoretical_run_id = theoretical_resp.json()["data"]["id"]
    await _run_worker(theoretical_run_id)

    hybrid_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations",
        json={"run_type": "BASE", "horizon_years": 1, "engine_mode": "DATA_DRIVEN_HYBRID", "label": "hybrid"},
        headers=planner_headers,
    )
    hybrid_run_id = hybrid_resp.json()["data"]["id"]
    assert hybrid_run_id != theoretical_run_id  # config now participates in BASE dedup
    await _run_worker(hybrid_run_id)

    theoretical_monthly = (
        await client.get(
            f"/api/v1/simulations/{theoretical_run_id}/results", params={"aggregate": "monthly"}, headers=planner_headers
        )
    ).json()["data"]["series"]
    hybrid_monthly = (
        await client.get(
            f"/api/v1/simulations/{hybrid_run_id}/results", params={"aggregate": "monthly"}, headers=planner_headers
        )
    ).json()["data"]["series"]

    theoretical_month1_per_capita = theoretical_monthly[0]["per_capita_kg_day"]
    hybrid_month1_per_capita = hybrid_monthly[0]["per_capita_kg_day"]

    assert theoretical_month1_per_capita == pytest.approx(0.45, rel=1e-2)
    # 15.0 tonnes/day * 1000 / 22500 population = 0.6667 kg/day/person
    assert hybrid_month1_per_capita == pytest.approx(15.0 * 1000 / 22500, rel=1e-2)
    assert hybrid_month1_per_capita > theoretical_month1_per_capita

    findings_resp = await client.get(f"/api/v1/simulations/{hybrid_run_id}/findings", headers=planner_headers)
    codes = {f["code"] for f in findings_resp.json()["data"]}
    assert "DATA_DRIVEN_RECALIBRATION" in codes


async def test_hybrid_run_with_no_log_history_behaves_like_theoretical(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "NoHistoryHybridVille")

    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations",
        json={"run_type": "BASE", "horizon_years": 1, "engine_mode": "DATA_DRIVEN_HYBRID"},
        headers=planner_headers,
    )
    run_id = resp.json()["data"]["id"]
    await _run_worker(run_id)

    monthly = (
        await client.get(f"/api/v1/simulations/{run_id}/results", params={"aggregate": "monthly"}, headers=planner_headers)
    ).json()["data"]["series"]
    assert monthly[0]["per_capita_kg_day"] == pytest.approx(0.45, rel=1e-2)

    findings_resp = await client.get(f"/api/v1/simulations/{run_id}/findings", headers=planner_headers)
    notes = [f["message"] for f in findings_resp.json()["data"] if f["code"] == "DATA_DRIVEN_RECALIBRATION"]
    assert any("no empirical overrides" in n for n in notes)
