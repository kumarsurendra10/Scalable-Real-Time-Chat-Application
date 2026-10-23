"""
Redis is used for THREE distinct jobs in this system, which is worth
calling out explicitly (interviewers like to probe this):

1. Pub/Sub message bus  -> lets N FastAPI replicas broadcast a message
   to a room even when the sending & receiving WebSocket connections
   are on different app instances (horizontal scaling).
2. Presence tracking     -> lightweight keys with TTL act as a heartbeat;
   a user is "online" as long as their key hasn't expired.
3. Read-receipt / typing fan-out -> same pub/sub channel carries typed
   event payloads (message, read_receipt, typing, presence).
"""
import json
from typing import AsyncGenerator

import redis.asyncio as redis

from app.core.config import settings

_redis_pool: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_pool


def room_channel(room_id: int) -> str:
    return f"{settings.REDIS_CHANNEL_PREFIX}{room_id}"


async def publish_event(room_id: int, event: dict) -> None:
    r = get_redis()
    await r.publish(room_channel(room_id), json.dumps(event))


async def subscribe_room(room_id: int) -> AsyncGenerator[dict, None]:
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(room_channel(room_id))
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            yield json.loads(message["data"])
    finally:
        await pubsub.unsubscribe(room_channel(room_id))
        await pubsub.aclose()


# ---------- Presence ----------

def presence_key(user_id: int) -> str:
    return f"presence:user:{user_id}"


async def mark_online(user_id: int) -> None:
    r = get_redis()
    await r.set(presence_key(user_id), "online", ex=settings.PRESENCE_TTL_SECONDS)


async def mark_offline(user_id: int) -> None:
    r = get_redis()
    await r.delete(presence_key(user_id))


async def is_online(user_id: int) -> bool:
    r = get_redis()
    return (await r.exists(presence_key(user_id))) == 1
