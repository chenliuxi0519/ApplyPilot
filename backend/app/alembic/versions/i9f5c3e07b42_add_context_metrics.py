"""记录每次模型调用实际收到多少上下文。

只存数量：送进模型的消息条数、估算 token、是否做了摘要、注入了几个档案字段。
不存档案内容、消息原文或工具输出——那些是用户敏感信息。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "i9f5c3e07b42"
down_revision: str | None = "h8e4b2d96a31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_run_event",
        sa.Column("history_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "agent_run_event",
        sa.Column("estimated_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "agent_run_event", sa.Column("summarized", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "agent_run_event", sa.Column("profile_fields", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_run_event", "profile_fields")
    op.drop_column("agent_run_event", "summarized")
    op.drop_column("agent_run_event", "estimated_tokens")
    op.drop_column("agent_run_event", "history_count")
