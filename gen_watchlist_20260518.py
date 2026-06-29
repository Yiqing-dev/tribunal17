"""Generate HTML reports for the 2026-05-18 watchlist from existing per-agent artifacts.

Reuses per-ticker outputs collected on 2026-05-13 and the 2026-05-12 market context.
"""
import json
import sys
from pathlib import Path

_here = Path(__file__).parent
project_root = _here.parent
sys.path.insert(0, str(project_root))

from subagent_pipeline.bridge import generate_report
from subagent_pipeline.renderers.debate_renderer import generate_committee_report
from subagent_pipeline.replay_store import ReplayStore

RESULTS_DIR = project_root / "agent_artifacts" / "results"
REPORTS_DIR = project_root / "data" / "reports"
REPLAYS_DIR = project_root / "data" / "replays"
TRADE_DATE = "2026-05-13"

TICKERS = [
    ("603065", "宿迁联盛"),
    ("000710", "贝瑞基因"),
    ("920344", "三元基因"),
    ("688298", "东方生物"),
    ("002131", "利欧股份"),
    ("002370", "亚太药业"),
]

OUTPUT_FILES = {
    "market_analyst":       "market_report.txt",
    "fundamentals_analyst": "fundamentals_report.txt",
    "news_analyst":         "news_report.txt",
    "sentiment_analyst":    "sentiment_report.txt",
    "catalyst_agent":       "catalyst_report.txt",
    "scenario_agent":       "scenario_report.txt",
    "research_manager":     "research_manager.txt",
    "aggressive_debator":   "risk_aggressive.txt",
    "conservative_debator": "risk_conservative.txt",
    "neutral_debator":      "risk_neutral.txt",
    "risk_manager":         "risk_manager.txt",
    "research_output":      "research_output.txt",
}


def _load_outputs(ticker: str) -> dict:
    outputs = {}
    for key, suffix in OUTPUT_FILES.items():
        path = RESULTS_DIR / f"{ticker}_{suffix}"
        outputs[key] = path.read_text(encoding="utf-8")
    bull_r1 = (RESULTS_DIR / f"{ticker}_bull_r1.txt").read_text(encoding="utf-8")
    bull_r2 = (RESULTS_DIR / f"{ticker}_bull_r2.txt").read_text(encoding="utf-8")
    bear_r1 = (RESULTS_DIR / f"{ticker}_bear_r1.txt").read_text(encoding="utf-8")
    bear_r2 = (RESULTS_DIR / f"{ticker}_bear_r2.txt").read_text(encoding="utf-8")
    outputs["bull_researcher"] = f"=== Round 1 ===\n{bull_r1}\n\n=== Round 2 ===\n{bull_r2}"
    outputs["bear_researcher"] = f"=== Round 1 ===\n{bear_r1}\n\n=== Round 2 ===\n{bear_r2}"
    return outputs


def _load_market_context():
    block_path = RESULTS_DIR / "market_context_block.txt"
    json_path = RESULTS_DIR / "market_context.json"
    block = block_path.read_text(encoding="utf-8") if block_path.exists() else ""
    ctx = json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else {}
    return block, ctx


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    REPLAYS_DIR.mkdir(parents=True, exist_ok=True)

    market_context_block, market_context = _load_market_context()
    print(f"Market context regime: {market_context.get('regime', 'N/A')}")
    print(f"Market context trade_date: {market_context.get('trade_date', 'N/A')}")

    store = ReplayStore(storage_dir=str(REPLAYS_DIR))
    summary = []

    for ticker, name in TICKERS:
        print(f"\n=== {ticker} {name} ===")
        try:
            outputs = _load_outputs(ticker)
        except FileNotFoundError as exc:
            print(f"  [SKIP] missing artifact: {exc}")
            continue

        paths = generate_report(
            outputs=outputs,
            ticker=ticker,
            ticker_name=name,
            trade_date=TRADE_DATE,
            output_dir=str(REPORTS_DIR),
            storage_dir=str(REPLAYS_DIR),
            market_context_block=market_context_block,
            market_context=market_context,
        )
        run_id = paths.get("run_id")
        print(f"  run_id    : {run_id}")
        for key in ("snapshot", "research", "audit"):
            if paths.get(key):
                print(f"  {key:9s}: {Path(paths[key]).name}")

        if run_id:
            try:
                trace = store.load(run_id)
                if trace:
                    cp = generate_committee_report(trace, output_dir=str(REPORTS_DIR))
                    if cp:
                        print(f"  committee: {Path(cp).name}")
            except Exception as exc:
                print(f"  [WARN] committee report failed: {exc}")

        summary.append((ticker, name, run_id))

    print("\n=== Summary ===")
    for ticker, name, run_id in summary:
        print(f"  {ticker} {name}: run_id={run_id}")

    return summary


if __name__ == "__main__":
    main()
