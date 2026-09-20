async def test_register_forces_researcher_role(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "escalator@example.com",
            "password": "SecurePass123!",
            "full_name": "Would-be Admin",
            "role": "ADMIN",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["role"] == "RESEARCHER"


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
