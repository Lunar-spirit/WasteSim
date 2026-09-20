async def _create_habitation(client, headers, name="Paramville"):
    resp = await client.post(
        "/api/v1/habitations",
        json={"name": name, "habitation_type": "VILLAGE", "state": "Karnataka", "district": "Udupi"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


async def _create_parameter_set(client, headers, habitation_id):
    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/parameter-sets", json={}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


async def test_full_validation_loop_fail_then_pass_then_commit(client, planner_headers):
    habitation_id = await _create_habitation(client, planner_headers, "Shirva")
    psid = await _create_parameter_set(client, planner_headers, habitation_id)

    bad_resp = await client.put(
        f"/api/v1/parameter-sets/{psid}/categories/demography",
        json={"population": 22500, "annual_growth_rate_pct": 14},
        headers=planner_headers,
    )
    assert bad_resp.status_code == 200

    await client.put(
        f"/api/v1/parameter-sets/{psid}/waste-baseline",
        json={"per_capita_generation_kg_day": 0.45},
        headers=planner_headers,
    )

    fail_resp = await client.post(f"/api/v1/parameter-sets/{psid}/validate", headers=planner_headers)
    assert fail_resp.status_code == 200  # a failed validation is HTTP 200, not 4xx
    fail_data = fail_resp.json()["data"]
    assert fail_data["result"] == "FAIL"
    assert fail_data["error_count"] >= 1
    assert any(i["field_path"] == "demography.annual_growth_rate_pct" for i in fail_data["issues"])

    commit_should_fail = await client.post(f"/api/v1/parameter-sets/{psid}/commit", headers=planner_headers)
    assert commit_should_fail.status_code == 409
    assert commit_should_fail.json()["error"]["code"] == "PARAMETER_SET_NOT_READY"

    fix_resp = await client.put(
        f"/api/v1/parameter-sets/{psid}/categories/demography",
        json={"annual_growth_rate_pct": 1.8},
        headers=planner_headers,
    )
    assert fix_resp.status_code == 200

    pass_resp = await client.post(f"/api/v1/parameter-sets/{psid}/validate", headers=planner_headers)
    pass_data = pass_resp.json()["data"]
    assert pass_data["result"] == "PASS"
    assert pass_data["error_count"] == 0
    assert pass_data["completeness_pct"] == 100.0

    commit_resp = await client.post(f"/api/v1/parameter-sets/{psid}/commit", headers=planner_headers)
    assert commit_resp.status_code == 200
    assert commit_resp.json()["data"]["status"] == "VALIDATED"

    habitation_resp = await client.get(f"/api/v1/habitations/{habitation_id}", headers=planner_headers)
    assert habitation_resp.json()["data"]["status"] == "READY"


async def test_cannot_edit_validated_parameter_set(client, planner_headers):
    habitation_id = await _create_habitation(client, planner_headers, "Immutableville")
    psid = await _create_parameter_set(client, planner_headers, habitation_id)

    await client.put(
        f"/api/v1/parameter-sets/{psid}/categories/demography",
        json={"population": 1000, "annual_growth_rate_pct": 1},
        headers=planner_headers,
    )
    await client.put(
        f"/api/v1/parameter-sets/{psid}/waste-baseline",
        json={"per_capita_generation_kg_day": 0.4},
        headers=planner_headers,
    )
    await client.post(f"/api/v1/parameter-sets/{psid}/validate", headers=planner_headers)
    commit_resp = await client.post(f"/api/v1/parameter-sets/{psid}/commit", headers=planner_headers)
    assert commit_resp.status_code == 200

    edit_after_commit = await client.put(
        f"/api/v1/parameter-sets/{psid}/categories/demography",
        json={"population": 2000},
        headers=planner_headers,
    )
    assert edit_after_commit.status_code == 409
    assert edit_after_commit.json()["error"]["code"] == "PARAMETER_SET_IMMUTABLE"
