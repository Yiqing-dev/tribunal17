"""Structured report-to-report diffing.

The user-facing reports need to explain what actually changed since the last
version, not only whether the final action flipped.  This module compares the
stable structured fields emitted by the pipeline and keeps the result compact
enough for static HTML pages and JSON exports.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .trace_models import RunTrace


@dataclass
class ReportDiff:
    """Compact diff between two runs for the same ticker."""

    previous_run_id: str = ""
    current_run_id: str = ""
    previous_trade_date: str = ""
    current_trade_date: str = ""
    previous_action: str = ""
    current_action: str = ""
    previous_confidence: float = -1.0
    current_confidence: float = -1.0
    confidence_delta: float = 0.0
    action_changed: bool = False
    thesis_changed: bool = False
    thesis_prev: str = ""
    thesis_curr: str = ""
    bull_claims_added: List[str] = field(default_factory=list)
    bull_claims_dropped: List[str] = field(default_factory=list)
    bear_claims_added: List[str] = field(default_factory=list)
    bear_claims_dropped: List[str] = field(default_factory=list)
    risk_flags_added: List[str] = field(default_factory=list)
    risk_flags_removed: List[str] = field(default_factory=list)
    confirmations_added: List[str] = field(default_factory=list)
    confirmations_removed: List[str] = field(default_factory=list)
    avoid_conditions_added: List[str] = field(default_factory=list)
    avoid_conditions_removed: List[str] = field(default_factory=list)
    review_triggers_added: List[str] = field(default_factory=list)
    review_triggers_removed: List[str] = field(default_factory=list)
    invalidators_added: List[str] = field(default_factory=list)
    invalidators_removed: List[str] = field(default_factory=list)
    stop_loss_changed: bool = False
    take_profit_changed: bool = False
    time_stop_changed: bool = False
    valuation_changed: bool = False
    quality_changed: bool = False
    previous_stop_loss: str = ""
    current_stop_loss: str = ""
    previous_take_profit: str = ""
    current_take_profit: str = ""
    previous_time_stop: str = ""
    current_time_stop: str = ""
    previous_valuation_label: str = ""
    current_valuation_label: str = ""
    previous_quality_label: str = ""
    current_quality_label: str = ""
    score: int = 0
    severity: str = "stable"  # stable / minor / moderate / major
    summary: List[str] = field(default_factory=list)

    @property
    def has_change(self) -> bool:
        return self.score > 0 or self.action_changed

    @property
    def trade_plan_changed(self) -> bool:
        return any([
            self.confirmations_added,
            self.confirmations_removed,
            self.avoid_conditions_added,
            self.avoid_conditions_removed,
            self.review_triggers_added,
            self.review_triggers_removed,
            self.invalidators_added,
            self.invalidators_removed,
            self.stop_loss_changed,
            self.take_profit_changed,
            self.time_stop_changed,
        ])

    @property
    def evidence_changed(self) -> bool:
        return bool(
            self.bull_claims_added
            or self.bull_claims_dropped
            or self.bear_claims_added
            or self.bear_claims_dropped
        )

    @property
    def risk_changed(self) -> bool:
        return bool(self.risk_flags_added or self.risk_flags_removed)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compare_reports(previous: Optional[RunTrace], current: Optional[RunTrace]) -> ReportDiff:
    """Compare two traces and return a structured diff."""
    if current is None:
        return ReportDiff()
    if previous is None:
        return ReportDiff(
            current_run_id=current.run_id,
            current_trade_date=current.trade_date,
            current_action=_final_action(current),
            current_confidence=_valid_conf(current.final_confidence),
            severity="stable",
        )

    diff = ReportDiff(
        previous_run_id=previous.run_id,
        current_run_id=current.run_id,
        previous_trade_date=previous.trade_date,
        current_trade_date=current.trade_date,
        previous_action=_final_action(previous),
        current_action=_final_action(current),
        previous_confidence=_valid_conf(previous.final_confidence),
        current_confidence=_valid_conf(current.final_confidence),
    )
    diff.action_changed = bool(diff.previous_action and diff.current_action and diff.previous_action != diff.current_action)
    if diff.previous_confidence >= 0 and diff.current_confidence >= 0:
        diff.confidence_delta = round(diff.current_confidence - diff.previous_confidence, 4)

    prev_extract = _extract_change_surface(previous)
    curr_extract = _extract_change_surface(current)

    diff.thesis_prev = prev_extract["thesis"]
    diff.thesis_curr = curr_extract["thesis"]
    diff.thesis_changed = bool(
        diff.thesis_prev
        and diff.thesis_curr
        and not _similar_text(diff.thesis_prev, diff.thesis_curr, threshold=0.72)
    )

    diff.bull_claims_added, diff.bull_claims_dropped = _diff_lists(
        prev_extract["bull_claims"], curr_extract["bull_claims"]
    )
    diff.bear_claims_added, diff.bear_claims_dropped = _diff_lists(
        prev_extract["bear_claims"], curr_extract["bear_claims"]
    )
    diff.risk_flags_added, diff.risk_flags_removed = _diff_lists(
        prev_extract["risk_flags"], curr_extract["risk_flags"]
    )
    diff.confirmations_added, diff.confirmations_removed = _diff_lists(
        prev_extract["confirmations"], curr_extract["confirmations"]
    )
    diff.avoid_conditions_added, diff.avoid_conditions_removed = _diff_lists(
        prev_extract["avoid_conditions"], curr_extract["avoid_conditions"]
    )
    diff.review_triggers_added, diff.review_triggers_removed = _diff_lists(
        prev_extract["review_triggers"], curr_extract["review_triggers"]
    )
    diff.invalidators_added, diff.invalidators_removed = _diff_lists(
        prev_extract["invalidators"], curr_extract["invalidators"]
    )

    diff.previous_stop_loss = prev_extract["stop_loss"]
    diff.current_stop_loss = curr_extract["stop_loss"]
    diff.stop_loss_changed = bool(diff.previous_stop_loss and diff.current_stop_loss and diff.previous_stop_loss != diff.current_stop_loss)
    diff.previous_take_profit = prev_extract["take_profit"]
    diff.current_take_profit = curr_extract["take_profit"]
    diff.take_profit_changed = bool(diff.previous_take_profit and diff.current_take_profit and diff.previous_take_profit != diff.current_take_profit)
    diff.previous_time_stop = prev_extract["time_stop"]
    diff.current_time_stop = curr_extract["time_stop"]
    diff.time_stop_changed = bool(diff.previous_time_stop and diff.current_time_stop and diff.previous_time_stop != diff.current_time_stop)

    diff.previous_valuation_label = prev_extract["valuation"]
    diff.current_valuation_label = curr_extract["valuation"]
    diff.valuation_changed = bool(diff.previous_valuation_label and diff.current_valuation_label and diff.previous_valuation_label != diff.current_valuation_label)
    diff.previous_quality_label = prev_extract["quality"]
    diff.current_quality_label = curr_extract["quality"]
    diff.quality_changed = bool(diff.previous_quality_label and diff.current_quality_label and diff.previous_quality_label != diff.current_quality_label)

    diff.score = _score_diff(diff)
    diff.severity = _severity(diff)
    diff.summary = _summary(diff)
    return diff


def _final_action(trace: RunTrace) -> str:
    if getattr(trace, "was_vetoed", False):
        return "VETO"
    return str(getattr(trace, "research_action", "") or "").upper()


def _valid_conf(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return -1.0
    return v if 0.0 <= v <= 1.0 else -1.0


def _node(trace: RunTrace, name: str):
    for nt in getattr(trace, "node_traces", []) or []:
        if nt.node_name == name:
            return nt
    return None


def _sd(trace: RunTrace, name: str) -> Dict[str, Any]:
    nt = _node(trace, name)
    return dict(getattr(nt, "structured_data", {}) or {}) if nt else {}


def _extract_change_surface(trace: RunTrace) -> Dict[str, Any]:
    bull_sd = _sd(trace, "Bull Researcher")
    bear_sd = _sd(trace, "Bear Researcher")
    risk_sd = _sd(trace, "Risk Judge")
    pm_sd = _sd(trace, "Research Manager")
    ro_sd = _sd(trace, "ResearchOutput")
    fund_sd = _sd(trace, "Fundamentals Analyst")
    trade_plan = ro_sd.get("trade_plan") or {}
    industry = fund_sd.get("industry_compare") or {}

    return {
        "thesis": _norm(pm_sd.get("conclusion") or _node_excerpt(trace, "Research Manager"), 180),
        "bull_claims": _claim_texts(bull_sd),
        "bear_claims": _claim_texts(bear_sd),
        "risk_flags": _risk_texts(risk_sd, _node(trace, "Risk Judge")),
        "confirmations": _list_texts(trade_plan.get("confirmations")),
        "avoid_conditions": _list_texts(trade_plan.get("avoid_conditions")),
        "review_triggers": _list_texts(trade_plan.get("review_triggers")),
        "invalidators": _list_texts(trade_plan.get("invalidators") or risk_sd.get("invalidation_conditions")),
        "stop_loss": _stop_loss_text(trade_plan.get("stop_loss")),
        "take_profit": _take_profit_text(trade_plan.get("take_profit")),
        "time_stop": _norm(trade_plan.get("time_stop", ""), 120),
        "valuation": _norm(industry.get("relative_valuation_label", ""), 80),
        "quality": _norm(industry.get("relative_quality_label", ""), 80),
    }


def _node_excerpt(trace: RunTrace, name: str) -> str:
    nt = _node(trace, name)
    return str(getattr(nt, "output_excerpt", "") or "") if nt else ""


def _claim_texts(sd: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for item in sd.get("supporting_claims") or sd.get("opposing_claims") or []:
        if isinstance(item, dict):
            text = item.get("text") or item.get("claim") or item.get("summary")
        else:
            text = item
        cleaned = _norm(text, 150)
        if cleaned:
            out.append(cleaned)
    return _dedup(out)


def _risk_texts(sd: Dict[str, Any], node) -> List[str]:
    out: List[str] = []
    flags = sd.get("risk_flags") or []
    if flags:
        for item in flags:
            if isinstance(item, dict):
                category = str(item.get("category") or "")
                desc = str(item.get("description") or "")
                text = f"{category}: {desc}" if category and desc else category or desc
            else:
                text = str(item)
            cleaned = _norm(text, 150)
            if cleaned:
                out.append(cleaned)
    elif node is not None:
        for cat in getattr(node, "risk_flag_categories", []) or []:
            cleaned = _norm(cat, 120)
            if cleaned:
                out.append(cleaned)
    return _dedup(out)


def _list_texts(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return []
    out = []
    for item in value:
        if isinstance(item, dict):
            text = item.get("condition") or item.get("label") or item.get("rule") or item.get("text") or item.get("description")
        else:
            text = item
        cleaned = _norm(text, 150)
        if cleaned:
            out.append(cleaned)
    return _dedup(out)


def _stop_loss_text(value: Any) -> str:
    if isinstance(value, dict):
        price = value.get("price")
        rule = _norm(value.get("rule", ""), 80)
        if price is not None and rule:
            return f"{price} {rule}"
        if price is not None:
            return str(price)
        return rule
    if isinstance(value, (int, float)):
        return str(value)
    return _norm(value, 100)


def _take_profit_text(value: Any) -> str:
    if not value:
        return ""
    items = value if isinstance(value, list) else [value]
    parts: List[str] = []
    for item in items[:3]:
        if isinstance(item, dict):
            label = _norm(item.get("label", ""), 60)
            zone = item.get("price_zone") or item.get("price") or ""
            if isinstance(zone, list):
                zone_text = "-".join(str(x) for x in zone[:2])
            else:
                zone_text = str(zone)
            parts.append(" ".join(p for p in [label, zone_text] if p))
        else:
            parts.append(str(item))
    return _norm("; ".join(parts), 150)


def _norm(value: Any, max_chars: int) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[*_`>#\-\[\]\(\)]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _dedup(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _diff_lists(prev: List[str], curr: List[str]) -> Tuple[List[str], List[str]]:
    added = [x for x in curr if not any(_similar_text(x, y) for y in prev)]
    removed = [x for x in prev if not any(_similar_text(x, y) for y in curr)]
    return added[:5], removed[:5]


def _similar_text(a: str, b: str, *, threshold: float = 0.78) -> bool:
    """Lightweight semantic-ish similarity for short Chinese report bullets.

    This is intentionally dependency-free.  It catches normalized rewrites and
    punctuation/wording drift without pretending to be an embedding model.
    """
    # Materially different if their numbers differ — "目标价 32 元" vs "28 元" or
    # "增 20%" vs "10%" must surface in "什么变了", not be smoothed away by a
    # number-blind fingerprint comparison.
    if set(re.findall(r"-?\d+(?:\.\d+)?%?", a)) != set(re.findall(r"-?\d+(?:\.\d+)?%?", b)):
        return False
    na = _fingerprint(a)
    nb = _fingerprint(b)
    if not na or not nb:
        return False
    min_len = min(len(na), len(nb))
    if na == nb or (min_len >= 6 and (na in nb or nb in na)):
        return True
    grams_a = _char_grams(na)
    grams_b = _char_grams(nb)
    if not grams_a or not grams_b:
        return False
    overlap = len(grams_a & grams_b)
    union = len(grams_a | grams_b)
    return bool(union and overlap / union >= threshold)


def _fingerprint(text: str) -> str:
    text = re.sub(r"\s+", "", str(text or "").lower())
    text = re.sub(r"[，。；：、,.!！?？（）()【】\[\]《》<>\"'`*_#\-]", "", text)
    replacements = {
        "较上次": "",
        "明显": "",
        "继续": "",
        "维持": "",
        "仍然": "",
        "当前": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _char_grams(text: str) -> set[str]:
    if len(text) <= 2:
        return {text}
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _score_diff(diff: ReportDiff) -> int:
    score = 0
    if diff.action_changed:
        score += 5
    if abs(diff.confidence_delta) >= 0.08:
        score += 2
    elif abs(diff.confidence_delta) >= 0.03:
        score += 1
    if diff.thesis_changed:
        score += 2
    if diff.risk_flags_added:
        score += 3
    if diff.risk_flags_removed:
        score += 1
    if diff.bear_claims_added:
        score += 2
    if diff.bull_claims_added or diff.bull_claims_dropped or diff.bear_claims_dropped:
        score += 1
    if diff.trade_plan_changed:
        score += 2
    if diff.valuation_changed or diff.quality_changed:
        score += 1
    return score


def _severity(diff: ReportDiff) -> str:
    if diff.action_changed or diff.score >= 5:
        return "major"
    if diff.score >= 3:
        return "moderate"
    if diff.score > 0:
        return "minor"
    return "stable"


def _summary(diff: ReportDiff) -> List[str]:
    items: List[str] = []
    if diff.action_changed:
        items.append(f"结论 {diff.previous_action or '—'} → {diff.current_action or '—'}")
    if abs(diff.confidence_delta) >= 0.03:
        items.append(f"置信度 {diff.confidence_delta:+.0%}")
    if diff.thesis_changed:
        items.append("核心论点有调整")
    if diff.risk_flags_added:
        items.append("新增风险：" + "；".join(diff.risk_flags_added[:2]))
    if diff.bear_claims_added:
        items.append("新增空头证据：" + "；".join(diff.bear_claims_added[:2]))
    if diff.bull_claims_added:
        items.append("新增多头证据：" + "；".join(diff.bull_claims_added[:2]))
    if diff.invalidators_added:
        items.append("新增失效条件：" + "；".join(diff.invalidators_added[:2]))
    if diff.review_triggers_added:
        items.append("新增复核触发：" + "；".join(diff.review_triggers_added[:2]))
    if diff.stop_loss_changed:
        items.append(f"止损 {diff.previous_stop_loss or '—'} → {diff.current_stop_loss or '—'}")
    if diff.take_profit_changed:
        items.append("目标位有调整")
    if diff.valuation_changed:
        items.append(f"估值相对位置 {diff.previous_valuation_label or '—'} → {diff.current_valuation_label or '—'}")
    if diff.quality_changed:
        items.append(f"质量相对位置 {diff.previous_quality_label or '—'} → {diff.current_quality_label or '—'}")
    return items[:8]
