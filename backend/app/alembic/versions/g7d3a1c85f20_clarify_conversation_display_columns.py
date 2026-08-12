
from collections.abc import Sequence

from alembic import op

revision: str = "g7d3a1c85f20"
down_revision: str | None = "f4b9c2d71e83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("agent_run", "user_message", new_column_name="display_question")
    op.alter_column("agent_run", "response_payload", new_column_name="display_response")


def downgrade() -> None:
    op.alter_column("agent_run", "display_question", new_column_name="user_message")
    op.alter_column("agent_run", "display_response", new_column_name="response_payload")
