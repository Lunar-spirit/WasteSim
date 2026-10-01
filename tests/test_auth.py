async def test_register_forces_viewer_role_and_is_active(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "newcomer@example.com",
            "password": "SecurePass123!",
            "full_name": "New Comer",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["role"] == "VIEWER"
    assert data["is_active"] is True


async def test_register_rejects_role_in_payload(client):
    # extra="forbid" on RegisterIn: a `role` key isn't silently dropped
    # (the old accept-and-ignore behavior), it's a validation error —
    # "explicitly prevent passing role", not just "ignore what was passed".
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "escalator@example.com",
            "password": "SecurePass123!",
            "full_name": "Would-be Admin",
            "role": "ADMIN",
        },
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_register_duplicate_email_fails(client):
    payload = {
        "email": "dup@example.com",
        "password": "SecurePass123!",
        "full_name": "Someone",
    }
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409
    assert second.json()["success"] is False
    assert second.json()["error"]["code"] == "EMAIL_TAKEN"


async def test_login_wrong_password_fails(client):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "loginme@example.com", "password": "SecurePass123!", "full_name": "X"},
    )
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "loginme@example.com", "password": "wrong"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_me_requires_token(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_returns_current_user(client, planner_headers):
    resp = await client.get("/api/v1/auth/me", headers=planner_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "PLANNER"


# --- Role upgrade workflow: VIEWER -> RESEARCHER ----------------------------


async def test_my_application_status_null_before_applying(client, viewer_headers):
    resp = await client.get("/api/v1/auth/my-application-status", headers=viewer_headers)
    assert resp.status_code == 200
    assert resp.json()["data"] is None


async def test_apply_researcher_success(client, viewer_headers):
    resp = await client.post(
        "/api/v1/auth/apply-researcher",
        json={
            "reason": "I study municipal waste systems at a local university.",
            "institution_or_department": "Dept. of Environmental Science",
        },
        headers=viewer_headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["status"] == "PENDING"
    assert data["target_role"] == "RESEARCHER"

    status_resp = await client.get("/api/v1/auth/my-application-status", headers=viewer_headers)
    assert status_resp.json()["data"]["status"] == "PENDING"


async def test_apply_researcher_rejects_short_reason(client, viewer_headers):
    resp = await client.post(
        "/api/v1/auth/apply-researcher",
        json={"reason": "too short"},
        headers=viewer_headers,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_apply_researcher_requires_viewer_role(client, researcher_headers):
    resp = await client.post(
        "/api/v1/auth/apply-researcher",
        json={"reason": "I already have researcher access somehow."},
        headers=researcher_headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "NOT_A_VIEWER"


async def test_apply_researcher_blocks_duplicate_pending(client, viewer_headers):
    first = await client.post(
        "/api/v1/auth/apply-researcher",
        json={"reason": "First application with a sufficiently long reason."},
        headers=viewer_headers,
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/auth/apply-researcher",
        json={"reason": "Second application, also long enough to pass."},
        headers=viewer_headers,
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "APPLICATION_ALREADY_PENDING"


async def test_non_admin_cannot_list_upgrade_requests(client, viewer_headers, researcher_headers):
    for headers in (viewer_headers, researcher_headers):
        resp = await client.get("/api/v1/admin/upgrade-requests", headers=headers)
        assert resp.status_code == 403


async def test_admin_approves_upgrade_request(client, viewer_headers, admin_headers):
    apply_resp = await client.post(
        "/api/v1/auth/apply-researcher",
        json={"reason": "Studying waste collection efficiency for my thesis.", "institution_or_department": "IIT"},
        headers=viewer_headers,
    )
    request_id = apply_resp.json()["data"]["id"]

    list_resp = await client.get(
        "/api/v1/admin/upgrade-requests", params={"status": "PENDING"}, headers=admin_headers
    )
    assert list_resp.status_code == 200, list_resp.text
    listed = list_resp.json()["data"]
    assert any(r["id"] == request_id for r in listed)
    row = next(r for r in listed if r["id"] == request_id)
    assert "applicant_email" in row and row["applicant_email"]
    assert row["institution_or_department"] == "IIT"

    review_resp = await client.post(
        f"/api/v1/admin/upgrade-requests/{request_id}/review",
        json={"action": "APPROVE", "review_notes": "Looks legitimate."},
        headers=admin_headers,
    )
    assert review_resp.status_code == 200, review_resp.text
    reviewed = review_resp.json()["data"]
    assert reviewed["status"] == "APPROVED"
    assert reviewed["reviewed_at"] is not None
    assert reviewed["reviewed_by"] is not None

    me_resp = await client.get("/api/v1/auth/me", headers=viewer_headers)
    assert me_resp.json()["data"]["role"] == "RESEARCHER"


async def test_admin_rejects_upgrade_request_leaves_role_unchanged(client, viewer_headers, admin_headers):
    apply_resp = await client.post(
        "/api/v1/auth/apply-researcher",
        json={"reason": "A reason that is long enough to pass validation."},
        headers=viewer_headers,
    )
    request_id = apply_resp.json()["data"]["id"]

    review_resp = await client.post(
        f"/api/v1/admin/upgrade-requests/{request_id}/review",
        json={"action": "REJECT", "review_notes": "Not enough detail on intended use."},
        headers=admin_headers,
    )
    assert review_resp.status_code == 200, review_resp.text
    data = review_resp.json()["data"]
    assert data["status"] == "REJECTED"
    assert data["review_notes"] == "Not enough detail on intended use."

    me_resp = await client.get("/api/v1/auth/me", headers=viewer_headers)
    assert me_resp.json()["data"]["role"] == "VIEWER"

    # Rejected, not pending -> the same user can apply again.
    reapply_resp = await client.post(
        "/api/v1/auth/apply-researcher",
        json={"reason": "A second attempt with more context included."},
        headers=viewer_headers,
    )
    assert reapply_resp.status_code == 201, reapply_resp.text


async def test_cannot_review_already_reviewed_request(client, viewer_headers, admin_headers):
    apply_resp = await client.post(
        "/api/v1/auth/apply-researcher",
        json={"reason": "A reason that is long enough to pass validation."},
        headers=viewer_headers,
    )
    request_id = apply_resp.json()["data"]["id"]

    first_review = await client.post(
        f"/api/v1/admin/upgrade-requests/{request_id}/review",
        json={"action": "APPROVE"},
        headers=admin_headers,
    )
    assert first_review.status_code == 200

    second_review = await client.post(
        f"/api/v1/admin/upgrade-requests/{request_id}/review",
        json={"action": "REJECT"},
        headers=admin_headers,
    )
    assert second_review.status_code == 409
    assert second_review.json()["error"]["code"] == "UPGRADE_REQUEST_ALREADY_REVIEWED"


# --- Direct admin role assignment (separate from the moderated workflow) ---


async def test_admin_lists_all_users(client, admin_headers, viewer_user):
    user, _password = viewer_user
    resp = await client.get("/api/v1/admin/users", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    emails = [u["email"] for u in resp.json()["data"]]
    assert user.email in emails


async def test_non_admin_cannot_list_users(client, viewer_headers, researcher_headers):
    for headers in (viewer_headers, researcher_headers):
        resp = await client.get("/api/v1/admin/users", headers=headers)
        assert resp.status_code == 403


async def test_admin_can_assign_any_role_directly(client, admin_headers, viewer_user):
    user, _password = viewer_user

    resp = await client.patch(
        f"/api/v1/admin/users/{user.id}/role", json={"role": "PLANNER"}, headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["role"] == "PLANNER"

    # No application, no approval — a straight admin override, and it can
    # move a role in any direction, not just VIEWER -> RESEARCHER.
    back_to_viewer = await client.patch(
        f"/api/v1/admin/users/{user.id}/role", json={"role": "VIEWER"}, headers=admin_headers
    )
    assert back_to_viewer.status_code == 200
    assert back_to_viewer.json()["data"]["role"] == "VIEWER"


async def test_non_admin_cannot_assign_roles(client, researcher_headers, viewer_user):
    user, _password = viewer_user
    resp = await client.patch(
        f"/api/v1/admin/users/{user.id}/role", json={"role": "ADMIN"}, headers=researcher_headers
    )
    assert resp.status_code == 403


async def test_assign_role_unknown_user_404(client, admin_headers):
    resp = await client.patch(
        "/api/v1/admin/users/00000000-0000-0000-0000-000000000000/role",
        json={"role": "PLANNER"},
        headers=admin_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "USER_NOT_FOUND"
