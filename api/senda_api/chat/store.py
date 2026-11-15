"""Chats, their messages and files in Postgres: short transactions, one per step, so a stream that breaks leaves
what was said. Every read is of one client's chats; another client's chat is as good as absent."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update

from ..db import Database
from ..models import Chat, ChatFile, Message, utcnow


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _summary(chat: Chat) -> dict:
    return {"id": str(chat.id), "created_at": stamp(chat.created_at), "updated_at": stamp(chat.updated_at),
            "title": chat.title}


def _message(m: Message) -> dict:
    return {"seq": m.seq, "role": m.role, "text": m.text, "widgets": m.widgets, "actions": m.actions,
            "created_at": stamp(m.created_at)}


def list_chats(db: Database, client: uuid.UUID) -> list[dict]:
    with db.session() as s:
        rows = s.scalars(select(Chat).where(Chat.client_id == client).order_by(Chat.updated_at.desc()))
        return [_summary(c) for c in rows]


def get_chat(db: Database, client: uuid.UUID, chat_id: uuid.UUID) -> dict | None:
    with db.session() as s:
        chat = s.scalar(select(Chat).where(Chat.id == chat_id, Chat.client_id == client))
        if chat is None:
            return None
        rows = s.scalars(select(Message).where(Message.chat_id == chat_id).order_by(Message.seq))
        return {**_summary(chat), "messages": [_message(m) for m in rows]}


def delete_chat(db: Database, client: uuid.UUID, chat_id: uuid.UUID) -> bool:
    with db.session() as s:
        return s.execute(delete(Chat).where(Chat.id == chat_id, Chat.client_id == client)).rowcount > 0


def history(db: Database, chat_id: uuid.UUID, limit: int) -> list[dict]:
    """The last `limit` messages with text, oldest first, as plain turns."""
    with db.session() as s:
        rows = s.scalars(select(Message).where(Message.chat_id == chat_id, Message.text != "")
                         .order_by(Message.seq.desc()).limit(limit))
        return [{"role": m.role, "text": m.text} for m in reversed(list(rows))]


def shapes_drawn(db: Database, chat_id: uuid.UUID) -> int:
    """How many shapes the assistant has drawn in a chat: the next one is named after them (`A<n+1>`)."""
    with db.session() as s:
        return sum(len(a["shapes"]) for acts in s.scalars(select(Message.actions).where(Message.chat_id == chat_id))
                   for a in acts or [] if a["type"] == "draw")


def memory(db: Database, chat_id: uuid.UUID) -> dict:
    """What the earlier answers of a chat left for the next one: all their numbers, and the last plan arguments of each fire."""
    numbers: list = []
    plans: dict = {}
    with db.session() as s:
        for m in s.scalars(select(Message.memory).where(Message.chat_id == chat_id).order_by(Message.seq)):
            numbers += m.get("numbers", [])
            plans.update(m.get("plans", {}))
    return {"numbers": numbers, "plans": plans}


def begin(db: Database, client: uuid.UUID, chat_id: uuid.UUID | None, title: str, question: str,
          board: dict | None) -> tuple[uuid.UUID, int] | None:
    """Put the question and an empty answer in the chat (a new chat when `chat_id` is None). Returns the chat id and
    the sequence number of the answer, or None when the chat is not this client's."""
    now = utcnow()
    with db.session() as s:
        if chat_id is None:
            chat_id = uuid.uuid4()
            s.add(Chat(id=chat_id, client_id=client, title=title, created_at=now, updated_at=now))
            last = 0
        else:
            if s.scalar(select(Chat.id).where(Chat.id == chat_id, Chat.client_id == client)) is None:
                return None
            last = s.scalar(select(func.coalesce(func.max(Message.seq), 0)).where(Message.chat_id == chat_id)) or 0
            s.execute(update(Chat).where(Chat.id == chat_id).values(updated_at=now))
        s.flush()
        s.add_all([Message(chat_id=chat_id, seq=last + 1, role="user", text=question, board=board, created_at=now),
                   Message(chat_id=chat_id, seq=last + 2, role="assistant", created_at=now)])
        return chat_id, last + 2


def save_answer(db: Database, chat_id: uuid.UUID, seq: int, saved: dict[str, Any]) -> None:
    with db.session() as s:
        s.execute(update(Message).where(Message.chat_id == chat_id, Message.seq == seq)
                  .values(text=saved["text"], widgets=saved["widgets"], actions=saved["actions"],
                          memory=saved.get("memory", {})))
        s.execute(update(Chat).where(Chat.id == chat_id).values(updated_at=utcnow()))


def drop(db: Database, chat_id: uuid.UUID, seq: int, new: bool) -> None:
    """A failed answer is not kept, with its question and files; a chat that was made for it goes too."""
    with db.session() as s:
        if new:
            s.execute(delete(Chat).where(Chat.id == chat_id))
        else:
            s.execute(delete(Message).where(Message.chat_id == chat_id, Message.seq.in_((seq - 1, seq))))


class Files:
    """The files of a chat as the tools see them: `len()` counts them, `files[id] = {...}` stores one."""

    def __init__(self, db: Database, chat_id: uuid.UUID, seq: int) -> None:
        self.db, self.chat_id, self.seq = db, chat_id, seq

    def __len__(self) -> int:
        with self.db.session() as s:
            return s.scalar(select(func.count()).select_from(ChatFile).where(ChatFile.chat_id == self.chat_id)) or 0

    def __setitem__(self, file_id: str, file: dict) -> None:
        with self.db.session() as s:
            s.add(ChatFile(id=uuid.UUID(file_id), chat_id=self.chat_id, message_seq=self.seq, name=file["name"],
                           mime=file["mime"], size=len(file["data"]), rows=file["rows"], kind=file["kind"],
                           data=file["data"]))


def get_file(db: Database, client: uuid.UUID, chat_id: uuid.UUID, file_id: uuid.UUID) -> dict | None:
    with db.session() as s:
        found = s.execute(select(ChatFile.name, ChatFile.mime, ChatFile.data).join(Chat, Chat.id == ChatFile.chat_id)
                          .where(ChatFile.id == file_id, ChatFile.chat_id == chat_id, Chat.client_id == client)).first()
        return None if found is None else {"name": found.name, "mime": found.mime, "data": bytes(found.data)}
