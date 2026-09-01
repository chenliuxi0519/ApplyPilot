"""add tool execution idempotency records

Revision ID: k2b7e5a13d38
Revises: j1a6d4f90c21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "k2b7e5a13d38"
down_revision: str | None = "j1a6d4f90c21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_execution",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('in_progress', 'succeeded')",
            name="ck_tool_execution_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_tool_execution_key"),
    )
    op.create_index(
        "ix_tool_execution_user_created",
        "tool_execution",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tool_execution_user_created", table_name="tool_execution")
    op.drop_table("tool_execution")
