import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.agent.state import AgentState, AgentStatus

DEFAULT_TTL = timedelta(minutes=30)
DEFAULT_CAPACITY = 200


class PendingRunNotFoundError(LookupError):
    pass


class NotPausedError(ValueError):
    pass


@dataclass
class _Entry:
    user_id: uuid.UUID
    created_at: datetime
    state: AgentState | None = None
    conversation_id: str = ""
    messages: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class PendingRun:
    state: AgentState
    conversation_id: str


def _now() -> datetime:
    return datetime.now(UTC)


def _drop_expired(store: dict[Any, _Entry], cutoff: datetime) -> None:
    for key in [key for key, entry in store.items() if entry.created_at < cutoff]:
        del store[key]


class AgentSessionStore:
    def __init__(
        self,
        *,
        ttl: timedelta = DEFAULT_TTL,
        capacity: int = DEFAULT_CAPACITY,
    ) -> None:
        self._ttl = ttl
        self._capacity = capacity
        self._pending: dict[uuid.UUID, _Entry] = {}
        self._conversations: dict[str, _Entry] = {}

    def remember_pending(self, state: AgentState, *, conversation_id: str) -> None:
        if state.status is not AgentStatus.WAITING_CONFIRMATION:
            raise NotPausedError(
                f"只能保存等待确认的运行，当前状态为 {state.status.value}"
            )
        self._expire()
        self._pending[state.run_id] = _Entry(
            user_id=state.user_id,
            created_at=_now(),
            state=state,
            conversation_id=conversation_id,
        )
        self._trim(self._pending)

    def take_pending(self, run_id: uuid.UUID, *, user_id: uuid.UUID) -> PendingRun:
        self._expire()
        entry = self._pending.get(run_id)
        if entry is None or entry.user_id != user_id or entry.state is None:
            raise PendingRunNotFoundError("没有找到该运行的待确认操作")
        del self._pending[run_id]
        return PendingRun(state=entry.state, conversation_id=entry.conversation_id)

    def has_pending(self, run_id: uuid.UUID, *, user_id: uuid.UUID) -> bool:
        self._expire()
        entry = self._pending.get(run_id)
        return entry is not None and entry.user_id == user_id

    def remember_conversation(
        self, conversation_id: str, *, messages: list[Any], user_id: uuid.UUID
    ) -> None:
        self._expire()
        self._conversations[conversation_id] = _Entry(
            user_id=user_id, created_at=_now(), messages=list(messages)
        )
        self._trim(self._conversations)

    def conversation(
        self, conversation_id: str | None, *, user_id: uuid.UUID
    ) -> list[Any]:
        if conversation_id is None:
            return []
        self._expire()
        entry = self._conversations.get(conversation_id)
        if entry is None or entry.user_id != user_id:
            return []
        return list(entry.messages)

    def forget_conversation(self, conversation_id: str) -> None:
        self._conversations.pop(conversation_id, None)

    def _expire(self) -> None:
        cutoff = _now() - self._ttl
        _drop_expired(self._pending, cutoff)
        _drop_expired(self._conversations, cutoff)

    def _trim(self, store: dict[Any, _Entry]) -> None:
        while len(store) > self._capacity:
            oldest = min(store, key=lambda key: store[key].created_at)
            del store[oldest]

    def clear(self) -> None:
        self._pending.clear()
        self._conversations.clear()

    @property
    def pending_count(self) -> int:
        self._expire()
        return len(self._pending)


session_store = AgentSessionStore()
