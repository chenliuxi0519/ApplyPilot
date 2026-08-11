import ast
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[2] / "app" / "agent"


FORBIDDEN_PREFIXES = ("app.modules", "app.tools", "app.api", "app.crud")


COMPOSITION_ROOTS = frozenset({"cli.py"})


PROVIDER_MODULES = ("anthropic",)
PROVIDER_ADAPTER = "anthropic_client.py"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_agent_does_not_reach_into_the_business_domain() -> None:
    offenders: dict[str, set[str]] = {}
    for path in sorted(AGENT_DIR.glob("*.py")):
        if path.name in COMPOSITION_ROOTS:
            continue
        bad = {
            module
            for module in _imported_modules(path)
            if module.startswith(FORBIDDEN_PREFIXES)
        }
        if bad:
            offenders[path.name] = bad
    assert offenders == {}, f"app/agent must stay domain agnostic: {offenders}"


def test_the_cli_adds_no_agent_logic() -> None:
    source = (AGENT_DIR / "cli.py").read_text(encoding="utf-8")
    for marker in (
        "validate_tool_call",
        "decide(",
        "execute_tool",
        "while True:\n        response",
    ):
        assert marker not in source, f"cli.py should not contain {marker!r}"


def test_only_the_adapter_knows_the_provider() -> None:
    offenders = [
        path.name
        for path in sorted(AGENT_DIR.glob("*.py"))
        if path.name != PROVIDER_ADAPTER
        and any(
            module.split(".")[0] in PROVIDER_MODULES
            for module in _imported_modules(path)
        )
    ]
    assert offenders == [], (
        f"only {PROVIDER_ADAPTER} may import a provider SDK, found: {offenders}"
    )


def test_the_loop_does_not_parse_provider_content_blocks() -> None:
    source = (AGENT_DIR / "loop.py").read_text(encoding="utf-8")
    for marker in ('"tool_use"', '"text"', '"content"', "block.type"):
        assert marker not in source, f"loop.py should not know about {marker}"
