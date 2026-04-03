"""Discussion Tracker — debate quality analysis and prediction review.

Loads RunTraces and evaluates:
- Debate quality: balance, dimension coverage, PM consumption, risk challenge
- Evidence utilization: citation tracking across agents
- Signal drift: compare with prior runs for the same ticker
- Prompt suggestions: rule-based improvement hints
- Prediction review: compare predicted vs actual outcomes

Pure Python, zero external imports, no LLM calls.

Usage:
    from subagent_pipeline.discussion_tracker import (
        generate_discussion_review, review_prediction,
    )

    review = generate_discussion_review("run-abc123def456")
    print(review.to_markdown())

    pred = review_prediction("run-abc123def456", actual_price=9.50)
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .replay_store import ReplayStore
from .replay_service import ReplayService
from .trace_models import RunTrace, NodeTrace

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

# Dimensions to check in claim text (Chinese keywords)
DIMENSIONS = ["基本面", "估值", "技术", "资金", "催化"]

# Node names for debate participants
_BULL_NODE = "Bull Researcher"
_BEAR_NODE = "Bear Researcher"
_PM_NODE = "Research Manager"
_RISK_JUDGE_NODE = "Risk Judge"
_RESEARCH_OUTPUT_NODE = "ResearchOutput"

# Risk debater node names
_RISK_DEBATER_NODES = {
    "Aggressive Debator",
    "Conservative Debator",
    "Neutral Debator",
}

# Analyst nodes that produce evidence
_ANALYST_NODES = {
    "Market Analyst",
    "Fundamentals Analyst",
    "News Analyst",
    "Social Analyst",
}

# Grade thresholds
_GRADE_THRESHOLDS = {
    "A": 0,   # No issues
    "B": 2,   # 1-2 minor issues
    "C": 4,   # 3-4 issues
    "D": 99,  # 5+ issues
}


# ── Data Classes ───────────────────────────────────────────────────────────


@dataclass
class DebateQualityScore:
    """Quality assessment of the bull/bear debate and downstream consumption."""

    # Bull side
    bull_claims_count: int = 0
    bull_confidence: float = 0.0

    # Bear side
    bear_claims_count: int = 0
    bear_confidence: float = 0.0

    # Balance (0 = completely one-sided, 1 = perfectly balanced)
    balance_score: float = 0.0

    # Dimension coverage
    addressed_dimensions: List[str] = field(default_factory=list)
    missed_dimensions: List[str] = field(default_factory=list)

    # PM consumption
    pm_consumption_rate: float = 0.0
    pm_missed_strong_claims: int = 0

    # Risk debate quality
    risk_challenge_rate: float = 0.0
    risk_flags_actionable: int = 0
    risk_flags_vague: int = 0

    # Overall grade
    debate_grade: str = "C"

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class EvidenceUtilization:
    """How well the evidence bundle was used across agents."""

    total_evidence: int = 0
    cited_by_bull: int = 0
    cited_by_bear: int = 0
    cited_by_pm: int = 0
    evidence_never_cited: List[str] = field(default_factory=list)
    utilization_rate: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PromptSuggestion:
    """Actionable suggestion for improving an agent's prompt."""

    agent: str = ""
    category: str = ""         # balance, coverage, consumption, evidence, risk
    description: str = ""
    severity: str = "info"     # info, warning, critical
    example: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PredictionReview:
    """Post-hoc evaluation of a prediction against actual outcome."""

    review_date: str = ""
    actual_price: float = 0.0
    predicted_direction: str = ""      # BUY/SELL/HOLD
    actual_direction: str = ""         # up/down/flat
    direction_correct: bool = False
    scenario_hit: str = ""             # base/bull/bear
    key_surprise: str = ""
    lesson: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class DiscussionReview:
    """Complete quality review of a single analysis run's discussion process."""

    run_id: str = ""
    ticker: str = ""
    trade_date: str = ""

    debate_quality: Optional[DebateQualityScore] = None
    evidence_utilization: Optional[EvidenceUtilization] = None
    signal_drift: Optional[Dict] = None
    prompt_suggestions: List[PromptSuggestion] = field(default_factory=list)
    prediction_review: Optional[PredictionReview] = None

    def to_dict(self) -> Dict:
        d: Dict[str, Any] = {
            "run_id": self.run_id,
            "ticker": self.ticker,
            "trade_date": self.trade_date,
            "debate_quality": self.debate_quality.to_dict() if self.debate_quality else None,
            "evidence_utilization": (
                self.evidence_utilization.to_dict() if self.evidence_utilization else None
            ),
            "signal_drift": self.signal_drift,
            "prompt_suggestions": [s.to_dict() for s in self.prompt_suggestions],
            "prediction_review": (
                self.prediction_review.to_dict() if self.prediction_review else None
            ),
        }
        return d

    def to_markdown(self) -> str:
        """Human-readable review summary."""
        lines: List[str] = []
        lines.append(f"# 讨论质量报告 — {self.ticker}")
        lines.append("")
        lines.append(f"> Run: `{self.run_id}` | 日期: {self.trade_date}")
        lines.append("")

        # ── Debate Quality ──
        dq = self.debate_quality
        if dq:
            lines.append("## 辩论质量")
            lines.append("")
            lines.append(f"**评级: {dq.debate_grade}**")
            lines.append("")
            lines.append(f"| 指标 | 值 |")
            lines.append(f"|------|-----|")
            lines.append(f"| 多方论点数 | {dq.bull_claims_count} |")
            lines.append(f"| 空方论点数 | {dq.bear_claims_count} |")
            lines.append(f"| 多方置信度 | {dq.bull_confidence:.0%} |")
            lines.append(f"| 空方置信度 | {dq.bear_confidence:.0%} |")
            lines.append(f"| 平衡度 | {dq.balance_score:.2f} |")
            lines.append(f"| PM消化率 | {dq.pm_consumption_rate:.0%} |")
            lines.append(f"| PM遗漏强论点 | {dq.pm_missed_strong_claims} |")
            lines.append(f"| 风险挑战率 | {dq.risk_challenge_rate:.0%} |")
            lines.append("")

            if dq.addressed_dimensions:
                lines.append(
                    f"覆盖维度: {', '.join(dq.addressed_dimensions)}"
                )
            if dq.missed_dimensions:
                lines.append(
                    f"缺失维度: {', '.join(dq.missed_dimensions)}"
                )
            lines.append("")

        # ── Evidence Utilization ──
        eu = self.evidence_utilization
        if eu:
            lines.append("## 证据利用")
            lines.append("")
            lines.append(f"| 指标 | 值 |")
            lines.append(f"|------|-----|")
            lines.append(f"| 总证据数 | {eu.total_evidence} |")
            lines.append(f"| 多方引用 | {eu.cited_by_bull} |")
            lines.append(f"| 空方引用 | {eu.cited_by_bear} |")
            lines.append(f"| PM引用 | {eu.cited_by_pm} |")
            lines.append(f"| 利用率 | {eu.utilization_rate:.0%} |")
            lines.append("")
            if eu.evidence_never_cited:
                lines.append(
                    f"未被引用: {', '.join(eu.evidence_never_cited)}"
                )
                lines.append("")

        # ── Signal Drift ──
        if self.signal_drift:
            lines.append("## 信号漂移")
            lines.append("")
            sd = self.signal_drift
            if sd.get("action_changed"):
                lines.append(
                    f"- 信号: {sd.get('prev_action', '?')} -> "
                    f"{sd.get('curr_action', '?')}"
                )
            if sd.get("confidence_delta") is not None:
                delta = sd["confidence_delta"]
                sign = "+" if delta > 0 else ""
                lines.append(f"- 置信度变化: {sign}{delta:.0%}")
            if sd.get("prev_date"):
                lines.append(f"- 上次日期: {sd['prev_date']}")
            lines.append("")

        # ── Prompt Suggestions ──
        if self.prompt_suggestions:
            lines.append("## 改进建议")
            lines.append("")
            for i, s in enumerate(self.prompt_suggestions, 1):
                icon = {"critical": "!!!", "warning": "!!", "info": "!"}.get(
                    s.severity, "!"
                )
                lines.append(
                    f"{i}. **[{icon}] {s.agent}** ({s.category}): "
                    f"{s.description}"
                )
                if s.example:
                    lines.append(f"   - 示例: {s.example}")
            lines.append("")

        # ── Prediction Review ──
        pr = self.prediction_review
        if pr:
            lines.append("## 预测回顾")
            lines.append("")
            result = "正确" if pr.direction_correct else "错误"
            lines.append(
                f"- 预测方向: {pr.predicted_direction} | "
                f"实际方向: {pr.actual_direction} | {result}"
            )
            if pr.scenario_hit:
                lines.append(f"- 命中情景: {pr.scenario_hit}")
            if pr.key_surprise:
                lines.append(f"- 关键意外: {pr.key_surprise}")
            if pr.lesson:
                lines.append(f"- 教训: {pr.lesson}")
            lines.append("")

        return "\n".join(lines)


# ── Internal Helpers ───────────────────────────────────────────────────────


def _find_node(trace: RunTrace, node_name: str) -> Optional[NodeTrace]:
    """Find a specific node trace by name."""
    for nt in trace.node_traces:
        if nt.node_name == node_name:
            return nt
    return None


def _find_nodes(trace: RunTrace, node_names: set) -> List[NodeTrace]:
    """Find all node traces matching any of the given names."""
    return [nt for nt in trace.node_traces if nt.node_name in node_names]


def _extract_claims_from_node(nt: NodeTrace) -> List[Dict]:
    """Extract claim list from a node's structured_data."""
    sd = nt.structured_data or {}
    claims = sd.get("supporting_claims", [])
    if not claims:
        claims = sd.get("claims", [])
    return claims


def _get_claim_confidence(claim: Dict) -> float:
    """Safely extract confidence from a claim dict."""
    try:
        return float(claim.get("confidence", 0.5))
    except (ValueError, TypeError):
        return 0.5


def _get_overall_confidence(nt: NodeTrace) -> float:
    """Get overall confidence from a debate node."""
    sd = nt.structured_data or {}
    try:
        return float(sd.get("overall_confidence", 0.0))
    except (ValueError, TypeError):
        return 0.0


def _scan_dimensions(claims: List[Dict], excerpt: str = "") -> List[str]:
    """Scan claim text and excerpt for dimension keywords."""
    covered = []
    # Combine all claim text
    all_text = excerpt
    for c in claims:
        all_text += " " + str(c.get("text", ""))
        all_text += " " + str(c.get("dimension", ""))

    for dim in DIMENSIONS:
        if dim in all_text:
            covered.append(dim)
    return covered


def _compute_balance(bull_count: int, bear_count: int,
                     bull_conf: float, bear_conf: float) -> float:
    """Compute debate balance score (0-1).

    Considers both claim count ratio and confidence gap.
    1.0 = perfectly balanced, 0.0 = completely one-sided.
    """
    total_claims = bull_count + bear_count
    if total_claims == 0:
        return 0.0

    # Count balance: min/max ratio
    count_balance = min(bull_count, bear_count) / max(bull_count, bear_count)

    # Confidence balance: 1 - normalized gap
    conf_sum = bull_conf + bear_conf
    if conf_sum > 0:
        conf_balance = 1.0 - abs(bull_conf - bear_conf) / conf_sum
    else:
        conf_balance = 0.5

    # Weighted average (count matters more)
    return 0.6 * count_balance + 0.4 * conf_balance


def _extract_evidence_ids(text: str) -> List[str]:
    """Extract E# evidence IDs from text (e.g., [E1], [E3, E5])."""
    return re.findall(r"E\d+", text)


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safely convert to float."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ── Core Functions ─────────────────────────────────────────────────────────


def _assess_debate_quality(trace: RunTrace) -> DebateQualityScore:
    """Assess debate quality from trace node data."""
    dq = DebateQualityScore()

    # ── Bull/Bear claims and confidence ──
    bull_node = _find_node(trace, _BULL_NODE)
    bear_node = _find_node(trace, _BEAR_NODE)

    bull_claims: List[Dict] = []
    bear_claims: List[Dict] = []

    if bull_node:
        bull_claims = _extract_claims_from_node(bull_node)
        dq.bull_claims_count = max(bull_node.claims_produced, len(bull_claims))
        dq.bull_confidence = _get_overall_confidence(bull_node)
        if dq.bull_confidence == 0.0 and bull_node.confidence >= 0:
            dq.bull_confidence = bull_node.confidence

    if bear_node:
        bear_claims = _extract_claims_from_node(bear_node)
        dq.bear_claims_count = max(bear_node.claims_produced, len(bear_claims))
        dq.bear_confidence = _get_overall_confidence(bear_node)
        if dq.bear_confidence == 0.0 and bear_node.confidence >= 0:
            dq.bear_confidence = bear_node.confidence

    # ── Balance ──
    dq.balance_score = _compute_balance(
        dq.bull_claims_count, dq.bear_claims_count,
        dq.bull_confidence, dq.bear_confidence,
    )

    # ── Dimension coverage ──
    bull_excerpt = bull_node.output_excerpt if bull_node else ""
    bear_excerpt = bear_node.output_excerpt if bear_node else ""
    all_claims = bull_claims + bear_claims

    covered = set(_scan_dimensions(all_claims, bull_excerpt + " " + bear_excerpt))
    dq.addressed_dimensions = sorted(covered)
    dq.missed_dimensions = [d for d in DIMENSIONS if d not in covered]

    # ── PM consumption ──
    pm_node = _find_node(trace, _PM_NODE)
    total_claim_ids = set()
    pm_claim_ids = set()

    if bull_node:
        total_claim_ids.update(bull_node.claim_ids_produced)
    if bear_node:
        total_claim_ids.update(bear_node.claim_ids_produced)

    if pm_node:
        pm_claim_ids.update(pm_node.claim_ids_referenced)

    if total_claim_ids:
        dq.pm_consumption_rate = len(pm_claim_ids & total_claim_ids) / len(total_claim_ids)
    elif pm_node and (dq.bull_claims_count + dq.bear_claims_count) > 0:
        # Fallback: use counts if IDs are not available
        total = dq.bull_claims_count + dq.bear_claims_count
        consumed = len(pm_node.claim_ids_referenced)
        dq.pm_consumption_rate = min(1.0, consumed / total) if total > 0 else 0.0

    # ── PM missed strong claims ──
    strong_claim_ids = set()
    for claims, node in [(bull_claims, bull_node), (bear_claims, bear_node)]:
        if not node:
            continue
        produced_ids = list(node.claim_ids_produced)
        for i, claim in enumerate(claims):
            conf = _get_claim_confidence(claim)
            if conf > 0.7:
                # Map claim to its ID if available
                if i < len(produced_ids):
                    strong_claim_ids.add(produced_ids[i])

    if strong_claim_ids:
        missed_strong = strong_claim_ids - pm_claim_ids
        dq.pm_missed_strong_claims = len(missed_strong)

    # ── Risk debate quality ──
    risk_nodes = _find_nodes(trace, _RISK_DEBATER_NODES)
    risk_judge = _find_node(trace, _RISK_JUDGE_NODE)

    if risk_nodes and pm_node:
        # Challenge rate: did any risk debater disagree with PM direction?
        pm_action = pm_node.research_action or ""
        challengers = 0
        for rn in risk_nodes:
            rn_action = rn.research_action or ""
            sd = rn.structured_data or {}
            rn_recommendation = sd.get("recommendation", rn_action)
            if rn_recommendation and rn_recommendation != pm_action:
                challengers += 1
        dq.risk_challenge_rate = challengers / len(risk_nodes) if risk_nodes else 0.0

    # ── Risk flag quality ──
    if risk_judge:
        total_flags = risk_judge.risk_flag_count
        categories = risk_judge.risk_flag_categories or []

        # Heuristic: flags with quantified invalidation are "actionable",
        # flags that are short/generic are "vague"
        actionable = 0
        vague = 0
        for cat in categories:
            # Actionable: contains numbers, percentages, specific conditions
            if re.search(r"\d", cat) or len(cat) > 15:
                actionable += 1
            else:
                vague += 1

        # If we have more flags than categories, the extras are vague
        uncategorized = max(0, total_flags - len(categories))
        dq.risk_flags_actionable = actionable
        dq.risk_flags_vague = vague + uncategorized

    # ── Grade ──
    issues = 0
    if dq.balance_score < 0.3:
        issues += 2
    elif dq.balance_score < 0.5:
        issues += 1
    if len(dq.missed_dimensions) >= 3:
        issues += 2
    elif len(dq.missed_dimensions) >= 1:
        issues += 1
    if dq.pm_missed_strong_claims > 0:
        issues += 1
    if dq.pm_consumption_rate < 0.5:
        issues += 1
    if risk_nodes and dq.risk_challenge_rate < 0.2:
        issues += 1

    if issues == 0:
        dq.debate_grade = "A"
    elif issues <= 2:
        dq.debate_grade = "B"
    elif issues <= 4:
        dq.debate_grade = "C"
    else:
        dq.debate_grade = "D"

    return dq


def _assess_evidence_utilization(trace: RunTrace) -> EvidenceUtilization:
    """Assess how well the evidence bundle was cited across agents."""
    eu = EvidenceUtilization()

    # Total evidence IDs from trace
    all_evidence = set(trace.total_evidence_ids or [])

    # Also scan analyst outputs for E# references to find total pool
    for nt in trace.node_traces:
        if nt.node_name in _ANALYST_NODES:
            # Evidence is produced *from* analyst outputs, so analyst nodes
            # themselves may have evidence_ids in output_excerpt
            ids = _extract_evidence_ids(nt.output_excerpt or "")
            all_evidence.update(ids)

    # If no evidence IDs found from trace metadata, try scanning all nodes
    if not all_evidence:
        for nt in trace.node_traces:
            all_evidence.update(nt.evidence_ids_referenced)

    eu.total_evidence = len(all_evidence)
    if eu.total_evidence == 0:
        return eu

    # Per-agent citation tracking
    bull_cited = set()
    bear_cited = set()
    pm_cited = set()
    all_cited = set()

    for nt in trace.node_traces:
        refs = set(nt.evidence_ids_referenced)
        all_cited.update(refs)

        if nt.node_name == _BULL_NODE:
            bull_cited = refs
        elif nt.node_name == _BEAR_NODE:
            bear_cited = refs
        elif nt.node_name == _PM_NODE:
            pm_cited = refs

    eu.cited_by_bull = len(bull_cited)
    eu.cited_by_bear = len(bear_cited)
    eu.cited_by_pm = len(pm_cited)

    never_cited = sorted(all_evidence - all_cited)
    eu.evidence_never_cited = never_cited
    eu.utilization_rate = (
        len(all_evidence - set(never_cited)) / len(all_evidence)
        if all_evidence else 0.0
    )

    return eu


def _check_signal_drift(
    trace: RunTrace, store: ReplayStore,
) -> Optional[Dict]:
    """Compare current run's signal with the most recent prior run for the same ticker."""
    ticker = trace.ticker
    if not ticker:
        return None

    # Find prior runs for same ticker
    runs = store.list_runs(ticker=ticker, limit=50)

    # Find the most recent run before this one
    prev_run_id = None
    prev_date = ""
    for entry in runs:
        rid = entry.get("run_id", "")
        td = entry.get("trade_date", "")
        if rid == trace.run_id:
            continue
        if td and td < (trace.trade_date or "9999"):
            prev_run_id = rid
            prev_date = td
            break

    if not prev_run_id:
        return None

    prev_trace = store.load(prev_run_id)
    if not prev_trace:
        return None

    drift: Dict[str, Any] = {
        "prev_run_id": prev_run_id,
        "prev_date": prev_date,
        "prev_action": prev_trace.research_action,
        "curr_action": trace.research_action,
        "action_changed": prev_trace.research_action != trace.research_action,
    }

    # Confidence delta
    if prev_trace.final_confidence >= 0 and trace.final_confidence >= 0:
        drift["confidence_delta"] = trace.final_confidence - prev_trace.final_confidence
    else:
        drift["confidence_delta"] = None

    return drift


def _generate_prompt_suggestions(
    dq: DebateQualityScore,
    eu: EvidenceUtilization,
    trace: RunTrace,
) -> List[PromptSuggestion]:
    """Generate rule-based prompt improvement suggestions."""
    suggestions: List[PromptSuggestion] = []

    # 1. One-sided debate
    if dq.balance_score < 0.3:
        weaker = "空方" if dq.bull_claims_count > dq.bear_claims_count else "多方"
        suggestions.append(PromptSuggestion(
            agent=f"{weaker}研究员",
            category="balance",
            description=f"辩论严重失衡 (balance={dq.balance_score:.2f})，{weaker}论点不足",
            severity="critical",
            example=f"在prompt中增加对{weaker}至少提出3条独立论点的要求",
        ))

    # 2. Missing dimensions
    if dq.missed_dimensions:
        missed_str = "、".join(dq.missed_dimensions)
        suggestions.append(PromptSuggestion(
            agent="Bull/Bear Researcher",
            category="coverage",
            description=f"辩论未覆盖维度: {missed_str}",
            severity="warning" if len(dq.missed_dimensions) <= 2 else "critical",
            example=f"在prompt中明确要求涵盖{missed_str}维度的分析",
        ))

    # 3. PM missed strong claims
    if dq.pm_missed_strong_claims > 0:
        suggestions.append(PromptSuggestion(
            agent="Research Manager",
            category="consumption",
            description=(
                f"PM遗漏了{dq.pm_missed_strong_claims}条高置信度(>0.7)论点"
            ),
            severity="warning",
            example="在PM prompt中添加\"逐一回应所有置信度>70%的论点\"指令",
        ))

    # 4. Low evidence utilization
    if eu.total_evidence > 0 and eu.utilization_rate < 0.5:
        suggestions.append(PromptSuggestion(
            agent="全局",
            category="evidence",
            description=(
                f"证据利用率仅{eu.utilization_rate:.0%}，"
                f"{len(eu.evidence_never_cited)}条证据从未被引用"
            ),
            severity="warning",
            example="在下游agent prompt中要求\"引用Evidence Bundle中的E#编号\"",
        ))

    # 5. Rubber-stamp risk debate
    risk_nodes = _find_nodes(trace, _RISK_DEBATER_NODES)
    if risk_nodes and dq.risk_challenge_rate < 0.2:
        suggestions.append(PromptSuggestion(
            agent="Risk Debaters",
            category="risk",
            description=(
                f"风险辩论挑战率仅{dq.risk_challenge_rate:.0%}，"
                "形同橡皮图章"
            ),
            severity="warning",
            example="要求至少一位风险辩论者提出与PM相反的立场",
        ))

    # 6. Vague risk flags
    if dq.risk_flags_vague > 0:
        suggestions.append(PromptSuggestion(
            agent="Risk Judge",
            category="risk",
            description=(
                f"{dq.risk_flags_vague}条风险标记缺乏量化失效条件"
            ),
            severity="info",
            example="要求每条风险标记包含具体的触发阈值或失效价格",
        ))

    return suggestions


def generate_discussion_review(
    run_id: str,
    storage_dir: str = "data/replays",
) -> DiscussionReview:
    """Generate a complete discussion quality review for a run.

    Args:
        run_id: The run ID to analyze.
        storage_dir: Path to ReplayStore directory.

    Returns:
        DiscussionReview with debate quality, evidence utilization,
        signal drift, and prompt suggestions.

    Raises:
        ValueError: If the run_id is not found.
    """
    store = ReplayStore(storage_dir=storage_dir)
    service = ReplayService(store=store)

    trace = store.load(run_id)
    if trace is None:
        raise ValueError(f"Run not found: {run_id}")

    # Compute metrics for reference (unused directly but validates trace)
    _metrics = service.compute_metrics_from_trace(trace)

    review = DiscussionReview(
        run_id=run_id,
        ticker=trace.ticker,
        trade_date=trace.trade_date,
    )

    # 1. Debate quality
    review.debate_quality = _assess_debate_quality(trace)

    # 2. Evidence utilization
    review.evidence_utilization = _assess_evidence_utilization(trace)

    # 3. Signal drift
    review.signal_drift = _check_signal_drift(trace, store)

    # 4. Prompt suggestions
    review.prompt_suggestions = _generate_prompt_suggestions(
        review.debate_quality, review.evidence_utilization, trace,
    )

    return review


def review_prediction(
    run_id: str,
    actual_price: float,
    storage_dir: str = "data/replays",
) -> PredictionReview:
    """Compare a run's prediction against the actual price outcome.

    Args:
        run_id: The run ID whose prediction to review.
        actual_price: The actual price observed after the prediction date.
        storage_dir: Path to ReplayStore directory.

    Returns:
        PredictionReview with direction comparison and lesson.

    Raises:
        ValueError: If the run_id is not found.
    """
    store = ReplayStore(storage_dir=storage_dir)
    trace = store.load(run_id)
    if trace is None:
        raise ValueError(f"Run not found: {run_id}")

    pr = PredictionReview(actual_price=actual_price)

    # Predicted direction from research_action
    action = trace.research_action or "HOLD"
    pr.predicted_direction = action

    # Determine entry price from ResearchOutput trade plan
    entry_price = 0.0
    for nt in trace.node_traces:
        if nt.node_name == _RESEARCH_OUTPUT_NODE:
            sd = nt.structured_data or {}
            tplan = sd.get("trade_plan", {})
            if tplan:
                ep = tplan.get("entry_price")
                if ep:
                    entry_price = _safe_float(ep)
            # Also try tradecard
            tc = sd.get("tradecard", {})
            if not entry_price and tc:
                entry_price = _safe_float(tc.get("entry_price", 0))
            break

    # Determine actual direction
    if entry_price > 0:
        pct_change = (actual_price - entry_price) / entry_price
        if pct_change > 0.02:
            pr.actual_direction = "up"
        elif pct_change < -0.02:
            pr.actual_direction = "down"
        else:
            pr.actual_direction = "flat"
    else:
        pr.actual_direction = "unknown"

    # Direction correctness
    action_upper = action.upper()
    if pr.actual_direction == "up":
        pr.direction_correct = action_upper == "BUY"
    elif pr.actual_direction == "down":
        pr.direction_correct = action_upper == "SELL"
    elif pr.actual_direction == "flat":
        pr.direction_correct = action_upper == "HOLD"
    else:
        pr.direction_correct = False

    # Scenario match
    scenario_node = _find_node(trace, "Scenario Agent")
    if scenario_node:
        sd = scenario_node.structured_data or {}
        base_prob = _safe_float(sd.get("base_prob", 0))
        bull_prob = _safe_float(sd.get("bull_prob", 0))
        bear_prob = _safe_float(sd.get("bear_prob", 0))

        if pr.actual_direction == "up" and bull_prob > 0:
            pr.scenario_hit = "bull"
        elif pr.actual_direction == "down" and bear_prob > 0:
            pr.scenario_hit = "bear"
        elif pr.actual_direction == "flat" and base_prob > 0:
            pr.scenario_hit = "base"
        else:
            pr.scenario_hit = ""

        # Key surprise: predicted one scenario but another materialized
        probs = {"base": base_prob, "bull": bull_prob, "bear": bear_prob}
        expected_scenario = max(probs, key=probs.get) if any(v > 0 for v in probs.values()) else ""
        if pr.scenario_hit and expected_scenario and pr.scenario_hit != expected_scenario:
            pr.key_surprise = (
                f"预期{expected_scenario}情景(概率{probs.get(expected_scenario, 0):.0%})，"
                f"实际{pr.scenario_hit}情景发生"
            )

    # Review date
    pr.review_date = trace.trade_date or ""

    # Generate lesson
    lessons = []
    if not pr.direction_correct and pr.actual_direction != "unknown":
        if action_upper == "BUY" and pr.actual_direction == "down":
            lessons.append("多头信号失败，需要加强下行风险评估")
        elif action_upper == "SELL" and pr.actual_direction == "up":
            lessons.append("空头信号失败，可能低估了正向催化因素")
        elif action_upper == "HOLD" and pr.actual_direction != "flat":
            lessons.append(
                f"HOLD信号但实际方向为{pr.actual_direction}，"
                "可能过于保守"
            )
    if pr.direction_correct:
        conf = trace.final_confidence
        if conf >= 0 and conf < 0.6:
            lessons.append("方向正确但置信度偏低，可提高conviction")
        elif conf >= 0.8:
            lessons.append("高置信度且方向正确，模型表现良好")
    if pr.key_surprise:
        lessons.append("情景预测偏差，建议复盘催化/风险因素权重")

    pr.lesson = "; ".join(lessons) if lessons else ""

    return pr
