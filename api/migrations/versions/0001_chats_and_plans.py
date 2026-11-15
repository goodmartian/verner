"""chats, messages, chat files and saved plans"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", STAMP, nullable=False),
        sa.Column("updated_at", STAMP, nullable=False),
    )
    op.create_index("chats_client_updated", "chats", ["client_id", sa.text("updated_at DESC")])
    op.create_table(
        "messages",
        sa.Column("chat_id", pg.UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("seq", sa.Integer, primary_key=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("text", sa.Text, nullable=False, server_default=""),
        sa.Column("widgets", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("actions", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("board", pg.JSONB, nullable=True),
        sa.Column("created_at", STAMP, nullable=False),
    )
    op.create_table(
        "chat_files",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("chat_id", pg.UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_seq", sa.Integer, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("mime", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("rows", sa.Integer, nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.ForeignKeyConstraint(["chat_id", "message_seq"], ["messages.chat_id", "messages.seq"], ondelete="CASCADE"),
    )
    op.create_index("ix_chat_files_chat_id", "chat_files", ["chat_id"])
    op.create_table(
        "plans",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("fire_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("request", pg.JSONB, nullable=False),
        sa.Column("response", pg.JSONB, nullable=False),
        sa.Column("created_at", STAMP, nullable=False),
    )
    op.create_index("plans_client_created", "plans", ["client_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_table("plans")
    op.drop_table("chat_files")
    op.drop_table("messages")
    op.drop_table("chats")
