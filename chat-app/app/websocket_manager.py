import asyncio
import json
from collections import defaultdict

from fastapi import WebSocket

from app.redis_client import get_redis

CHANNEL_PREFIX = "room:"
PRESENCE_CHANNEL = "presence"


class ConnectionManager:
    """
    Holds LOCAL websocket connections (per server process/pod) keyed by room_id.
    Cross-instance fan-out happens via Redis Pub/Sub, so this scales horizontally
    across multiple Docker containers / replicas behind a load balancer.
    """

    def __init__(self):
        # room_id -> set of (websocket, user_id)
        self.active_connections: dict[str, set[tuple[WebSocket, str]]] = defaultdict(set)
        self._redis = get_redis()
        self._pubsub = None
        self._listener_task: asyncio.Task | None = None

    async def start_listener(self):
        """Call once at app startup - subscribes to all room channels via pattern match."""
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(f"{CHANNEL_PREFIX}*")
        self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self):
        async for message in self._pubsub.listen():
            if message["type"] != "pmessage":
                continue
            channel = message["channel"]
            room_id = channel.replace(CHANNEL_PREFIX, "")
            data = json.loads(message["data"])
            await self._broadcast_local(room_id, data)

    async def _broadcast_local(self, room_id: str, data: dict):
        dead = []
        for ws, user_id in self.active_connections.get(room_id, set()):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append((ws, user_id))
        for conn in dead:
            self.active_connections[room_id].discard(conn)

    async def connect(self, websocket: WebSocket, room_id: str, user_id: str):
        await websocket.accept()
        self.active_connections[room_id].add((websocket, user_id))

    def disconnect(self, websocket: WebSocket, room_id: str, user_id: str):
        self.active_connections[room_id].discard((websocket, user_id))

    async def publish(self, room_id: str, data: dict):
        """Publish to Redis so ALL server instances (including this one) broadcast it."""
        await self._redis.publish(f"{CHANNEL_PREFIX}{room_id}", json.dumps(data))

    async def publish_presence(self, user_id: str, is_online: bool):
        await self._redis.publish(
            PRESENCE_CHANNEL, json.dumps({"user_id": user_id, "is_online": is_online})
        )


manager = ConnectionManager()
