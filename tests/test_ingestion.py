"""Module M5 — dataset upload and tabular ingestion.

Celery's `.delay()` really enqueues onto Redis (docker-compose brings up a
real broker), but no worker process runs during pytest, so nothing ever
drains that queue. Every test instead calls `run_ingest_tabular_upload`
directly with the test suite's own NullPool session maker, simulating
exactly what BG-02 does without needing a live worker — see
app/workers/tasks_ingest.py's docstring for why `session_factory` is
injectable.
"""

from tests.conftest import TestSessionLocal
from app.workers.tasks_ingest import run_ingest_tabular_upload
from tests.test_parameters import _create_habitation, _create_parameter_set

GOOD_CSV = (
    b"category,param_key,value\n"
    b"demography,population,5000\n"
    b"demography,annual_growth_rate_pct,2.5\n"
    b"waste_baseline,per_capita_generation_kg_day,0.4\n"
)

MIXED_CSV = (
    b"category,param_key,value\n"
    b"demography,population,5000\n"
    b"demography,annual_growth_rate_pct,500\n"  # out of catalogue range -> rejected
    b"waste_baseline,per_capita_generation_kg_day,0.4\n"
)

ALL_BAD_CSV = (
    b"category,param_key,value\n"
    b"demography,annual_growth_rate_pct,500\n"
    b"demography,population,-5\n"
)


async def _upload_csv(client, headers, habitation_id, psid, content: bytes, filename="params.csv"):
    return await client.post(
        f"/api/v1/habitations/{habitation_id}/uploads",
        headers=headers,
        files={"file": (filename, content, "text/csv")},
        data={"target": "PARAMETERS", "parameter_set_id": str(psid)},
    )


async def _run_worker(upload_id: str) -> None:
    await run_ingest_tabular_upload(upload_id, session_factory=TestSessionLocal)


async def test_upload_then_worker_validates_mixed_rows(client, planner_headers):
    habitation_id = await _create_habitation(client, planner_headers, "Ingestville")
    psid = await _create_parameter_set(client, planner_headers, habitation_id)

    resp = await _upload_csv(client, planner_headers, habitation_id, psid, MIXED_CSV)
    assert resp.status_code == 202, resp.text
    data = resp.json()["data"]
    assert data["status"] == "RECEIVED"
    assert data["duplicate_of"] is None
    upload_id = data["upload_id"]

    await _run_worker(upload_id)

    status_resp = await client.get(f"/api/v1/uploads/{upload_id}", headers=planner_headers)
    assert status_resp.status_code == 200
    status_data = status_resp.json()["data"]
    assert status_data["status"] == "VALIDATED"
    assert status_data["rows_total"] == 3
    assert status_data["rows_accepted"] == 2
    assert status_data["rows_rejected"] == 1

    issues_resp = await client.get(f"/api/v1/uploads/{upload_id}/issues", headers=planner_headers)
    issues = issues_resp.json()["data"]
    bad_row = next(i for i in issues if i["field_path"] == "demography.annual_growth_rate_pct")
    assert bad_row["code"] == "VALUE_OUT_OF_RANGE"
    assert bad_row["row_number"] == 2  # 1-based, second data row


async def test_ingest_writes_accepted_rows_into_the_draft_set(client, planner_headers):
    habitation_id = await _create_habitation(client, planner_headers, "Committown")
    psid = await _create_parameter_set(client, planner_headers, habitation_id)

    resp = await _upload_csv(client, planner_headers, habitation_id, psid, GOOD_CSV)
    upload_id = resp.json()["data"]["upload_id"]
    await _run_worker(upload_id)

    ingest_resp = await client.post(f"/api/v1/uploads/{upload_id}/ingest", headers=planner_headers)
    assert ingest_resp.status_code == 200, ingest_resp.text
    assert ingest_resp.json()["data"]["status"] == "INGESTED"

    ps_resp = await client.get(f"/api/v1/parameter-sets/{psid}", headers=planner_headers)
    categories = ps_resp.json()["data"]["categories"]
    assert categories["demography"]["population"] == 5000
    assert float(categories["demography"]["annual_growth_rate_pct"]) == 2.5
    waste_baseline = ps_resp.json()["data"]["waste_baseline"]
    assert float(waste_baseline["per_capita_generation_kg_day"]) == 0.4


async def test_file_with_no_accepted_rows_is_rejected_outright(client, planner_headers):
    habitation_id = await _create_habitation(client, planner_headers, "Rejectville")
    psid = await _create_parameter_set(client, planner_headers, habitation_id)

    resp = await _upload_csv(client, planner_headers, habitation_id, psid, ALL_BAD_CSV)
    upload_id = resp.json()["data"]["upload_id"]
    await _run_worker(upload_id)

    status_resp = await client.get(f"/api/v1/uploads/{upload_id}", headers=planner_headers)
    status_data = status_resp.json()["data"]
    assert status_data["status"] == "REJECTED"
    assert status_data["rows_accepted"] == 0


async def test_duplicate_upload_within_24h_is_not_reprocessed(client, planner_headers):
    habitation_id = await _create_habitation(client, planner_headers, "Dupeville")
    psid = await _create_parameter_set(client, planner_headers, habitation_id)

    first = await _upload_csv(client, planner_headers, habitation_id, psid, GOOD_CSV)
    assert first.status_code == 202
    first_id = first.json()["data"]["upload_id"]

    second = await _upload_csv(client, planner_headers, habitation_id, psid, GOOD_CSV)
    assert second.status_code == 200  # not 202 — BR-11
    second_data = second.json()["data"]
    assert second_data["duplicate_of"] == first_id
    assert second_data["upload_id"] == first_id


async def test_gis_layer_upload_without_layer_type_is_rejected(client, planner_headers):
    # target=GIS_LAYER itself is handled by app/gis — see tests/test_gis_ingestion.py
    # for the full upload-and-load flow. This just checks the field validation
    # that belongs to the generic /uploads endpoint.
    habitation_id = await _create_habitation(client, planner_headers, "Gisville")
    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/uploads",
        headers=planner_headers,
        files={"file": ("roads.geojson", b'{"type": "FeatureCollection", "features": []}', "application/json")},
        data={"target": "GIS_LAYER"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MISSING_LAYER_TYPE"


async def test_unsupported_extension_is_rejected(client, planner_headers):
    habitation_id = await _create_habitation(client, planner_headers, "Badextville")
    psid = await _create_parameter_set(client, planner_headers, habitation_id)
    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/uploads",
        headers=planner_headers,
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"target": "PARAMETERS", "parameter_set_id": str(psid)},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "FILE_TYPE_NOT_SUPPORTED"
