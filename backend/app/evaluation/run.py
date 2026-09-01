import argparse
import sys
from pathlib import Path

from app.core.config import settings
from app.core.db import engine
from app.evaluation.case import Category
from app.evaluation.compare import ReportFormatError, compare, load_report
from app.evaluation.compare import render as render_comparison
from app.evaluation.dataset import DATASET, cases
from app.evaluation.report import render, to_json, write_json
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
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="任何非致命警告也视为评测失败，适合迭代回归门禁",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        dest="baseline_path",
        help="上一次运行导出的 JSON 报告；逐用例对照，出现回归即判失败",
    )
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

    passed = all(outcome.passed for outcome in outcomes)
    clean = all(not outcome.warnings for outcome in outcomes)
    regressed = False

    if args.baseline_path is not None:
        try:
            comparison = compare(
                baseline=load_report(args.baseline_path),
                current=to_json(outcomes, mode=mode),
            )
        except ReportFormatError as error:
            print(f"\n无法与基线对照：{error}")
            return EXIT_UNAVAILABLE
        print("\n" + render_comparison(comparison))
        # 有回归就必须失败，哪怕这次的绝对通过数比上次还高。
        regressed = comparison.has_regression

    ok = passed and (clean or not args.require_clean) and not regressed
    return EXIT_OK if ok else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
