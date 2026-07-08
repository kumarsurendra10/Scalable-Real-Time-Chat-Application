import json
from datetime import datetime

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException, Query
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, decode_token
from app.database import get_db
from app.models import User, Room, Message, MessageReadReceipt, room_members
from app.schemas import RoomCreate, RoomOut, MessageOut
from app.websocket_manager import manager
from app.redis_client import get_redis

router = APIRouter(tags=["chat"])


@router.post("/rooms", response_model=RoomOut)
async def create_room(
    room_in: RoomCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    room = Room(name=room_in.name, is_group=room_in.is_group)
    room.members.append(current_user)

    if room_in.member_usernames:
        result = await db.execute(select(User).where(User.username.in_(room_in.member_usernames)))
        for member in result.scalars().all():
            if member.id != current_user.id:
                room.members.append(member)

    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room


@router.get("/rooms/{room_id}/messages", response_model=list[MessageOut])
async def get_message_history(
    room_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Message)
        .where(Message.room_id == room_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = list(result.scalars().all())
    messages.reverse()
    return messages


async def _authenticate_ws(token: str, db: AsyncSession) -> User:
    try:
        user_id = decode_token(token)
    except JWTError:
        raise WebSocketDisconnect(code=4001)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise WebSocketDisconnect(code=4001)
    return user


@router.websocket("/ws/chat/{room_id}")
async def websocket_chat(
    websocket: WebSocket,
    room_id: str,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Client connects with: ws://host/ws/chat/{room_id}?token=<JWT>

    Message types sent by client (JSON):
      {"type": "message", "content": "hello"}
      {"type": "typing"}
      {"type": "read_receipt", "message_id": "..."}
    """
    try:
        user = await _authenticate_ws(token, db)
    except WebSocketDisconnect:
        await websocket.close(code=4001)
        return

    await manager.connect(websocket, room_id, user.id)

    # Mark online + notify presence
    user.is_online = True
    await db.commit()
    await manager.publish_presence(user.id, True)
    await manager.publish(room_id, {"type": "presence", "user_id": user.id, "is_online": True})

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")

            if msg_type == "message":
                content = data.get("content", "").strip()
                if not content:
                    continue
                message = Message(room_id=room_id, sender_id=user.id, content=content)
                db.add(message)
                await db.commit()
                await db.refresh(message)

                # Cache last message in Redis for quick "recent chats" preview
                r = get_redis()
                await r.set(
                    f"room:{room_id}:last_message",
                    json.dumps({"content": content, "sender_id": user.id}),
                    ex=86400,
                )

                await manager.publish(
                    room_id,
                    {
                        "type": "message",
                        "id": message.id,
                        "room_id": room_id,
                        "sender_id": user.id,
                        "content": content,
                        "created_at": message.created_at.isoformat(),
                    },
                )

            elif msg_type == "typing":
                await manager.publish(
                    room_id, {"type": "typing", "user_id": user.id, "room_id": room_id}
                )

            elif msg_type == "read_receipt":
                message_id = data.get("message_id")
                if message_id:
                    receipt = MessageReadReceipt(message_id=message_id, user_id=user.id)
                    db.add(receipt)
                    await db.commit()
                    await manager.publish(
                        room_id,
                        {
                            "type": "read_receipt",
                            "message_id": message_id,
                            "user_id": user.id,
                        },
                    )

    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id, user.id)
        user.is_online = False
        user.last_seen = datetime.utcnow()
        await db.commit()
        await manager.publish_presence(user.id, False)
        await manager.publish(room_id, {"type": "presence", "user_id": user.id, "is_online": False})
