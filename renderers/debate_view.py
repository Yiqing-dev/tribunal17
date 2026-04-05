"""AI Investment Committee — debate visualization data contract.

This module defines the front-end contract for rendering the multi-agent
debate process.  The builder function extracts structured debate data from
RunTrace objects and produces a DebateView that the renderer can consume
without touching raw protocol internals.
"""

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


# ── Participant ──────────────────────────────────────────────────────────

# Agent key → (Chinese role, English label, avatar CSS class, phase)
COMMITTEE_ROSTER = {
    "fundamentals_analyst": ("基本面分析师", "Fundamental Analyst", "avatar-fundamental", "初判"),
    "market_analyst":       ("技术面分析师", "Technical Analyst",    "avatar-technical",    "初判"),
    "news_analyst":         ("催化分析师",   "Catalyst Analyst",     "avatar-catalyst",     "初判"),
    "sentiment_analyst":    ("资金面分析师", "Flow Analyst",         "avatar-flow",         "初判"),
    "bull_researcher":      ("多方研究员",   "Bull Researcher",      "avatar-bull",         "辩论"),
    "bear_researcher":      ("空方研究员",   "Bear Researcher",      "avatar-bear",         "辩论"),
    "aggressive_debator":   ("进攻型风控",   "Aggressive Risk",      "avatar-aggr",         "风控辩论"),
    "conservative_debator": ("防守型风控",   "Conservative Risk",    "avatar-cons",         "风控辩论"),
    "neutral_debator":      ("平衡型风控",   "Balanced Risk",        "avatar-neut",         "风控辩论"),
    "research_manager":     ("研究主席",     "Research Chair",       "avatar-chair",        "裁决"),
    "risk_manager":         ("风控官",       "Risk Officer",         "avatar-risk",         "终审"),
}

# Stance → (Chinese label, CSS class)
STANCE_LABELS = {
    "bullish":      ("看多", "stance-bull"),
    "bearish":      ("看空", "stance-bear"),
    "neutral":      ("中性", "stance-neutral"),
    "cautious":     ("谨慎", "stance-cautious"),
    "aggressive":   ("进攻", "stance-bull"),
    "conservative": ("防守", "stance-bear"),
    "balanced":     ("平衡", "stance-neutral"),
}

ACTION_LABELS = {
    "BUY":  ("建议关注", "action-buy"),
    "HOLD": ("持有观望", "action-hold"),
    "SELL": ("建议回避", "action-sell"),
    "VETO": ("风控否决", "action-veto"),
}


@dataclass
class ParticipantView:
    """One member of the AI Investment Committee."""
    agent_key: str
    role_cn: str
    role_en: str
    avatar_class: str
    phase: str
    stance: str = ""           # bullish / bearish / neutral
    stance_label: str = ""     # 看多 / 看空 / 中性
    stance_class: str = ""
    contributed: bool = True   # False if agent had no output


@dataclass
class ClaimView:
    """A structured claim for the bull/bear arena."""
    claim_id: str = ""
    text: str = ""
    dimension: str = ""          # 基本面 / 估值 / 技术面 / ...
    strength: int = 0            # 0-100, from confidence × dimension_score
    confidence: float = 0.0      # 0.0-1.0
    source_agent: str = ""       # Chinese role name
    source_agent_en: str = ""    # English role
    evidence_tags: List[str] = field(default_factory=list)  # ["E1", "E3"]
    invalidation: str = ""


@dataclass
class TimelineEntry:
    """One speaker's contribution within a debate round."""
    speaker_cn: str = ""
    speaker_en: str = ""
    avatar_class: str = ""
    stance: str = ""
    stance_label: str = ""
    stance_class: str = ""
    summary: str = ""            # one-liner (not full text)
    evidence_refs: List[str] = field(default_factory=list)
    impact: str = ""             # positive / negative / neutral
    detail_text: str = ""        # expandable detail (optional)


@dataclass
class DebateRound:
    """One round of the debate timeline."""
    round_number: int = 0
    phase_label: str = ""        # 初判 / 多空辩论 / 场景推演 / 风控质疑 / 最终裁决
    phase_en: str = ""           # Initial / Bull-Bear / Scenario / Risk / Verdict
    entries: List[TimelineEntry] = field(default_factory=list)


@dataclass
class VerdictView:
    """Final actionable decision card."""
    action: str = "HOLD"
    action_label: str = "持有观望"
    action_class: str = "action-hold"
    confidence: float = 0.0
    confidence_pct: int = 0      # 0-100
    position_label: str = ""     # 轻仓 / 中仓 / 重仓
    trigger: str = ""            # what would confirm the trade
    invalidator: str = ""        # what would reverse the decision
    core_reason: str = ""        # one-sentence summary
    risk_score: int = 0          # 0-10
    risk_cleared: bool = True
    risk_flags: List[Dict] = field(default_factory=list)
    was_vetoed: bool = False


@dataclass
class DebateView:
    """Complete front-end contract for AI Investment Committee page.

    This is the single data object the renderer needs.  It contains
    everything required to render the 6-section committee page.
    """
    # ── Meta ──
    ticker: str = ""
    ticker_name: str = ""
    trade_date: str = ""
    run_id: str = ""

    # ── 1. Committee Roster ──
    participants: List[ParticipantView] = field(default_factory=list)

    # ── 2. Debate Timeline ──
    rounds: List[DebateRound] = field(default_factory=list)
    total_rounds: int = 0

    # ── 3. Bull/Bear Arena ──
    bull_claims: List[ClaimView] = field(default_factory=list)
    bear_claims: List[ClaimView] = field(default_factory=list)
    bull_score: float = 0.0
    bear_score: float = 0.0
    bull_ratio: float = 50.0     # 0-100, for visual bar

    # ── 4. Controversy Focus ──
    controversies: List[str] = field(default_factory=list)

    # ── 5. Final Verdict ──
    verdict: VerdictView = field(default_factory=VerdictView)

    # ── Market context (from market layer agents) ──
    market_regime: str = ""           # RISK_ON / NEUTRAL / RISK_OFF
    market_regime_label: str = ""     # 进攻 / 中性 / 防御
    market_weather: str = ""          # one-line Chinese summary
    market_wind: str = ""             # 顺风 / 逆风 / 中性
    market_wind_reason: str = ""      # why wind direction
    position_cap_multiplier: float = 1.0
    sector_leaders: List[str] = field(default_factory=list)
    avoid_sectors: List[str] = field(default_factory=list)

    # ── 6. Audit Summary ──
    total_evidence: int = 0
    total_claims: int = 0
    conflict_level: str = "medium"    # high / medium / low
    consensus_level: str = "medium"   # high / medium / low
    conflict_label: str = "分歧中等"
    consensus_label: str = "收敛中等"
    report_url: str = ""              # link to full research report

    def to_dict(self) -> dict:
        return asdict(self)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Builder — RunTrace → DebateView                                       ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def _stance_for_agent(agent_key: str, sd: dict) -> str:
    """Infer stance from agent output."""
    if agent_key in ("bull_researcher", "aggressive_debator"):
        return "bullish"
    if agent_key in ("bear_researcher", "conservative_debator"):
        return "bearish"
    if agent_key in ("neutral_debator",):
        return "neutral"
    # For analysts, infer from pillar_score or overall direction
    score = sd.get("pillar_score")
    if score is not None:
        if score >= 3:
            return "bullish"
        if score <= 1:
            return "bearish"
    action = sd.get("research_action", "").upper()
    if action == "BUY":
        return "bullish"
    if action in ("SELL", "VETO"):
        return "bearish"
    return "neutral"


def _one_line_summary(agent_key: str, sd: dict, excerpt: str) -> str:
    """Extract a one-line summary from structured data or excerpt."""
    # PM / Risk have conclusion
    conclusion = sd.get("conclusion", "")
    if conclusion and len(conclusion) < 200:
        return conclusion[:120]

    # Claims-based agents: use first claim text
    claims = sd.get("supporting_claims", [])
    if claims and claims[0].get("text"):
        return claims[0]["text"][:120]

    # Fall back to excerpt first sentence
    if excerpt:
        first = excerpt.split("。")[0].split("\n")[0]
        return first[:120]
    return ""


def _position_label(pct: float) -> str:
    """Convert max_position_pct to human label."""
    if pct <= 0.02:
        return "极轻仓"
    if pct <= 0.03:
        return "轻仓"
    if pct <= 0.05:
        return "中仓"
    return "重仓"


def build_debate_view(run_trace) -> DebateView:
    """Build a DebateView from a RunTrace object.

    Works with both live RunTrace instances and dict-deserialized traces.
    """
    # Handle both dict and object
    mkt_ctx: Dict = {}
    if isinstance(run_trace, dict):
        # Support two dict formats:
        # 1. Fixture: {"meta": {...}, "nodes": [...], "market_context": {...}}
        # 2. RunTrace.to_dict(): {"ticker": ..., "node_traces": [...], "market_context": {...}}
        meta = run_trace.get("meta", {})
        nodes = run_trace.get("nodes", []) or run_trace.get("node_traces", [])
        ticker = meta.get("ticker", "") or run_trace.get("ticker", "")
        ticker_name = meta.get("ticker_name", "") or run_trace.get("ticker_name", "")
        trade_date = (meta.get("trade_date", meta.get("as_of", ""))
                      or run_trace.get("trade_date", run_trace.get("as_of", "")))
        run_id = meta.get("run_id", "") or run_trace.get("run_id", "")
        mkt_ctx = run_trace.get("market_context", {}) or {}
    else:
        nodes = []
        for nt in getattr(run_trace, "node_traces", []):
            n = {
                "node_name": nt.node_name,
                "seq": nt.seq,
                "structured_data": nt.structured_data or {},
                "output_excerpt": nt.output_excerpt or "",
                "parse_status": getattr(nt, "parse_status", ""),
                "evidence_ids_referenced": getattr(nt, "evidence_ids_referenced", []),
                "claim_ids_produced": getattr(nt, "claim_ids_produced", []),
            }
            nodes.append(n)
        ticker = getattr(run_trace, "ticker", "")
        ticker_name = getattr(run_trace, "ticker_name", "")
        mkt_ctx = getattr(run_trace, "market_context", {}) or {}
        trade_date = getattr(run_trace, "trade_date", "")
        run_id = getattr(run_trace, "run_id", "")

    # Reverse map: node_name → agent_key
    from ..bridge import AGENT_NODE_MAP
    name_to_key = {v: k for k, v in AGENT_NODE_MAP.items()}

    # Index nodes by agent_key
    node_by_key: Dict[str, dict] = {}
    for n in nodes:
        key = name_to_key.get(n["node_name"], "")
        if key:
            node_by_key[key] = n

    # ── 1. Participants ──────────────────────────────────────────────
    participants = []
    for agent_key, (role_cn, role_en, avatar, phase) in COMMITTEE_ROSTER.items():
        node = node_by_key.get(agent_key)
        sd = node.get("structured_data", {}) if node else {}
        stance = _stance_for_agent(agent_key, sd) if node else ""
        sl, sc = STANCE_LABELS.get(stance, ("", ""))
        participants.append(ParticipantView(
            agent_key=agent_key,
            role_cn=role_cn,
            role_en=role_en,
            avatar_class=avatar,
            phase=phase,
            stance=stance,
            stance_label=sl,
            stance_class=sc,
            contributed=node is not None,
        ))

    # ── 2. Timeline ──────────────────────────────────────────────────
    rounds = []

    # Round 1: Initial assessments (4 analysts)
    r1_entries = []
    for ak in ("fundamentals_analyst", "market_analyst", "news_analyst", "sentiment_analyst"):
        node = node_by_key.get(ak)
        if not node:
            continue
        sd = node.get("structured_data", {})
        excerpt = node.get("output_excerpt", "")
        stance = _stance_for_agent(ak, sd)
        role_cn = COMMITTEE_ROSTER[ak][0]
        role_en = COMMITTEE_ROSTER[ak][1]
        avatar = COMMITTEE_ROSTER[ak][2]
        sl, sc = STANCE_LABELS.get(stance, ("", ""))
        summary = _one_line_summary(ak, sd, excerpt)
        ev_refs = sd.get("evidence_ids", []) or node.get("evidence_ids_referenced", [])
        r1_entries.append(TimelineEntry(
            speaker_cn=role_cn, speaker_en=role_en, avatar_class=avatar,
            stance=stance, stance_label=sl, stance_class=sc,
            summary=summary, evidence_refs=ev_refs[:5],
            impact="positive" if stance == "bullish" else "negative" if stance == "bearish" else "neutral",
        ))
    if r1_entries:
        rounds.append(DebateRound(
            round_number=1, phase_label="初判", phase_en="Initial Assessment",
            entries=r1_entries,
        ))

    # Round 2: Bull/Bear debate
    r2_entries = []
    for ak in ("bull_researcher", "bear_researcher"):
        node = node_by_key.get(ak)
        if not node:
            continue
        sd = node.get("structured_data", {})
        excerpt = node.get("output_excerpt", "")
        stance = _stance_for_agent(ak, sd)
        role_cn = COMMITTEE_ROSTER[ak][0]
        role_en = COMMITTEE_ROSTER[ak][1]
        avatar = COMMITTEE_ROSTER[ak][2]
        sl, sc = STANCE_LABELS.get(stance, ("", ""))
        claims = sd.get("supporting_claims", [])
        first_text = (claims[0].get("text") or "") if claims else ""
        summary = first_text[:120] if first_text else _one_line_summary(ak, sd, excerpt)
        ev_refs = []
        for c in claims[:3]:
            ev_refs.extend(c.get("supports", []))
        r2_entries.append(TimelineEntry(
            speaker_cn=role_cn, speaker_en=role_en, avatar_class=avatar,
            stance=stance, stance_label=sl, stance_class=sc,
            summary=summary, evidence_refs=list(dict.fromkeys(ev_refs))[:5],
            impact="positive" if stance == "bullish" else "negative",
        ))
    if r2_entries:
        rounds.append(DebateRound(
            round_number=2, phase_label="多空辩论", phase_en="Bull-Bear Debate",
            entries=r2_entries,
        ))

    # Round 3: Scenario (if exists)
    scenario_node = node_by_key.get("scenario_agent")
    if scenario_node:
        sd = scenario_node.get("structured_data", {})
        base_p = sd.get("base_prob", 0)
        bull_p = sd.get("bull_prob", 0)
        bear_p = sd.get("bear_prob", 0)
        summary = f"基准 {base_p}% / 乐观 {bull_p}% / 悲观 {bear_p}%"
        if sd.get("base_trigger"):
            summary += f"，关键触发: {sd['base_trigger'][:60]}"
        rounds.append(DebateRound(
            round_number=3, phase_label="场景推演", phase_en="Scenario Analysis",
            entries=[TimelineEntry(
                speaker_cn="场景分析师", speaker_en="Scenario Agent",
                avatar_class="avatar-scenario", stance="neutral",
                stance_label="中性", stance_class="stance-neutral",
                summary=summary,
            )],
        ))

    # Round 4: Risk debate
    r4_entries = []
    for ak in ("aggressive_debator", "conservative_debator", "neutral_debator"):
        node = node_by_key.get(ak)
        if not node:
            continue
        sd = node.get("structured_data", {})
        excerpt = node.get("output_excerpt", "")
        stance = _stance_for_agent(ak, sd)
        role_cn = COMMITTEE_ROSTER[ak][0]
        role_en = COMMITTEE_ROSTER[ak][1]
        avatar = COMMITTEE_ROSTER[ak][2]
        sl, sc = STANCE_LABELS.get(stance, ("", ""))
        summary = _one_line_summary(ak, sd, excerpt)
        r4_entries.append(TimelineEntry(
            speaker_cn=role_cn, speaker_en=role_en, avatar_class=avatar,
            stance=stance, stance_label=sl, stance_class=sc,
            summary=summary,
            impact="positive" if stance == "bullish" else "negative" if stance == "bearish" else "neutral",
        ))
    if r4_entries:
        rounds.append(DebateRound(
            round_number=4, phase_label="风控质疑", phase_en="Risk Challenge",
            entries=r4_entries,
        ))

    # Round 5: Verdict (PM + Risk Judge)
    r5_entries = []
    for ak in ("research_manager", "risk_manager"):
        node = node_by_key.get(ak)
        if not node:
            continue
        sd = node.get("structured_data", {})
        excerpt = node.get("output_excerpt", "")
        stance = _stance_for_agent(ak, sd)
        role_cn = COMMITTEE_ROSTER[ak][0]
        role_en = COMMITTEE_ROSTER[ak][1]
        avatar = COMMITTEE_ROSTER[ak][2]
        sl, sc = STANCE_LABELS.get(stance, ("", ""))
        summary = _one_line_summary(ak, sd, excerpt)
        r5_entries.append(TimelineEntry(
            speaker_cn=role_cn, speaker_en=role_en, avatar_class=avatar,
            stance=stance, stance_label=sl, stance_class=sc,
            summary=summary,
            impact="positive" if stance == "bullish" else "negative" if stance == "bearish" else "neutral",
        ))
    if r5_entries:
        rounds.append(DebateRound(
            round_number=5, phase_label="最终裁决", phase_en="Final Verdict",
            entries=r5_entries,
        ))

    # ── 3. Bull/Bear Arena ───────────────────────────────────────────
    bull_claims: List[ClaimView] = []
    bear_claims: List[ClaimView] = []

    bull_node = node_by_key.get("bull_researcher")
    if bull_node:
        sd = bull_node.get("structured_data", {})
        for c in sd.get("supporting_claims", []):
            conf = c.get("confidence", 0.5)
            dim_score = c.get("dimension_score") or 5
            strength = min(100, int(conf * dim_score * 10))
            bull_claims.append(ClaimView(
                claim_id=c.get("claim_id", ""),
                text=c.get("text", ""),
                dimension=c.get("dimension", ""),
                strength=strength,
                confidence=conf,
                source_agent="多方研究员",
                source_agent_en="Bull Researcher",
                evidence_tags=c.get("supports", [])[:5],
                invalidation=c.get("invalidation", ""),
            ))
    bull_claims.sort(key=lambda x: x.strength, reverse=True)
    bull_claims = bull_claims[:5]

    bear_node = node_by_key.get("bear_researcher")
    if bear_node:
        sd = bear_node.get("structured_data", {})
        for c in sd.get("supporting_claims", []):
            conf = c.get("confidence", 0.5)
            dim_score = c.get("dimension_score") or 5
            strength = min(100, int(conf * dim_score * 10))
            bear_claims.append(ClaimView(
                claim_id=c.get("claim_id", ""),
                text=c.get("text", ""),
                dimension=c.get("dimension", ""),
                strength=strength,
                confidence=conf,
                source_agent="空方研究员",
                source_agent_en="Bear Researcher",
                evidence_tags=c.get("supports", [])[:5],
                invalidation=c.get("invalidation", ""),
            ))
    bear_claims.sort(key=lambda x: x.strength, reverse=True)
    bear_claims = bear_claims[:5]

    bull_score = sum(c.confidence for c in bull_claims)
    bear_score = sum(c.confidence for c in bear_claims)
    total_score = bull_score + bear_score
    bull_ratio = (bull_score / total_score * 100) if total_score > 0 else 50.0

    # ── 4. Controversies ─────────────────────────────────────────────
    controversies = []
    # From debate packet unresolved conflicts
    pm_node = node_by_key.get("research_manager")
    if pm_node:
        sd = pm_node.get("structured_data", {})
        for q in sd.get("open_questions", []):
            if q and len(q) > 5:
                controversies.append(q)

    # From opposing dimensions: if both sides have high-confidence claims
    # on the same dimension, that's a controversy
    bull_dims = {c.dimension: c for c in bull_claims if c.dimension}
    bear_dims = {c.dimension: c for c in bear_claims if c.dimension}
    for dim in set(bull_dims) & set(bear_dims):
        bc, brc = bull_dims[dim], bear_dims[dim]
        if bc.confidence >= 0.5 and brc.confidence >= 0.5:
            short = f"{dim}维度存在分歧：多方认为{bc.text[:30]}，空方认为{brc.text[:30]}"
            if short not in controversies:
                controversies.append(short)

    controversies = controversies[:5]

    # ── 5. Verdict ───────────────────────────────────────────────────
    verdict = VerdictView()
    risk_node = node_by_key.get("risk_manager")

    if pm_node:
        sd = pm_node.get("structured_data", {})
        action = sd.get("research_action", "HOLD").upper()
        al, ac = ACTION_LABELS.get(action, ("持有观望", "action-hold"))
        conf = sd.get("confidence", 0.5)
        pos_pct = sd.get("target_position_pct") or sd.get("max_position_pct") or 0.05
        invalidation = sd.get("invalidation", "")
        if isinstance(invalidation, list):
            invalidation = "；".join(invalidation[:3])

        verdict = VerdictView(
            action=action,
            action_label=al,
            action_class=ac,
            confidence=conf,
            confidence_pct=int(conf * 100),
            position_label=_position_label(pos_pct),
            trigger=sd.get("bull_case", "")[:80] if sd.get("bull_case") else "",
            invalidator=invalidation[:120],
            core_reason=sd.get("conclusion", "")[:120],
        )

    if risk_node:
        rsd = risk_node.get("structured_data", {})
        verdict.risk_score = rsd.get("risk_score", 0) or 0
        verdict.risk_cleared = rsd.get("risk_cleared", True)
        verdict.risk_flags = rsd.get("risk_flags", [])[:5]
        verdict.was_vetoed = rsd.get("research_action", "").upper() == "VETO"
        if verdict.was_vetoed:
            verdict.action = "VETO"
            al, ac = ACTION_LABELS["VETO"]
            verdict.action_label = al
            verdict.action_class = ac

    # ── 6. Audit Summary ────────────────────────────────────────────
    total_evidence = 0
    total_claims_count = 0
    for n in nodes:
        total_evidence += len(n.get("evidence_ids_referenced", []))
        total_claims_count += len(n.get("claim_ids_produced", []))

    score_diff = abs(bull_score - bear_score)
    if score_diff < 0.3:
        conflict_level, conflict_label = "high", "分歧较大"
    elif score_diff < 0.8:
        conflict_level, conflict_label = "medium", "分歧中等"
    else:
        conflict_level, conflict_label = "low", "分歧较小"

    consensus_level = "high" if verdict.confidence >= 0.7 else "medium" if verdict.confidence >= 0.5 else "low"
    consensus_label = "已收敛" if consensus_level == "high" else "基本收敛" if consensus_level == "medium" else "待观察"

    # ── Market context → wind direction ────────────────────────────
    regime = str(mkt_ctx.get("regime", "")).upper()
    regime_labels = {"RISK_ON": "进攻", "RISK_OFF": "防御", "NEUTRAL": "中性"}
    regime_label = regime_labels.get(regime, "")
    market_weather = str(mkt_ctx.get("market_weather", ""))
    pcm = mkt_ctx.get("position_cap_multiplier", 1.0)
    leaders = mkt_ctx.get("sector_leaders", [])
    avoid = mkt_ctx.get("avoid_sectors", [])

    # Determine wind: action vs regime alignment
    action = verdict.action.upper()
    if regime == "RISK_ON" and action == "BUY":
        market_wind, market_wind_reason = "顺风", "市场进攻 + 个股看多"
    elif regime == "RISK_OFF" and action == "BUY":
        market_wind, market_wind_reason = "逆风", "市场防御但个股看多，逆势操作需额外确认"
    elif regime == "RISK_OFF" and action in ("SELL", "VETO"):
        market_wind, market_wind_reason = "顺风", "市场防御 + 个股规避，方向一致"
    elif regime == "RISK_ON" and action in ("SELL", "VETO"):
        market_wind, market_wind_reason = "逆风", "市场进攻但个股规避，需确认个股特有风险"
    elif regime:
        market_wind, market_wind_reason = "中性", "市场中性，不构成额外加减分"
    else:
        market_wind, market_wind_reason = "", ""

    return DebateView(
        ticker=ticker,
        ticker_name=ticker_name,
        trade_date=trade_date,
        run_id=run_id,
        participants=participants,
        rounds=rounds,
        total_rounds=len(rounds),
        bull_claims=bull_claims,
        bear_claims=bear_claims,
        bull_score=round(bull_score, 2),
        bear_score=round(bear_score, 2),
        bull_ratio=round(bull_ratio, 1),
        controversies=controversies,
        verdict=verdict,
        market_regime=regime,
        market_regime_label=regime_label,
        market_weather=market_weather,
        market_wind=market_wind,
        market_wind_reason=market_wind_reason,
        position_cap_multiplier=pcm if isinstance(pcm, (int, float)) else 1.0,
        sector_leaders=leaders if isinstance(leaders, list) else [],
        avoid_sectors=avoid if isinstance(avoid, list) else [],
        total_evidence=total_evidence,
        total_claims=total_claims_count,
        conflict_level=conflict_level,
        conflict_label=conflict_label,
        consensus_level=consensus_level,
        consensus_label=consensus_label,
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Demo fixture — realistic data for HTML prototype                      ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def build_demo_debate_view() -> DebateView:
    """Build a realistic DebateView for demo/mockup purposes.

    Based on actual pipeline output structure for 601985 中国核电.
    """
    participants = []
    for ak, (rcn, ren, av, ph) in COMMITTEE_ROSTER.items():
        stance_map = {
            "fundamentals_analyst": "bullish",
            "market_analyst": "neutral",
            "news_analyst": "bullish",
            "sentiment_analyst": "neutral",
            "bull_researcher": "bullish",
            "bear_researcher": "bearish",
            "aggressive_debator": "bullish",
            "conservative_debator": "bearish",
            "neutral_debator": "neutral",
            "research_manager": "bullish",
            "risk_manager": "neutral",
        }
        st = stance_map.get(ak, "neutral")
        sl, sc = STANCE_LABELS.get(st, ("", ""))
        participants.append(ParticipantView(
            agent_key=ak, role_cn=rcn, role_en=ren,
            avatar_class=av, phase=ph,
            stance=st, stance_label=sl, stance_class=sc,
        ))

    rounds = [
        DebateRound(
            round_number=1, phase_label="初判", phase_en="Initial Assessment",
            entries=[
                TimelineEntry(
                    speaker_cn="基本面分析师", speaker_en="Fundamental Analyst",
                    avatar_class="avatar-fundamental", stance="bullish",
                    stance_label="看多", stance_class="stance-bull",
                    summary="营收与利润持续稳增，核电机组利用率保持高位，现金流充裕，分红稳定",
                    evidence_refs=["E1", "E2", "E5"],
                    impact="positive",
                ),
                TimelineEntry(
                    speaker_cn="技术面分析师", speaker_en="Technical Analyst",
                    avatar_class="avatar-technical", stance="neutral",
                    stance_label="中性", stance_class="stance-neutral",
                    summary="股价在14日均线附近震荡，趋势刚转强但量能不足，MACD红柱缩短",
                    evidence_refs=["E3", "E4"],
                    impact="neutral",
                ),
                TimelineEntry(
                    speaker_cn="催化分析师", speaker_en="Catalyst Analyst",
                    avatar_class="avatar-catalyst", stance="bullish",
                    stance_label="看多", stance_class="stance-bull",
                    summary="核电审批重启加速，预计年内再批2-3台机组，政策催化持续性较强",
                    evidence_refs=["E6", "E7"],
                    impact="positive",
                ),
                TimelineEntry(
                    speaker_cn="资金面分析师", speaker_en="Flow Analyst",
                    avatar_class="avatar-flow", stance="neutral",
                    stance_label="中性", stance_class="stance-neutral",
                    summary="北向资金近5日小幅净流入，融资余额持平，机构持仓未见明显变化",
                    evidence_refs=["E8"],
                    impact="neutral",
                ),
            ],
        ),
        DebateRound(
            round_number=2, phase_label="多空辩论", phase_en="Bull-Bear Debate",
            entries=[
                TimelineEntry(
                    speaker_cn="多方研究员", speaker_en="Bull Researcher",
                    avatar_class="avatar-bull", stance="bullish",
                    stance_label="看多", stance_class="stance-bull",
                    summary="核电审批加速确认增长路径，机组投产高峰将释放业绩弹性，估值仍有空间",
                    evidence_refs=["E1", "E5", "E6", "E7"],
                    impact="positive",
                ),
                TimelineEntry(
                    speaker_cn="空方研究员", speaker_en="Bear Researcher",
                    avatar_class="avatar-bear", stance="bearish",
                    stance_label="看空", stance_class="stance-bear",
                    summary="电价下行压力加大，利润增速可能不及预期，当前估值已透支部分增长预期",
                    evidence_refs=["E9", "E10", "E11"],
                    impact="negative",
                ),
            ],
        ),
        DebateRound(
            round_number=3, phase_label="场景推演", phase_en="Scenario Analysis",
            entries=[
                TimelineEntry(
                    speaker_cn="场景分析师", speaker_en="Scenario Agent",
                    avatar_class="avatar-scenario", stance="neutral",
                    stance_label="中性", stance_class="stance-neutral",
                    summary="基准 55% / 乐观 25% / 悲观 20%，关键触发: 下季度机组投产进度确认",
                    impact="neutral",
                ),
            ],
        ),
        DebateRound(
            round_number=4, phase_label="风控质疑", phase_en="Risk Challenge",
            entries=[
                TimelineEntry(
                    speaker_cn="进攻型风控", speaker_en="Aggressive Risk",
                    avatar_class="avatar-aggr", stance="bullish",
                    stance_label="看多", stance_class="stance-bull",
                    summary="核电是确定性增长赛道，下行风险有限，建议提高仓位捕捉板块共振机会",
                    impact="positive",
                ),
                TimelineEntry(
                    speaker_cn="防守型风控", speaker_en="Conservative Risk",
                    avatar_class="avatar-cons", stance="bearish",
                    stance_label="看空", stance_class="stance-bear",
                    summary="利润增速放缓趋势不可忽视，若电价改革不及预期，当前位置风险收益比不佳",
                    impact="negative",
                ),
                TimelineEntry(
                    speaker_cn="平衡型风控", speaker_en="Balanced Risk",
                    avatar_class="avatar-neut", stance="neutral",
                    stance_label="中性", stance_class="stance-neutral",
                    summary="基本面逻辑成立但需等待量价确认，建议中仓买入并设定明确止损",
                    impact="neutral",
                ),
            ],
        ),
        DebateRound(
            round_number=5, phase_label="最终裁决", phase_en="Final Verdict",
            entries=[
                TimelineEntry(
                    speaker_cn="研究主席", speaker_en="Research Chair",
                    avatar_class="avatar-chair", stance="bullish",
                    stance_label="看多", stance_class="stance-bull",
                    summary="维持 BUY，核电增长逻辑未被推翻，但降低目标仓位至中仓，附加放量确认条件",
                    impact="positive",
                ),
                TimelineEntry(
                    speaker_cn="风控官", speaker_en="Risk Officer",
                    avatar_class="avatar-risk", stance="neutral",
                    stance_label="中性", stance_class="stance-neutral",
                    summary="风控通过，风险评分4/10，未触发否决条件。标注估值风险和电价政策风险",
                    impact="neutral",
                ),
            ],
        ),
    ]

    bull_claims = [
        ClaimView(claim_id="clm-b001", text="核电审批重启加速，年内预计再批2-3台机组，增长确定性较强",
                  dimension="催化剂", strength=85, confidence=0.85,
                  source_agent="多方研究员", source_agent_en="Bull Researcher",
                  evidence_tags=["E6", "E7"], invalidation="审批政策突然收紧"),
        ClaimView(claim_id="clm-b002", text="在运机组利用率持续高位，产能利用充分支撑业绩增长",
                  dimension="基本面", strength=78, confidence=0.78,
                  source_agent="多方研究员", source_agent_en="Bull Researcher",
                  evidence_tags=["E1", "E2"], invalidation="利用率大幅下滑"),
        ClaimView(claim_id="clm-b003", text="核电板块处于主线轮动内，市场环境加分",
                  dimension="资金面", strength=71, confidence=0.71,
                  source_agent="资金面分析师", source_agent_en="Flow Analyst",
                  evidence_tags=["E8"], invalidation="板块资金持续流出"),
    ]

    bear_claims = [
        ClaimView(claim_id="clm-r001", text="电价市场化改革推进中，下行压力将压缩利润率空间",
                  dimension="基本面", strength=83, confidence=0.83,
                  source_agent="空方研究员", source_agent_en="Bear Researcher",
                  evidence_tags=["E9", "E10"], invalidation="电价政策转向支持核电"),
        ClaimView(claim_id="clm-r002", text="当前PE已高于5年均值，估值透支未来2个季度增长",
                  dimension="估值", strength=76, confidence=0.76,
                  source_agent="空方研究员", source_agent_en="Bear Researcher",
                  evidence_tags=["E11"], invalidation="业绩超预期大幅提升"),
        ClaimView(claim_id="clm-r003", text="利润弹性弱于收入增长，边际回报递减趋势明显",
                  dimension="基本面", strength=68, confidence=0.68,
                  source_agent="空方研究员", source_agent_en="Bear Researcher",
                  evidence_tags=["E9"], invalidation="成本端出现重大利好"),
    ]

    controversies = [
        "当前估值是否已透支未来2个季度增长预期",
        "电价市场化改革对利润率的实际影响幅度",
        "技术面放量突破是否已成立，还是假突破风险",
        "核电审批政策的持续性是否足够支撑长期逻辑",
    ]

    verdict = VerdictView(
        action="BUY",
        action_label="建议关注",
        action_class="action-buy",
        confidence=0.72,
        confidence_pct=72,
        position_label="中仓",
        trigger="放量突破前高且板块维持强势",
        invalidator="跌破14日均线且板块转弱，或电价政策不及预期",
        core_reason="基本面稳定，核电增长逻辑未被推翻，板块顺风，但需等待技术确认",
        risk_score=4,
        risk_cleared=True,
        risk_flags=[
            {"category": "估值风险", "severity": "medium", "description": "PE高于5年均值"},
            {"category": "政策风险", "severity": "low", "description": "电价改革方向不确定"},
        ],
    )

    bs = sum(c.confidence for c in bull_claims)
    brs = sum(c.confidence for c in bear_claims)
    total = bs + brs

    return DebateView(
        ticker="601985.SS",
        ticker_name="中国核电",
        trade_date="2026-03-13",
        run_id="run-demo-001",
        participants=participants,
        rounds=rounds,
        total_rounds=5,
        bull_claims=bull_claims,
        bear_claims=bear_claims,
        bull_score=round(bs, 2),
        bear_score=round(brs, 2),
        bull_ratio=round(bs / total * 100, 1) if total else 50,
        controversies=controversies,
        verdict=verdict,
        market_regime="RISK_ON",
        market_regime_label="进攻",
        market_weather="市场处于进攻状态，核电板块处于主线轮动中，北向资金持续净买入",
        market_wind="顺风",
        market_wind_reason="市场进攻 + 个股看多",
        position_cap_multiplier=1.0,
        sector_leaders=["核电", "半导体", "新能源"],
        avoid_sectors=["房地产", "教育"],
        total_evidence=11,
        total_claims=6,
        conflict_level="medium",
        conflict_label="分歧中等",
        consensus_level="high",
        consensus_label="已收敛",
        report_url="/runs/run-demo-001",
    )
