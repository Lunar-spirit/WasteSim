HABITATION_PAYLOAD = {
    "name": "Testville",
    "habitation_type": "VILLAGE",
    "state": "Karnataka",
    "district": "Udupi",
}


async def test_planner_can_create_habitation(client, planner_headers):
    resp = await client.post("/api/v1/habitations", json=HABITATION_PAYLOAD, headers=planner_headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["status"] == "DRAFT"


async def test_researcher_cannot_create_habitation(client, researcher_headers):
    resp = await client.post(
        "/api/v1/habitations",
        json={**HABITATION_PAYLOAD, "name": "Otherville"},
        headers=researcher_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN_ROLE"


async def test_duplicate_habitation_name_rejected(client, planner_headers):
    payload = {**HABITATION_PAYLOAD, "name": "Duplitown"}
    first = await client.post("/api/v1/habitations", json=payload, headers=planner_headers)
    assert first.status_code == 201
    second = await client.post("/api/v1/habitations", json=payload, headers=planner_headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "HABITATION_DUPLICATE"


async def test_get_habitation_by_id(client, planner_headers):
    create_resp = await client.post(
        "/api/v1/habitations", json={**HABITATION_PAYLOAD, "name": "Fetchville"}, headers=planner_headers
    )
    habitation_id = create_resp.json()["data"]["id"]
    get_resp = await client.get(f"/api/v1/habitations/{habitation_id}", headers=planner_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["name"] == "Fetchville"
