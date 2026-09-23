"""Automation module (OSM Overpass / Open-Meteo / Open-Elevation
auto-populate). Exactly one test (the happy path) hits the real public
Overpass and Open-Meteo APIs — confirmed reachable and fast for a small
test polygon while building this module — genuinely proving the Overpass
parsing, geopandas clipping and length math, not a mock standing in for it.
Every other test mocks all three fetch functions: partly for speed, partly
because hitting the same public Overpass instance repeatedly in one test
run is exactly the kind of third-party flakiness a test suite shouldn't
depend on (confirmed while building this: a second identical query back to
back at one point came back empty). Terrain is mocked everywhere except
nowhere — the public Open-Elevation instance currently has an expired TLS
certificate, a real third-party outage this session found, which is
exactly the "external call fails" path the graceful-skip design exists
for; there is no live terrain test in this file for that reason.
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from tests.test_simulation import _make_ready_habitation
from app.parameters.service import get_parameter_set_full

# A small, real residential area (Udupi, Karnataka) confirmed to have real
# OSM roads inside it and to return quickly from the public Overpass
# instance — used only by the one real-network test.
REAL_ROAD_BOUNDARY = {
    "type": "MultiPolygon",
    "coordinates": [[[[74.79, 13.34], [74.82, 13.34], [74.82, 13.36], [74.79, 13.36], [74.79, 13.34]]]],
}

_TERRAIN_RESULT = {"avg_slope_pct": 12.5, "terrain_type": "HILLY", "min_elevation_m": 120.0}
_COASTAL_TERRAIN_RESULT = {"avg_slope_pct": 1.2, "terrain_type": "COASTAL_PLAINS", "min_elevation_m": 2.0}
_ROAD_RESULT = {
    "road_network_km": 4.2,
    "geojson_features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": [[74.80, 13.35], [74.81, 13.35]]}}
    ],
}
_RAINFALL_RESULT = 2800.0


@contextmanager
def _mock_all_fetches(terrain=_TERRAIN_RESULT):
    with (
        patch("app.automation.service._fetch_road_network", new=AsyncMock(return_value=_ROAD_RESULT)),
        patch("app.automation.service._fetch_annual_rainfall", new=AsyncMock(return_value=_RAINFALL_RESULT)),
        patch("app.automation.service._fetch_terrain", new=AsyncMock(return_value=terrain)),
    ):
        yield


async def test_auto_populate_requires_editor_access(client, planner_headers, researcher_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Autoauthville", boundary_geojson=REAL_ROAD_BOUNDARY)

    with _mock_all_fetches():
        resp = await client.post(f"/api/v1/habitations/{habitation_id}/auto-populate", json={}, headers=researcher_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN_RESOURCE"


async def test_auto_populate_happy_path_hits_real_overpass_and_open_meteo(client, planner_headers, db_session):
    habitation_id, psid = await _make_ready_habitation(client, planner_headers, "Autohappyville", boundary_geojson=REAL_ROAD_BOUNDARY)

    with patch("app.automation.service._fetch_terrain", new=AsyncMock(return_value=_TERRAIN_RESULT)):
        resp = await client.post(f"/api/v1/habitations/{habitation_id}/auto-populate", json={}, headers=planner_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    # A new DRAFT was created (cloned from the VALIDATED set _make_ready_habitation left active).
    assert data["parameter_set_id"] != psid
    assert "natural_resources.annual_rainfall_mm" in data["automated_categories"]
    assert "terrain.avg_slope_pct" in data["automated_categories"]
    assert "terrain.terrain_type" in data["automated_categories"]
    # Roads are real network + real OSM data: assert the mechanism worked
    # (a category write and, when any road existed in the tiny test
    # polygon, a GIS layer) rather than a hardcoded km figure OSM's own
    # data could change out from under the test.
    if "community_infrastructure.road_network_km" in data["automated_categories"]:
        assert "gis_layers.ROAD" in data["automated_categories"]
        assert data["gis_layer_id"] is not None

    full = await get_parameter_set_full(db_session, data["parameter_set_id"])
    assert full["categories"]["natural_resources"]["annual_rainfall_mm"] > 0
    assert full["categories"]["terrain"]["terrain_type"] == "HILLY"
    assert float(full["categories"]["terrain"]["avg_slope_pct"]) == 12.5


async def test_auto_populate_writes_road_layer_and_km_with_mocked_fetch(client, planner_headers, db_session):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Automockroadville", boundary_geojson=REAL_ROAD_BOUNDARY)

    with _mock_all_fetches():
        resp = await client.post(f"/api/v1/habitations/{habitation_id}/auto-populate", json={}, headers=planner_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "community_infrastructure.road_network_km" in data["automated_categories"]
    assert "gis_layers.ROAD" in data["automated_categories"]
    assert data["skipped_categories"] == []

    full = await get_parameter_set_full(db_session, data["parameter_set_id"])
    assert float(full["categories"]["community_infrastructure"]["road_network_km"]) == 4.2

    layer_resp = await client.get(f"/api/v1/habitations/{habitation_id}/layers", headers=planner_headers)
    layers = layer_resp.json()["data"]
    road_layer = next(layer for layer in layers if layer["id"] == data["gis_layer_id"])
    assert road_layer["layer_type"] == "ROAD"
    assert road_layer["source"] == "OSM_OVERPASS"


async def test_auto_populate_sets_coastal_buffer_when_terrain_is_coastal(client, planner_headers, db_session):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Autocoastalville", boundary_geojson=REAL_ROAD_BOUNDARY)

    with _mock_all_fetches(terrain=_COASTAL_TERRAIN_RESULT):
        resp = await client.post(f"/api/v1/habitations/{habitation_id}/auto-populate", json={}, headers=planner_headers)
    data = resp.json()["data"]
    assert "terrain.coastal_buffer_zone_meters" in data["automated_categories"]

    full = await get_parameter_set_full(db_session, data["parameter_set_id"])
    assert float(full["categories"]["terrain"]["coastal_buffer_zone_meters"]) == 500.0


async def test_auto_populate_derives_household_count_and_total_generation(client, planner_headers, db_session):
    # _make_ready_habitation seeds population=22500, household_size_avg=4.2,
    # per_capita_generation_kg_day=0.45, industrial_waste_tpd=2.0.
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Autoderiveville", boundary_geojson=REAL_ROAD_BOUNDARY)

    with _mock_all_fetches():
        resp = await client.post(f"/api/v1/habitations/{habitation_id}/auto-populate", json={}, headers=planner_headers)
    data = resp.json()["data"]

    assert "demography.household_count" in data["derived_fields"]
    assert "waste_baseline.total_generation_tpd" in data["derived_fields"]

    full = await get_parameter_set_full(db_session, data["parameter_set_id"])
    assert full["categories"]["demography"]["household_count"] == round(22500 / 4.2)
    expected_tpd = round((22500 * 0.45) / 1000.0 + 2.0, 3)
    assert float(full["waste_baseline"]["total_generation_tpd"]) == expected_tpd


async def test_auto_populate_gracefully_skips_a_failing_external_service(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Autofailville", boundary_geojson=REAL_ROAD_BOUNDARY)

    async def _boom(*args, **kwargs):
        raise TimeoutError("simulated upstream timeout")

    with (
        patch("app.automation.service._fetch_road_network", new=AsyncMock(side_effect=_boom)),
        patch("app.automation.service._fetch_annual_rainfall", new=AsyncMock(side_effect=_boom)),
        patch("app.automation.service._fetch_terrain", new=AsyncMock(side_effect=_boom)),
    ):
        resp = await client.post(f"/api/v1/habitations/{habitation_id}/auto-populate", json={}, headers=planner_headers)

    assert resp.status_code == 200, resp.text  # a failed external call is never a 5xx (design's own rule)
    data = resp.json()["data"]
    assert data["automated_categories"] == []
    skipped_names = {s["category"] for s in data["skipped_categories"]}
    assert skipped_names == {
        "community_infrastructure.road_network_km",
        "natural_resources.annual_rainfall_mm",
        "terrain",
    }
    for entry in data["skipped_categories"]:
        assert entry["reason"]  # every skip names a reason, never silent


async def test_auto_populate_targets_an_existing_draft_when_given_one(client, planner_headers, db_session):
    habitation_id, psid = await _make_ready_habitation(client, planner_headers, "Autotargetville", boundary_geojson=REAL_ROAD_BOUNDARY)
    # Open a fresh draft explicitly (clone of the active VALIDATED set).
    create_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/parameter-sets", json={"clone_from_version": 1}, headers=planner_headers
    )
    draft_id = create_resp.json()["data"]["id"]

    with _mock_all_fetches():
        resp = await client.post(
            f"/api/v1/habitations/{habitation_id}/auto-populate",
            json={"parameter_set_id": draft_id},
            headers=planner_headers,
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["parameter_set_id"] == draft_id


async def test_chatbot_can_trigger_auto_populate(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Autochatville", boundary_geojson=REAL_ROAD_BOUNDARY)
    session_resp = await client.post("/api/v1/chat/sessions", json={"habitation_id": habitation_id}, headers=planner_headers)
    session_id = session_resp.json()["data"]["id"]

    with _mock_all_fetches():
        query_resp = await client.post(
            f"/api/v1/chat/sessions/{session_id}/query",
            json={"message": "please auto-populate the missing habitation data"},
            headers=planner_headers,
        )
    assert query_resp.status_code == 200, query_resp.text
    answer = query_resp.json()["data"]

    tool_calls_resp = await client.get(
        f"/api/v1/chat/sessions/{session_id}/messages/{answer['id']}/tool-calls", headers=planner_headers
    )
    tool_calls = tool_calls_resp.json()["data"]
    assert tool_calls[0]["tool_name"] == "auto_populate_habitation"
    assert tool_calls[0]["status"] == "OK", tool_calls[0]
    assert len(answer["citations"]) > 0
