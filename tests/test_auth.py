import pytest

pytestmark = pytest.mark.asyncio


async def test_register_new_user(client):
    resp = await client.post(
        "/auth/register",
        json={"username": "surendra", "email": "surendra@example.com", "password": "secret123"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["user"]["username"] == "surendra"
    assert "access_token" in data


async def test_register_duplicate_username_fails(client):
    payload = {"username": "dup", "email": "dup1@example.com", "password": "secret123"}
    await client.post("/auth/register", json=payload)

    payload2 = {"username": "dup", "email": "dup2@example.com", "password": "secret123"}
    resp = await client.post("/auth/register", json=payload2)
    assert resp.status_code == 400


async def test_login_success(client):
    await client.post(
        "/auth/register",
        json={"username": "loginuser", "email": "login@example.com", "password": "mypassword"},
    )
    resp = await client.post("/auth/login", json={"username": "loginuser", "password": "mypassword"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_password_fails(client):
    await client.post(
        "/auth/register",
        json={"username": "wronguser", "email": "wrong@example.com", "password": "correctpass"},
    )
    resp = await client.post("/auth/login", json={"username": "wronguser", "password": "badpass"})
    assert resp.status_code == 401


async def test_protected_route_requires_token(client):
    resp = await client.get("/users/me")
    assert resp.status_code == 401
