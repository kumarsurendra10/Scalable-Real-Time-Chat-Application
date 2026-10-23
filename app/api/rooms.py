from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.redis_client import is_online
from app.db.database import get_db
from app.db.models import Message, ReadReceipt, Room, RoomMember, RoomRole, User
from app.schemas.message import MessageOut, PresenceOut, RoomCreate, RoomOut

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.post("", response_model=RoomOut, status_code=201)
async def create_room(
    payload: RoomCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    room = Room(name=payload.name, is_group=payload.is_group, created_by=current_user.id)
    db.add(room)
    await db.flush()  # get room.id before commit

    # creator becomes owner
    db.add(RoomMember(room_id=room.id, user_id=current_user.id, role=RoomRole.OWNER))

    # invite other members by username
    if payload.member_usernames:
        result = await db.execute(select(User).where(User.username.in_(payload.member_usernames)))
        for user in result.scalars().all():
            if user.id != current_user.id:
                db.add(RoomMember(room_id=room.id, user_id=user.id, role=RoomRole.MEMBER))

    await db.commit()
    await db.refresh(room)
    return room


@router.get("", response_model=list[RoomOut])
async def list_my_rooms(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Room).join(RoomMember, Room.id == RoomMember.room_id).where(RoomMember.user_id == current_user.id)
    )
    return result.scalars().all()


@router.post("/{room_id}/join", status_code=204)
async def join_room(
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    room = await db.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    existing = await db.execute(
        select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.user_id == current_user.id)
    )
    if existing.scalar_one_or_none():
        return  # already a member, no-op
    db.add(RoomMember(room_id=room_id, user_id=current_user.id, role=RoomRole.MEMBER))
    await db.commit()


async def _assert_member(room_id: int, user_id: int, db: AsyncSession) -> None:
    result = await db.execute(
        select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.user_id == user_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this room")


@router.get("/{room_id}/messages", response_model=list[MessageOut])
async def get_message_history(
    room_id: int,
    limit: int = 50,
    before_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_member(room_id, current_user.id, db)

    query = select(Message).where(Message.room_id == room_id)
    if before_id:
        query = query.where(Message.id < before_id)
    query = query.order_by(Message.id.desc()).limit(limit)

    result = await db.execute(query)
    messages = result.scalars().all()
    return list(reversed(messages))  # chronological order


@router.get("/{room_id}/members/presence", response_model=list[PresenceOut])
async def get_room_presence(
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_member(room_id, current_user.id, db)
    result = await db.execute(select(RoomMember.user_id).where(RoomMember.room_id == room_id))
    user_ids = [row[0] for row in result.all()]
    return [PresenceOut(user_id=uid, online=await is_online(uid)) for uid in user_ids]


@router.post("/{room_id}/messages/{message_id}/read", status_code=204)
async def mark_message_read(
    room_id: int,
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_member(room_id, current_user.id, db)
    message = await db.get(Message, message_id)
    if not message or message.room_id != room_id:
        raise HTTPException(status_code=404, detail="Message not found")

    existing = await db.execute(
        select(ReadReceipt).where(ReadReceipt.message_id == message_id, ReadReceipt.user_id == current_user.id)
    )
    if not existing.scalar_one_or_none():
        db.add(ReadReceipt(message_id=message_id, user_id=current_user.id))
        await db.commit()
