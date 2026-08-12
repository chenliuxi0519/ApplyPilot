from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Column, Enum


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


def enum_column(
    enum_type: type[StrEnum], *, length: int, nullable: bool = False
) -> Column[Any]:
    return Column(
        Enum(
            enum_type,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            validate_strings=True,
            length=length,
        ),
        nullable=nullable,
    )
