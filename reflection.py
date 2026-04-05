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
from datetime import datetime
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
        content = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
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

    # No evaluation
    if rec.direction_correct is None:
        rec.confidence_calibration = ""
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
