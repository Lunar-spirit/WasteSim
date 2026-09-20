"""Module M14 (reports). Real MinIO (the same throwaway bucket test_ingestion
uses), real WeasyPrint/openpyxl rendering — not mocked, so a genuinely
broken template would fail these tests."""

from tests.conftest import TestSessionLocal
from tests.test_simulation import _make_ready_habitation
from app.workers.tasks_simulate import run_simulation
from app.workers.tasks_reports import run_report_generation


async def _make_completed_run(client, headers, habitation_id, horizon_years=2):
    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations", json={"horizon_years": horizon_years}, headers=headers
    )
    run_id = resp.json()["data"]["id"]
    await run_simulation(run_id, session_factory=TestSessionLocal)
    return run_id


async def test_report_requires_exactly_one_subject(client, planner_headers):
    resp = await client.post("/api/v1/reports", json={"format": "PDF"}, headers=planner_headers)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "REPORT_SUBJECT_REQUIRED"

    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Bothville")
    run_id = await _make_completed_run(client, planner_headers, habitation_id)
    resp2 = await client.post(
        "/api/v1/reports",
        json={"run_id": run_id, "comparison_id": "00000000-0000-0000-0000-000000000000", "format": "PDF"},
        headers=planner_headers,
    )
    assert resp2.status_code == 400
    assert resp2.json()["error"]["code"] == "REPORT_SUBJECT_REQUIRED"


async def test_pdf_report_generates_and_downloads(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Reportville")
    run_id = await _make_completed_run(client, planner_headers, habitation_id)

    create_resp = await client.post(
        "/api/v1/reports", json={"run_id": run_id, "format": "PDF"}, headers=planner_headers
    )
    assert create_resp.status_code == 202, create_resp.text
    report_id = create_resp.json()["data"]["id"]

    await run_report_generation(report_id, session_factory=TestSessionLocal)

    status_resp = await client.get(f"/api/v1/reports/{report_id}", headers=planner_headers)
    data = status_resp.json()["data"]
    assert data["status"] == "READY", data

    download_resp = await client.get(f"/api/v1/reports/{report_id}/download", headers=planner_headers)
    assert download_resp.status_code == 200, download_resp.text
    url = download_resp.json()["data"]["url"]
    assert "reports/" in url

    # Fetch it for real and confirm it is an actual PDF, not an empty stub.
    import httpx

    pdf_resp = httpx.get(url)
    assert pdf_resp.status_code == 200
    assert pdf_resp.content[:4] == b"%PDF"
    assert len(pdf_resp.content) > 500


async def test_xlsx_comparison_report_generates(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "XlsxCompareville")
    run_1 = await _make_completed_run(client, planner_headers, habitation_id)
    run_2 = await _make_completed_run(client, planner_headers, habitation_id, horizon_years=3)

    comparison_resp = await client.post(
        "/api/v1/comparisons", json={"run_ids": [run_1, run_2]}, headers=planner_headers
    )
    comparison_id = comparison_resp.json()["data"]["id"]

    create_resp = await client.post(
        "/api/v1/reports", json={"comparison_id": comparison_id, "format": "XLSX"}, headers=planner_headers
    )
    report_id = create_resp.json()["data"]["id"]
    await run_report_generation(report_id, session_factory=TestSessionLocal)

    status_resp = await client.get(f"/api/v1/reports/{report_id}", headers=planner_headers)
    assert status_resp.json()["data"]["status"] == "READY"
