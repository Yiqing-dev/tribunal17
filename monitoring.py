"""Rolling drift monitoring: per-regime / per-action / per-pillar accuracy.

Runs after L7 backtest. Computes 30/60/90-day rolling direction accuracy
stratified by market regime, action type, and pillar. Flags strata that fall
below warning/alert thresholds so drift is visible before it compounds.

Data flow:
  SignalLedger records ──┐
                         ├──→ join on (ticker, trade_date)
  BacktestResults ───────┘        │
                                  ▼
                        StratumResult per (label, window_days)
                                  │
                                  ▼
                        RollingMonitorReport → rolling-{date}.json
                                             → brief-{date}.md alerts section
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Hard-coded thresholds. See plan doc P2 for rationale (random=50%, below 40%
# means the model is actively destructive; 35% is catastrophic). Keep these
# visible as module-level constants so monitoring behavior is auditable.
ACCURACY_WARN = 0.40
ACCURACY_ALERT = 0.35
MIN_SAMPLE_N = 10
ROLLING_WINDOWS = (30, 60, 90)


@dataclass
class StratumResult:
    """Accuracy for a single stratum within a rolling window."""
    label: str                 # e.g. "regime=RISK_ON", "action=BUY", "pillar=market"
    window_days: int
    n: int                     # Sample count (only directional signals; HOLD excluded)
    accuracy: float            # 0.0 – 1.0
    alert_level: str = ""      # "" | "warn" | "alert"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RollingMonitorReport:
    """Aggregated rolling drift report written once per pipeline run."""
    computed_at: str = ""
    trade_date: str = ""
    stratum_results: List[StratumResult] = field(default_factory=list)
    alerts: List[StratumResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "computed_at": self.computed_at,
            "trade_date": self.trade_date,
            "stratum_results": [s.to_dict() for s in self.stratum_results],
            "alerts": [a.to_dict() for a in self.alerts],
        }

    def to_markdown_section(self) -> str:
        """Markdown section for append to brief-{date}.md."""
        lines = ["## 滚动监控告警", ""]
        if not self.alerts:
            lines.append("*未发现异常，所有层滚动准确率 ≥ 40% 或样本不足 (n<10)。*")
            return "\n".join(lines)
        lines.append(
            f"共 {len(self.alerts)} 个层跌破阈值（样本数 ≥ {MIN_SAMPLE_N}）："
        )
        lines.append("")
        lines.append("| 层 | 窗口 | 样本 | 准确率 | 等级 |")
        lines.append("|------|------|------|--------|------|")
        for a in self.alerts:
            lines.append(
                f"| {a.label} | {a.window_days}d | {a.n} | "
                f"{a.accuracy:.0%} | **{a.alert_level.upper()}** |"
            )
        return "\n".join(lines)


def _pillar_direction(score: int) -> str:
    """Pillar score → directional view. score=2 is neutral (excluded from accuracy)."""
    if score is None or score < 0:
        return "neutral"
    if score >= 3:
        return "up"
    if score <= 1:
        return "down"
    return "neutral"


def _infer_actual_direction(return_pct: float, band_pct: float = 2.0) -> str:
    """Forward return → actual market direction (with neutral band)."""
    if return_pct is None:
        return "neutral"
    if return_pct > band_pct:
        return "up"
    if return_pct < -band_pct:
        return "down"
    return "neutral"


def load_supplement(path: str) -> Dict[str, str]:
    """Load regime_supplement.json. Returns {} if missing/malformed."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load supplement %s: %s", path, e)
    return {}


def _alert_level_for(accuracy: float, n: int) -> str:
    """Classify a stratum's alert level based on accuracy + sample count."""
    if n < MIN_SAMPLE_N:
        return ""
    if accuracy < ACCURACY_ALERT:
        return "alert"
    if accuracy < ACCURACY_WARN:
        return "warn"
    return ""


def _compute_window(
    records_with_outcomes: List[Dict[str, Any]],
    days: int,
) -> List[StratumResult]:
    """Compute stratified accuracy within one window.

    Each record dict must have keys: action, regime, actual_direction,
    direction_expected (up/down/flat/abstain), direction_correct (bool|None),
    pillar_scores (dict).
    """
    # Filter to directional (up/down) for direction accuracy; HOLD/VETO excluded.
    directional = [
        r for r in records_with_outcomes
        if r.get("direction_expected") in ("up", "down")
        and r.get("direction_correct") is not None
    ]
    if not directional:
        return []

    results: List[StratumResult] = []

    # By regime
    regimes: Dict[str, List[bool]] = {}
    for r in directional:
        reg = r.get("regime") or "UNKNOWN"
        regimes.setdefault(reg, []).append(bool(r["direction_correct"]))
    for reg, correct_list in regimes.items():
        n = len(correct_list)
        acc = sum(correct_list) / n
        results.append(StratumResult(
            label=f"regime={reg}", window_days=days,
            n=n, accuracy=acc, alert_level=_alert_level_for(acc, n),
        ))

    # By action
    actions: Dict[str, List[bool]] = {}
    for r in directional:
        act = (r.get("action") or "").upper()
        actions.setdefault(act, []).append(bool(r["direction_correct"]))
    for act, correct_list in actions.items():
        n = len(correct_list)
        acc = sum(correct_list) / n
        results.append(StratumResult(
            label=f"action={act}", window_days=days,
            n=n, accuracy=acc, alert_level=_alert_level_for(acc, n),
        ))

    # By pillar — pillar_direction vs actual_direction (score=2 skipped as neutral)
    pillar_keys = ("market", "fundamental", "news", "sentiment")
    for pk in pillar_keys:
        score_key = f"{pk}_score"
        pillar_hits: List[bool] = []
        for r in directional:
            pillars = r.get("pillar_scores") or {}
            score = pillars.get(score_key, -1)
            pdir = _pillar_direction(score)
            if pdir == "neutral":
                continue  # pillar abstained
            actual = r.get("actual_direction") or "neutral"
            if actual == "neutral":
                continue  # market was flat — pillar had no chance to be right/wrong
            pillar_hits.append(pdir == actual)
        if pillar_hits:
            n = len(pillar_hits)
            acc = sum(pillar_hits) / n
            results.append(StratumResult(
                label=f"pillar={pk}", window_days=days,
                n=n, accuracy=acc, alert_level=_alert_level_for(acc, n),
            ))

    return results


def compute_rolling_monitor(
    trade_date: str,
    ledger_path: str = "data/signals/signals.jsonl",
    supplement_path: str = "data/signals/regime_supplement.json",
    storage_dir: str = "data/replays",
    output_dir: str = "data/monitoring",
    windows: Tuple[int, ...] = ROLLING_WINDOWS,
) -> RollingMonitorReport:
    """Main entry: read ledger + run backtest for each window, stratify, persist."""
    from .signal_ledger import SignalLedger
    from .backtest import run_backtest_from_ledger, BacktestConfig

    report = RollingMonitorReport(
        computed_at=datetime.now().isoformat(),
        trade_date=trade_date,
    )

    # Parse trade_date; if invalid, use today.
    try:
        ref_date = datetime.strptime(trade_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        ref_date = datetime.now()

    # Load ledger + supplement once
    ledger = SignalLedger(path=ledger_path)
    try:
        all_records = ledger.read()
    except FileNotFoundError:
        logger.info("No ledger at %s — rolling monitor returns empty.", ledger_path)
        return report
    supplement = load_supplement(supplement_path)

    # Index ledger by (ticker, trade_date) for O(1) join against backtest
    ledger_index: Dict[Tuple[str, str], Any] = {}
    for rec in all_records:
        ledger_index[(rec.ticker, rec.trade_date)] = rec

    for window_days in windows:
        cutoff = (ref_date - timedelta(days=window_days)).strftime("%Y-%m-%d")
        bt_config = BacktestConfig()
        try:
            bt_report = run_backtest_from_ledger(
                ledger_path=ledger_path,
                config=bt_config,
                after=cutoff,
            )
        except Exception as e:
            logger.warning(
                "run_backtest_from_ledger failed for window=%dd: %s", window_days, e
            )
            continue

        # Join backtest results with ledger records
        joined: List[Dict[str, Any]] = []
        for bt in bt_report.results:
            if bt.eval_status != "completed":
                continue
            key = (bt.ticker, bt.trade_date)
            rec = ledger_index.get(key)
            if rec is None:
                continue
            regime = rec.market_regime or supplement.get(rec.run_id) or ""
            joined.append({
                "ticker": bt.ticker,
                "trade_date": bt.trade_date,
                "action": bt.action,
                "direction_expected": bt.direction_expected,
                "direction_correct": bt.direction_correct,
                "actual_direction": _infer_actual_direction(bt.stock_return_pct),
                "regime": regime.upper() if regime else "UNKNOWN",
                "pillar_scores": {
                    "market_score": rec.market_score,
                    "fundamental_score": rec.fundamental_score,
                    "news_score": rec.news_score,
                    "sentiment_score": rec.sentiment_score,
                },
            })

        window_results = _compute_window(joined, window_days)
        report.stratum_results.extend(window_results)

    # Alerts = strata with any non-empty alert_level
    report.alerts = [s for s in report.stratum_results if s.alert_level]

    # Persist JSON
    _write_report(report, output_dir)

    return report


def _write_report(report: RollingMonitorReport, output_dir: str) -> Path:
    """Atomic write of rolling-{date}.json under output_dir."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    date_slug = report.trade_date.replace("-", "") or "unknown"
    path = out / f"rolling-{date_slug}.json"

    content = json.dumps(report.to_dict(), ensure_ascii=False, indent=2, allow_nan=False)
    fd, tmp = tempfile.mkstemp(dir=str(out), suffix=".tmp", prefix=".roll-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path
