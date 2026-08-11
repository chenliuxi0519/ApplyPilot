
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4b9c2d71e83"
down_revision: str | None = "e2a8f3149c72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column("work_experience_years", sa.Numeric(4, 1), nullable=True),
    )
    op.add_column(
        "user_profile",
        sa.Column("experience_summary", sa.String(4000), nullable=True),
    )
    op.create_check_constraint(
        "ck_user_profile_work_experience_range",
        "user_profile",
        "work_experience_years IS NULL OR "
        "(work_experience_years >= 0 AND work_experience_years <= 60)",
    )
    op.drop_constraint(
        "ck_profile_field_history_field_name",
        "profile_field_history",
        type_="check",
    )
    op.create_check_constraint(
        "ck_profile_field_history_field_name",
        "profile_field_history",
        "field_name IN ('undergraduate_university', 'undergraduate_major', "
        "'gpa_value', 'gpa_scale', 'ielts_overall', "
        "'work_experience_years', 'experience_summary', 'budget_cny', "
        "'target_regions', 'target_fields', 'career_goal')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_profile_field_history_field_name",
        "profile_field_history",
        type_="check",
    )
    op.create_check_constraint(
        "ck_profile_field_history_field_name",
        "profile_field_history",
        "field_name IN ('undergraduate_university', 'undergraduate_major', "
        "'gpa_value', 'gpa_scale', 'ielts_overall', 'budget_cny', "
        "'target_regions', 'target_fields', 'career_goal')",
    )
    op.drop_constraint(
        "ck_user_profile_work_experience_range",
        "user_profile",
        type_="check",
    )
    op.drop_column("user_profile", "experience_summary")
    op.drop_column("user_profile", "work_experience_years")
