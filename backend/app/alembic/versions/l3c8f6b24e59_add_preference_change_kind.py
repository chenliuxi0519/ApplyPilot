"""record how each preference version came to be

Revision ID: l3c8f6b24e59
Revises: k2b7e5a13d38
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "l3c8f6b24e59"
down_revision: str | None = "k2b7e5a13d38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 已有的行都是在"声明"这个概念之前写的，只能按第一次记录处理；
    # 先带默认值补齐，再把默认值撤掉，避免以后写入时漏传也能悄悄通过。
    op.add_column(
        "user_preference",
        sa.Column(
            "change_kind",
            sa.String(length=16),
            nullable=False,
            server_default="new",
        ),
    )
    op.alter_column("user_preference", "change_kind", server_default=None)
    op.create_check_constraint(
        "ck_user_preference_change_kind",
        "user_preference",
        "change_kind IN ('new', 'refine', 'replace')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_user_preference_change_kind", "user_preference", type_="check"
    )
    op.drop_column("user_preference", "change_kind")
