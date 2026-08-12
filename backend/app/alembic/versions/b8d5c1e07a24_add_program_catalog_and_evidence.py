
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8d5c1e07a24"
down_revision: str | None = "a7c4e2f91b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_CYCLE_CHECK = r"application_cycle ~ '^\d{4}/\d{2}$'"

FIELD_NAME_CHECK = (
    "field_name IN ('ielts_overall', 'ielts_min_band', 'toefl_overall', "
    "'gpa_min', 'gpa_scale', 'work_experience_years', 'application_deadline', "
    "'tuition', 'degree_background', 'prerequisite_courses')"
)

VALUE_TYPE_CHECK = (
    "value_type IN ('numeric', 'date', 'money', 'text', 'text_list')"
)

FIELD_VALUE_TYPE_CHECK = (
    "(field_name = 'ielts_overall' AND value_type = 'numeric') OR "
    "(field_name = 'ielts_min_band' AND value_type = 'numeric') OR "
    "(field_name = 'toefl_overall' AND value_type = 'numeric') OR "
    "(field_name = 'gpa_min' AND value_type = 'numeric') OR "
    "(field_name = 'gpa_scale' AND value_type = 'numeric') OR "
    "(field_name = 'work_experience_years' AND value_type = 'numeric') OR "
    "(field_name = 'application_deadline' AND value_type = 'date') OR "
    "(field_name = 'tuition' AND value_type = 'money') OR "
    "(field_name = 'degree_background' AND value_type = 'text') OR "
    "(field_name = 'prerequisite_courses' AND value_type = 'text_list')"
)

VALUE_SLOT_CHECK = (
    "(value_type = 'numeric' AND numeric_value IS NOT NULL AND "
    "date_value IS NULL AND money_amount IS NULL AND money_currency IS NULL "
    "AND text_value IS NULL AND text_list_value IS NULL) OR "
    "(value_type = 'date' AND date_value IS NOT NULL AND "
    "numeric_value IS NULL AND money_amount IS NULL AND "
    "money_currency IS NULL AND text_value IS NULL AND "
    "text_list_value IS NULL) OR "
    "(value_type = 'money' AND money_amount IS NOT NULL AND "
    "money_currency IS NOT NULL AND numeric_value IS NULL AND "
    "date_value IS NULL AND text_value IS NULL AND "
    "text_list_value IS NULL) OR "
    "(value_type = 'text' AND text_value IS NOT NULL AND "
    "numeric_value IS NULL AND date_value IS NULL AND money_amount IS NULL "
    "AND money_currency IS NULL AND text_list_value IS NULL) OR "
    "(value_type = 'text_list' AND text_list_value IS NOT NULL AND "
    "numeric_value IS NULL AND date_value IS NULL AND money_amount IS NULL "
    "AND money_currency IS NULL AND text_value IS NULL)"
)

MONEY_CURRENCY_CHECK = (
    "money_currency IS NULL OR "
    "money_currency IN ('SGD', 'HKD', 'GBP', 'CNY', 'USD', 'EUR')"
)

MONEY_NON_NEGATIVE_CHECK = "money_amount IS NULL OR money_amount >= 0"


def _value_columns() -> list[sa.Column]:
    return [
        sa.Column("numeric_value", sa.Numeric(12, 3), nullable=True),
        sa.Column("date_value", sa.Date(), nullable=True),
        sa.Column("money_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("money_currency", sa.String(3), nullable=True),
        sa.Column("text_value", sa.String(1000), nullable=True),
        sa.Column(
            "text_list_value", postgresql.ARRAY(sa.String(200)), nullable=True
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "university",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("short_name", sa.String(50), nullable=False),
        sa.Column("region", sa.String(32), nullable=False),
        sa.Column("website_url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "region IN ('singapore', 'hong_kong', 'united_kingdom')",
            name="ck_university_region",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_university_name"),
        sa.UniqueConstraint("short_name", name="uq_university_short_name"),
    )

    op.create_table(
        "program",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("university_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("degree_type", sa.String(32), nullable=False),
        sa.Column(
            "field_tags",
            postgresql.ARRAY(sa.String(50)),
            server_default=sa.text("'{}'::character varying[]"),
            nullable=False,
        ),
        sa.Column("program_url", sa.String(500), nullable=True),
        sa.Column("duration_months", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "degree_type IN ('taught_master', 'research_master', 'phd')",
            name="ck_program_degree_type",
        ),
        sa.CheckConstraint(
            "duration_months IS NULL OR duration_months > 0",
            name="ck_program_duration_positive",
        ),
        sa.ForeignKeyConstraint(
            ["university_id"], ["university.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "university_id", "name", name="uq_program_university_name"
        ),
    )
    op.create_index("ix_program_university_id", "program", ["university_id"])
    op.create_index(
        "ix_program_field_tags", "program", ["field_tags"], postgresql_using="gin"
    )

    op.create_table(
        "requirement_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column("application_cycle", sa.String(7), nullable=False),
        sa.Column("field_name", sa.String(64), nullable=False),
        sa.Column("value_type", sa.String(32), nullable=False),
        *_value_columns(),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            APPLICATION_CYCLE_CHECK,
            name="ck_requirement_evidence_application_cycle",
        ),
        sa.CheckConstraint(
            FIELD_NAME_CHECK, name="ck_requirement_evidence_field_name"
        ),
        sa.CheckConstraint(
            VALUE_TYPE_CHECK, name="ck_requirement_evidence_value_type"
        ),
        sa.CheckConstraint(
            "source_type IN ('program_page', 'admission_page', 'fees_page', "
            "'university_english_requirement', 'official_pdf', 'official_faq', "
            "'handbook')",
            name="ck_requirement_evidence_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('unverified', 'verified', 'conflicted', 'superseded', "
            "'rejected')",
            name="ck_requirement_evidence_status",
        ),
        sa.CheckConstraint(
            FIELD_VALUE_TYPE_CHECK,
            name="ck_requirement_evidence_field_value_type",
        ),
        sa.CheckConstraint(
            VALUE_SLOT_CHECK, name="ck_requirement_evidence_value_slot"
        ),
        sa.CheckConstraint(
            MONEY_CURRENCY_CHECK, name="ck_requirement_evidence_money_currency"
        ),
        sa.CheckConstraint(
            MONEY_NON_NEGATIVE_CHECK,
            name="ck_requirement_evidence_money_non_negative",
        ),
        sa.ForeignKeyConstraint(["program_id"], ["program.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_requirement_evidence_program_cycle_field_status",
        "requirement_evidence",
        ["program_id", "application_cycle", "field_name", "status"],
    )
    op.create_index(
        "ix_requirement_evidence_status", "requirement_evidence", ["status"]
    )

    op.create_table(
        "program_requirement",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column("application_cycle", sa.String(7), nullable=False),
        sa.Column("field_name", sa.String(64), nullable=False),
        sa.Column("value_type", sa.String(32), nullable=False),
        *_value_columns(),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("published_evidence_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            APPLICATION_CYCLE_CHECK,
            name="ck_program_requirement_application_cycle",
        ),
        sa.CheckConstraint(
            FIELD_NAME_CHECK, name="ck_program_requirement_field_name"
        ),
        sa.CheckConstraint(
            VALUE_TYPE_CHECK, name="ck_program_requirement_value_type"
        ),
        sa.CheckConstraint(
            "status IN ('published', 'conflict_pending')",
            name="ck_program_requirement_status",
        ),
        sa.CheckConstraint(
            FIELD_VALUE_TYPE_CHECK,
            name="ck_program_requirement_field_value_type",
        ),
        sa.CheckConstraint(
            VALUE_SLOT_CHECK, name="ck_program_requirement_value_slot"
        ),
        sa.CheckConstraint(
            MONEY_CURRENCY_CHECK, name="ck_program_requirement_money_currency"
        ),
        sa.CheckConstraint(
            MONEY_NON_NEGATIVE_CHECK,
            name="ck_program_requirement_money_non_negative",
        ),
        sa.ForeignKeyConstraint(["program_id"], ["program.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["published_evidence_id"],
            ["requirement_evidence.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "program_id",
            "application_cycle",
            "field_name",
            name="uq_program_requirement_program_cycle_field",
        ),
    )
    op.create_index(
        "ix_program_requirement_program_cycle",
        "program_requirement",
        ["program_id", "application_cycle"],
    )

    op.create_table(
        "requirement_review_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('initial_publish', 'evidence_corroborated', "
            "'conflict_recorded', 'evidence_accepted', 'evidence_rejected')",
            name="ck_requirement_review_log_decision",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["program_requirement.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"], ["requirement_evidence.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_requirement_review_log_requirement_created",
        "requirement_review_log",
        ["requirement_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_requirement_review_log_requirement_created",
        table_name="requirement_review_log",
    )
    op.drop_table("requirement_review_log")
    op.drop_index(
        "ix_program_requirement_program_cycle", table_name="program_requirement"
    )
    op.drop_table("program_requirement")
    op.drop_index(
        "ix_requirement_evidence_status", table_name="requirement_evidence"
    )
    op.drop_index(
        "ix_requirement_evidence_program_cycle_field_status",
        table_name="requirement_evidence",
    )
    op.drop_table("requirement_evidence")
    op.drop_index("ix_program_field_tags", table_name="program")
    op.drop_index("ix_program_university_id", table_name="program")
    op.drop_table("program")
    op.drop_table("university")
