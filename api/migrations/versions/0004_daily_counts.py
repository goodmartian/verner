"""the kind of an event in the guard's quota (a chat question or an export), and the daily counts (Google calls, export
rows)"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_guard_questions", sa.Column("kind", sa.String(16), nullable=False, server_default="chat"))
    op.create_table(
        "daily_counts",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("value", sa.BigInteger, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("daily_counts")
    op.drop_column("chat_guard_questions", "kind")
