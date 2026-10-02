"""Empirical calibration of a BASE run from app.daily_logs field data —
app/simulation/service.py's _calibrate_from_daily_logs()."""

from tests.test_simulation import _make_ready_habitation

BASE_LOG = {
    "total_collected_tonnes": 10.0,
    "organic_tonnes": 6.0,
    "dry_recyclable_tonnes": 4.0,
    "vehicles_deployed": 3,
    "trips_completed": 6,
    "anomaly_flag": "NORMAL",
}


async def _seed_daily_logs(client, headers, habitation_id: str, count: int, start_day: int = 1) -> None:
    for i in range(count):
        day = start_day + i
        resp = await client.post(
            f"/api/v1/habitations/{habitation_id}/daily-logs",
            headers=headers,
            json={**BASE_LOG, "log_date": f"2026-01-{day:02d}" if day <= 31 else f"2026-02-{day - 31:02d}"},
        )
        assert resp.status_code == 200, resp.text


async def test_base_run_calibrates_when_enough_logs_exist(client, planner_headers):
    habitation_id, _ = await _make_ready_habitation(client, planner_headers, "CalibratedVille")
    await _seed_daily_logs(client, planner_headers, habitation_id, count=14)

    create_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations",
        json={"run_type": "BASE", "horizon_years": 1},
        headers=planner_headers,
    )
    assert create_resp.status_code == 202, create_resp.text
    data = create_resp.json()["data"]
    assert data["meta"]["calibrated_from_daily_logs"] is True
    assert data["meta"]["log_sample_count"] == 14
    # population is 22500 (_make_ready_habitation) — 10 tonnes/day = 10_000 kg/day
    assert data["meta"]["empirical_per_capita_kg"] == round(10_000 / 22500, 2)
    assert data["meta"]["empirical_organic_pct"] == 60.0
    assert data["param_overrides"]["waste_baseline.per_capita_generation_kg_day"] == round(10_000 / 22500, 4)
    composition = data["param_overrides"]["waste_baseline.composition"]
    assert composition["organic"] == 60.0
    # Non-organic baseline shares (plastic 12, paper 10, glass 3, metal 2, other 18 — sum 45)
    # rescaled to fill the remaining 40%: each scaled by 40/45.
    assert round(composition["plastic"], 4) == round(12.0 * (40 / 45), 4)


async def test_base_run_falls_back_to_parameter_set_with_too_few_logs(client, planner_headers):
    habitation_id, _ = await _make_ready_habitation(client, planner_headers, "UncalibratedVille")
    await _seed_daily_logs(client, planner_headers, habitation_id, count=5)

    create_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations",
        json={"run_type": "BASE", "horizon_years": 1},
        headers=planner_headers,
    )
    assert create_resp.status_code == 202, create_resp.text
    data = create_resp.json()["data"]
    assert data["meta"]["calibrated_from_daily_logs"] is False
    assert "waste_baseline.composition" not in data["param_overrides"]


async def test_explicit_override_wins_over_calibration_but_composition_still_applies(client, planner_headers):
    habitation_id, _ = await _make_ready_habitation(client, planner_headers, "OverrideWinsVille")
    await _seed_daily_logs(client, planner_headers, habitation_id, count=14)

    create_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations",
        json={
            "run_type": "BASE",
            "horizon_years": 1,
            "param_overrides": {"waste_baseline.per_capita_generation_kg_day": 0.6},
        },
        headers=planner_headers,
    )
    assert create_resp.status_code == 202, create_resp.text
    data = create_resp.json()["data"]
    # The explicit 0.6 survives untouched...
    assert data["param_overrides"]["waste_baseline.per_capita_generation_kg_day"] == 0.6
    # ...but composition (which the request didn't override) still got calibrated,
    # so the run is still considered calibrated overall.
    assert data["meta"]["calibrated_from_daily_logs"] is True
    assert data["param_overrides"]["waste_baseline.composition"]["organic"] == 60.0


async def test_no_daily_logs_at_all_falls_back_cleanly(client, planner_headers):
    habitation_id, _ = await _make_ready_habitation(client, planner_headers, "NoLogsVille")

    create_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations",
        json={"run_type": "BASE", "horizon_years": 1},
        headers=planner_headers,
    )
    assert create_resp.status_code == 202, create_resp.text
    data = create_resp.json()["data"]
    assert data["meta"] == {"calibrated_from_daily_logs": False}
