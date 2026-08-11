from app.harness import ToolDefinition, ToolRegistry
from app.tools.applications import (
    CREATE_APPLICATION,
    CREATE_APPLICATION_TASK,
    UPDATE_APPLICATION_STATUS,
    UPDATE_APPLICATION_TASK,
)
from app.tools.profile import GET_USER_PROFILE, UPDATE_USER_PROFILE
from app.tools.programs import (
    COMPARE_PROGRAMS,
    GET_PROGRAM_REQUIREMENTS,
    SEARCH_PROGRAMS,
)

BUSINESS_TOOLS: tuple[ToolDefinition, ...] = (
    GET_USER_PROFILE,
    UPDATE_USER_PROFILE,
    SEARCH_PROGRAMS,
    GET_PROGRAM_REQUIREMENTS,
    COMPARE_PROGRAMS,
    CREATE_APPLICATION,
    CREATE_APPLICATION_TASK,
    UPDATE_APPLICATION_TASK,
    UPDATE_APPLICATION_STATUS,
)


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for definition in BUSINESS_TOOLS:
        registry.register(definition)
    return registry
