"""add versioned user preferences

Revision ID: j1a6d4f90c21
Revises: i9f5c3e07b42
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "j1a6d4f90c21"
down_revision: str | None = "i9f5c3e07b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_preference",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("preference_key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'retracted')",
            name="ck_user_preference_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["user_preference.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_preference_user_updated",
        "user_preference",
        ["user_id", "updated_at"],
    )
    op.create_index(
        "uq_user_preference_active_key",
        "user_preference",
        ["user_id", "preference_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_user_preference_active_key", table_name="user_preference"
    )
    op.drop_index(
        "ix_user_preference_user_updated", table_name="user_preference"
    )
    op.drop_table("user_preference")
