
"""Authenticated, Redis-backed WebSocket chat endpoint."""

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_current_user_ws
from app.core.redis_client import (
    mark_offline,
    mark_online,
    publish_event,
    subscribe_room,
)
from app.db.database import AsyncSessionLocal
from app.db.models import Message, ReadReceipt, Room, RoomMember
from app.ws.manager import manager

router = APIRouter()
logger = logging.getLogger(__name__)


async def _room_exists(room_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        return await db.get(Room, room_id) is not None


async def _is_member(room_id: int, user_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(RoomMember).where(
                RoomMember.room_id == room_id,
                RoomMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none() is not None


async def _save_message(
    room_id: int,
    sender_id: int,
    content: str,
) -> Message:
    async with AsyncSessionLocal() as db:
        message = Message(
            room_id=room_id,
            sender_id=sender_id,
            content=content,
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        return message


async def _save_read_receipt(
    message_id: int,
    user_id: int,
) -> bool:
    async with AsyncSessionLocal() as db:
        message = await db.get(Message, message_id)

        if message is None:
            return False

        membership = await db.execute(
            select(RoomMember).where(
                RoomMember.room_id == message.room_id,
                RoomMember.user_id == user_id,
            )
        )

        if membership.scalar_one_or_none() is None:
            return False

        existing = await db.execute(
            select(ReadReceipt).where(
                ReadReceipt.message_id == message_id,
                ReadReceipt.user_id == user_id,
            )
        )

        if existing.scalar_one_or_none() is None:
            db.add(
                ReadReceipt(
                    message_id=message_id,
                    user_id=user_id,
                )
            )
            await db.commit()

        return True



        
        

async def _listen_for_room_events(room_id: int) -> None:
    """Relay room events from Redis to local WebSocket connections."""
    try:
        async for event in subscribe_room(room_id):
            await manager.broadcast_local(room_id, event)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Redis listener failed for room %s", room_id)
        raise
        


@router.websocket("/ws/rooms/{room_id}")
async def room_ws(
    websocket: WebSocket,
    room_id: int,
    token: str,
):
    # 1. Authenticate the user.
    try:
        async with AsyncSessionLocal() as db:
            user = await get_current_user_ws(token, db)

    except (SQLAlchemyError, ValueError, TypeError):
        logger.exception(
            "Authentication lookup failed for room %s",
            room_id,
        )
        await websocket.close(
            code=1011,
            reason="Authentication service error",
        )
        return

    if user is None:
        await websocket.close(
            code=4401,
            reason="Invalid or expired token",
        )
        return

    # 2. Verify room existence and membership before accepting.
    try:
        if not await _room_exists(room_id):
            await websocket.close(
                code=4404,
                reason="Room not found",
            )
            return

        if not await _is_member(room_id, user.id):
            await websocket.close(
                code=4403,
                reason="Join this room before connecting",
            )
            return

    except SQLAlchemyError:
        logger.exception(
            "Room validation failed for room %s",
            room_id,
        )
        await websocket.close(
            code=1011,
            reason="Room validation error",
        )
        return

    # 3. Accept and register the connection.
    await websocket.accept()
    manager.connect(room_id, user.id, websocket)

    listener_task = None
    presence_started = False

    try:
        await mark_online(user.id)
        presence_started = True

        await publish_event(
            room_id,
            {
                "type": "presence",
                "user_id": user.id,
                "online": True,
            },
        )

        # 4. Listen for events published through Redis.
        listener_task = asyncio.create_task(
            _listen_for_room_events(room_id)
        )

        # 5. Process incoming client events.
        while True:
            raw = await websocket.receive_text()

            try:
                data: Any = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "detail": "Invalid JSON",
                })
                continue

            if not isinstance(data, dict):
                await websocket.send_json({
                    "type": "error",
                    "detail": "Message must be a JSON object",
                })
                continue

            event_type = data.get("type")

            if event_type == "message":
                content = data.get("content")

                if not isinstance(content, str):
                    await websocket.send_json({
                        "type": "error",
                        "detail": "content must be text",
                    })
                    continue

                content = content.strip()

                if not content:
                    continue

                if len(content) > 4000:
                    await websocket.send_json({
                        "type": "error",
                        "detail": "Message exceeds 4000 characters",
                    })
                    continue

                # Save first, then publish to Redis.
                try:
                    message = await _save_message(
                        room_id,
                        user.id,
                        content,
                    )

                except SQLAlchemyError:
                    logger.exception(
                        "Failed to save message in room %s",
                        room_id,
                    )
                    await websocket.send_json({
                        "type": "error",
                        "detail": "Message could not be saved",
                    })
                    continue

                try:
                    await publish_event(
                        room_id,
                        {
                            "type": "message",
                            "id": message.id,
                            "room_id": room_id,
                            "sender_id": user.id,
                            "content": message.content,
                            "created_at": (
                                message.created_at.isoformat()
                            ),
                        },
                    )

                except Exception:
                    logger.exception(
                        "Failed to publish message in room %s",
                        room_id,
                    )
                    await websocket.send_json({
                        "type": "error",
                        "detail": "Message could not be broadcast",
                    })

            elif event_type == "typing":
                await publish_event(
                    room_id,
                    {
                        "type": "typing",
                        "user_id": user.id,
                        "is_typing": bool(
                            data.get("is_typing")
                        ),
                    },
                )

            elif event_type == "read":
                message_id = data.get("message_id")

                if (
                    isinstance(message_id, int)
                    and not isinstance(message_id, bool)
                    and message_id > 0
                ):
                    saved = await _save_read_receipt(
                        message_id,
                        user.id,
                    )

                    if saved:
                        await publish_event(
                            room_id,
                            {
                                "type": "read_receipt",
                                "message_id": message_id,
                                "user_id": user.id,
                            },
                        )

            elif event_type == "ping":
                await mark_online(user.id)
                await websocket.send_json({
                    "type": "pong",
                })

            else:
                await websocket.send_json({
                    "type": "error",
                    "detail": "Unknown event type",
                })

    except WebSocketDisconnect:
        logger.info(
            "WebSocket disconnected: user=%s room=%s",
            user.id,
            room_id,
        )

    except asyncio.CancelledError:
        raise

    except Exception:
        logger.exception(
            "Unexpected WebSocket error: user=%s room=%s",
            user.id,
            room_id,
        )

        with suppress(Exception):
            await websocket.close(
                code=1011,
                reason="Internal WebSocket error",
            )

    finally:
        # 6. Cancel and await the Redis listener safely.
        if listener_task is not None:
            listener_task.cancel()

            with suppress(asyncio.CancelledError, Exception):
                await listener_task

        # 7. Remove this socket from the local manager.
        manager.disconnect(
            room_id,
            user.id,
            websocket,
        )

        # Update presence when no local connections remain.
        if (
            presence_started
            and manager.local_user_count(room_id) == 0
        ):
            with suppress(Exception):
                await mark_offline(user.id)

                await publish_event(
                    room_id,
                    {
                        "type": "presence",
                        "user_id": user.id,
                        "online": False,
                    },
                )
