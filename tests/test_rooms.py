import pytest

pytestmark = pytest.mark.asyncio


async def _register(client, username):
    resp = await client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "secret123"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, resp.json()["user"]["id"]


async def test_create_room_and_list(client):
    headers, _ = await _register(client, "alice")

    resp = await client.post("/rooms", json={"name": "General", "is_group": True}, headers=headers)
    assert resp.status_code == 201
    room = resp.json()
    assert room["name"] == "General"

    resp2 = await client.get("/rooms", headers=headers)
    assert resp2.status_code == 200
    rooms = resp2.json()
    assert any(r["id"] == room["id"] for r in rooms)


async def test_group_chat_invites_members(client):
    headers_a, _ = await _register(client, "bob")
    headers_b, bob_id = await _register(client, "carol")

    resp = await client.post(
        "/rooms",
        json={"name": "Team Chat", "is_group": True, "member_usernames": ["carol"]},
        headers=headers_a,
    )
    room_id = resp.json()["id"]

    # carol should now see the room in her room list
    resp2 = await client.get("/rooms", headers=headers_b)
    room_ids = [r["id"] for r in resp2.json()]
    assert room_id in room_ids


async def test_non_member_cannot_read_messages(client):
    headers_a, _ = await _register(client, "dave")
    headers_b, _ = await _register(client, "erin")

    resp = await client.post("/rooms", json={"name": "Private", "is_group": True}, headers=headers_a)
    room_id = resp.json()["id"]

    resp2 = await client.get(f"/rooms/{room_id}/messages", headers=headers_b)
    assert resp2.status_code == 403


async def test_join_room_then_access_messages(client):
    headers_a, _ = await _register(client, "frank")
    headers_b, _ = await _register(client, "grace")

    resp = await client.post("/rooms", json={"name": "Open Room", "is_group": True}, headers=headers_a)
    room_id = resp.json()["id"]

    join_resp = await client.post(f"/rooms/{room_id}/join", headers=headers_b)
    assert join_resp.status_code == 204

    msgs_resp = await client.get(f"/rooms/{room_id}/messages", headers=headers_b)
    assert msgs_resp.status_code == 200
    assert msgs_resp.json() == []
