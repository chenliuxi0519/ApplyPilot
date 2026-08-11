
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1f7b6c34a92"
down_revision: str | None = "c4e91f28ab07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUN_STATUS_CHECK = (
    "status IN ('running', 'completed', 'waiting_confirmation', 'failed', "
    "'budget_exceeded')"
)

ERROR_CODES = (
    "'unknown_tool', 'invalid_input', 'domain_invalid', 'not_found', "
    "'conflict', 'permission_denied', 'confirmation_required', "
    "'user_rejected', 'internal'"
)

EVENT_TYPES = (
    "'model_request', 'tool_call', 'run_finished', "
    "'human_confirmation_required', 'human_approved', 'human_rejected', "
    "'run_resumed'"
)

FINAL_STATUSES = (
    "'running', 'completed', 'waiting_confirmation', 'failed', 'budget_exceeded'"
)


def upgrade() -> None:
    op.create_table(
        "agent_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("tool_call_count", sa.Integer(), nullable=False),
        sa.Column("final_answer", sa.Text(), nullable=True),
        sa.Column("last_error_code", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(RUN_STATUS_CHECK, name="ck_agent_run_status"),
        sa.CheckConstraint(
            f"last_error_code IS NULL OR last_error_code IN ({ERROR_CODES})",
            name="ck_agent_run_last_error_code",
        ),
        sa.CheckConstraint(
            "(finished_at IS NULL) = "
            "(status IN ('running', 'waiting_confirmation'))",
            name="ck_agent_run_finished_at",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_run_user_started", "agent_run", ["user_id", "started_at"]
    )

    op.create_table(
        "agent_run_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("stop_reason", sa.String(32), nullable=True),
        sa.Column("produced_tool_calls", sa.Integer(), nullable=True),
        sa.Column("tool_name", sa.String(64), nullable=True),
        sa.Column("tool_call_id", sa.String(128), nullable=True),
        sa.Column("policy_outcome", sa.String(32), nullable=True),
        sa.Column("tool_result_status", sa.String(8), nullable=True),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("final_status", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"event_type IN ({EVENT_TYPES})", name="ck_agent_run_event_type"
        ),
        sa.CheckConstraint(
            "policy_outcome IS NULL OR policy_outcome IN "
            "('allow', 'require_human_confirmation', 'deny')",
            name="ck_agent_run_event_policy_outcome",
        ),
        sa.CheckConstraint(
            f"error_code IS NULL OR error_code IN ({ERROR_CODES})",
            name="ck_agent_run_event_error_code",
        ),
        sa.CheckConstraint(
            "tool_result_status IS NULL OR tool_result_status IN ('ok', 'error')",
            name="ck_agent_run_event_result_status",
        ),
        sa.CheckConstraint(
            f"final_status IS NULL OR final_status IN ({FINAL_STATUSES})",
            name="ck_agent_run_event_final_status",
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_agent_run_event_sequence"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_run_event_sequence"),
    )
    op.create_index(
        "ix_agent_run_event_run_sequence",
        "agent_run_event",
        ["run_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_run_event_run_sequence", table_name="agent_run_event"
    )
    op.drop_table("agent_run_event")
    op.drop_index("ix_agent_run_user_started", table_name="agent_run")
    op.drop_table("agent_run")
