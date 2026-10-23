import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.asyncio


async def _register(client, username):
    resp = await client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "secret123"},
    )
    body = resp.json()
    return body["access_token"], body["user"]["id"]


async def test_websocket_message_roundtrip(client):
    """Two users in the same room; a message sent by one must be
    received by the other over the WebSocket, proving the Redis
    pub/sub fan-out path works end-to-end (using fakeredis)."""
    token_a, _ = await _register(client, "wsuser1")
    token_b, _ = await _register(client, "wsuser2")

    resp = await client.post(
        "/rooms",
        json={"name": "WS Room", "is_group": True, "member_usernames": ["wsuser2"]},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    room_id = resp.json()["id"]

    # starlette's TestClient drives the ASGI app synchronously for
    # websocket testing and shares the same app instance (and therefore
    # the same monkeypatched fake redis) as the async client fixture.
    sync_client = TestClient(app)

    with sync_client.websocket_connect(f"/ws/rooms/{room_id}?token={token_a}") as ws_a:
        with sync_client.websocket_connect(f"/ws/rooms/{room_id}?token={token_b}") as ws_b:
            ws_a.send_json({"type": "message", "content": "hello from A"})

            # ws_b may first receive its own "presence: online" broadcast
            # (it announces itself to the room on connect) before the
            # chat message arrives, so skip past any non-message events.
            received = ws_b.receive_json()
            while received["type"] != "message":
                received = ws_b.receive_json()

            assert received["content"] == "hello from A"
