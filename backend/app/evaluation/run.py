import argparse
import sys
from pathlib import Path

from app.core.config import settings
from app.core.db import engine
from app.evaluation.case import Category
from app.evaluation.dataset import DATASET, cases
from app.evaluation.report import render, write_json
from app.evaluation.runner import Mode, run_cases

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNAVAILABLE = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.evaluation.run",
        description="运行 ApplyPilot Agent 评测。",
    )
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in Mode],
        default=Mode.DETERMINISTIC.value,
    )
    parser.add_argument("--case-id", action="append", default=[], dest="case_ids")
    parser.add_argument("--category", choices=[c.value for c in Category])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--json", type=Path, dest="json_path")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="保留评测创建的临时用户，便于人工检查",
    )
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--list", action="store_true", help="打印评测数据集后退出")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    mode = Mode(args.mode)

    if args.list:
        for case in DATASET:
            marker = "real" if case.real else "    "
            print(f"{marker}  {case.category.value:<17}{case.id}")
        print(f"\n共 {len(DATASET)} 个用例")
        return EXIT_OK

    selected = cases(
        category=None if args.category is None else Category(args.category),
        case_ids=args.case_ids,
        real_only=mode is Mode.REAL,
    )
    if not selected:
        print("没有符合筛选条件的用例。")
        return EXIT_UNAVAILABLE

    if mode is Mode.REAL and not settings.agent_is_configured:
        missing = ", ".join(settings.missing_agent_settings())
        print(f"真实模型评测已跳过：未配置 {missing}")
        return EXIT_UNAVAILABLE

    outcomes = run_cases(
        selected,
        engine=engine,
        mode=mode,
        keep=args.keep,
        repeat=args.repeat,
        fail_fast=args.fail_fast,
    )
    print(render(outcomes, mode=mode))

    if args.json_path is not None:
        write_json(outcomes, mode=mode, path=args.json_path)
        print(f"\n结果已写入 {args.json_path}")

    return EXIT_OK if all(outcome.passed for outcome in outcomes) else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
