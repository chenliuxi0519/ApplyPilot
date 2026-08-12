import uuid
from typing import Protocol

from app.agent.state import AgentState
from app.agent.trace import TraceEvent


class RunRecorder(Protocol):
    def start_run(self, state: AgentState) -> None: ...

    def record_event(
        self, run_id: uuid.UUID, sequence: int, event: TraceEvent
    ) -> None: ...

    def finish_run(self, state: AgentState) -> None: ...


class NullRunRecorder:
    def start_run(self, state: AgentState) -> None:
        del state

    def record_event(self, run_id: uuid.UUID, sequence: int, event: TraceEvent) -> None:
        del run_id, sequence, event

    def finish_run(self, state: AgentState) -> None:
        del state


class InMemoryRunRecorder:
    def __init__(self) -> None:
        self.started: list[uuid.UUID] = []
        self.finished: list[tuple[uuid.UUID, str]] = []
        self.events: list[tuple[uuid.UUID, int, TraceEvent]] = []

    def start_run(self, state: AgentState) -> None:
        self.started.append(state.run_id)

    def record_event(self, run_id: uuid.UUID, sequence: int, event: TraceEvent) -> None:
        self.events.append((run_id, sequence, event))

    def finish_run(self, state: AgentState) -> None:
        self.finished.append((state.run_id, state.status.value))

    def sequences(self) -> list[int]:
        return [sequence for _, sequence, _ in self.events]

    def event_types(self) -> list[str]:
        return [event.event_type.value for _, _, event in self.events]
