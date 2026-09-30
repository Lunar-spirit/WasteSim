BOUNDARY = {
    "type": "MultiPolygon",
    "coordinates": [[[[74.79, 13.34], [74.81, 13.34], [74.81, 13.36], [74.79, 13.36], [74.79, 13.34]]]],
}


async def _create_habitation_with_boundary(client, headers, name="Geoville"):
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


async def test_upload_layer_inside_boundary_succeeds(client, planner_headers):
    habitation_id = await _create_habitation_with_boundary(client, planner_headers, "Geoville1")
    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/layers",
        headers=planner_headers,
        json={
            "layer_name": "Main road",
            "layer_type": "ROAD",
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "Main St"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[74.795, 13.345], [74.805, 13.355]],
                        },
                    }
                ],
            },
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["status"] == "READY"
    # Manually-drawn/pasted geometry gets its length computed the same way
    # an uploaded file or an automated fetch does (PostGIS's geography
    # cast, not a Python-side estimate) — real distance for this ~1.4km
    # diagonal, not the None it silently stayed before this was wired up.
    assert data["total_length_km"] is not None
    assert 1.3 < data["total_length_km"] < 1.6

    features_resp = await client.get(
        f"/api/v1/habitations/{habitation_id}/features", headers=planner_headers
    )
    assert len(features_resp.json()["data"]["features"]) == 1


async def test_manual_point_layer_has_no_length(client, planner_headers):
    """A point layer's "road length" is meaningless, not zero — None either
    way, but worth pinning down given total_length_km is now computed for
    every manually-created layer, not just ROAD/LineString ones."""
    habitation_id = await _create_habitation_with_boundary(client, planner_headers, "Geoville3")
    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/layers",
        headers=planner_headers,
        json={
            "layer_name": "Collection point",
            "layer_type": "COLLECTION_ZONE",
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [74.80, 13.35]}}
                ],
            },
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["total_length_km"] is None


async def test_upload_layer_outside_boundary_rejected(client, planner_headers):
    habitation_id = await _create_habitation_with_boundary(client, planner_headers, "Geoville2")
    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/layers",
        headers=planner_headers,
        json={
            "layer_name": "Far away road",
            "layer_type": "ROAD",
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "Somewhere else"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[80.0, 20.0], [80.1, 20.1]],
                        },
                    }
                ],
            },
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "LAYER_OUTSIDE_BOUNDARY"

    features_resp = await client.get(
        f"/api/v1/habitations/{habitation_id}/features", headers=planner_headers
    )
    assert len(features_resp.json()["data"]["features"]) == 0


async def test_list_layers_self_heals_stale_null_total_length_km(client, planner_headers, db_session):
    """Reproduces a real bug found live in this deployment's own data: a
    layer created before total_length_km was ever computed (or one where
    that computation silently failed some other way in the future) has a
    real LineString feature in gis_features but total_length_km left NULL
    on the gis_layers row, forever, with no backfill ever run. GET
    .../layers must not just trust that stale column — see
    app/gis/service.py's list_layers()."""
    from sqlalchemy import text

    habitation_id = await _create_habitation_with_boundary(client, planner_headers, "StaleLengthVille")
    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/layers",
        headers=planner_headers,
        json={
            "layer_name": "Main road",
            "layer_type": "ROAD",
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {"type": "LineString", "coordinates": [[74.795, 13.345], [74.805, 13.355]]},
                    }
                ],
            },
        },
    )
    assert resp.status_code == 201, resp.text
    layer_id = resp.json()["data"]["id"]
    assert resp.json()["data"]["total_length_km"] is not None  # sanity: the write-time computation itself is fine

    # Simulate the real legacy condition directly in the DB, bypassing the
    # normal write path entirely — a row whose total_length_km was never
    # computed despite having a real feature.
    await db_session.execute(
        text("UPDATE gis_layers SET total_length_km = NULL WHERE id = :id"), {"id": layer_id}
    )
    await db_session.commit()

    list_resp = await client.get(f"/api/v1/habitations/{habitation_id}/layers", headers=planner_headers)
    assert list_resp.status_code == 200, list_resp.text
    layer = next(row for row in list_resp.json()["data"] if row["id"] == layer_id)
    assert layer["total_length_km"] is not None
    assert 1.3 < layer["total_length_km"] < 1.6
