import uuid

BOUNDARY = {
    "type": "MultiPolygon",
    "coordinates": [[[[74.79, 13.34], [74.81, 13.34], [74.81, 13.36], [74.79, 13.36], [74.79, 13.34]]]],
}

ROAD_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "LineString", "coordinates": [[74.795, 13.345], [74.805, 13.355]]},
        }
    ],
}


async def _create_draft_habitation(client, headers, name="AccessVille") -> str:
    """Created by an ADMIN (not the PLANNER under test), so the PLANNER
    fixture starts with no membership on it at all — the scenario the
    access-control rules exist for."""
    resp = await client.post(
        "/api/v1/habitations",
        headers=headers,
        json={
            "name": name,
            "habitation_type": "VILLAGE",
            "state": "Karnataka",
            "district": "Udupi",
            "boundary_geojson": BOUNDARY,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


async def _try_write(client, headers, habitation_id):
    return await client.post(
        f"/api/v1/habitations/{habitation_id}/layers",
        headers=headers,
        json={"layer_name": "Main road", "layer_type": "ROAD", "geojson": ROAD_GEOJSON},
    )


async def test_assign_grants_write_and_unassign_revokes_it(client, admin_headers, planner_headers, planner_user):
    habitation_id = await _create_draft_habitation(client, admin_headers)
    planner, _ = planner_user

    blocked = await _try_write(client, planner_headers, habitation_id)
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["error"]["code"] == "FORBIDDEN_RESOURCE"

    assign_resp = await client.post(
        "/api/v1/admin/access/assign",
        headers=admin_headers,
        json={"user_id": str(planner.id), "habitation_id": habitation_id},
    )
    assert assign_resp.status_code == 201, assign_resp.text

    allowed = await _try_write(client, planner_headers, habitation_id)
    assert allowed.status_code == 201, allowed.text

    unassign_resp = await client.request(
        "DELETE",
        "/api/v1/admin/access/unassign",
        headers=admin_headers,
        json={"user_id": str(planner.id), "habitation_id": habitation_id},
    )
    assert unassign_resp.status_code == 200, unassign_resp.text

    blocked_again = await _try_write(client, planner_headers, habitation_id)
    assert blocked_again.status_code == 403, blocked_again.text


async def test_assign_requires_admin(client, planner_headers, admin_headers, researcher_user):
    habitation_id = await _create_draft_habitation(client, admin_headers, name="RequiresAdminVille")
    researcher, _ = researcher_user
    resp = await client.post(
        "/api/v1/admin/access/assign",
        headers=planner_headers,
        json={"user_id": str(researcher.id), "habitation_id": habitation_id},
    )
    assert resp.status_code == 403, resp.text


async def test_assign_rejects_non_planner_target(client, admin_headers, researcher_user):
    habitation_id = await _create_draft_habitation(client, admin_headers, name="RejectsNonPlannerVille")
    researcher, _ = researcher_user
    resp = await client.post(
        "/api/v1/admin/access/assign",
        headers=admin_headers,
        json={"user_id": str(researcher.id), "habitation_id": habitation_id},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "USER_NOT_PLANNER"


async def test_unassign_nonexistent_assignment_404s(client, admin_headers, planner_user):
    habitation_id = await _create_draft_habitation(client, admin_headers, name="UnassignNonexistentVille")
    planner, _ = planner_user
    resp = await client.request(
        "DELETE",
        "/api/v1/admin/access/unassign",
        headers=admin_headers,
        json={"user_id": str(planner.id), "habitation_id": habitation_id},
    )
    assert resp.status_code == 404, resp.text


async def test_researcher_reads_any_habitation_planner_cannot(client, admin_headers, planner_headers, researcher_headers):
    habitation_id = await _create_draft_habitation(client, admin_headers, name="ResearcherReadVille")

    researcher_get = await client.get(f"/api/v1/habitations/{habitation_id}", headers=researcher_headers)
    assert researcher_get.status_code == 200, researcher_get.text

    researcher_list = await client.get("/api/v1/habitations", headers=researcher_headers)
    assert any(h["id"] == habitation_id for h in researcher_list.json()["data"])

    planner_get = await client.get(f"/api/v1/habitations/{habitation_id}", headers=planner_headers)
    assert planner_get.status_code == 403, planner_get.text


async def test_researcher_still_cannot_write(client, admin_headers, researcher_headers):
    habitation_id = await _create_draft_habitation(client, admin_headers, name="ResearcherNoWriteVille")
    resp = await _try_write(client, researcher_headers, habitation_id)
    assert resp.status_code == 403, resp.text


async def test_list_users_shows_role_and_assignments(client, admin_headers, planner_headers, planner_user):
    habitation_id = await _create_draft_habitation(client, admin_headers, name="ListUsersVille")
    planner, _ = planner_user
    await client.post(
        "/api/v1/admin/access/assign",
        headers=admin_headers,
        json={"user_id": str(planner.id), "habitation_id": habitation_id},
    )

    resp = await client.get("/api/v1/admin/access/users", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    rows = {row["id"]: row for row in resp.json()["data"]}
    assert str(planner.id) in rows
    assert rows[str(planner.id)]["role"] == "PLANNER"
    assert habitation_id in rows[str(planner.id)]["habitation_ids"]


async def test_list_users_requires_admin(client, planner_headers):
    resp = await client.get("/api/v1/admin/access/users", headers=planner_headers)
    assert resp.status_code == 403, resp.text


async def test_role_change_elevates_user(client, admin_headers, researcher_user):
    researcher, password = researcher_user
    resp = await client.patch(
        f"/api/v1/admin/access/users/{researcher.id}/role",
        headers=admin_headers,
        json={"role": "PLANNER"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["role"] == "PLANNER"

    login = await client.post("/api/v1/auth/login", json={"email": researcher.email, "password": password})
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    )
    assert me.json()["data"]["role"] == "PLANNER"


async def test_role_change_unknown_user_404s(client, admin_headers):
    resp = await client.patch(
        f"/api/v1/admin/access/users/{uuid.uuid4()}/role",
        headers=admin_headers,
        json={"role": "PLANNER"},
    )
    assert resp.status_code == 404, resp.text


async def test_researcher_can_clone_and_edit_own_draft(client, admin_headers, researcher_headers):
    """A RESEARCHER never gets EDITOR access to a habitation, but can still
    "clone parameter sets into private drafts" per the access-control
    invariants: start a draft (owned by them) and edit only that draft."""
    habitation_id = await _create_draft_habitation(client, admin_headers, name="ResearcherDraftVille")

    create_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/parameter-sets",
        headers=researcher_headers,
        json={},
    )
    assert create_resp.status_code == 201, create_resp.text
    psid = create_resp.json()["data"]["id"]

    edit_resp = await client.put(
        f"/api/v1/parameter-sets/{psid}/categories/demography",
        headers=researcher_headers,
        json={"population": 1200},
    )
    assert edit_resp.status_code == 200, edit_resp.text

    validate_resp = await client.post(f"/api/v1/parameter-sets/{psid}/validate", headers=researcher_headers)
    assert validate_resp.status_code == 200, validate_resp.text

    commit_resp = await client.post(f"/api/v1/parameter-sets/{psid}/commit", headers=researcher_headers)
    assert commit_resp.status_code == 403, commit_resp.text


async def test_researcher_cannot_edit_someone_elses_draft(client, admin_headers, planner_headers, researcher_headers, planner_user):
    habitation_id = await _create_draft_habitation(client, admin_headers, name="OtherPeoplesDraftsVille")
    planner, _ = planner_user
    await client.post(
        "/api/v1/admin/access/assign",
        headers=admin_headers,
        json={"user_id": str(planner.id), "habitation_id": habitation_id},
    )
    create_resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/parameter-sets", headers=planner_headers, json={}
    )
    assert create_resp.status_code == 201, create_resp.text
    psid = create_resp.json()["data"]["id"]

    edit_resp = await client.put(
        f"/api/v1/parameter-sets/{psid}/categories/demography",
        headers=researcher_headers,
        json={"population": 1200},
    )
    assert edit_resp.status_code == 403, edit_resp.text
