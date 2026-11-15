"""the chat guard (quota, points, bans, the key of the address hash) and the daily model spend"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

STAMP = sa.DateTime(timezone=True)


def _by_address(name: str, *columns: sa.Column) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("who", sa.String(64), nullable=False),
        sa.Column("at", STAMP, nullable=False),
        *columns,
    )
    op.create_index(f"{name}_who_at", name, ["who", "at"])
    op.create_index(f"{name}_at", name, ["at"])


def upgrade() -> None:
    op.create_table(
        "chat_guard_keys",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("value", sa.LargeBinary, nullable=False),
    )
    _by_address("chat_guard_questions")
    _by_address("chat_guard_points", sa.Column("points", sa.Integer, nullable=False))
    _by_address("chat_guard_bans", sa.Column("until", STAMP, nullable=False))
    op.create_table(
        "chat_spend",
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("usd", sa.Float, nullable=False),
    )


def downgrade() -> None:
    for name in ("chat_spend", "chat_guard_bans", "chat_guard_points", "chat_guard_questions", "chat_guard_keys"):
        op.drop_table(name)
