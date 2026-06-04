"""Prepare a daily Lunheng court run for Claude Code / Codex agents.

This module is intentionally a bridge, not a hidden LLM runner.  Python cannot
call Claude Code or Codex subagents by itself; the generated runbook gives those
agent runtimes an explicit ticker list and execution checklist.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence


HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a Lunheng daily stock-research runbook.")
    parser.add_argument("--output-dir", default=str(HERE / "data" / "reports"))
    parser.add_argument(
        "--tickers",
        nargs="+",
        help="Daily ticker list, separated by commas or spaces.",
    )
    parser.add_argument(
        "--tickers-file",
        help="Path to a daily watchlist file.",
    )
    parser.add_argument(
        "--runbook-path",
        help="Where to write the generated agent runbook. Defaults to output-dir/lunheng_runbook.md.",
    )
    parser.add_argument(
        "command_text",
        nargs="*",
        help="Launch phrase, e.g. 论衡十七司，升堂！【600519，000858】",
    )
    return parser


def render_runbook(items) -> str:
    def _ticker_arg(item) -> str:
        bare = item.ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
        return f"{bare}:{item.name}" if item.name else bare

    tickers_arg = ",".join(_ticker_arg(item) for item in items)
    lines = [
        "# 论衡十七司每日个股研报 Runbook",
        "",
        "## 今日清单",
        "",
    ]
    for i, item in enumerate(items, 1):
        display = f"{item.ticker} {item.name}".strip()
        lines.append(f"{i}. {display}")
    lines.extend([
        "",
        "## Agent 执行约定",
        "",
        "1. 由当前 Claude Code / Codex 大语言模型调用 subagent；Python 只负责清单、产物和 HTML 工作台。",
        "2. 对每只股票按项目既有 `tribunal.md` 流程执行 L0-L7。",
        "3. 默认使用多角色 subagent：bull case、bear case、risk/review、final synthesis。",
        "4. 面向股民的 HTML 研报只保留结论、依据、风险、催化剂和后续观察点；不展示内部复核管线。",
        "5. 每只股票完成后落盘 replay trace 与三层 HTML 研报。",
        "6. 全部股票完成后刷新 Workbench。",
        "",
        "## 本地命令",
        "",
        "从已有 agent 输出生成 HTML：",
        "",
        "```bash",
        f"python -m subagent_pipeline.batch_process --tickers {tickers_arg}",
        "```",
        "",
        "启动 HTML Workbench：",
        "",
        "```bash",
        f"python start_workbench.py --tickers {tickers_arg}",
        "```",
        "",
    ])
    return "\n".join(lines)


def prepare_runbook(
    *,
    tickers: Sequence[str] | None = None,
    tickers_file: str | None = None,
    command_text: str = "",
    output_dir: str = str(HERE / "data" / "reports"),
    runbook_path: str | None = None,
) -> Path:
    from subagent_pipeline.watchlist import load_watchlist, save_watchlist

    items = load_watchlist(tickers=tickers, tickers_file=tickers_file, command_text=command_text)
    if not items:
        raise ValueError("No valid tickers found in Lunheng court command.")
    save_watchlist(items, output_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = Path(runbook_path) if runbook_path else out / "lunheng_runbook.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_runbook(items), encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        path = prepare_runbook(
            tickers=args.tickers,
            tickers_file=args.tickers_file,
            command_text=" ".join(args.command_text),
            output_dir=args.output_dir,
            runbook_path=args.runbook_path,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Lunheng runbook: {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
