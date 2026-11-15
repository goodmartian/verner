"""what the assistant may rely on in later turns: the numbers its tools gave and the last plan arguments"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("memory", pg.JSONB, nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("messages", "memory")
