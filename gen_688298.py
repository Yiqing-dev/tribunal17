"""Generate HTML reports for 688298 东方生物 from individual result files."""
import json
import sys
from pathlib import Path

# Add project root to path
_here = Path(__file__).parent
project_root = _here.parent
sys.path.insert(0, str(project_root))

from subagent_pipeline.bridge import generate_report

RESULTS_DIR = project_root / "agent_artifacts" / "results"
REPORTS_DIR = project_root / "data" / "reports"
REPLAYS_DIR = project_root / "data" / "replays"

def main():
    ticker = "688298"
    ticker_name = "东方生物"
    trade_date = "2026-03-16"

    # Bull/bear are merged R1+R2
    bull_r1 = (RESULTS_DIR / "688298_bull_r1.txt").read_text(encoding="utf-8")
    bull_r2 = (RESULTS_DIR / "688298_bull_r2.txt").read_text(encoding="utf-8")
    bear_r1 = (RESULTS_DIR / "688298_bear_r1.txt").read_text(encoding="utf-8")
    bear_r2 = (RESULTS_DIR / "688298_bear_r2.txt").read_text(encoding="utf-8")

    outputs = {
        "market_analyst":        (RESULTS_DIR / "688298_market_report.txt").read_text(encoding="utf-8"),
        "fundamentals_analyst":  (RESULTS_DIR / "688298_fundamentals_report.txt").read_text(encoding="utf-8"),
        "news_analyst":          (RESULTS_DIR / "688298_news_report.txt").read_text(encoding="utf-8"),
        "sentiment_analyst":     (RESULTS_DIR / "688298_sentiment_report.txt").read_text(encoding="utf-8"),
        "catalyst_agent":        (RESULTS_DIR / "688298_catalyst_report.txt").read_text(encoding="utf-8"),
        "bull_researcher":       f"=== Round 1 ===\n{bull_r1}\n\n=== Round 2 ===\n{bull_r2}",
        "bear_researcher":       f"=== Round 1 ===\n{bear_r1}\n\n=== Round 2 ===\n{bear_r2}",
        "scenario_agent":        (RESULTS_DIR / "688298_scenario_report.txt").read_text(encoding="utf-8"),
        "research_manager":      (RESULTS_DIR / "688298_research_manager.txt").read_text(encoding="utf-8"),
        "aggressive_debator":    (RESULTS_DIR / "688298_risk_aggressive.txt").read_text(encoding="utf-8"),
        "conservative_debator":  (RESULTS_DIR / "688298_risk_conservative.txt").read_text(encoding="utf-8"),
        "neutral_debator":       (RESULTS_DIR / "688298_risk_neutral.txt").read_text(encoding="utf-8"),
        "risk_manager":          (RESULTS_DIR / "688298_risk_manager.txt").read_text(encoding="utf-8"),
        "research_output":       (RESULTS_DIR / "688298_research_output.txt").read_text(encoding="utf-8"),
    }

    # Load market context
    market_context_block = ""
    market_context = {}
    ctx_block_path = RESULTS_DIR / "market_context_block.txt"
    ctx_json_path = RESULTS_DIR / "market_context.json"
    if ctx_block_path.exists():
        market_context_block = ctx_block_path.read_text(encoding="utf-8")
    if ctx_json_path.exists():
        market_context = json.loads(ctx_json_path.read_text(encoding="utf-8"))

    print(f"Loaded {len(outputs)} agent outputs")
    print(f"Market context: regime={market_context.get('regime', 'N/A')}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    REPLAYS_DIR.mkdir(parents=True, exist_ok=True)

    paths = generate_report(
        outputs=outputs,
        ticker=ticker,
        ticker_name=ticker_name,
        trade_date=trade_date,
        output_dir=str(REPORTS_DIR),
        storage_dir=str(REPLAYS_DIR),
        market_context_block=market_context_block,
        market_context=market_context,
    )

    print("\n=== Generated Reports ===")
    for key, path in paths.items():
        if key != "run_id":
            print(f"  {key:12s}: {path}")
    print(f"  run_id      : {paths.get('run_id')}")

    run_id = paths.get("run_id")
    if run_id:
        try:
            from subagent_pipeline.renderers.debate_renderer import generate_committee_report
            from subagent_pipeline.replay_store import ReplayStore
            store = ReplayStore(storage_dir=str(REPLAYS_DIR))
            trace = store.load_run(run_id)
            if trace:
                cp = generate_committee_report(trace, output_dir=str(REPORTS_DIR))
                if cp:
                    print(f"  committee   : {cp}")
        except Exception as e:
            print(f"[WARN] Committee report failed: {e}")

    return paths


if __name__ == "__main__":
    main()
