
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7c4e2f91b63"
down_revision: str | None = "6f3a2b1c9d40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_profile",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("undergraduate_university", sa.String(255), nullable=True),
        sa.Column("undergraduate_major", sa.String(255), nullable=True),
        sa.Column("gpa_value", sa.Numeric(5, 2), nullable=True),
        sa.Column("gpa_scale", sa.Numeric(5, 2), nullable=True),
        sa.Column("ielts_overall", sa.Numeric(2, 1), nullable=True),
        sa.Column("budget_cny", sa.BigInteger(), nullable=True),
        sa.Column(
            "target_regions",
            postgresql.ARRAY(sa.String(100)),
            server_default=sa.text("'{}'::character varying[]"),
            nullable=False,
        ),
        sa.Column(
            "target_fields",
            postgresql.ARRAY(sa.String(100)),
            server_default=sa.text("'{}'::character varying[]"),
            nullable=False,
        ),
        sa.Column("career_goal", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(gpa_value IS NULL AND gpa_scale IS NULL) OR "
            "(gpa_value IS NOT NULL AND gpa_scale IS NOT NULL)",
            name="ck_user_profile_gpa_pair",
        ),
        sa.CheckConstraint(
            "gpa_value IS NULL OR gpa_value >= 0",
            name="ck_user_profile_gpa_non_negative",
        ),
        sa.CheckConstraint(
            "gpa_scale IS NULL OR gpa_scale > 0",
            name="ck_user_profile_gpa_scale_positive",
        ),
        sa.CheckConstraint(
            "gpa_value IS NULL OR gpa_value <= gpa_scale",
            name="ck_user_profile_gpa_within_scale",
        ),
        sa.CheckConstraint(
            "ielts_overall IS NULL OR "
            "(ielts_overall >= 0 AND ielts_overall <= 9)",
            name="ck_user_profile_ielts_range",
        ),
        sa.CheckConstraint(
            "budget_cny IS NULL OR budget_cny >= 0",
            name="ck_user_profile_budget_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_profile_user_id"),
    )
    op.create_table(
        "profile_field_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_profile_id", sa.Uuid(), nullable=False),
        sa.Column("field_name", sa.String(64), nullable=False),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("verification_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "field_name IN ('undergraduate_university', "
            "'undergraduate_major', 'gpa_value', 'gpa_scale', "
            "'ielts_overall', 'budget_cny', 'target_regions', "
            "'target_fields', 'career_goal')",
            name="ck_profile_field_history_field_name",
        ),
        sa.CheckConstraint(
            "source IN ('user_explicit', 'agent_extracted')",
            name="ck_profile_field_history_source",
        ),
        sa.CheckConstraint(
            "verification_status IN ('unverified', 'user_confirmed')",
            name="ck_profile_field_history_verification_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_profile_field_history_confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["user_profile_id"], ["user_profile.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_profile_field_history_profile_field_created",
        "profile_field_history",
        ["user_profile_id", "field_name", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_profile_field_history_profile_field_created",
        table_name="profile_field_history",
    )
    op.drop_table("profile_field_history")
    op.drop_table("user_profile")
