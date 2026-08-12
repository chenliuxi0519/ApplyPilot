from dataclasses import dataclass

DEFAULT_MAX_STEPS = 8
DEFAULT_MAX_TOOL_CALLS = 10


@dataclass(frozen=True)
class Budget:
    max_steps: int = DEFAULT_MAX_STEPS
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS

    def steps_exhausted(self, step_count: int) -> bool:
        return step_count >= self.max_steps

    def would_exceed_tool_calls(self, tool_call_count: int, batch_size: int) -> bool:
        return tool_call_count + batch_size > self.max_tool_calls
