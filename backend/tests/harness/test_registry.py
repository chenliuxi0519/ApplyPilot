import json

import pytest

from app.harness import DuplicateToolError, ToolRegistry, UnknownToolError
from app.tools import BUSINESS_TOOLS, build_default_registry
from tests.harness.conftest import make_definition


def test_registered_tool_can_be_read_back(registry: ToolRegistry) -> None:
    definition = registry.get("echo")
    assert definition.name == "echo"
    assert "echo" in registry
    assert len(registry) == 1


def test_duplicate_name_is_rejected(registry: ToolRegistry) -> None:
    with pytest.raises(DuplicateToolError):
        registry.register(make_definition())
    assert len(registry) == 1


def test_unknown_tool_raises(registry: ToolRegistry) -> None:
    with pytest.raises(UnknownToolError):
        registry.get("nope")
    assert registry.try_get("nope") is None
    assert "nope" not in registry


def test_listing_is_sorted_by_name() -> None:
    registry = ToolRegistry()
    for name in ("zulu", "alpha", "mike"):
        registry.register(make_definition(name=name))
    assert [definition.name for definition in registry.list()] == [
        "alpha",
        "mike",
        "zulu",
    ]


def test_llm_schema_shape(registry: ToolRegistry) -> None:
    schemas = registry.llm_schemas()
    assert len(schemas) == 1
    assert sorted(schemas[0]) == ["description", "input_schema", "name"]
    assert schemas[0]["input_schema"]["type"] == "object"
    assert "message" in schemas[0]["input_schema"]["properties"]


def test_every_business_tool_schema_is_json_serializable() -> None:
    registry = build_default_registry()

    assert len(registry) == len(BUSINESS_TOOLS)
    assert registry.names() == sorted(tool.name for tool in BUSINESS_TOOLS)

    json.dumps(registry.llm_schemas())
    for definition in registry.list():
        json.dumps(definition.output_schema)
