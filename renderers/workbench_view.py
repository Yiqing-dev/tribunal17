"""Product workbench view models.

The workbench is a report-library layer over replay traces. It turns a folder
of generated reports into a product surface: latest report per ticker, follow-up
state, review trigger, quality caveats, and links into the three report tiers.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..replay_service import ReplayService
from ..trace_models import RunTrace, _now_cst
from .views import _summarize_display_text, _strip_internal_tokens

logger = logging.getLogger(__name__)

_UNSAFE_PATH_RE = re.compile(r"[^A-Za-z0-9._\-]")


def _safe_filename(part: str) -> str:
    return _UNSAFE_PATH_RE.sub("_", str(part))


def _short_run_id(run_id: str) -> str:
    return str(run_id or "").replace("run-", "")[:12]


def _report_links(ticker: str, run_id: str) -> Dict[str, str]:
    safe_t = _safe_filename(ticker)
    short = _short_run_id(run_id)
    return {
        "snapshot": f"{safe_t}-run-{short}-snapshot.html",
        "research": f"{safe_t}-run-{short}-research.html",
        "audit": f"{safe_t}-run-{short}-audit.html",
    }


@dataclass
class WorkbenchRow:
    """One ticker in the product workbench."""

    run_id: str = ""
    ticker: str = ""
    ticker_name: str = ""
    trade_date: str = ""
    action: str = ""
    action_label: str = ""
    action_class: str = "hold"
    confidence: float = -1.0
    quality_grade: str = ""
    quality_score: float = 0.0
    profile_label: str = ""
    status: str = "已生成"
    status_class: str = "hold"
    why_now: str = ""
    next_review: str = ""
    invalidator: str = ""
    data_quality_count: int = 0
    risk_count: int = 0
    relative_valuation_label: str = ""
    relative_quality_label: str = ""
    report_links: Dict[str, str] = field(default_factory=dict)
    previous_run_id: str = ""
    previous_trade_date: str = ""
    previous_action: str = ""
    previous_confidence: float = -1.0

    @property
    def display_name(self) -> str:
        return f"{self.ticker} {self.ticker_name}".strip()

    @property
    def confidence_pct(self) -> str:
        return "—" if self.confidence < 0 else f"{self.confidence:.0%}"

    @property
    def action_changed(self) -> bool:
        return bool(self.previous_action and self.previous_action != self.action)

    @property
    def confidence_delta(self) -> float:
        if self.confidence < 0 or self.previous_confidence < 0:
            return 0.0
        return self.confidence - self.previous_confidence


@dataclass
class WorkbenchView:
    """Report-library / watchlist product surface."""

    generated_at: str = ""
    rows: List[WorkbenchRow] = field(default_factory=list)
    total_reports: int = 0
    total_tickers: int = 0
    trade_dates: List[str] = field(default_factory=list)

    @property
    def buy_count(self) -> int:
        return sum(1 for r in self.rows if r.action == "BUY")

    @property
    def wait_count(self) -> int:
        return sum(1 for r in self.rows if r.status == "等待触发")

    @property
    def review_count(self) -> int:
        return sum(1 for r in self.rows if r.status == "需复核")

    @property
    def avoid_count(self) -> int:
        return sum(1 for r in self.rows if r.status == "回避")

    @property
    def changed_count(self) -> int:
        return sum(1 for r in self.rows if r.action_changed)

    @property
    def avg_confidence(self) -> float:
        vals = [r.confidence for r in self.rows if r.confidence >= 0]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def grade_mix(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for r in self.rows:
            grade = r.quality_grade or "—"
            counts[grade] = counts.get(grade, 0) + 1
        return counts

    @classmethod
    def build(
        cls,
        service: ReplayService,
        *,
        limit: int = 120,
        latest_per_ticker: bool = True,
    ) -> "WorkbenchView":
        entries = service.store.list_runs(limit=0)
        total_reports = len(entries)
        if latest_per_ticker:
            selected = []
            seen = set()
            for entry in entries:
                ticker = entry.get("ticker", "")
                if not ticker or ticker in seen:
                    continue
                seen.add(ticker)
                selected.append(entry)
                if limit > 0 and len(selected) >= limit:
                    break
        else:
            selected = entries[:limit] if limit > 0 else entries

        by_ticker: Dict[str, List[dict]] = {}
        for entry in entries:
            by_ticker.setdefault(entry.get("ticker", ""), []).append(entry)

        rows: List[WorkbenchRow] = []
        for entry in selected:
            run_id = entry.get("run_id", "")
            trace = service.load_run(run_id)
            if not trace:
                continue
            previous = _previous_entry(by_ticker.get(trace.ticker, []), run_id)
            rows.append(_build_row(service, trace, previous))

        action_order = {"BUY": 0, "HOLD": 1, "SELL": 2, "VETO": 3}
        status_order = {"可跟踪": 0, "等待触发": 1, "需复核": 2, "回避": 3, "已生成": 4}
        rows.sort(
            key=lambda r: (
                0 if r.action_changed else 1,
                status_order.get(r.status, 9),
                action_order.get(r.action, 9),
                -max(r.confidence, 0),
                r.ticker,
            )
        )

        return cls(
            generated_at=_now_cst().strftime("%Y-%m-%d %H:%M CST"),
            rows=rows,
            total_reports=total_reports,
            total_tickers=len({e.get("ticker", "") for e in entries if e.get("ticker")}),
            trade_dates=sorted({r.trade_date for r in rows if r.trade_date}, reverse=True)[:8],
        )


def _previous_entry(entries_for_ticker: List[dict], current_run_id: str) -> Optional[dict]:
    found_current = False
    for entry in entries_for_ticker:
        if entry.get("run_id") == current_run_id:
            found_current = True
            continue
        if found_current:
            return entry
    return None


def _node_sd(service: ReplayService, run_id: str, node_name: str) -> Dict:
    node = service.show_node_output(run_id, node_name) or {}
    return node.get("structured_data") or {}


def _quality(trace: RunTrace) -> tuple[str, float]:
    try:
        from ..research_quality import evaluate_trace_quality

        rec = evaluate_trace_quality(trace.to_dict())
        return rec.composite_grade, rec.composite_score
    except Exception:
        logger.warning("research quality evaluation failed for %s", trace.run_id, exc_info=True)
        return "", 0.0


def _first_text(items, max_chars: int = 90) -> str:
    if isinstance(items, str):
        return _summarize_display_text(_strip_internal_tokens(items), max_chars=max_chars)
    if not isinstance(items, list):
        return ""
    for item in items:
        if item:
            return _summarize_display_text(_strip_internal_tokens(str(item)), max_chars=max_chars)
    return ""


def _derive_status(action: str, quality_grade: str, flags: List[Dict], risk_flags: List[Dict]) -> tuple[str, str]:
    high_data_flag = any(str(f.get("severity", "")).lower() in ("high", "critical") for f in flags)
    high_risk = any(str(f.get("severity", "")).lower() in ("high", "critical") for f in risk_flags)
    if action in ("VETO", "SELL"):
        return "回避", "sell"
    if high_data_flag or quality_grade == "D":
        return "需复核", "veto"
    if high_risk or quality_grade == "C":
        return "需复核", "hold"
    if action == "BUY":
        return "可跟踪", "buy"
    if action == "HOLD":
        return "等待触发", "hold"
    return "已生成", "hold"


def _build_row(service: ReplayService, trace: RunTrace, previous_entry: Optional[dict]) -> WorkbenchRow:
    from .decision_labels import get_action_class, get_action_label

    run_id = trace.run_id
    fund_sd = _node_sd(service, run_id, "Fundamentals Analyst")
    risk_sd = _node_sd(service, run_id, "Risk Judge")
    ro_sd = _node_sd(service, run_id, "ResearchOutput")
    catalyst_sd = _node_sd(service, run_id, "Catalyst Agent")

    profile = fund_sd.get("stock_profile") or {}
    industry = fund_sd.get("industry_compare") or {}
    data_flags = fund_sd.get("data_quality_flags") or []
    risk_flags = risk_sd.get("risk_flags") or []
    trade_plan = ro_sd.get("trade_plan") or {}

    action = (trace.research_action or "HOLD").upper()
    if trace.was_vetoed:
        action = "VETO"
    grade, qscore = _quality(trace)
    status, status_class = _derive_status(action, grade, data_flags, risk_flags)

    why_now = _first_text(trade_plan.get("confirmations"), max_chars=86)
    if not why_now:
        catalysts = catalyst_sd.get("catalysts") or []
        if catalysts:
            why_now = _first_text(catalysts[0].get("event_description", ""), max_chars=86)
    if not why_now:
        pm_sd = _node_sd(service, run_id, "Research Manager")
        why_now = _first_text(pm_sd.get("conclusion", ""), max_chars=86)

    next_review = _first_text(trade_plan.get("review_triggers"), max_chars=86)
    if not next_review:
        next_review = _first_text(trade_plan.get("time_stop", ""), max_chars=86)
    if not next_review and data_flags:
        next_review = _first_text(data_flags[0].get("message", ""), max_chars=86)

    invalidator = _first_text(trade_plan.get("invalidators"), max_chars=86)
    if not invalidator:
        invalidator = _first_text(risk_sd.get("invalidation_conditions"), max_chars=86)

    prev_action = ""
    prev_conf = -1.0
    prev_rid = ""
    prev_date = ""
    if previous_entry:
        prev_rid = previous_entry.get("run_id", "")
        prev_date = previous_entry.get("trade_date", "")
        prev_trace = service.load_run(prev_rid) if prev_rid else None
        if prev_trace:
            prev_action = (prev_trace.research_action or "").upper()
            prev_conf = prev_trace.final_confidence

    return WorkbenchRow(
        run_id=run_id,
        ticker=trace.ticker,
        ticker_name=getattr(trace, "ticker_name", ""),
        trade_date=trace.trade_date,
        action=action,
        action_label=get_action_label(action),
        action_class=get_action_class(action),
        confidence=trace.final_confidence,
        quality_grade=grade,
        quality_score=qscore,
        profile_label=profile.get("label_cn", "") or profile.get("primary", ""),
        status=status,
        status_class=status_class,
        why_now=why_now,
        next_review=next_review,
        invalidator=invalidator,
        data_quality_count=len(data_flags),
        risk_count=len(risk_flags),
        relative_valuation_label=str(industry.get("relative_valuation_label", "")),
        relative_quality_label=str(industry.get("relative_quality_label", "")),
        report_links=_report_links(trace.ticker, run_id),
        previous_run_id=prev_rid,
        previous_trade_date=prev_date,
        previous_action=prev_action,
        previous_confidence=prev_conf,
    )
