"""Tables of the chats and the saved plans. Fires, weather and climate stay in files."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    desc,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (Index("chats_client_updated", "client_id", desc("updated_at")),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))  # the browser: cookie `senda_client`
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    chat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text, default="")
    widgets: Mapped[list] = mapped_column(JSONB, default=list)
    actions: Mapped[list] = mapped_column(JSONB, default=list)
    board: Mapped[dict | None] = mapped_column(JSONB, default=None)  # what the person had on the screen
    # of an answer: `numbers` ([key, value] of its tool results, so a later answer may quote them) and `plans`
    # (the last make_plan arguments by fire id, so a later drawing refers to the same plan); not the results themselves
    memory: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatFile(Base):
    __tablename__ = "chat_files"
    __table_args__ = (
        ForeignKeyConstraint(["chat_id", "message_seq"], ["messages.chat_id", "messages.seq"], ondelete="CASCADE"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    chat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    message_seq: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    rows: Mapped[int | None] = mapped_column(Integer, default=None)
    kind: Mapped[str] = mapped_column(String(16))
    data: Mapped[bytes] = mapped_column(LargeBinary)


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (Index("plans_client_created", "client_id", desc("created_at")),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    fire_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    request: Mapped[dict] = mapped_column(JSONB)
    response: Mapped[dict] = mapped_column(JSONB)  # {"plan": ..., "fire": ...} as they were when it was saved
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# The chat guard (`chat.guard`) and the daily spend (`chat.spend`): kept here so a restart forgets no ban and no dollar.
# An address is never stored as it is: `who` is a keyed hash of it, with the key in `chat_guard_keys`.


class GuardKey(Base):
    __tablename__ = "chat_guard_keys"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[bytes] = mapped_column(LargeBinary)


class GuardQuestion(Base):
    """An accepted event of an address, for its quota: a question of the chat or an export; kept one day."""

    __tablename__ = "chat_guard_questions"
    __table_args__ = (Index("chat_guard_questions_who_at", "who", "at"), Index("chat_guard_questions_at", "at"))

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    who: Mapped[str] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(16), default="chat", server_default="chat")


class GuardPoint(Base):
    """Points of a verdict against an address; they count for half an hour."""

    __tablename__ = "chat_guard_points"
    __table_args__ = (Index("chat_guard_points_who_at", "who", "at"), Index("chat_guard_points_at", "at"))

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    who: Mapped[str] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    points: Mapped[int] = mapped_column(Integer)


class GuardBan(Base):
    """A ban of an address: when it began (the bans of a day climb the ladder) and when it ends."""

    __tablename__ = "chat_guard_bans"
    __table_args__ = (Index("chat_guard_bans_who_at", "who", "at"), Index("chat_guard_bans_at", "at"))

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    who: Mapped[str] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChatSpend(Base):
    """Dollars spent on the model in a UTC day."""

    __tablename__ = "chat_spend"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    usd: Mapped[float] = mapped_column(Float)


class DailyCount(Base):
    """A count of one thing in a UTC day against its cap (`limits.DailyCounter`): Google calls, export rows."""

    __tablename__ = "daily_counts"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger)
