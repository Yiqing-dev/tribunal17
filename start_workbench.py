"""Start the local stock-research workbench.

This launcher is intentionally repo-local so Claude Code and Codex can start
the product workbench without remembering PYTHONPATH details.

Usage:
    python start_workbench.py
    python start_workbench.py --tickers 600519,000858,002594
    python start_workbench.py --tickers-file watchlist.txt
    python start_workbench.py "论衡十七司，升堂！【600519，000858，002594】"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the TradingAgents local workbench.")
    parser.add_argument("--output-dir", default=str(HERE / "data" / "reports"))
    parser.add_argument("--storage-dir", default=str(HERE / "data" / "replays"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--tickers",
        nargs="+",
        help="Daily ticker list, separated by commas or spaces. Example: --tickers 600519,000858",
    )
    parser.add_argument(
        "--tickers-file",
        help="Path to a daily watchlist file. Lines may be '600519' or '600519 贵州茅台'.",
    )
    parser.add_argument(
        "--no-generate",
        action="store_true",
        help="Do not regenerate workbench.html before serving.",
    )
    parser.add_argument(
        "command_text",
        nargs="*",
        help="Optional launch phrase, e.g. 论衡十七司，升堂！【600519，000858】",
    )
    return parser


def warn_missing_workbench(output_dir: str) -> bool:
    """Warn when serving is requested without an existing workbench page."""
    workbench_path = Path(output_dir) / "workbench.html"
    if workbench_path.exists():
        return False
    print(
        f"Warning: --no-generate was used but {workbench_path} does not exist; "
        "the workbench URL will return 404 until reports are generated.",
        flush=True,
    )
    return True


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from subagent_pipeline.watchlist import load_watchlist, save_watchlist, watchlist_names

    watchlist = load_watchlist(
        tickers=args.tickers,
        tickers_file=args.tickers_file,
        command_text=" ".join(args.command_text),
    )
    if watchlist:
        save_watchlist(watchlist, args.output_dir)

    if not args.no_generate:
        from subagent_pipeline.renderers.report_renderer import generate_workbench_report

        generate_workbench_report(
            output_dir=args.output_dir,
            storage_dir=args.storage_dir,
            tickers=[item.ticker for item in watchlist],
            ticker_names=watchlist_names(watchlist),
        )
    else:
        warn_missing_workbench(args.output_dir)

    url = f"http://{args.host}:{args.port}/workbench.html"
    if watchlist:
        print(f"Daily watchlist: {len(watchlist)} tickers", flush=True)
    print(f"Workbench URL: {url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)

    from subagent_pipeline.workbench_server import serve_workbench

    serve_workbench(
        output_dir=args.output_dir,
        storage_dir=args.storage_dir,
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
