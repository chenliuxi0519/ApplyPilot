"""记录每次运行由哪个执行引擎创建。

双引擎并存期间，恢复必须按运行自身的引擎来路由，而不是按当前的默认配置：
已经由 graph 创建并暂停的运行，在默认引擎切回 loop 之后仍然要能恢复。

列可空：迁移之前的历史运行没有这个信息，读取时按 loop 处理。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h8e4b2d96a31"
down_revision: str | None = "g7d3a1c85f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_run",
        sa.Column("engine", sa.String(length=16), nullable=True),
    )
    op.create_check_constraint(
        "ck_agent_run_engine",
        "agent_run",
        "engine IS NULL OR engine IN ('loop', 'graph')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agent_run_engine", "agent_run", type_="check")
    op.drop_column("agent_run", "engine")
