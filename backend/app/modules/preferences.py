"""跨会话长期偏好：版本化存储，覆盖必须先声明再确认。

这里存的是"约束以后每一次选校"的软要求——校园环境、学校类型这种没有唯一
真值、也没法外部校验的诉求。有唯一真值的事实（GPA、语言成绩）属于个人档案，
不进这张表：两者的更新语义不一样，事实变了叫修正，偏好变了叫改主意，后者
必须留下旧值才能解释"为什么这次推荐和上次不同"。

同一个槽位（preference_key）同时只允许一条 active 记录，靠 partial unique
index 保证。覆盖和撤销都不删行，只改状态并用 supersedes_id 串起来。

模型不能只把新值丢进来就算数，它必须同时声明这次是哪种变更（PreferenceChange）。
声明会和库里的实际存量对照，对不上直接拒绝——这样"海被撤销了"和"模型写
value 时漏了海"在记录上是两件不同的事，而不是只能靠读一段文本去猜。

推翻旧值（REPLACE）在工具层会升级成高风险操作，由人工确认流程放行；新增和
细化不打扰用户。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import CheckConstraint, Column, DateTime, Index, String, Text, text
from sqlmodel import Field, Session, SQLModel, col, select

from app.models import User
from app.modules.columns import enum_column, get_datetime_utc


class PreferenceStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class PreferenceChange(StrEnum):
    """模型对"这次是在做什么"的声明，写入前会和实际存量对照。"""

    # 这个槽位还没有生效值，第一次记。
    NEW = "new"
    # 在旧值基础上补充或收紧，不推翻它——不需要打扰用户。
    REFINE = "refine"
    # 推翻旧值。破坏性变更，要用户确认。
    REPLACE = "replace"


class UserPreference(SQLModel, table=True):
    """一条版本化的跨会话偏好。

    同一 user_id + preference_key 最多只有一条 active 记录；被覆盖和被撤销的
    行都留在表里，change_kind 记下当时那一步是哪种变更，raw_text 记下触发它的
    用户原话。两者合起来才能回答"这条约束是什么时候、因为哪句话没的"。
    """

    __tablename__ = "user_preference"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'superseded', 'retracted')",
            name="ck_user_preference_status",
        ),
        CheckConstraint(
            "change_kind IN ('new', 'refine', 'replace')",
            name="ck_user_preference_change_kind",
        ),
        Index(
            "uq_user_preference_active_key",
            "user_id",
            "preference_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_user_preference_user_updated", "user_id", "updated_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", ondelete="CASCADE", nullable=False
    )
    preference_key: str = Field(sa_column=Column(String(64), nullable=False))
    value: str = Field(sa_column=Column(Text, nullable=False))
    raw_text: str = Field(sa_column=Column(Text, nullable=False))
    change_kind: PreferenceChange = Field(
        default=PreferenceChange.NEW,
        sa_column=enum_column(PreferenceChange, length=16),
    )
    status: PreferenceStatus = Field(
        default=PreferenceStatus.ACTIVE,
        sa_column=enum_column(PreferenceStatus, length=16),
    )
    supersedes_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="user_preference.id",
        ondelete="SET NULL",
        nullable=True,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class PreferencePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    preference_key: str
    value: str
    raw_text: str
    change_kind: PreferenceChange
    updated_at: datetime


class PreferencesPublic(BaseModel):
    data: list[PreferencePublic]
    count: int


class PreferenceNotFoundError(LookupError):
    pass


class PreferenceUserNotFoundError(LookupError):
    pass


class PreferenceChangeMismatchError(ValueError):
    """声明的变更类型和库里的实际存量对不上。"""


def list_active_preferences(
    *, session: Session, user_id: uuid.UUID, limit: int = 20
) -> list[UserPreference]:
    statement = (
        select(UserPreference)
        .where(
            col(UserPreference.user_id) == user_id,
            col(UserPreference.status) == PreferenceStatus.ACTIVE,
        )
        .order_by(col(UserPreference.preference_key))
        .limit(limit)
    )
    return list(session.exec(statement).all())


def active_preference(
    *, session: Session, user_id: uuid.UUID, preference_key: str, lock: bool = False
) -> UserPreference | None:
    statement = select(UserPreference).where(
        col(UserPreference.user_id) == user_id,
        col(UserPreference.preference_key) == preference_key.strip(),
        col(UserPreference.status) == PreferenceStatus.ACTIVE,
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


def _check_declaration(
    *, change_kind: PreferenceChange, current: UserPreference | None, key: str
) -> None:
    """模型说的和库里有的必须对得上，否则这次写入不算数。

    这是整条链路里唯一能挡住"模型以为自己在新增、实际上把旧约束顶掉了"的地方：
    声明如果不被校验，它就只是一句自述，起不到审计作用。
    """
    if change_kind is PreferenceChange.NEW and current is not None:
        raise PreferenceChangeMismatchError(
            f"槽位 {key} 已经有一条生效偏好：{current.value}。"
            "要推翻它请声明 replace，只是补充请声明 refine。"
        )
    if change_kind is not PreferenceChange.NEW and current is None:
        raise PreferenceChangeMismatchError(
            f"槽位 {key} 还没有任何生效偏好，第一次记录请声明 new。"
        )


def remember_preference(
    *,
    session: Session,
    user_id: uuid.UUID,
    preference_key: str,
    value: str,
    raw_text: str,
    change_kind: PreferenceChange = PreferenceChange.NEW,
) -> UserPreference:
    """写入一条偏好，并把这次变更的类型一起记下来。

    REFINE 和 REPLACE 都会让旧行转成 superseded、新行用 supersedes_id 指回去；
    两者的区别不在于怎么落库，而在于 REPLACE 在工具层是高风险操作，必须先经过
    用户确认才会走到这里。
    """
    key = preference_key.strip()
    normalized_value = value.strip()
    normalized_raw = raw_text.strip()
    try:
        user = session.exec(
            select(User).where(col(User.id) == user_id).with_for_update()
        ).one_or_none()
        if user is None:
            raise PreferenceUserNotFoundError("用户不存在")

        current = active_preference(
            session=session, user_id=user_id, preference_key=key, lock=True
        )
        _check_declaration(change_kind=change_kind, current=current, key=key)

        if current is not None and current.value == normalized_value:
            # 值没变就不制造新版本，避免重复陈述把历史链撑成一堆同样的行。
            session.commit()
            session.refresh(current)
            return current

        now = get_datetime_utc()
        if current is not None:
            current.status = PreferenceStatus.SUPERSEDED
            current.updated_at = now
            session.add(current)
            # 先让旧行离开 active，再插新行，避免撞上 partial unique index。
            session.flush()

        preference = UserPreference(
            user_id=user_id,
            preference_key=key,
            value=normalized_value,
            raw_text=normalized_raw,
            change_kind=change_kind,
            supersedes_id=None if current is None else current.id,
            created_at=now,
            updated_at=now,
        )
        session.add(preference)
        session.commit()
        session.refresh(preference)
        return preference
    except Exception:
        session.rollback()
        raise


def forget_preference(
    *, session: Session, user_id: uuid.UUID, preference_key: str
) -> UserPreference:
    """撤销一条生效偏好。

    只改状态不删行：以后要解释"这个约束为什么不在了"，得能翻到它。
    """
    try:
        current = active_preference(
            session=session, user_id=user_id, preference_key=preference_key, lock=True
        )
        if current is None:
            raise PreferenceNotFoundError("没有找到这条长期偏好")
        current.status = PreferenceStatus.RETRACTED
        current.updated_at = get_datetime_utc()
        session.add(current)
        session.commit()
        session.refresh(current)
        return current
    except Exception:
        session.rollback()
        raise
