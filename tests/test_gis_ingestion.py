"""Module M4 completion — BG-01 (the async GIS ingestion worker), the map
overlay endpoint, and vector tiles.

Same pattern as tests/test_ingestion.py: Celery's `.delay()` really enqueues
onto Redis, but no worker process runs during pytest, so every test calls
`run_ingest_gis_layer` directly with the test suite's NullPool session
maker to simulate what BG-01 does.
"""
import json
import zipfile
from io import BytesIO

from tests.conftest import TestSessionLocal
from app.workers.tasks_gis import run_ingest_gis_layer

BOUNDARY = {
    "type": "MultiPolygon",
    "coordinates": [[[[74.79, 13.34], [74.81, 13.34], [74.81, 13.36], [74.79, 13.36], [74.79, 13.34]]]],
}

ROAD_INSIDE_GEOJSON = json.dumps(
    {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Main St", "road_type": "highway"},
                "geometry": {"type": "LineString", "coordinates": [[74.795, 13.345], [74.805, 13.355]]},
            }
        ],
    }
).encode()

ROAD_MOSTLY_OUTSIDE_GEOJSON = json.dumps(
    {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Far road"},
                "geometry": {"type": "LineString", "coordinates": [[80.0, 20.0], [80.1, 20.1]]},
            }
        ],
    }
).encode()


async def _create_habitation_with_boundary(client, headers, name):
    resp = await client.post(
        "/api/v1/habitations",
        json={
            "name": name,
            "habitation_type": "VILLAGE",
            "state": "Karnataka",
            "district": "Udupi",
            "boundary_geojson": BOUNDARY,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


async def _upload_gis_file(client, headers, habitation_id, content, filename, layer_name, layer_type="ROAD"):
    return await client.post(
        f"/api/v1/habitations/{habitation_id}/uploads",
        headers=headers,
        files={"file": (filename, content, "application/octet-stream")},
        data={"target": "GIS_LAYER", "layer_name": layer_name, "layer_type": layer_type},
    )


async def _run_worker(upload_id: str) -> None:
    await run_ingest_gis_layer(upload_id, session_factory=TestSessionLocal)


async def test_upload_geojson_layer_inside_boundary_becomes_ready(client, planner_headers):
    habitation_id = await _create_habitation_with_boundary(client, planner_headers, "Roadville")
    resp = await _upload_gis_file(client, planner_headers, habitation_id, ROAD_INSIDE_GEOJSON, "roads.geojson", "Roadville roads")
    assert resp.status_code == 202, resp.text
    upload_id = resp.json()["data"]["upload_id"]

    await _run_worker(upload_id)

    upload_status = await client.get(f"/api/v1/uploads/{upload_id}", headers=planner_headers)
    assert upload_status.json()["data"]["status"] == "INGESTED"

    layers = await client.get(f"/api/v1/habitations/{habitation_id}/layers", headers=planner_headers)
    layer = layers.json()["data"][0]
    assert layer["status"] == "READY"
    assert layer["feature_count"] == 1
    assert layer["source"] == "UPLOAD"
    assert layer["geometry_type"] == "LineString"

    features = await client.get(f"/api/v1/layers/{layer['id']}/features", headers=planner_headers)
    assert len(features.json()["data"]["features"]) == 1


async def test_upload_geojson_layer_outside_boundary_is_rejected_with_no_features_kept(
    client, planner_headers
):
    habitation_id = await _create_habitation_with_boundary(client, planner_headers, "Farville")
    resp = await _upload_gis_file(
        client, planner_headers, habitation_id, ROAD_MOSTLY_OUTSIDE_GEOJSON, "far.geojson", "Far roads"
    )
    upload_id = resp.json()["data"]["upload_id"]

    await _run_worker(upload_id)

    upload_status = await client.get(f"/api/v1/uploads/{upload_id}", headers=planner_headers)
    assert upload_status.json()["data"]["status"] == "REJECTED"

    layers = await client.get(f"/api/v1/habitations/{habitation_id}/layers", headers=planner_headers)
    layer = layers.json()["data"][0]
    assert layer["status"] == "FAILED"
    assert layer["feature_count"] == 0

    issues = await client.get(f"/api/v1/uploads/{upload_id}/issues", headers=planner_headers)
    codes = [i["code"] for i in issues.json()["data"]]
    assert "LAYER_OUTSIDE_BOUNDARY" in codes

    features = await client.get(f"/api/v1/layers/{layer['id']}/features", headers=planner_headers)
    assert len(features.json()["data"]["features"]) == 0


async def test_shapefile_zip_with_no_prj_is_rejected_with_crs_undeclared(client, planner_headers):
    habitation_id = await _create_habitation_with_boundary(client, planner_headers, "Noprjville")

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # Deliberately incomplete/no .prj — content doesn't matter, the
        # worker must reject on the missing .prj before it ever tries to
        # parse geometry.
        zf.writestr("layer.shp", b"not a real shapefile")
        zf.writestr("layer.dbf", b"not a real dbf")
    buf.seek(0)

    resp = await _upload_gis_file(client, planner_headers, habitation_id, buf.read(), "roads.zip", "No CRS roads")
    upload_id = resp.json()["data"]["upload_id"]

    await _run_worker(upload_id)

    upload_status = await client.get(f"/api/v1/uploads/{upload_id}", headers=planner_headers)
    assert upload_status.json()["data"]["status"] == "REJECTED"

    issues = await client.get(f"/api/v1/uploads/{upload_id}/issues", headers=planner_headers)
    codes = [i["code"] for i in issues.json()["data"]]
    assert "CRS_UNDECLARED" in codes


async def test_zip_with_path_traversal_entry_is_rejected_before_extraction(client, planner_headers):
    habitation_id = await _create_habitation_with_boundary(client, planner_headers, "Zipbombville")

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", b"escape attempt")
    buf.seek(0)

    resp = await _upload_gis_file(client, planner_headers, habitation_id, buf.read(), "evil.zip", "Evil layer")
    upload_id = resp.json()["data"]["upload_id"]

    await _run_worker(upload_id)

    upload_status = await client.get(f"/api/v1/uploads/{upload_id}", headers=planner_headers)
    assert upload_status.json()["data"]["status"] == "REJECTED"


async def test_map_overlay_returns_boundary_and_ready_layers_only(client, planner_headers):
    habitation_id = await _create_habitation_with_boundary(client, planner_headers, "Mapville")
    resp = await _upload_gis_file(client, planner_headers, habitation_id, ROAD_INSIDE_GEOJSON, "roads.geojson", "Mapville roads")
    upload_id = resp.json()["data"]["upload_id"]
    await _run_worker(upload_id)

    map_resp = await client.get(f"/api/v1/habitations/{habitation_id}/map?layers=ROAD", headers=planner_headers)
    assert map_resp.status_code == 200, map_resp.text
    data = map_resp.json()["data"]
    assert data["boundary"] is not None
    assert len(data["layers"]) == 1
    assert data["layers"][0]["layer_type"] == "ROAD"
    assert data["layers"][0]["mode"] == "geojson"
    assert data["layers"][0]["feature_count"] == 1


async def test_map_overlay_never_returns_another_habitations_layer(client, planner_headers):
    habitation_a = await _create_habitation_with_boundary(client, planner_headers, "HabA")
    habitation_b = await _create_habitation_with_boundary(client, planner_headers, "HabB")

    resp = await _upload_gis_file(client, planner_headers, habitation_a, ROAD_INSIDE_GEOJSON, "roads.geojson", "A roads")
    await _run_worker(resp.json()["data"]["upload_id"])

    map_resp = await client.get(f"/api/v1/habitations/{habitation_b}/map", headers=planner_headers)
    assert map_resp.json()["data"]["layers"] == []


async def test_patch_layer_renames_and_restyles(client, planner_headers):
    habitation_id = await _create_habitation_with_boundary(client, planner_headers, "Patchville")
    resp = await _upload_gis_file(client, planner_headers, habitation_id, ROAD_INSIDE_GEOJSON, "roads.geojson", "Old name")
    await _run_worker(resp.json()["data"]["upload_id"])
    layer_id = (await client.get(f"/api/v1/habitations/{habitation_id}/layers", headers=planner_headers)).json()["data"][0]["id"]

    patch_resp = await client.patch(
        f"/api/v1/layers/{layer_id}",
        json={"layer_name": "New name", "style": {"color": "#f00"}, "z_index": 5},
        headers=planner_headers,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    data = patch_resp.json()["data"]
    assert data["layer_name"] == "New name"
    assert data["style"] == {"color": "#f00"}
    assert data["z_index"] == 5


async def test_delete_layer_cascades_features(client, planner_headers):
    habitation_id = await _create_habitation_with_boundary(client, planner_headers, "Deleteville")
    resp = await _upload_gis_file(client, planner_headers, habitation_id, ROAD_INSIDE_GEOJSON, "roads.geojson", "To delete")
    await _run_worker(resp.json()["data"]["upload_id"])
    layer_id = (await client.get(f"/api/v1/habitations/{habitation_id}/layers", headers=planner_headers)).json()["data"][0]["id"]

    delete_resp = await client.delete(f"/api/v1/layers/{layer_id}", headers=planner_headers)
    assert delete_resp.status_code == 204

    layers = await client.get(f"/api/v1/habitations/{habitation_id}/layers", headers=planner_headers)
    assert layers.json()["data"] == []

    get_resp = await client.get(f"/api/v1/layers/{layer_id}", headers=planner_headers)
    assert get_resp.status_code == 404


async def test_tile_endpoint_returns_mvt_bytes_for_a_covering_tile(client, planner_headers):
    habitation_id = await _create_habitation_with_boundary(client, planner_headers, "Tileville")
    resp = await _upload_gis_file(client, planner_headers, habitation_id, ROAD_INSIDE_GEOJSON, "roads.geojson", "Tile roads")
    await _run_worker(resp.json()["data"]["upload_id"])
    layer_id = (await client.get(f"/api/v1/habitations/{habitation_id}/layers", headers=planner_headers)).json()["data"][0]["id"]

    # z=0 (the whole world in one tile) technically "contains" the line, but
    # ST_AsMVTGeom legitimately returns NULL for it there: a ~1.2km line
    # rendered into a world-sized tile is sub-pixel and simplifies away to
    # nothing — that's correct MVT behaviour, not a bug. z/x/y below is the
    # actual covering tile at a zoom where the line is a meaningful size.
    tile_resp = await client.get(f"/api/v1/layers/{layer_id}/tiles/14/11596/7578.mvt", headers=planner_headers)
    assert tile_resp.status_code == 200
    assert tile_resp.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert len(tile_resp.content) > 0


async def test_duplicate_layer_name_is_rejected(client, planner_headers):
    habitation_id = await _create_habitation_with_boundary(client, planner_headers, "Duplayerville")
    first = await _upload_gis_file(client, planner_headers, habitation_id, ROAD_INSIDE_GEOJSON, "roads.geojson", "Same name")
    assert first.status_code == 202

    # Different bytes from ROAD_INSIDE_GEOJSON so BR-11's checksum dedup
    # doesn't short-circuit before the layer_name uniqueness check ever runs.
    second_content = ROAD_INSIDE_GEOJSON.replace(b"Main St", b"Second St")
    second = await _upload_gis_file(client, planner_headers, habitation_id, second_content, "roads2.geojson", "Same name")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "LAYER_NAME_DUPLICATE"


async def test_gis_upload_without_boundary_is_refused(client, planner_headers):
    resp = await client.post(
        "/api/v1/habitations",
        json={"name": "Noboundaryville", "habitation_type": "VILLAGE", "state": "Karnataka", "district": "Udupi"},
        headers=planner_headers,
    )
    habitation_id = resp.json()["data"]["id"]

    upload_resp = await _upload_gis_file(
        client, planner_headers, habitation_id, ROAD_INSIDE_GEOJSON, "roads.geojson", "No boundary roads"
    )
    assert upload_resp.status_code == 409
    assert upload_resp.json()["error"]["code"] == "HABITATION_BOUNDARY_REQUIRED"
