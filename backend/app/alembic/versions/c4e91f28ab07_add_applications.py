
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e91f28ab07"
down_revision: str | None = "b8d5c1e07a24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_CYCLE_CHECK = r"application_cycle ~ '^\d{4}/\d{2}$'"

APPLICATION_STATUS_CHECK = (
    "status IN ('shortlisted', 'preparing', 'ready_to_submit', 'submitted', "
    "'result_pending', 'offered', 'rejected', 'withdrawn')"
)

SUBMITTED_AT_CHECK = (
    "status NOT IN ('submitted', 'result_pending', 'offered', 'rejected') "
    "OR submitted_at IS NOT NULL"
)


def upgrade() -> None:
    op.create_table(
        "application",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column("application_cycle", sa.String(7), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("target_deadline", sa.Date(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            APPLICATION_CYCLE_CHECK, name="ck_application_application_cycle"
        ),
        sa.CheckConstraint(APPLICATION_STATUS_CHECK, name="ck_application_status"),
        sa.CheckConstraint(SUBMITTED_AT_CHECK, name="ck_application_submitted_at"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),

        sa.ForeignKeyConstraint(["program_id"], ["program.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "program_id",
            "application_cycle",
            name="uq_application_user_program_cycle",
        ),
    )
    op.create_index("ix_application_user_status", "application", ["user_id", "status"])
    op.create_index(
        "ix_application_user_deadline", "application", ["user_id", "target_deadline"]
    )

    op.create_table(
        "application_task",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_requirement_id", sa.Uuid(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "task_type IN ('cv', 'personal_statement', 'transcript', "
            "'language_score', 'recommendation', 'application_form', 'other')",
            name="ck_application_task_type",
        ),
        sa.CheckConstraint(
            "status IN ('todo', 'in_progress', 'blocked', 'done')",
            name="ck_application_task_status",
        ),
        sa.CheckConstraint(
            "source IN ('template', 'program_requirement', 'user')",
            name="ck_application_task_source",
        ),
        sa.CheckConstraint(
            "(status = 'done') = (completed_at IS NOT NULL)",
            name="ck_application_task_completed_at",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["application.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_requirement_id"],
            ["program_requirement.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_task_application_status",
        "application_task",
        ["application_id", "status"],
    )
    op.create_index(
        "ix_application_task_application_due",
        "application_task",
        ["application_id", "due_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_application_task_application_due", table_name="application_task"
    )
    op.drop_index(
        "ix_application_task_application_status", table_name="application_task"
    )
    op.drop_table("application_task")
    op.drop_index("ix_application_user_deadline", table_name="application")
    op.drop_index("ix_application_user_status", table_name="application")
    op.drop_table("application")
