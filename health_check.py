"""Post-run health check — detect anomalous drift and silent failures.

Run after each daily batch to catch:
1. Action flips (BUY→SELL or vice versa) without corresponding market move
2. Confidence anomalies (e.g., all stocks at same confidence)
3. Missing/failed nodes in traces
4. Stale data (trade_date mismatch)

Usage:
    from subagent_pipeline.health_check import check_run_health, check_batch_health

    # Single run
    issues = check_run_health(run_id, storage_dir="data/replays")

    # Batch (today's runs vs yesterday's)
    report = check_batch_health(
        today_run_ids=[...],
        storage_dir="data/replays",
        signal_path="data/signals/signals.jsonl",
    )
    if report["alerts"]:
        print("ALERTS:", report["alerts"])
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .shared import mean_confidence

logger = logging.getLogger(__name__)


def check_run_health(run_id: str, storage_dir: str = "data/replays") -> List[str]:
    """Check a single run for anomalies. Returns list of issue strings."""
    from .replay_store import ReplayStore
    store = ReplayStore(storage_dir=storage_dir)
    trace = store.load(run_id)
    if trace is None:
        return [f"Trace not found: {run_id}"]

    issues = []

    # 1. Missing nodes
    expected_min = 10  # at minimum: 4 analysts + catalyst + 2 debate + scenario + PM + risk
    if trace.total_nodes < expected_min:
        issues.append(
            f"Only {trace.total_nodes} nodes (expected >= {expected_min}). "
            f"Pipeline may have been cut short."
        )

    # 2. Error nodes
    if trace.error_count > 0:
        error_names = [nt.node_name for nt in trace.node_traces
                       if nt.status.value == "error"]
        issues.append(f"{trace.error_count} error nodes: {', '.join(error_names)}")

    # 3. No action
    if not trace.research_action:
        issues.append("No research_action set — output parsing may have failed")

    # 4. Confidence sentinel
    if trace.final_confidence < 0:
        issues.append("final_confidence is sentinel (-1.0) — no stage set confidence")

    # 5. Extreme confidence
    if trace.final_confidence > 0.95:
        issues.append(
            f"Unusually high confidence ({trace.final_confidence:.0%}). "
            f"May indicate parsing artifact."
        )

    # 6. VETO without source
    if trace.was_vetoed and not trace.veto_source:
        issues.append("Was vetoed but veto_source is empty")

    return issues


def check_batch_health(
    today_run_ids: List[str],
    storage_dir: str = "data/replays",
    signal_path: str = "data/signals/signals.jsonl",
) -> Dict[str, Any]:
    """Check a batch of today's runs for cross-stock anomalies.

    Returns dict with:
        - alerts: list of critical issues
        - warnings: list of non-critical observations
        - summary: dict of counts
    """
    from .replay_store import ReplayStore
    from .signal_ledger import SignalLedger

    store = ReplayStore(storage_dir=storage_dir)
    alerts: List[str] = []
    warnings: List[str] = []

    # Load today's traces
    traces = []
    for rid in today_run_ids:
        t = store.load(rid)
        if t:
            traces.append(t)
        else:
            alerts.append(f"Missing trace: {rid}")

    if not traces:
        return {"alerts": ["No valid traces found"], "warnings": [], "summary": {}}

    # 1. All same action?
    actions = [t.research_action for t in traces if t.research_action]
    if len(set(actions)) == 1 and len(actions) >= 5:
        warnings.append(
            f"All {len(actions)} stocks have action={actions[0]}. "
            f"Possible systematic bias or prompt issue."
        )

    # 2. Confidence clustering
    confs = [t.final_confidence for t in traces if t.final_confidence >= 0]
    if confs and len(confs) >= 3:
        spread = max(confs) - min(confs)
        if spread < 0.05:
            warnings.append(
                f"Confidence spread is only {spread:.2f} across {len(confs)} stocks. "
                f"May indicate agents not differentiating."
            )

    # 3. Per-run health
    per_run_issues = {}
    for t in traces:
        issues = check_run_health(t.run_id, storage_dir=storage_dir)
        if issues:
            per_run_issues[f"{t.ticker} ({t.run_id[:12]})"] = issues
            for issue in issues:
                if "error" in issue.lower() or "not found" in issue.lower():
                    alerts.append(f"{t.ticker}: {issue}")

    # 4. Action flips vs previous day
    ledger = SignalLedger(path=signal_path)
    flip_count = 0

    def _fmt_conf(c) -> str:
        # -1.0 sentinel ("not set") must not render as "-100%".
        return f"{c:.0%}" if isinstance(c, (int, float)) and c >= 0 else "—"

    for t in traces:
        # XC-05: find the most recent signal STRICTLY BEFORE today's trade_date.
        # `before=` is inclusive, so filter out any same-day record — this works
        # whether or not today's signal has already been appended to the ledger,
        # removing the previous fragile [0]/[1] positional assumption.
        prev_signals = ledger.read(ticker=t.ticker, before=t.trade_date, limit=5)
        prev = next(
            (s for s in prev_signals if s.trade_date and s.trade_date < t.trade_date),
            None,
        )
        if prev and prev.action != t.research_action:
            if (prev.action in ("BUY", "SELL") and
                    t.research_action in ("BUY", "SELL")):
                direction = f"{prev.action}→{t.research_action}"
                alerts.append(
                    f"{t.ticker}: Action flip {direction} "
                    f"(confidence {_fmt_conf(prev.confidence)}→{_fmt_conf(t.final_confidence)})"
                )
                flip_count += 1

    summary = {
        "total_runs": len(today_run_ids),
        "loaded": len(traces),
        "actions": {a: actions.count(a) for a in set(actions)} if actions else {},
        "avg_confidence": round(mean_confidence(confs), 3) if confs else 0,
        "error_runs": sum(1 for t in traces if t.error_count > 0),
        "veto_count": sum(1 for t in traces if t.was_vetoed),
        "action_flips": flip_count,
        "per_run_issues": per_run_issues,
    }

    return {"alerts": alerts, "warnings": warnings, "summary": summary}
