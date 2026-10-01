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


# --- Habitation access control (ADMIN-managed habitation_members) ----------


async def test_admin_can_grant_and_list_members(client, admin_headers, researcher_user):
    user, _password = researcher_user
    create_resp = await client.post(
        "/api/v1/habitations", json={**HABITATION_PAYLOAD, "name": "Accessgrantville"}, headers=admin_headers
    )
    habitation_id = create_resp.json()["data"]["id"]

    grant_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/members",
        json={"email": user.email, "access_level": "VIEWER"},
        headers=admin_headers,
    )
    assert grant_resp.status_code == 201, grant_resp.text
    assert grant_resp.json()["data"]["access_level"] == "VIEWER"

    list_resp = await client.get(f"/api/v1/habitations/{habitation_id}/members", headers=admin_headers)
    assert list_resp.status_code == 200
    members = list_resp.json()["data"]
    # +1: create_habitation() auto-grants the creator (this admin) OWNER.
    assert len(members) == 2
    granted = next(m for m in members if m["user_email"] == user.email)
    assert granted["access_level"] == "VIEWER"


async def test_grant_access_upserts_existing_member(client, admin_headers, researcher_user):
    user, _password = researcher_user
    create_resp = await client.post(
        "/api/v1/habitations", json={**HABITATION_PAYLOAD, "name": "Upsertville"}, headers=admin_headers
    )
    habitation_id = create_resp.json()["data"]["id"]

    await client.post(
        f"/api/v1/habitations/{habitation_id}/members",
        json={"email": user.email, "access_level": "VIEWER"},
        headers=admin_headers,
    )
    second = await client.post(
        f"/api/v1/habitations/{habitation_id}/members",
        json={"email": user.email, "access_level": "EDITOR"},
        headers=admin_headers,
    )
    assert second.status_code == 201

    list_resp = await client.get(f"/api/v1/habitations/{habitation_id}/members", headers=admin_headers)
    members = list_resp.json()["data"]
    researcher_rows = [m for m in members if m["user_email"] == user.email]
    assert len(researcher_rows) == 1  # upserted, not duplicated
    assert researcher_rows[0]["access_level"] == "EDITOR"


async def test_grant_access_unknown_email_404(client, admin_headers):
    create_resp = await client.post(
        "/api/v1/habitations", json={**HABITATION_PAYLOAD, "name": "Nosuchuserville"}, headers=admin_headers
    )
    habitation_id = create_resp.json()["data"]["id"]

    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/members",
        json={"email": "nobody@example.com", "access_level": "VIEWER"},
        headers=admin_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "USER_NOT_FOUND"


async def test_non_admin_cannot_grant_or_list_access(client, admin_headers, researcher_headers, viewer_user):
    user, _password = viewer_user
    create_resp = await client.post(
        "/api/v1/habitations", json={**HABITATION_PAYLOAD, "name": "Forbiddenaccessville"}, headers=admin_headers
    )
    habitation_id = create_resp.json()["data"]["id"]

    grant_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/members",
        json={"email": user.email, "access_level": "VIEWER"},
        headers=researcher_headers,
    )
    assert grant_resp.status_code == 403

    list_resp = await client.get(f"/api/v1/habitations/{habitation_id}/members", headers=researcher_headers)
    assert list_resp.status_code == 403


async def test_granted_access_actually_unlocks_a_draft_habitation(client, admin_headers, viewer_headers, viewer_user):
    user, _password = viewer_user
    create_resp = await client.post(
        "/api/v1/habitations", json={**HABITATION_PAYLOAD, "name": "Draftaccessville"}, headers=admin_headers
    )
    habitation_id = create_resp.json()["data"]["id"]

    # DRAFT habitation -> not readable without explicit membership, even for
    # an authenticated VIEWER (ensure_read_access's own rule).
    before = await client.get(f"/api/v1/habitations/{habitation_id}", headers=viewer_headers)
    assert before.status_code == 403

    await client.post(
        f"/api/v1/habitations/{habitation_id}/members",
        json={"email": user.email, "access_level": "VIEWER"},
        headers=admin_headers,
    )

    after = await client.get(f"/api/v1/habitations/{habitation_id}", headers=viewer_headers)
    assert after.status_code == 200


async def test_admin_can_revoke_access(client, admin_headers, viewer_headers, viewer_user):
    user, _password = viewer_user
    create_resp = await client.post(
        "/api/v1/habitations", json={**HABITATION_PAYLOAD, "name": "Revokeville"}, headers=admin_headers
    )
    habitation_id = create_resp.json()["data"]["id"]

    grant_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/members",
        json={"email": user.email, "access_level": "VIEWER"},
        headers=admin_headers,
    )
    member_id = grant_resp.json()["data"]["id"]

    assert (await client.get(f"/api/v1/habitations/{habitation_id}", headers=viewer_headers)).status_code == 200

    revoke_resp = await client.delete(
        f"/api/v1/habitations/{habitation_id}/members/{member_id}", headers=admin_headers
    )
    assert revoke_resp.status_code == 204

    assert (await client.get(f"/api/v1/habitations/{habitation_id}", headers=viewer_headers)).status_code == 403

    list_resp = await client.get(f"/api/v1/habitations/{habitation_id}/members", headers=admin_headers)
    remaining = list_resp.json()["data"]
    # Only the creator's own auto-granted OWNER row remains; the revoked
    # VIEWER grant is gone.
    assert len(remaining) == 1
    assert remaining[0]["access_level"] == "OWNER"
