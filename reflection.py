"""Reflection module — post-hoc analysis of prediction accuracy.

Compares pipeline predictions against actual forward price action,
extracts structured lessons, and persists them for future runs.

This module does NOT call LLMs. It produces structured reflection data
that can be:
1. Fed to an LLM agent via Claude Code's Agent tool for deeper analysis
2. Stored as JSON for dashboard display
3. Used by opinion_tracker to adjust confidence calibration

Usage:
    from subagent_pipeline.reflection import (
        reflect_on_backtest, ReflectionRecord, ReflectionReport,
    )

    # Single signal reflection
    record = reflect_on_backtest(backtest_result, run_trace)

    # Batch reflection from a BacktestReport
    report = build_reflection_report(backtest_report, storage_dir="data/replays")
    report.save_json("data/reports")
    print(report.to_markdown())
"""

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────────


@dataclass
class ReflectionRecord:
    """Structured reflection on a single prediction vs outcome."""

    run_id: str = ""
    ticker: str = ""
    ticker_name: str = ""
    trade_date: str = ""

    # What we predicted
    predicted_action: str = ""          # BUY/HOLD/SELL/VETO
    predicted_confidence: float = -1.0
    predicted_direction: str = ""       # up/down/flat/abstain

    # What actually happened
    actual_return_pct: float = 0.0
    actual_direction: str = ""          # up/down/flat
    max_drawdown_pct: float = 0.0
    max_gain_pct: float = 0.0
    eval_window_days: int = 10

    # Outcome assessment
    direction_correct: Optional[bool] = None
    outcome: str = ""                   # win/loss/neutral
    hit_stop_loss: bool = False
    hit_take_profit: bool = False

    # Pillar scores at time of prediction
    market_score: int = -1
    fundamental_score: int = -1
    news_score: int = -1
    sentiment_score: int = -1

    # Key risk flags at time of prediction
    risk_flags: List[str] = field(default_factory=list)

    # Extracted lessons (structured, no LLM needed)
    error_type: str = ""                # direction_wrong, overconfident, underconfident, timing, risk_miss
    lesson: str = ""                    # Human-readable lesson
    pillar_blame: str = ""              # Which pillar was most wrong (if direction wrong)
    confidence_calibration: str = ""    # overconfident / underconfident / calibrated

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: Dict) -> "ReflectionRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ReflectionReport:
    """Aggregated reflection across multiple predictions."""

    trade_date: str = ""
    generated_at: str = ""
    records: List[ReflectionRecord] = field(default_factory=list)

    # Aggregate stats
    total_signals: int = 0
    direction_accuracy_pct: float = 0.0
    avg_confidence_when_correct: float = 0.0
    avg_confidence_when_wrong: float = 0.0

    # Error breakdown
    error_breakdown: Dict[str, int] = field(default_factory=dict)

    # Calibration
    overconfident_count: int = 0
    underconfident_count: int = 0
    calibrated_count: int = 0

    # Pillar blame distribution
    pillar_blame_counts: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["records"] = [r.to_dict() for r in self.records]
        return d

    def save_json(self, output_dir: str = "data/reports") -> Path:
        """Persist to JSON file."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        date_slug = self.trade_date.replace("-", "") or "unknown"
        path = out / f"reflection-{date_slug}.json"
        content = json.dumps(self.to_dict(), ensure_ascii=False, indent=2, allow_nan=False)
        fd, tmp = tempfile.mkstemp(dir=str(out), suffix=".tmp", prefix=".refl-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, str(path))
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return path

    def to_markdown(self) -> str:
        """Human-readable reflection summary."""
        lines = [
            f"# 反思报告 {self.trade_date}",
            "",
            f"信号总数: {self.total_signals} | "
            f"方向准确率: {self.direction_accuracy_pct:.0f}%",
            "",
        ]

        if self.avg_confidence_when_correct > 0 or self.avg_confidence_when_wrong > 0:
            lines.append(
                f"正确时平均置信度: {self.avg_confidence_when_correct:.0%} | "
                f"错误时平均置信度: {self.avg_confidence_when_wrong:.0%}"
            )
            lines.append("")

        if self.error_breakdown:
            lines.append("## 错误类型分布")
            for err_type, count in sorted(self.error_breakdown.items(),
                                          key=lambda x: -x[1]):
                lines.append(f"- {err_type}: {count}")
            lines.append("")

        if self.pillar_blame_counts:
            lines.append("## 支柱归因（方向错误时哪个支柱最偏离）")
            for pillar, count in sorted(self.pillar_blame_counts.items(),
                                        key=lambda x: -x[1]):
                lines.append(f"- {pillar}: {count}")
            lines.append("")

        # Top lessons
        wrong = [r for r in self.records if r.direction_correct is False]
        if wrong:
            lines.append("## 关键教训")
            for r in wrong[:5]:
                lines.append(
                    f"- **{r.ticker} {r.ticker_name}** ({r.trade_date}): "
                    f"预测 {r.predicted_action} {r.predicted_confidence:.0%} → "
                    f"实际 {r.actual_return_pct:+.1f}% | {r.lesson}"
                )
            lines.append("")

        lines.append("---")
        lines.append("*自动生成，基于回测数据的结构化反思*")
        return "\n".join(lines)


# ── Core Logic ───────────────────────────────────────────────────────────


def reflect_on_backtest(bt_result, trace=None) -> ReflectionRecord:
    """Generate a structured reflection for a single backtest result.

    Args:
        bt_result: BacktestResult dataclass from backtest module
        trace: Optional RunTrace for richer context (pillar scores, risk flags)

    Returns:
        ReflectionRecord with error_type, lesson, pillar_blame, calibration
    """
    rec = ReflectionRecord(
        run_id=bt_result.run_id,
        ticker=bt_result.ticker,
        ticker_name=getattr(bt_result, "ticker_name", ""),
        trade_date=bt_result.trade_date,
        predicted_action=bt_result.action,
        predicted_confidence=bt_result.confidence,
        predicted_direction=bt_result.direction_expected,
        actual_return_pct=bt_result.stock_return_pct,
        actual_direction=_infer_direction(bt_result.stock_return_pct),
        max_drawdown_pct=bt_result.max_drawdown_pct,
        max_gain_pct=bt_result.max_gain_pct,
        eval_window_days=bt_result.eval_window_days,
        direction_correct=bt_result.direction_correct,
        outcome=bt_result.outcome,
        hit_stop_loss=bt_result.hit_stop_loss,
        hit_take_profit=bt_result.hit_take_profit,
    )

    # Enrich from RunTrace
    if trace is not None:
        _enrich_from_trace(rec, trace)

    # Classify error
    _classify_error(rec)

    # Generate lesson
    _generate_lesson(rec)

    return rec


def build_reflection_report(
    backtest_report,
    storage_dir: str = "data/replays",
) -> ReflectionReport:
    """Build a full reflection report from a BacktestReport.

    Args:
        backtest_report: BacktestReport from backtest module
        storage_dir: Where RunTrace JSONs are stored
    """
    from .replay_store import ReplayStore

    store = ReplayStore(storage_dir=storage_dir)
    report = ReflectionReport(
        generated_at=datetime.now().isoformat(),
    )

    records = []
    dates = set()
    for bt in backtest_report.results:
        if bt.eval_status != "completed":
            continue
        trace = store.load(bt.run_id)
        rec = reflect_on_backtest(bt, trace)
        records.append(rec)
        dates.add(bt.trade_date)

    report.records = records
    report.total_signals = len(records)
    report.trade_date = min(dates) + "~" + max(dates) if dates else ""

    # Aggregate stats
    correct = [r for r in records if r.direction_correct is True]
    wrong = [r for r in records if r.direction_correct is False]
    evaluated = correct + wrong

    if evaluated:
        report.direction_accuracy_pct = len(correct) / len(evaluated) * 100

    if correct:
        report.avg_confidence_when_correct = (
            sum(r.predicted_confidence for r in correct) / len(correct)
        )
    if wrong:
        report.avg_confidence_when_wrong = (
            sum(r.predicted_confidence for r in wrong) / len(wrong)
        )

    # Error breakdown
    for r in records:
        if r.error_type:
            report.error_breakdown[r.error_type] = (
                report.error_breakdown.get(r.error_type, 0) + 1
            )

    # Calibration
    for r in records:
        if r.confidence_calibration == "overconfident":
            report.overconfident_count += 1
        elif r.confidence_calibration == "underconfident":
            report.underconfident_count += 1
        elif r.confidence_calibration == "calibrated":
            report.calibrated_count += 1

    # Pillar blame
    for r in records:
        if r.pillar_blame:
            report.pillar_blame_counts[r.pillar_blame] = (
                report.pillar_blame_counts.get(r.pillar_blame, 0) + 1
            )

    return report


# ── Internal Helpers ─────────────────────────────────────────────────────


def _infer_direction(return_pct: float, band: float = 2.0) -> str:
    """Infer actual direction from return percentage."""
    if return_pct > band:
        return "up"
    elif return_pct < -band:
        return "down"
    return "flat"


def _enrich_from_trace(rec: ReflectionRecord, trace) -> None:
    """Extract pillar scores and risk flags from RunTrace."""
    for nt in trace.node_traces:
        sd = nt.structured_data or {}

        # Pillar scores from analysts
        if "pillar_score" in sd:
            if nt.node_name == "Market Analyst":
                rec.market_score = sd["pillar_score"]
            elif nt.node_name == "Fundamental Analyst":
                rec.fundamental_score = sd["pillar_score"]
            elif nt.node_name == "News Analyst":
                rec.news_score = sd["pillar_score"]
            elif nt.node_name == "Social Analyst":
                rec.sentiment_score = sd["pillar_score"]

        # Risk flags from Risk Judge
        if nt.node_name == "Risk Judge" and nt.risk_flag_categories:
            rec.risk_flags = list(nt.risk_flag_categories)


def _classify_error(rec: ReflectionRecord) -> None:
    """Classify the error type based on prediction vs outcome."""
    if rec.direction_correct is None:
        # HOLD uses band-test semantics — direction_correct is always None
        # but outcome='hold_breach' is a real error (price broke out of stop/TP band).
        if rec.outcome == "hold_breach":
            rec.error_type = "hold_breach"
        else:
            rec.error_type = ""
        return

    if rec.direction_correct:
        # Correct direction — check calibration
        if rec.predicted_confidence >= 0.7 and abs(rec.actual_return_pct) < 2:
            rec.error_type = "overconfident"
        else:
            rec.error_type = ""  # no error
        return

    # Wrong direction
    if rec.predicted_action == "BUY" and rec.actual_return_pct < -5:
        rec.error_type = "direction_wrong_severe"
    elif rec.predicted_action == "SELL" and rec.actual_return_pct > 5:
        rec.error_type = "direction_wrong_severe"
    elif rec.predicted_confidence >= 0.7:
        rec.error_type = "overconfident"
    else:
        rec.error_type = "direction_wrong"

    # Pillar blame — find the most optimistic pillar when direction was wrong
    if rec.predicted_action == "BUY":
        # We predicted buy but stock went down — which pillar was most bullish?
        scores = {
            "market": rec.market_score,
            "fundamental": rec.fundamental_score,
            "news": rec.news_score,
            "sentiment": rec.sentiment_score,
        }
        valid = {k: v for k, v in scores.items() if v >= 0}
        if valid:
            rec.pillar_blame = max(valid, key=valid.get)
    elif rec.predicted_action == "SELL":
        # We predicted sell but stock went up — which pillar was most bearish?
        scores = {
            "market": rec.market_score,
            "fundamental": rec.fundamental_score,
            "news": rec.news_score,
            "sentiment": rec.sentiment_score,
        }
        valid = {k: v for k, v in scores.items() if v >= 0}
        if valid:
            rec.pillar_blame = min(valid, key=valid.get)


def _generate_lesson(rec: ReflectionRecord) -> None:
    """Generate a human-readable lesson string."""
    # Calibration assessment
    if rec.direction_correct is True:
        if rec.predicted_confidence >= 0.7 and abs(rec.actual_return_pct) > 5:
            rec.confidence_calibration = "calibrated"
            rec.lesson = "高置信度预测得到验证"
        elif rec.predicted_confidence >= 0.7 and abs(rec.actual_return_pct) < 2:
            rec.confidence_calibration = "overconfident"
            rec.lesson = "方向正确但幅度远低于预期，置信度偏高"
        elif rec.predicted_confidence < 0.5 and abs(rec.actual_return_pct) > 5:
            rec.confidence_calibration = "underconfident"
            rec.lesson = "低置信度但实际涨幅显著，可能低估了某个信号"
        else:
            rec.confidence_calibration = "calibrated"
            rec.lesson = "预测方向正确，置信度匹配"
        return

    if rec.direction_correct is False:
        rec.confidence_calibration = "overconfident" if rec.predicted_confidence >= 0.6 else "calibrated"

        if rec.hit_stop_loss:
            rec.lesson = f"触发止损，实际回撤 {rec.max_drawdown_pct:.1f}%"
            if rec.pillar_blame:
                rec.lesson += f"，{rec.pillar_blame} 评分过高需校准"
        elif rec.error_type == "direction_wrong_severe":
            rec.lesson = (
                f"严重方向错误：预测 {rec.predicted_action} "
                f"但实际 {rec.actual_return_pct:+.1f}%"
            )
            if rec.risk_flags:
                rec.lesson += f"，已有风险标记 [{', '.join(rec.risk_flags[:2])}] 但未充分重视"
            elif rec.pillar_blame:
                rec.lesson += f"，{rec.pillar_blame} 支柱判断有误"
        else:
            rec.lesson = f"方向错误：预测 {rec.predicted_action} → 实际 {rec.actual_return_pct:+.1f}%"
            if rec.pillar_blame:
                rec.lesson += f"，建议复查 {rec.pillar_blame} 数据"

    # No evaluation — but HOLD with hold_breach outcome carries a band-test lesson
    if rec.direction_correct is None:
        rec.confidence_calibration = ""
        if rec.outcome == "hold_breach":
            # HOLD predicted price would stay within band, but it broke out
            direction = "上破" if rec.actual_return_pct > 0 else "下破"
            rec.lesson = f"HOLD 带位测试失败：价格{direction}，实际 {rec.actual_return_pct:+.1f}%"
        elif rec.outcome == "hold_success":
            rec.lesson = "HOLD 带位成立：价格留在 stop/TP 区间内"
        else:
            rec.lesson = ""


def generate_reflection_prompt(report: ReflectionReport) -> str:
    """Generate a prompt for LLM-based deep reflection via Agent tool.

    This is NOT called automatically — it returns a string that the
    orchestrator can feed to an Agent for deeper analysis.
    """
    md = report.to_markdown()
    return f"""你是投研系统的复盘分析师。以下是近期预测 vs 实际结果的结构化反思报告：

{md}

请基于以上数据完成以下分析：

1. **系统性偏差识别**：是否存在某个方向（看多/看空）的系统性偏差？哪个支柱评分最不可靠？

2. **置信度校准建议**：当前置信度是否偏高或偏低？建议如何调整阈值？

3. **风险标记有效性**：已识别的风险标记（{', '.join(set(f for r in report.records for f in r.risk_flags))}）是否有效预警了亏损？

4. **前3条可执行改进**：具体到"当出现X信号时，应该Y"的格式。

5. **本轮最佳/最差预测**：各选1个，说明原因。

用中文回复，结构清晰。"""


# ── Per-ticker Feedback Block Construction (P1) ────────────────────────────

# Canonical Chinese labels for each pillar — used in per-analyst block headers.
_PILLAR_LABELS_ZH = {
    "market": "技术面",
    "fundamentals": "基本面",
    "news": "消息面",
    "sentiment": "情绪面",
}

# Base-rate prior text — same across all pillars; intentionally repeated so that
# even zero-history tickers receive the corrective prior. Targets the systematic
# overconfidence bias observed in the reflection aggregate (43/0 asymmetry).
_BASE_RATE_PRIOR = (
    "**基准先验**: 当证据不足时，倾向中性 (pillar_score=2)；"
    "不要在缺少具体触发条件时给出 ≥3 或 ≤1 的极端评分。"
    "历史数据显示本系统存在结构性自我夸大倾向 (overconfident=43 / underconfident=0)。"
)

_PM_BASE_RATE_PRIOR = (
    "**基准先验**: HOLD 是默认选项；只有在有明确触发条件时才偏离。"
    "此先验旨在抵消 LLM 的结构性自我夸大倾向（历史 43 overconfident / 0 underconfident）。"
)


def _pillar_dir_from_score(score: Any) -> str:
    """Local copy of monitoring._pillar_direction to keep reflection import-free."""
    try:
        s = int(score)
    except (TypeError, ValueError):
        return "neutral"
    if s < 0:
        return "neutral"
    if s >= 3:
        return "up"
    if s <= 1:
        return "down"
    return "neutral"


def _infer_dir_from_return(return_pct: float, band_pct: float = 2.0) -> str:
    if return_pct is None:
        return "neutral"
    if return_pct > band_pct:
        return "up"
    if return_pct < -band_pct:
        return "down"
    return "neutral"


def _load_recent_reflection_records_for_ticker(
    ticker: str, reports_dir: str, limit: int = 2,
) -> List[Dict[str, Any]]:
    """Scan reflection-*.json files in reports_dir, return latest `limit` records
    for `ticker`, sorted by trade_date descending."""
    out_dir = Path(reports_dir)
    if not out_dir.exists():
        return []
    records: List[Dict[str, Any]] = []
    for fp in out_dir.glob("reflection-*.json"):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for rec in data.get("records", []):
            if rec.get("ticker") == ticker:
                records.append(rec)
    records.sort(key=lambda r: r.get("trade_date", ""), reverse=True)
    return records[:limit]


def _pillar_accuracy_from_backtest(
    bt_report: Any,
    signal_records: List[Any],
    pillar_score_key: str,
) -> Dict[str, int]:
    """Compute per-pillar directional accuracy counts from backtest + signals.

    Returns dict with keys: n, correct, overconfident.
    A pillar "prediction" is considered valid when pillar_score is non-neutral
    (≤1 or ≥3) AND market actually moved (actual_direction != neutral).
    """
    # Index signals by (ticker, trade_date)
    sig_index = {(s.ticker, s.trade_date): s for s in signal_records}

    n = correct = overconfident = 0
    for bt in bt_report.results:
        if bt.eval_status != "completed":
            continue
        sig = sig_index.get((bt.ticker, bt.trade_date))
        if sig is None:
            continue
        score = getattr(sig, pillar_score_key, -1)
        pdir = _pillar_dir_from_score(score)
        if pdir == "neutral":
            continue
        actual = _infer_dir_from_return(bt.stock_return_pct)
        if actual == "neutral":
            continue
        n += 1
        if pdir == actual:
            correct += 1
        # overconfident: extreme score (0/4) but wrong direction
        if pdir != actual and int(score) in (0, 4):
            overconfident += 1
    return {"n": n, "correct": correct, "overconfident": overconfident}


def _format_pillar_block(
    ticker: str,
    pillar_key: str,     # "market" | "fundamentals" | "news" | "sentiment"
    stats: Dict[str, int],
    recent_errors: List[str],
    days: int,
) -> str:
    """Render a per-pillar analyst feedback block. Never returns empty."""
    pillar_zh = _PILLAR_LABELS_ZH.get(pillar_key, pillar_key)
    lines = [f"## 历史反馈（{ticker} / {pillar_key}-{pillar_zh} / 近{days}天）"]
    n = stats.get("n", 0)
    if n == 0:
        lines.append(f"- 近{days}天该 pillar 无足量方向性信号可评估。")
    else:
        acc_pct = stats["correct"] / n * 100 if n else 0.0
        lines.append(
            f"- {pillar_key} pillar 方向准确率: {acc_pct:.0f}% "
            f"({stats['correct']}/{n} 次信号)"
        )
        if stats.get("overconfident"):
            lines.append(
                f"- 其中高分数（0/4）但方向错误: {stats['overconfident']} 次 "
                "（表明极端评分需更谨慎）"
            )
    if recent_errors:
        lines.append("- 该 pillar 最近失误模式：")
        for err in recent_errors:
            lines.append(f"  - {err}")
    lines.append("")
    lines.append(_BASE_RATE_PRIOR)
    return "\n".join(lines)


def _format_pm_block(
    ticker: str,
    total_n: int,
    total_correct: int,
    overconf: int,
    underconf: int,
    pillar_blame_counts: Dict[str, int],
    recent_lessons: List[Dict[str, Any]],
    days: int,
) -> str:
    """Render the aggregate PM (research_manager) feedback block. Never empty."""
    lines = [f"## 历史反馈（{ticker} 综合 / 近{days}天）"]
    if total_n == 0:
        lines.append(f"- 近{days}天无足量方向性信号（HOLD 已排除）。")
    else:
        acc = total_correct / total_n * 100
        lines.append(
            f"- 方向准确率: {acc:.0f}% ({total_correct}/{total_n} 次信号，HOLD 已排除)"
        )
        lines.append(
            f"- 置信度校准: overconfident={overconf} | underconfident={underconf}"
        )
        if pillar_blame_counts:
            parts = " / ".join(
                f"{k}={v}"
                for k, v in sorted(pillar_blame_counts.items(), key=lambda x: -x[1])
            )
            lines.append(f"- 跨 pillar 失误归因: {parts}")

    if recent_lessons:
        lines.append("")
        lines.append("**最近 2 条教训:**")
        for r in recent_lessons[:2]:
            lesson = r.get("lesson") or ""
            if lesson:
                lines.append(f"1. {r.get('trade_date','')}: {lesson}")
    lines.append("")
    lines.append(_PM_BASE_RATE_PRIOR)
    return "\n".join(lines)


def build_feedback_blocks(
    ticker: str,
    days: int = 30,
    ledger_path: str = "data/signals/signals.jsonl",
    storage_dir: str = "data/replays",
    reports_dir: str = "data/reports",
) -> Dict[str, str]:
    """Build pillar-filtered feedback blocks for prompt injection.

    Returns a dict with 5 keys: {"market", "fundamentals", "news", "sentiment", "pm"}.
    Each value is a non-empty markdown string.

    Each analyst block contains ONLY that pillar's statistics to prevent
    synchronization bias (the failure mode where all analysts read the same
    feedback and produce consensus-safe but independently-weak decisions).
    The PM block aggregates cross-pillar view and recent lessons for the
    final decision maker.

    Cold-start tickers always receive the base-rate prior — blocks are never empty.
    """
    from .signal_ledger import SignalLedger
    from .backtest import run_backtest_from_ledger, BacktestConfig

    # Cutoff: N days before today
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Normalize ticker for ledger lookup (accept bare 6-digit or suffixed)
    try:
        from .signal_ledger import normalize_ticker
        norm_ticker = normalize_ticker(ticker)
    except (ImportError, AttributeError):
        norm_ticker = ticker

    # Load signals + run cheap ledger backtest for this ticker
    signals: List[Any] = []
    bt_report = None
    try:
        ledger = SignalLedger(path=ledger_path)
        signals = ledger.read(ticker=norm_ticker, after=cutoff)
    except FileNotFoundError:
        signals = []
    except Exception as e:
        logger.warning("SignalLedger read failed: %s", e)
        signals = []

    if signals:
        try:
            bt_report = run_backtest_from_ledger(
                ledger_path=ledger_path,
                config=BacktestConfig(),
                ticker=norm_ticker,
                after=cutoff,
            )
        except Exception as e:
            logger.warning("run_backtest_from_ledger failed: %s", e)
            bt_report = None

    # Per-pillar stats + recent error extracts
    pillar_stats: Dict[str, Dict[str, int]] = {}
    pillar_recent_errors: Dict[str, List[str]] = {
        "market": [], "fundamentals": [], "news": [], "sentiment": [],
    }
    pillar_key_map = {
        "market": "market_score",
        "fundamentals": "fundamental_score",
        "news": "news_score",
        "sentiment": "sentiment_score",
    }

    if bt_report is not None:
        for pkey, sig_key in pillar_key_map.items():
            pillar_stats[pkey] = _pillar_accuracy_from_backtest(
                bt_report, signals, sig_key,
            )
    else:
        for pkey in pillar_key_map:
            pillar_stats[pkey] = {"n": 0, "correct": 0, "overconfident": 0}

    # Load recent lessons from reflection JSON files (for PM block + pillar_blame)
    recent_reflection_records = _load_recent_reflection_records_for_ticker(
        norm_ticker, reports_dir, limit=5,
    )
    # Populate per-pillar recent_errors: if a reflection record has pillar_blame=X,
    # surface its lesson to that pillar's block.
    for r in recent_reflection_records:
        blame = r.get("pillar_blame") or ""
        # Reflection uses "fundamental" singular; our keys use plural "fundamentals".
        blame_key = "fundamentals" if blame == "fundamental" else blame
        lesson = r.get("lesson") or ""
        if blame_key in pillar_recent_errors and lesson:
            pillar_recent_errors[blame_key].append(
                f"{r.get('trade_date','')}: {lesson}"
            )

    # PM block aggregates
    total_n = sum(s.get("n", 0) for s in pillar_stats.values())
    total_correct = sum(s.get("correct", 0) for s in pillar_stats.values())
    # Deduplicate — pillar_stats double-counts the same bt result across 4 pillars.
    # For PM, use the directional BUY/SELL count from bt_report itself.
    pm_total_n = pm_total_correct = 0
    pm_overconf = pm_underconf = 0
    pm_pillar_blame: Dict[str, int] = {}
    if bt_report is not None:
        for bt in bt_report.results:
            if bt.eval_status != "completed":
                continue
            if bt.direction_expected not in ("up", "down"):
                continue
            if bt.direction_correct is None:
                continue
            pm_total_n += 1
            if bt.direction_correct:
                pm_total_correct += 1
    for r in recent_reflection_records:
        calib = r.get("confidence_calibration") or ""
        if calib == "overconfident":
            pm_overconf += 1
        elif calib == "underconfident":
            pm_underconf += 1
        blame = r.get("pillar_blame") or ""
        if blame:
            pm_pillar_blame[blame] = pm_pillar_blame.get(blame, 0) + 1

    # Build per-pillar blocks
    blocks: Dict[str, str] = {}
    for pkey in pillar_key_map:
        blocks[pkey] = _format_pillar_block(
            ticker=norm_ticker,
            pillar_key=pkey,
            stats=pillar_stats[pkey],
            recent_errors=pillar_recent_errors.get(pkey, []),
            days=days,
        )

    blocks["pm"] = _format_pm_block(
        ticker=norm_ticker,
        total_n=pm_total_n,
        total_correct=pm_total_correct,
        overconf=pm_overconf,
        underconf=pm_underconf,
        pillar_blame_counts=pm_pillar_blame,
        recent_lessons=recent_reflection_records,
        days=days,
    )

    return blocks
