import ast
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parents[2] / "app" / "harness"
TOOLS_DIR = Path(__file__).resolve().parents[2] / "app" / "tools"

FORBIDDEN_HARNESS_PREFIXES = ("app.modules", "app.tools", "app.api", "app.crud")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_harness_does_not_depend_on_the_business_domain() -> None:
    offenders: dict[str, set[str]] = {}
    for path in sorted(HARNESS_DIR.glob("*.py")):
        bad = {
            module
            for module in _imported_modules(path)
            if module.startswith(FORBIDDEN_HARNESS_PREFIXES)
        }
        if bad:
            offenders[path.name] = bad
    assert offenders == {}, (
        f"app/harness must stay domain agnostic, but found: {offenders}"
    )


def test_tools_do_not_own_transactions() -> None:
    offenders = [
        path.name
        for path in sorted(TOOLS_DIR.glob("*.py"))
        if ".commit(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_tools_do_not_query_the_orm_directly() -> None:
    offenders = [
        path.name
        for path in sorted(TOOLS_DIR.glob("*.py"))
        if "session.exec" in (text := path.read_text(encoding="utf-8"))
        or "session.get(" in text
    ]
    assert offenders == []
