"""把数据库里的业务事实整理成模型能读的上下文块。

长期记忆分两半，因为它们的更新语义不一样：

* 有唯一真值、可被外部校验的**事实**（GPA、语言成绩、申请状态）直接复用
  UserProfile 和 Application，它们本来就是权威来源。事实变了叫修正，旧值
  没有保留价值。
* 没有真值、只能由用户表态的**偏好**（校园环境、学校类型）放在 UserPreference。
  偏好变了叫改主意，旧值必须留着，否则没法解释"为什么这次推荐和上次不同"。

两者都只取当前决策用得上的部分，不把整库倒给模型。会话内的短期状态由
LangGraph checkpoint 负责，不在这里。
"""

import uuid
from decimal import Decimal

from sqlmodel import Session

from app.modules import preferences as preference_service
from app.modules.applications import service as application_service
from app.modules.applications.models import Application
from app.modules.profiles import service as profile_service
from app.modules.profiles.models import UserProfile
from app.modules.programs import service as program_service

# 申请太多时只带最近要交的几个，避免上下文被清单撑爆。
MAX_APPLICATIONS = 5
# 生效偏好按槽位去重后本来就不多；这个上限只是兜底，正常不会触发。
MAX_PREFERENCES = 20
MAX_SUMMARY_CHARS = 200


def _decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _profile_lines(profile: UserProfile) -> list[str]:
    """字段全部来自 UserProfile 现有 schema，没有的就不写。"""
    gpa = None
    if profile.gpa_value is not None:
        scale = _decimal(profile.gpa_scale)
        gpa = _decimal(profile.gpa_value)
        if scale:
            gpa = f"{gpa}/{scale}"

    summary = profile.experience_summary
    if summary and len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[:MAX_SUMMARY_CHARS] + "…"

    candidates: list[tuple[str, str | None]] = [
        ("undergraduate_university", profile.undergraduate_university),
        ("undergraduate_major", profile.undergraduate_major),
        ("gpa", gpa),
        ("ielts_overall", _decimal(profile.ielts_overall)),
        ("work_experience_years", _decimal(profile.work_experience_years)),
        ("budget_cny", None if profile.budget_cny is None else str(profile.budget_cny)),
        ("target_regions", "、".join(profile.target_regions) or None),
        ("target_fields", "、".join(profile.target_fields) or None),
        ("career_goal", profile.career_goal),
        ("experience_summary", summary),
    ]
    return [f"{name}: {value}" for name, value in candidates if value]


def _application_line(session: Session, application: Application) -> str:
    label = str(application.program_id)
    try:
        program, university = program_service.get_program_with_university(
            session=session, program_id=application.program_id
        )
        label = f"{university.short_name} {program.name}"
    except LookupError:
        pass

    parts = [
        f"{label}（{application.application_cycle}）",
        f"status={application.status.value}",
        f"application_id={application.id}",
        f"version={application.version}",
    ]
    if application.target_deadline is not None:
        parts.append(f"deadline={application.target_deadline.isoformat()}")

    tasks = application_service.list_tasks(
        session=session, application_id=application.id
    )
    readiness = application_service.evaluate_readiness(tasks)
    parts.append(f"required_done={readiness.required_done}/{readiness.required_total}")
    return "- " + "，".join(parts)


def build_business_context(*, session: Session, user_id: uuid.UUID) -> tuple[str, int]:
    """返回 (上下文文本, 注入的档案字段数)。

    字段数只用于 trace 计数，不会把字段内容写进运行记录。
    """
    blocks: list[str] = []
    profile_fields = 0

    profile = profile_service.get_profile(session=session, user_id=user_id)
    lines = _profile_lines(profile) if profile is not None else []
    profile_fields = len(lines)
    body = "\n".join(lines) if lines else "（用户尚未填写个人档案）"
    blocks.append(f"[USER_PROFILE]\n{body}\n[/USER_PROFILE]")

    # 只注入 active 版本。被覆盖和被撤销的行留在库里是为了审计，不该再影响决策——
    # 把它们一起塞进上下文，模型就会看到互相打架的约束。
    preferences = preference_service.list_active_preferences(
        session=session, user_id=user_id, limit=MAX_PREFERENCES
    )
    if preferences:
        preference_rows = "\n".join(
            f"- {row.preference_key}: {row.value}" for row in preferences
        )
    else:
        preference_rows = "（用户尚未保存跨会话偏好）"
    blocks.append(
        "[PERSISTENT_USER_PREFERENCES]\n"
        f"{preference_rows}\n"
        "以上是用户明确要求长期生效的偏好，每个槽位只列当前生效的版本。"
        "与本轮对话中的临时条件冲突时，本轮条件只影响这一次回答，不改动这里。\n"
        "[/PERSISTENT_USER_PREFERENCES]"
    )

    applications, _ = application_service.list_applications(
        session=session, user_id=user_id, limit=MAX_APPLICATIONS
    )
    if applications:
        rows = "\n".join(_application_line(session, item) for item in applications)
    else:
        rows = "（还没有在跟进的申请）"
    blocks.append(
        f"[CURRENT_APPLICATION_CONTEXT]\n{rows}\n[/CURRENT_APPLICATION_CONTEXT]"
    )

    return "\n\n".join(blocks), profile_fields
