import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2] / "app"
EVALUATION_DIR = APP_DIR / "evaluation"


PRODUCTION_PACKAGES = ("agent", "api", "harness", "modules", "tools", "core")
ENTRY_POINTS = frozenset({"seed_gold_requirements.py"})


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_no_production_package_imports_the_evaluation() -> None:
    offenders: dict[str, set[str]] = {}
    for package in PRODUCTION_PACKAGES:
        for path in sorted((APP_DIR / package).rglob("*.py")):
            bad = {
                module
                for module in _imported_modules(path)
                if module.startswith("app.evaluation")
            }
            if bad:
                offenders[str(path.relative_to(APP_DIR))] = bad
    assert offenders == {}, f"evaluation must stay downstream: {offenders}"


def test_only_the_seed_script_at_the_app_root_imports_the_evaluation() -> None:
    offenders = [
        path.name
        for path in sorted(APP_DIR.glob("*.py"))
        if path.name not in ENTRY_POINTS
        and any(
            module.startswith("app.evaluation") for module in _imported_modules(path)
        )
    ]
    assert offenders == []


def test_the_evaluation_never_writes_business_rows_directly() -> None:
    source = (EVALUATION_DIR / "fixtures.py").read_text(encoding="utf-8")
    for marker in ("Application(", "ApplicationTask(", "UserProfile("):
        assert marker not in source, f"fixtures.py should not construct {marker}"


def test_the_scorer_reads_stored_history_rather_than_live_state() -> None:
    source = (EVALUATION_DIR / "scoring.py").read_text(encoding="utf-8")
    for marker in ("AgentState", "AgentLoop", "state.trace"):
        assert marker not in source, f"scoring.py should not touch {marker}"
