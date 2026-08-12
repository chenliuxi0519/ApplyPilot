
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2a8f3149c72"
down_revision: str | None = "d1f7b6c34a92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_run", sa.Column("conversation_id", sa.String(96), nullable=True)
    )
    op.add_column("agent_run", sa.Column("user_message", sa.Text(), nullable=True))
    op.add_column(
        "agent_run", sa.Column("response_payload", sa.JSON(), nullable=True)
    )
    op.create_index(
        "ix_agent_run_conversation_id",
        "agent_run",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_run_conversation_id", table_name="agent_run")
    op.drop_column("agent_run", "response_payload")
    op.drop_column("agent_run", "user_message")
    op.drop_column("agent_run", "conversation_id")
