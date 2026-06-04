"""Automatic review-trigger detection for generated stock reports."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .report_diff import ReportDiff, compare_reports
from .trace_models import RunTrace


@dataclass
class ReviewTrigger:
    """One reason a report should be reviewed again."""

    kind: str = ""
    severity: str = "medium"  # low / medium / high / critical
    reason: str = ""
    due_date: str = ""
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def evaluate_review_triggers(
    current: RunTrace,
    previous: Optional[RunTrace] = None,
    *,
    quality_grade: str = "",
    current_price: float = 0.0,
    as_of_date: str = "",
) -> List[ReviewTrigger]:
    """Detect review triggers from report content and previous-report drift."""
    triggers: List[ReviewTrigger] = []
    diff = compare_reports(previous, current) if previous else ReportDiff(current_run_id=current.run_id)

    if diff.action_changed:
        triggers.append(ReviewTrigger(
            kind="action_change",
            severity="high",
            reason=f"结论从 {diff.previous_action or '—'} 变为 {diff.current_action or '—'}",
            source="report_diff",
        ))
    if diff.risk_flags_added:
        triggers.append(ReviewTrigger(
            kind="risk_added",
            severity="high",
            reason="新增风险：" + "；".join(diff.risk_flags_added[:2]),
            source="report_diff",
        ))
    if diff.trade_plan_changed and not diff.action_changed:
        triggers.append(ReviewTrigger(
            kind="plan_change",
            severity="medium",
            reason="交易计划或复核条件较上次有调整",
            source="report_diff",
        ))

    fund_sd = _sd(current, "Fundamentals Analyst")
    risk_sd = _sd(current, "Risk Judge")
    ro_sd = _sd(current, "ResearchOutput")
    trade_plan = ro_sd.get("trade_plan") or {}

    for flag in fund_sd.get("data_quality_flags") or []:
        sev = str(flag.get("severity") or "medium").lower()
        if sev in ("critical", "high"):
            triggers.append(ReviewTrigger(
                kind="data_quality",
                severity="high" if sev == "high" else "critical",
                reason=str(flag.get("message") or "关键数据口径需复核"),
                source="fundamentals",
            ))

    if quality_grade in ("C", "D"):
        triggers.append(ReviewTrigger(
            kind="quality_gate",
            severity="high" if quality_grade == "D" else "medium",
            reason=f"研究质量等级 {quality_grade}，需要人工确认关键证据",
            source="research_quality",
        ))

    risk_flags = risk_sd.get("risk_flags") or []
    for flag in risk_flags:
        if not isinstance(flag, dict):
            continue
        sev = str(flag.get("severity") or "").lower()
        if sev in ("critical", "high"):
            text = str(flag.get("description") or flag.get("category") or "高风险项需复核")
            triggers.append(ReviewTrigger(
                kind="high_risk",
                severity="critical" if sev == "critical" else "high",
                reason=text,
                source="risk_judge",
            ))

    _append_price_stop_triggers(triggers, current, trade_plan, current_price=current_price)
    _append_plan_triggers(triggers, current, trade_plan, as_of_date=as_of_date)

    return _dedup_and_sort(triggers)


def primary_review_trigger(triggers: List[ReviewTrigger]) -> ReviewTrigger:
    """Return the highest-priority trigger or an empty trigger."""
    if not triggers:
        return ReviewTrigger()
    return sorted(triggers, key=lambda t: (_SEV_RANK.get(t.severity, 9), t.due_date or "9999-99-99"))[0]


def _append_price_stop_triggers(
    triggers: List[ReviewTrigger],
    trace: RunTrace,
    trade_plan: Dict[str, Any],
    *,
    current_price: float = 0.0,
) -> None:
    stop = _stop_loss_price(trade_plan.get("stop_loss"))
    price = float(current_price or 0) if current_price else _current_price(trace)
    action = str(getattr(trace, "research_action", "") or "").upper()
    if stop <= 0 or price <= 0 or action not in ("BUY", "HOLD"):
        return
    if price <= stop:
        triggers.append(ReviewTrigger(
            kind="stop_loss",
            severity="critical",
            reason=f"现价 {price:.2f} 已触及止损 {stop:.2f}",
            source="trade_plan",
        ))
    elif price <= stop * 1.02:
        triggers.append(ReviewTrigger(
            kind="stop_loss_near",
            severity="high",
            reason=f"现价 {price:.2f} 距止损 {stop:.2f} 不足 2%",
            source="trade_plan",
        ))


def _append_plan_triggers(
    triggers: List[ReviewTrigger],
    trace: RunTrace,
    trade_plan: Dict[str, Any],
    *,
    as_of_date: str = "",
) -> None:
    due = _due_date_from_time_stop(trace.trade_date, trade_plan.get("time_stop"))
    if trade_plan.get("time_stop"):
        severity = "medium"
        if due and as_of_date and due <= as_of_date:
            severity = "high"
        triggers.append(ReviewTrigger(
            kind="time_stop",
            severity=severity,
            reason="时间止损：" + str(trade_plan.get("time_stop")),
            due_date=due,
            source="trade_plan",
        ))
    for text in _list_texts(trade_plan.get("review_triggers"))[:3]:
        severity = "high" if any(word in text for word in ("止损", "跌破", "财报", "业绩", "监管")) else "medium"
        triggers.append(ReviewTrigger(
            kind="planned_review",
            severity=severity,
            reason="计划复核：" + text,
            due_date=due,
            source="trade_plan",
        ))


def _sd(trace: RunTrace, node_name: str) -> Dict[str, Any]:
    for nt in getattr(trace, "node_traces", []) or []:
        if nt.node_name == node_name:
            return dict(getattr(nt, "structured_data", {}) or {})
    return {}


def _current_price(trace: RunTrace) -> float:
    mkt = _sd(trace, "Market Analyst")
    for key in ("current_price", "price", "close"):
        try:
            val = float(mkt.get(key, 0) or 0)
        except (TypeError, ValueError):
            val = 0.0
        if val > 0:
            return val
    prices = mkt.get("price_history") or []
    if prices:
        try:
            last = prices[-1]
            if isinstance(last, dict):
                return float(last.get("close") or last.get("price") or 0)
            return float(last)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _stop_loss_price(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("price")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _due_date_from_time_stop(trade_date: str, time_stop: Any) -> str:
    text = str(time_stop or "")
    if not text:
        return ""
    m = re.search(r"(\d+)\s*(?:个)?(交易日|天|日)", text)
    if not m:
        return ""
    n = int(m.group(1))
    if m.group(2) == "交易日":
        # Advance N REAL trading days via the CN calendar (weekends + holidays) —
        # an accurate due date, NOT a ×7/5 fake. If the calendar is unavailable,
        # fall back to "" rather than emit a misleading approximate date.
        try:
            from .akshare_collector import _advance_trading_days
            return _advance_trading_days(str(trade_date), n)
        except Exception:
            return ""
    try:
        base = datetime.strptime(str(trade_date), "%Y-%m-%d")
        return (base + timedelta(days=n)).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def _list_texts(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if isinstance(item, dict):
            text = item.get("condition") or item.get("label") or item.get("text") or item.get("description")
        else:
            text = item
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        if cleaned:
            out.append(cleaned[:160])
    return out


def _dedup_and_sort(triggers: List[ReviewTrigger]) -> List[ReviewTrigger]:
    seen = set()
    out: List[ReviewTrigger] = []
    for t in triggers:
        key = (t.kind, t.reason)
        if key in seen or not t.reason:
            continue
        seen.add(key)
        out.append(t)
    return sorted(out, key=lambda t: (_SEV_RANK.get(t.severity, 9), t.due_date or "9999-99-99", t.kind))[:8]
