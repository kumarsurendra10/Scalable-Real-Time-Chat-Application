from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.user import UserOut


class RoomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    is_group: bool = True
    member_usernames: list[str] = []  # usernames to invite at creation time


class RoomOut(BaseModel):
    id: int
    name: str
    is_group: bool
    created_by: int
    created_at: datetime

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class MessageOut(BaseModel):
    id: int
    room_id: int
    sender_id: int
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class PresenceOut(BaseModel):
    user_id: int
    online: bool
