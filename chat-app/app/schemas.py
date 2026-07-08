from datetime import datetime
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    email: EmailStr
    is_online: bool

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RoomCreate(BaseModel):
    name: str
    is_group: bool = False
    member_usernames: list[str] = []


class RoomOut(BaseModel):
    id: str
    name: str
    is_group: bool

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: str
    room_id: str
    sender_id: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


# WebSocket message envelope (client <-> server)
class WSMessage(BaseModel):
    type: str  # "message" | "typing" | "read_receipt" | "presence"
    room_id: str | None = None
    content: str | None = None
    message_id: str | None = None
