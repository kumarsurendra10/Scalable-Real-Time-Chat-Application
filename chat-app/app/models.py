import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Boolean, Table, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


# Many-to-many: users <-> rooms (group chat membership)
room_members = Table(
    "room_members",
    Base.metadata,
    Column("room_id", String, ForeignKey("rooms.id"), primary_key=True),
    Column("user_id", String, ForeignKey("users.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    rooms = relationship("Room", secondary=room_members, back_populates="members")


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_group: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    members = relationship("User", secondary=room_members, back_populates="rooms")
    messages = relationship("Message", back_populates="room")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    room_id: Mapped[str] = mapped_column(String, ForeignKey("rooms.id"), index=True)
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    room = relationship("Room", back_populates="messages")
    sender = relationship("User")


class MessageReadReceipt(Base):
    __tablename__ = "message_read_receipts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    message_id: Mapped[str] = mapped_column(String, ForeignKey("messages.id"), index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    read_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
