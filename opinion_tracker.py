"""Opinion Tracker — daily cross-ticker opinion drift analysis.

Reads historical RunTraces, extracts per-ticker-per-day snapshots of
action/confidence/scores/arguments, computes day-over-day drifts,
and aggregates into a multi-ticker watchlist report.

Pure Python, zero external imports, no LLM calls.

Usage:
    from subagent_pipeline.opinion_tracker import (
        build_watchlist_report, track_ticker, latest_drift,
    )

    # Multi-ticker watchlist
    report = build_watchlist_report(
        tickers=["601985.SS", "000710.SZ"],
        date_from="2026-03-14", date_to="2026-03-19",
    )
    print(report.to_markdown())

    # Single-ticker quick view
    snapshots, drifts = track_ticker("601985.SS", limit=30)

    # Most recent change for a ticker
    drift = latest_drift("601985.SS")
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .replay_store import ReplayStore
from .trace_models import RunTrace

logger = logging.getLogger(__name__)

# ── Node name → pillar score field ──────────────────────────────────────
_PILLAR_MAP = {
    "Market Analyst": "market_score",
    "Fundamentals Analyst": "fundamental_score",
    "News Analyst": "news_score",
    "Social Analyst": "sentiment_score",
}

# Action severity ranking (lower = more bearish)
_ACTION_RANK = {"VETO": 0, "SELL": 1, "HOLD": 2, "BUY": 3}


# ── Data Classes ────────────────────────────────────────────────────────


@dataclass
class DailySnapshot:
    """Complete opinion state for one ticker on one day."""

    # Identity
    run_id: str = ""
    ticker: str = ""
    ticker_name: str = ""
    trade_date: str = ""

    # Final decision
    action: str = ""
    confidence: float = -1.0
    was_vetoed: bool = False

    # Pillar scores (0-4)
    market_score: int = -1
    fundamental_score: int = -1
    news_score: int = -1
    sentiment_score: int = -1

    # Risk
    risk_score: int = -1
    risk_cleared: bool = False
    risk_flags: List[str] = field(default_factory=list)

    # Bull case
    bull_thesis: str = ""
    bull_claims: List[Dict] = field(default_factory=list)
    bull_overall_confidence: float = 0.0

    # Bear case
    bear_thesis: str = ""
    bear_claims: List[Dict] = field(default_factory=list)
    bear_overall_confidence: float = 0.0

    # Scenario probabilities
    base_prob: float = 0.0
    bull_prob: float = 0.0
    bear_prob: float = 0.0

    # PM synthesis
    pm_conclusion: str = ""
    thesis_effect: str = ""

    # Trade plan
    stop_loss: float = 0.0
    take_profit: float = 0.0
    entry_price: float = 0.0

    # Market context
    market_regime: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "DailySnapshot":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class OpinionDrift:
    """Day-over-day opinion change for one ticker."""

    ticker: str = ""
    ticker_name: str = ""
    date_prev: str = ""
    date_curr: str = ""

    # Action
    action_prev: str = ""
    action_curr: str = ""
    action_changed: bool = False

    # Confidence
    confidence_prev: float = -1.0
    confidence_curr: float = -1.0
    confidence_delta: float = 0.0

    # Pillar score deltas
    market_score_delta: int = 0
    fundamental_score_delta: int = 0
    news_score_delta: int = 0
    sentiment_score_delta: int = 0

    # Risk
    risk_score_prev: int = -1
    risk_score_curr: int = -1
    risk_score_delta: int = 0
    risk_flags_added: List[str] = field(default_factory=list)
    risk_flags_removed: List[str] = field(default_factory=list)

    # Bull/bear argument drift
    bull_claims_added: List[str] = field(default_factory=list)
    bull_claims_dropped: List[str] = field(default_factory=list)
    bear_claims_added: List[str] = field(default_factory=list)
    bear_claims_dropped: List[str] = field(default_factory=list)
    bull_confidence_delta: float = 0.0
    bear_confidence_delta: float = 0.0

    # Scenario probability shift
    base_prob_delta: float = 0.0
    bull_prob_delta: float = 0.0
    bear_prob_delta: float = 0.0

    # Thesis drift
    thesis_effect_curr: str = ""

    # Market regime
    regime_prev: str = ""
    regime_curr: str = ""
    regime_changed: bool = False

    # Summary assessment
    drift_magnitude: str = ""       # major / minor / stable
    drift_direction: str = ""       # bullish_shift / bearish_shift / unchanged

    # Stale signal detection
    is_stale: bool = False          # True when signal unchanged for >= stale_threshold days
    stale_streak: int = 0           # Consecutive days with same action + unchanged pillars

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class WatchlistReport:
    """Aggregated opinion tracking across a watchlist over a date range."""

    date_from: str = ""
    date_to: str = ""
    generated_at: str = ""
    tickers: List[str] = field(default_factory=list)

    # Per-ticker data
    snapshots: Dict[str, List[DailySnapshot]] = field(default_factory=dict)
    drifts: Dict[str, List[OpinionDrift]] = field(default_factory=dict)

    # Watchlist-level highlights
    action_flips: List[Dict] = field(default_factory=list)
    biggest_confidence_moves: List[Dict] = field(default_factory=list)
    new_risk_flags: List[Dict] = field(default_factory=list)
    stale_signals: List[Dict] = field(default_factory=list)
    unstable_tickers: List[Dict] = field(default_factory=list)

    # Latest snapshot per ticker
    current_state: Dict[str, DailySnapshot] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "date_from": self.date_from,
            "date_to": self.date_to,
            "generated_at": self.generated_at,
            "tickers": self.tickers,
            "snapshots": {
                t: [s.to_dict() for s in snaps]
                for t, snaps in self.snapshots.items()
            },
            "drifts": {
                t: [d.to_dict() for d in drs]
                for t, drs in self.drifts.items()
            },
            "action_flips": self.action_flips,
            "biggest_confidence_moves": self.biggest_confidence_moves,
            "new_risk_flags": self.new_risk_flags,
            "unstable_tickers": self.unstable_tickers,
            "current_state": {
                t: s.to_dict() for t, s in self.current_state.items()
            },
        }

    def save_json(self, output_dir: str = "data/reports") -> Path:
        """Persist report as JSON."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"watchlist-{self.date_from}-{self.date_to}.json"
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def to_markdown(self) -> str:
        """Human-readable watchlist summary."""
        lines: List[str] = []
        n_tickers = len(self.tickers)
        lines.append("# 观点跟踪报告")
        lines.append("")
        lines.append(
            f"> {self.date_from} ~ {self.date_to} | "
            f"{n_tickers} 只股票 | 生成于 {self.generated_at[:10]}"
        )
        lines.append("")

        # ── Highlights ──
        lines.append("## 重要变动")
        lines.append("")

        # Action flips
        if self.action_flips:
            lines.append("### 信号翻转")
            lines.append("| 日期 | 股票 | 变动 |")
            lines.append("|------|------|------|")
            for flip in self.action_flips:
                lines.append(
                    f"| {flip['date']} | {flip['ticker_name']} "
                    f"| {flip['from_action']} -> {flip['to_action']} |"
                )
            lines.append("")
        else:
            lines.append("_(无信号翻转)_")
            lines.append("")

        # Big confidence moves
        if self.biggest_confidence_moves:
            lines.append("### 置信度大幅波动")
            lines.append("| 日期 | 股票 | 变动 | 前值 | 现值 |")
            lines.append("|------|------|------|------|------|")
            for m in self.biggest_confidence_moves[:10]:
                sign = "+" if m["delta"] > 0 else ""
                lines.append(
                    f"| {m['date']} | {m['ticker_name']} "
                    f"| {sign}{m['delta']:.0%} "
                    f"| {m['from_val']:.0%} | {m['to_val']:.0%} |"
                )
            lines.append("")

        # New risk flags
        if self.new_risk_flags:
            lines.append("### 新增风险标记")
            lines.append("| 日期 | 股票 | 风险 |")
            lines.append("|------|------|------|")
            for rf in self.new_risk_flags:
                lines.append(
                    f"| {rf['date']} | {rf['ticker_name']} "
                    f"| {', '.join(rf['flags'])} |"
                )
            lines.append("")

        # Unstable tickers warning
        if self.unstable_tickers:
            lines.append("### 信号不稳定预警")
            lines.append("")
            lines.append(
                "以下股票在观察期内信号频繁翻转（>=3次），"
                "跟随操作风险较高："
            )
            lines.append("")
            lines.append("| 股票 | 翻转次数 | 观察天数 | 翻转率 |")
            lines.append("|------|---------|---------|--------|")
            for ut in self.unstable_tickers:
                lines.append(
                    f"| {ut['ticker_name']} | {ut['flip_count']} "
                    f"| {ut['total_days']} | {ut['flip_rate']}% |"
                )
            lines.append("")

        # ── Per-ticker detail ──
        lines.append("## 个股详情")
        lines.append("")

        for ticker in self.tickers:
            snaps = self.snapshots.get(ticker, [])
            if not snaps:
                continue
            name = snaps[0].ticker_name or ticker
            lines.append(f"### {ticker} {name}")
            lines.append("")

            # Score table
            lines.append(
                "| 日期 | 信号 | 置信度 | 技术 | 基本面 | 消息 | 情绪 | 风险 |"
            )
            lines.append(
                "|------|------|--------|------|--------|------|------|------|"
            )
            for s in snaps:
                conf = f"{s.confidence:.0%}" if s.confidence >= 0 else "--"
                mk = _score_str(s.market_score)
                fu = _score_str(s.fundamental_score)
                nw = _score_str(s.news_score)
                se = _score_str(s.sentiment_score)
                rs = f"{s.risk_score}/10" if s.risk_score >= 0 else "--"
                lines.append(
                    f"| {s.trade_date[5:]} | {s.action} | {conf} "
                    f"| {mk} | {fu} | {nw} | {se} | {rs} |"
                )
            lines.append("")

            # Drifts
            ticker_drifts = self.drifts.get(ticker, [])
            for d in ticker_drifts:
                if d.drift_magnitude == "stable":
                    continue
                tag = "重大" if d.drift_magnitude == "major" else "变动"
                arrow = _direction_arrow(d.drift_direction)
                lines.append(f"**{d.date_prev} -> {d.date_curr} ({tag}) {arrow}**:")

                if d.action_changed:
                    lines.append(
                        f"- 信号: {d.action_prev} -> {d.action_curr}"
                    )
                if abs(d.confidence_delta) > 0.01:
                    sign = "+" if d.confidence_delta > 0 else ""
                    lines.append(f"- 置信度: {sign}{d.confidence_delta:.0%}")

                for label, delta in [
                    ("技术面", d.market_score_delta),
                    ("基本面", d.fundamental_score_delta),
                    ("消息面", d.news_score_delta),
                    ("情绪面", d.sentiment_score_delta),
                ]:
                    if delta != 0:
                        sign = "+" if delta > 0 else ""
                        lines.append(f"- {label}评分: {sign}{delta}")

                for claim in d.bull_claims_added[:3]:
                    lines.append(f"- 新增多方论据: \"{claim[:80]}\"")
                for claim in d.bull_claims_dropped[:3]:
                    lines.append(f"- 移除多方论据: \"{claim[:80]}\"")
                for claim in d.bear_claims_added[:3]:
                    lines.append(f"- 新增空方论据: \"{claim[:80]}\"")
                for claim in d.bear_claims_dropped[:3]:
                    lines.append(f"- 移除空方论据: \"{claim[:80]}\"")
                if d.risk_flags_added:
                    lines.append(
                        f"- 新增风险: {', '.join(d.risk_flags_added)}"
                    )
                if d.risk_flags_removed:
                    lines.append(
                        f"- 消除风险: {', '.join(d.risk_flags_removed)}"
                    )
                lines.append("")

        return "\n".join(lines)


# ── Extraction ──────────────────────────────────────────────────────────


def extract_snapshot(trace: RunTrace) -> DailySnapshot:
    """Extract a DailySnapshot from a RunTrace."""
    snap = DailySnapshot(
        run_id=trace.run_id,
        ticker=_normalize_ticker(trace.ticker),
        ticker_name=trace.ticker_name,
        trade_date=trace.trade_date,
        action=trace.research_action,
        confidence=trace.final_confidence,
        was_vetoed=trace.was_vetoed,
        market_regime=trace.market_context.get("regime", ""),
    )

    for nt in trace.node_traces:
        sd = nt.structured_data or {}

        # Pillar scores from analysts
        if nt.node_name in _PILLAR_MAP:
            score = sd.get("pillar_score")
            if score is not None:
                setattr(snap, _PILLAR_MAP[nt.node_name], int(score))

        # Bull researcher
        elif nt.node_name == "Bull Researcher":
            snap.bull_thesis = sd.get("thesis", "")
            snap.bull_overall_confidence = float(
                sd.get("overall_confidence", 0.0)
            )
            for c in sd.get("supporting_claims", []):
                snap.bull_claims.append({
                    "text": str(c.get("text", ""))[:200],
                    "confidence": float(c.get("confidence", 0.5)),
                    "dimension": c.get("dimension", ""),
                })

        # Bear researcher
        elif nt.node_name == "Bear Researcher":
            snap.bear_thesis = sd.get("thesis", "")
            snap.bear_overall_confidence = float(
                sd.get("overall_confidence", 0.0)
            )
            for c in sd.get("supporting_claims", []):
                snap.bear_claims.append({
                    "text": str(c.get("text", ""))[:200],
                    "confidence": float(c.get("confidence", 0.5)),
                    "dimension": c.get("dimension", ""),
                })

        # Scenario agent
        elif nt.node_name == "Scenario Agent":
            snap.base_prob = _safe_float(sd.get("base_prob", 0.0))
            snap.bull_prob = _safe_float(sd.get("bull_prob", 0.0))
            snap.bear_prob = _safe_float(sd.get("bear_prob", 0.0))

        # Research Manager (PM)
        elif nt.node_name == "Research Manager":
            snap.pm_conclusion = sd.get("conclusion", "")
            snap.thesis_effect = nt.thesis_effect

        # Risk Judge
        elif nt.node_name == "Risk Judge":
            if nt.risk_score is not None:
                snap.risk_score = int(nt.risk_score)
            snap.risk_cleared = bool(nt.risk_cleared)
            snap.risk_flags = list(nt.risk_flag_categories or [])

        # ResearchOutput — trade plan prices
        elif nt.node_name == "ResearchOutput":
            tc = sd.get("tradecard", {})
            if tc:
                p = tc.get("pillars", {})
                if p:
                    # Fill pillar scores from tradecard if analysts didn't set them
                    if snap.market_score < 0:
                        snap.market_score = _safe_int(p.get("market_score", -1))
                    if snap.fundamental_score < 0:
                        snap.fundamental_score = _safe_int(
                            p.get("fundamental_score", -1)
                        )
                    if snap.news_score < 0:
                        snap.news_score = _safe_int(
                            p.get("news_score", p.get("macro_score", -1))
                        )
                    if snap.sentiment_score < 0:
                        snap.sentiment_score = _safe_int(
                            p.get("sentiment_score", -1)
                        )

            tplan = sd.get("trade_plan", {})
            if tplan:
                sl_obj = tplan.get("stop_loss", {})
                if isinstance(sl_obj, dict):
                    snap.stop_loss = float(sl_obj.get("price", 0) or 0)
                elif isinstance(sl_obj, (int, float)):
                    snap.stop_loss = float(sl_obj)

                tp_list = tplan.get("take_profit", [])
                if tp_list and isinstance(tp_list, list):
                    first = tp_list[0]
                    if isinstance(first, dict):
                        zone = first.get("price_zone", [])
                        if zone and len(zone) >= 2:
                            snap.take_profit = (
                                float(zone[0]) + float(zone[1])
                            ) / 2
                        elif zone:
                            snap.take_profit = float(zone[0])

    return snap


# ── Drift Computation ───────────────────────────────────────────────────


def compute_drift(prev: DailySnapshot, curr: DailySnapshot) -> OpinionDrift:
    """Compute day-over-day opinion change between two snapshots."""
    d = OpinionDrift(
        ticker=curr.ticker,
        ticker_name=curr.ticker_name,
        date_prev=prev.trade_date,
        date_curr=curr.trade_date,
        action_prev=prev.action,
        action_curr=curr.action,
        action_changed=prev.action != curr.action,
        confidence_prev=prev.confidence,
        confidence_curr=curr.confidence,
        thesis_effect_curr=curr.thesis_effect,
        regime_prev=prev.market_regime,
        regime_curr=curr.market_regime,
        regime_changed=prev.market_regime != curr.market_regime,
    )

    # Confidence delta (guard sentinels)
    if prev.confidence >= 0 and curr.confidence >= 0:
        d.confidence_delta = curr.confidence - prev.confidence

    # Pillar score deltas
    d.market_score_delta = _score_delta(prev.market_score, curr.market_score)
    d.fundamental_score_delta = _score_delta(
        prev.fundamental_score, curr.fundamental_score
    )
    d.news_score_delta = _score_delta(prev.news_score, curr.news_score)
    d.sentiment_score_delta = _score_delta(
        prev.sentiment_score, curr.sentiment_score
    )

    # Risk drift
    d.risk_score_prev = prev.risk_score
    d.risk_score_curr = curr.risk_score
    d.risk_score_delta = _score_delta(prev.risk_score, curr.risk_score)
    prev_flags = set(prev.risk_flags)
    curr_flags = set(curr.risk_flags)
    d.risk_flags_added = sorted(curr_flags - prev_flags)
    d.risk_flags_removed = sorted(prev_flags - curr_flags)

    # Bull/bear argument diff
    d.bull_claims_added, d.bull_claims_dropped = _diff_claims(
        prev.bull_claims, curr.bull_claims
    )
    d.bear_claims_added, d.bear_claims_dropped = _diff_claims(
        prev.bear_claims, curr.bear_claims
    )
    d.bull_confidence_delta = curr.bull_overall_confidence - prev.bull_overall_confidence
    d.bear_confidence_delta = curr.bear_overall_confidence - prev.bear_overall_confidence

    # Scenario prob deltas
    d.base_prob_delta = curr.base_prob - prev.base_prob
    d.bull_prob_delta = curr.bull_prob - prev.bull_prob
    d.bear_prob_delta = curr.bear_prob - prev.bear_prob

    # Assess magnitude
    d.drift_magnitude = _assess_magnitude(d)
    d.drift_direction = _assess_direction(d)

    return d


# ── Orchestration ───────────────────────────────────────────────────────


def build_watchlist_report(
    tickers: List[str],
    date_from: str = "",
    date_to: str = "",
    storage_dir: str = "data/replays",
) -> WatchlistReport:
    """Build a cross-ticker opinion tracking report.

    Args:
        tickers: List of ticker strings (e.g. ["601985.SS", "000710.SZ"])
        date_from: Start date (inclusive), "" for all
        date_to: End date (inclusive), "" for all
        storage_dir: Path to ReplayStore directory
    """
    store = ReplayStore(storage_dir=storage_dir)
    report = WatchlistReport(
        date_from=date_from,
        date_to=date_to,
        generated_at=datetime.now().isoformat(),
        tickers=list(tickers),
    )

    for ticker in tickers:
        # Normalize for manifest lookup
        bare = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")

        # Load all runs for this ticker — search bare AND suffixed forms
        # then merge by run_id (manifest may have mixed formats)
        seen_ids: set = set()
        manifest_entries: list = []
        for variant in {bare, ticker}:
            for e in store.list_runs(ticker=variant, limit=500):
                rid = e.get("run_id", "")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    manifest_entries.append(e)

        # Filter by date range and dedup (keep latest per date)
        by_date: Dict[str, str] = {}  # trade_date -> run_id (latest wins)
        for entry in reversed(manifest_entries):  # oldest first
            td = entry.get("trade_date", "")
            rid = entry.get("run_id", "")
            if not td or not rid:
                continue
            if date_from and td < date_from:
                continue
            if date_to and td > date_to:
                continue
            by_date[td] = rid

        # Extract snapshots
        snapshots: List[DailySnapshot] = []
        for td in sorted(by_date.keys()):
            trace = store.load(by_date[td])
            if trace is None:
                continue
            snap = extract_snapshot(trace)
            snapshots.append(snap)

        report.snapshots[ticker] = snapshots

        # Compute drifts
        drift_list: List[OpinionDrift] = []
        for i in range(1, len(snapshots)):
            drift = compute_drift(snapshots[i - 1], snapshots[i])
            drift_list.append(drift)
        # Post-process: stale signal detection
        _STALE_THRESHOLD = 3
        for i, dr in enumerate(drift_list):
            same_action = not dr.action_changed
            small_conf = abs(dr.confidence_delta) < 2.0  # <2% confidence change
            same_pillars = (dr.market_score_delta == 0
                            and dr.fundamental_score_delta == 0
                            and dr.news_score_delta == 0
                            and dr.sentiment_score_delta == 0)
            if same_action and small_conf and same_pillars:
                prev_streak = drift_list[i - 1].stale_streak if i > 0 else 0
                dr.stale_streak = prev_streak + 1
            else:
                dr.stale_streak = 0
            dr.is_stale = dr.stale_streak >= _STALE_THRESHOLD

        report.drifts[ticker] = drift_list

        # Current state
        if snapshots:
            report.current_state[ticker] = snapshots[-1]

        # Collect highlights
        for dr in drift_list:
            if dr.action_changed:
                report.action_flips.append({
                    "ticker": ticker,
                    "ticker_name": dr.ticker_name,
                    "date": dr.date_curr,
                    "from_action": dr.action_prev,
                    "to_action": dr.action_curr,
                })
            if abs(dr.confidence_delta) >= 0.05:
                report.biggest_confidence_moves.append({
                    "ticker": ticker,
                    "ticker_name": dr.ticker_name,
                    "date": dr.date_curr,
                    "delta": dr.confidence_delta,
                    "from_val": dr.confidence_prev,
                    "to_val": dr.confidence_curr,
                })
            if dr.risk_flags_added:
                report.new_risk_flags.append({
                    "ticker": ticker,
                    "ticker_name": dr.ticker_name,
                    "date": dr.date_curr,
                    "flags": dr.risk_flags_added,
                })
            if dr.is_stale:
                report.stale_signals.append({
                    "ticker": ticker,
                    "ticker_name": dr.ticker_name,
                    "date": dr.date_curr,
                    "stale_streak": dr.stale_streak,
                    "action": dr.action_curr,
                })

    # Sort highlights
    report.action_flips.sort(key=lambda x: x["date"], reverse=True)
    report.biggest_confidence_moves.sort(
        key=lambda x: abs(x["delta"]), reverse=True
    )
    report.new_risk_flags.sort(key=lambda x: x["date"], reverse=True)

    # Unstable ticker detection: >=3 flips in the date range
    _FLIP_THRESHOLD = 3
    flip_counts: Dict[str, int] = {}
    for flip in report.action_flips:
        t = flip["ticker"]
        flip_counts[t] = flip_counts.get(t, 0) + 1
    for t, count in flip_counts.items():
        n_snapshots = len(report.snapshots.get(t, []))
        if count >= _FLIP_THRESHOLD:
            name = report.current_state.get(t)
            ticker_name = name.ticker_name if name else t
            report.unstable_tickers.append({
                "ticker": t,
                "ticker_name": ticker_name,
                "flip_count": count,
                "total_days": n_snapshots,
                "flip_rate": round(count / max(n_snapshots - 1, 1) * 100, 1),
            })
    report.unstable_tickers.sort(key=lambda x: x["flip_count"], reverse=True)

    return report


# ── Convenience Functions ───────────────────────────────────────────────


def track_ticker(
    ticker: str,
    storage_dir: str = "data/replays",
    limit: int = 30,
) -> Tuple[List[DailySnapshot], List[OpinionDrift]]:
    """Quick single-ticker tracking. Returns (snapshots, drifts)."""
    report = build_watchlist_report(
        tickers=[ticker],
        storage_dir=storage_dir,
    )
    snapshots = report.snapshots.get(ticker, [])
    if limit > 0:
        snapshots = snapshots[-limit:]
    drifts = report.drifts.get(ticker, [])
    if limit > 0:
        drifts = drifts[-(limit - 1):] if limit > 1 else []
    return snapshots, drifts


def latest_drift(
    ticker: str,
    storage_dir: str = "data/replays",
) -> Optional[OpinionDrift]:
    """Get the most recent day-over-day drift for a ticker."""
    _, drifts = track_ticker(ticker, storage_dir=storage_dir, limit=2)
    return drifts[-1] if drifts else None


# ── Internal Helpers ────────────────────────────────────────────────────


def _normalize_ticker(ticker: str) -> str:
    """Ensure ticker has exchange suffix.

    Delegates to the canonical implementation in signal_ledger.
    """
    from subagent_pipeline.signal_ledger import normalize_ticker
    return normalize_ticker(ticker)


def _safe_float(val, default: float = 0.0) -> float:
    """Convert to float, stripping '%' suffix if present."""
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip().rstrip("%")
        v = float(s)
        # If original had '%', treat as fraction
        if str(val).strip().endswith("%"):
            v /= 100.0
        return v
    except (ValueError, TypeError):
        return default


def _safe_int(val, default: int = -1) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _score_delta(prev: int, curr: int) -> int:
    """Compute score delta, treating -1 sentinels as skip."""
    if prev < 0 or curr < 0:
        return 0
    return curr - prev


def _score_str(val: int) -> str:
    return str(val) if val >= 0 else "--"


def _direction_arrow(direction: str) -> str:
    if direction == "bullish_shift":
        return "^"
    elif direction == "bearish_shift":
        return "v"
    return "="


def _claims_match(a_text: str, b_text: str) -> bool:
    """Fuzzy match two claim texts (same argument, possibly rephrased)."""
    a = a_text.strip()
    b = b_text.strip()
    if not a or not b:
        return False
    if a == b:
        return True
    # Substring containment (shorter in longer)
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if shorter[:60] in longer:
        return True
    # Character overlap on first 40 chars
    a40 = set(a[:40])
    b40 = set(b[:40])
    if a40 and b40:
        overlap = len(a40 & b40) / max(len(a40), len(b40))
        if overlap > 0.6:
            return True
    return False


def _diff_claims(
    prev_claims: List[Dict], curr_claims: List[Dict]
) -> Tuple[List[str], List[str]]:
    """Diff claim lists, returning (added, dropped) texts."""
    matched_prev: set = set()
    matched_curr: set = set()

    for i, p in enumerate(prev_claims):
        for j, c in enumerate(curr_claims):
            if j in matched_curr:
                continue
            if _claims_match(p.get("text", ""), c.get("text", "")):
                matched_prev.add(i)
                matched_curr.add(j)
                break

    added = [
        curr_claims[j]["text"]
        for j in range(len(curr_claims))
        if j not in matched_curr
    ]
    dropped = [
        prev_claims[i]["text"]
        for i in range(len(prev_claims))
        if i not in matched_prev
    ]
    return added, dropped


def _assess_magnitude(d: OpinionDrift) -> str:
    """Classify drift as major / minor / stable."""
    if d.action_changed:
        return "major"
    if abs(d.confidence_delta) >= 0.15:
        return "major"
    if any(
        abs(v) >= 2
        for v in (
            d.market_score_delta,
            d.fundamental_score_delta,
            d.news_score_delta,
            d.sentiment_score_delta,
        )
    ):
        return "major"

    if abs(d.confidence_delta) >= 0.05:
        return "minor"
    if any(
        abs(v) >= 1
        for v in (
            d.market_score_delta,
            d.fundamental_score_delta,
            d.news_score_delta,
            d.sentiment_score_delta,
        )
    ):
        return "minor"
    if d.risk_flags_added:
        return "minor"
    if abs(d.risk_score_delta) >= 2:
        return "minor"

    return "stable"


def _assess_direction(d: OpinionDrift) -> str:
    """Classify drift direction."""
    prev_rank = _ACTION_RANK.get(d.action_prev, 2)
    curr_rank = _ACTION_RANK.get(d.action_curr, 2)
    if curr_rank > prev_rank:
        return "bullish_shift"
    if curr_rank < prev_rank:
        return "bearish_shift"
    if d.confidence_delta > 0.05:
        return "bullish_shift"
    if d.confidence_delta < -0.05:
        return "bearish_shift"
    return "unchanged"
