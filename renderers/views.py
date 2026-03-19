"""
Read models for the dashboard — the contract between routes and templates.

These reshape ReplayService outputs into presentation-ready objects.
Templates receive these views, never raw NodeTrace/RunTrace instances.

Three-tier report hierarchy (same evidence chain, different compression):
- Tier 1 SnapshotView: Conclusion + signals + brief risk (single screen)
- Tier 2 ResearchView: Full research logic — bull/bear, evidence, scenarios, thesis
- Tier 3 AuditView:    Trustworthiness — evidence chains, replay, parser, compliance, history
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ..replay_service import ReplayService
from ..trace_models import RunMetrics, RunTrace


# ── Shared utilities ──────────────────────────────────────────────────

def _strip_internal_tokens(text: str) -> str:
    """Remove internal system tokens from user-facing text.

    Strips: LLM preambles, clm-xxxx, Bull/Bear Claim N, E1/E2/E3,
    CITED_EVIDENCE blocks, hex ID bracket lists, Chinese internal terms,
    markdown ** artifacts, and internal action words.
    """
    if not text:
        return text

    # ── LLM preamble removal (full leading sentences) ──
    from .decision_labels import INTERNAL_TOKEN_PREFIXES
    # Strip leading lines that are LLM self-introductions
    lines = text.split("\n")
    cleaned_lines = []
    still_leading = True
    for line in lines:
        stripped = line.strip()
        if still_leading and any(stripped.startswith(p) for p in INTERNAL_TOKEN_PREFIXES):
            continue
        still_leading = False
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines).strip()

    # ── Internal ID patterns ──
    # clm-xxxx hex IDs (any length after prefix)
    text = re.sub(r'clm-[0-9a-f]+', '', text)
    # Standalone hex IDs like 79107dc0-2, ab5df0c6
    text = re.sub(r'\b[0-9a-f]{6,}-?\d*\b', '', text)
    # Bracket-enclosed ID lists: [-1, 79107dc0-2, 79107dc0-5]
    text = re.sub(r'\[[\s,\-\d0-9a-f]*\]', '', text)
    # Bull/Bear Claim references (with comma-separated numbers or bracket list)
    text = re.sub(r'Bull\s+Claim(?:\s+\d+(?:\s*,\s*\d+)*|\s*\[[^\]]*\])?', '', text)
    text = re.sub(r'Bear\s+Claim(?:\s+\d+(?:\s*,\s*\d+)*|\s*\[[^\]]*\])?', '', text)
    # Bull/Bear with bracket list (no "Claim"): Bull [clm-1]
    text = re.sub(r'Bull\s*\[[^\]]*\]', '', text)
    text = re.sub(r'Bear\s*\[[^\]]*\]', '', text)
    # Evidence IDs like E1, E2 (standalone or bracketed [E1], [E8])
    text = re.sub(r'\[E\d+\]', '', text)
    text = re.sub(r'\bE\d+\b', '', text)
    # CITED_EVIDENCE blocks (with optional ** markdown)
    text = re.sub(r'\*{0,2}CITED_EVIDENCE\*{0,2}:?\s*\[[^\]]*\]', '', text)

    # ── Chinese internal terms ──
    text = re.sub(r'熊派主张', '看空观点', text)
    text = re.sub(r'牛派主张', '看多观点', text)
    text = re.sub(r'结构化主张', '', text)
    text = re.sub(r'仲裁', '综合判断', text)
    # Structured reference markers: （支持clm-xxx,2）or (反对...)
    text = re.sub(r'[（(]支持[^)）]*[)）]', '', text)
    text = re.sub(r'[（(]反对[^)）]*[)）]', '', text)

    # ── Markdown artifacts ──
    text = re.sub(r'\*\*', '', text)

    # ── Tone moderation: soften extreme superlatives from bull/bear advocacy ──
    from .decision_labels import TONE_MODERATION_MAP
    for extreme, moderate in TONE_MODERATION_MAP.items():
        text = text.replace(extreme, moderate)

    # ── Cleanup: empty brackets/parens, repeated commas/punctuation, extra whitespace ──
    text = re.sub(r'\[\s*\]', '', text)
    text = re.sub(r'[（(]\s*[,，]?\s*[)）]', '', text)  # （,） or ()
    # Dangling preposition phrases left after ID stripping
    text = re.sub(r'基于对\s*和?\s*的', '', text)
    text = re.sub(r'对\s+和\s+的', '的', text)
    text = re.sub(r'[,，]\s*[,，]', '，', text)
    text = re.sub(r'、\s*、', '、', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def _enforce_thesis_limit(text: str, max_chars: int = 50) -> str:
    """Enforce single-sentence, max_chars limit on thesis text."""
    text = _strip_internal_tokens(text)
    if not text:
        return text
    # Try to cut at first sentence boundary within limit
    for sep in ("。", "；"):
        idx = text.find(sep)
        if 0 < idx <= max_chars:
            return text[:idx + 1]
    # If no sentence boundary, hard cut
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def _check_degradation(
    metrics: Optional[RunMetrics],
    nodes_list: list,
    failures: list,
) -> Tuple[bool, List[str]]:
    """Check if a report should enter Degraded Mode.

    Criteria (any one triggers):
    - strict_parse_rate < 60%
    - claim_to_evidence_binding_rate < 30%
    - ≥2 nodes with fallback/failed parse status or unattributed claims

    Note: replay_completeness_rate is intentionally NOT used here.
    It measures trace coverage (whether analyst nodes were instrumented),
    not output quality. A run can be high quality with 64% completeness
    if the missing nodes are analysts that don't produce structured claims.

    Returns (is_degraded, reasons).
    """
    reasons = []

    if metrics:
        if metrics.strict_parse_rate < 0.60:
            reasons.append(f"AI输出解析率仅 {metrics.strict_parse_rate:.0%}，低于60%阈值")
        if metrics.claim_to_evidence_binding_rate < 0.30:
            reasons.append(f"论据-证据绑定率仅 {metrics.claim_to_evidence_binding_rate:.0%}，低于30%阈值")

    # Count weak nodes: fallback or failed parse
    weak_names = set()
    for n in nodes_list:
        ps = n.get("parse_status", "")
        if ps in ("fallback_used", "failed"):
            weak_names.add(n.get("node_name", ""))

    # Also count nodes with unattributed claims
    for f in failures:
        for issue in f.get("issues", []):
            if issue.get("type") == "unattributed_claims":
                weak_names.add(f.get("node_name", ""))

    if len(weak_names) >= 2:
        from .decision_labels import get_node_label
        labels = [get_node_label(n) for n in list(weak_names)[:3]]
        reasons.append(f"{len(weak_names)}个研究节点使用回退解析（{' / '.join(labels)}）")

    return bool(reasons), reasons


# ── Banner ────────────────────────────────────────────────────────────────

@dataclass
class BannerView:
    """AI-generated content banner displayed on every run-scoped page."""
    ai_label: str = ""
    source_count: int = 0
    compliance_status: str = ""
    compliance_class: str = ""   # CSS class: allow / downgrade / review / block
    timestamp: str = ""

    @classmethod
    def from_trace(cls, trace: RunTrace) -> "BannerView":
        AI_CONTENT_LABEL_ZH = (
            "\u26a0\ufe0f \u672c\u5185\u5bb9\u7531 AI \u8f85\u52a9\u751f\u6210\uff0c"
            "\u57fa\u4e8e\u516c\u5f00\u5e02\u573a\u6570\u636e\u4e0e\u5b98\u65b9\u62ab\u9732\u6587\u4ef6\u3002"
            "AI \u5206\u6790\u7ed3\u679c\u4ec5\u4f9b\u53c2\u8003\uff0c\u4e0d\u6784\u6210\u6295\u8d44\u5efa\u8bae\u3002"
            "\u6570\u636e\u6765\u6e90\u4e0e\u63a8\u7406\u8fc7\u7a0b\u53ef\u901a\u8fc7\u8bc1\u636e\u94fe\u8ffd\u6eaf\u3002"
        )
        status = trace.compliance_status or "unknown"
        badge_map = {
            "allow": "allow",
            "downgrade": "downgrade",
            "review": "review",
            "block": "block",
        }
        return cls(
            ai_label=AI_CONTENT_LABEL_ZH,
            source_count=len(trace.total_evidence_ids),
            compliance_status=status,
            compliance_class=badge_map.get(status, "unknown"),
            timestamp=trace.started_at.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(trace.started_at, datetime) else str(trace.started_at),
        )


# ── Run Summary (list page) ──────────────────────────────────────────────

@dataclass
class RunSummaryView:
    """One row in the run list table."""
    run_id: str = ""
    ticker: str = ""
    trade_date: str = ""
    started_at: str = ""
    total_nodes: int = 0
    error_count: int = 0
    research_action: str = ""
    was_vetoed: bool = False
    compliance_status: str = ""
    status_badge: str = ""   # success / warning / error

    @classmethod
    def from_manifest(cls, entry: dict) -> "RunSummaryView":
        error_count = entry.get("error_count", 0)
        compliance = entry.get("compliance_status", "")
        was_vetoed = entry.get("was_vetoed", False)

        if error_count > 0:
            badge = "error"
        elif compliance in ("block", "review") or was_vetoed:
            badge = "warning"
        else:
            badge = "success"

        started = entry.get("started_at", "")
        if isinstance(started, str) and "T" in started:
            try:
                started = datetime.fromisoformat(started).strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                pass

        return cls(
            run_id=entry.get("run_id", ""),
            ticker=entry.get("ticker", ""),
            trade_date=entry.get("trade_date", ""),
            started_at=started,
            total_nodes=entry.get("total_nodes", 0),
            error_count=error_count,
            research_action=entry.get("research_action", ""),
            was_vetoed=was_vetoed,
            compliance_status=compliance,
            status_badge=badge,
        )


# ── Node Trace (timeline + detail) ───────────────────────────────────────

@dataclass
class NodeTraceView:
    """Presentation model for a single node trace."""
    node_name: str = ""
    seq: int = 0
    status: str = "ok"
    status_class: str = "ok"   # CSS class
    duration_formatted: str = ""
    research_action: str = ""
    confidence: float = -1.0
    thesis_effect: str = ""

    # Parse quality
    parse_status: str = ""
    parse_confidence: float = -1.0
    parse_missing_fields: List[str] = field(default_factory=list)
    parse_warnings: List[str] = field(default_factory=list)

    # Hashes
    input_hash: str = ""
    output_hash: str = ""
    output_excerpt: str = ""

    # Evidence / claims
    evidence_ids_referenced: List[str] = field(default_factory=list)
    claim_ids_referenced: List[str] = field(default_factory=list)
    claim_ids_produced: List[str] = field(default_factory=list)
    claims_produced: int = 0
    claims_attributed: int = 0
    claims_unattributed: int = 0

    # Risk
    risk_score: Optional[int] = None
    risk_cleared: Optional[bool] = None
    risk_flag_count: int = 0
    risk_flag_categories: List[str] = field(default_factory=list)
    vetoed: bool = False
    veto_reasons: List[str] = field(default_factory=list)

    # Compliance
    compliance_status: str = ""
    compliance_reasons: List[str] = field(default_factory=list)
    compliance_rules_fired: List[str] = field(default_factory=list)

    # Ledger
    ledger_prev_status: str = ""
    ledger_new_status: str = ""
    ledger_transition_reason: str = ""

    # Errors
    errors: List[str] = field(default_factory=list)

    # Convenience flags for conditional template rendering
    has_evidence: bool = False
    has_claims: bool = False
    has_risk: bool = False
    has_compliance: bool = False
    has_ledger: bool = False
    has_errors: bool = False

    @classmethod
    def from_service_output(cls, node_output: dict, node_input: dict = None) -> "NodeTraceView":
        """Build from ReplayService.show_node_output() + show_node_input()."""
        status = node_output.get("status", "ok")
        status_map = {"ok": "ok", "warn": "warn", "error": "error", "skipped": "skipped"}
        duration_ms = node_output.get("duration_ms", 0)
        if duration_ms >= 1000:
            dur_fmt = f"{duration_ms / 1000:.1f}s"
        else:
            dur_fmt = f"{int(duration_ms)}ms"

        evidence = node_output.get("evidence_ids_referenced", [])
        if node_input:
            evidence = evidence or node_input.get("evidence_ids_referenced", [])

        claim_refs = node_output.get("claim_ids_referenced", [])
        if node_input:
            claim_refs = claim_refs or node_input.get("claim_ids_referenced", [])

        claim_prods = node_output.get("claim_ids_produced", [])

        return cls(
            node_name=node_output.get("node_name", ""),
            seq=node_output.get("seq", 0),
            status=status,
            status_class=status_map.get(status, "ok"),
            duration_formatted=dur_fmt,
            research_action=node_output.get("research_action", ""),
            confidence=node_output.get("confidence", -1.0),
            thesis_effect=node_output.get("thesis_effect", ""),
            parse_status=node_output.get("parse_status", ""),
            parse_confidence=node_output.get("parse_confidence", -1.0),
            parse_missing_fields=node_output.get("parse_missing_fields", []),
            parse_warnings=node_output.get("parse_warnings", []),
            input_hash=node_input.get("input_hash", "") if node_input else "",
            output_hash=node_output.get("output_hash", ""),
            output_excerpt=node_output.get("output_excerpt", ""),
            evidence_ids_referenced=evidence,
            claim_ids_referenced=claim_refs,
            claim_ids_produced=claim_prods,
            claims_produced=node_output.get("claims_produced", 0),
            claims_attributed=node_output.get("claims_attributed", 0),
            claims_unattributed=node_output.get("claims_unattributed", 0),
            risk_score=node_output.get("risk_score"),
            risk_cleared=node_output.get("risk_cleared"),
            risk_flag_count=node_output.get("risk_flag_count", 0),
            risk_flag_categories=node_output.get("risk_flag_categories", []),
            vetoed=node_output.get("vetoed", False),
            veto_reasons=node_output.get("veto_reasons", []),
            compliance_status=node_output.get("compliance_status", ""),
            compliance_reasons=node_output.get("compliance_reasons", []),
            compliance_rules_fired=node_output.get("compliance_rules_fired", []),
            ledger_prev_status=node_output.get("ledger_prev_status", ""),
            ledger_new_status=node_output.get("ledger_new_status", ""),
            ledger_transition_reason=node_output.get("ledger_transition_reason", ""),
            errors=node_output.get("errors", []),
            has_evidence=bool(evidence),
            has_claims=bool(claim_prods) or node_output.get("claims_produced", 0) > 0,
            has_risk=node_output.get("risk_score") is not None,
            has_compliance=bool(node_output.get("compliance_status")),
            has_ledger=bool(node_output.get("ledger_new_status")),
            has_errors=bool(node_output.get("errors")),
        )

    @classmethod
    def from_list_entry(cls, entry: dict) -> "NodeTraceView":
        """Build a lightweight view from ReplayService.list_nodes() entry."""
        status = entry.get("status", "ok")
        duration_ms = entry.get("duration_ms", 0)
        if duration_ms >= 1000:
            dur_fmt = f"{duration_ms / 1000:.1f}s"
        else:
            dur_fmt = f"{int(duration_ms)}ms"
        return cls(
            node_name=entry.get("node_name", ""),
            seq=entry.get("seq", 0),
            status=status,
            status_class={"ok": "ok", "warn": "warn", "error": "error"}.get(status, "ok"),
            duration_formatted=dur_fmt,
            research_action=entry.get("research_action", ""),
            parse_status=entry.get("parse_status", ""),
        )


# ── War Room ──────────────────────────────────────────────────────────────

@dataclass
class WarRoomView:
    """War Room page data — reconstructed from traces, not raw markdown."""
    run_id: str = ""
    ticker: str = ""
    ticker_name: str = ""
    trade_date: str = ""
    research_action: str = ""
    confidence: float = -1.0
    was_vetoed: bool = False
    risk_score: Optional[int] = None
    risk_cleared: Optional[bool] = None

    # Key nodes (fully populated NodeTraceViews)
    synthesis_node: Optional[NodeTraceView] = None
    risk_node: Optional[NodeTraceView] = None
    bull_node: Optional[NodeTraceView] = None
    bear_node: Optional[NodeTraceView] = None
    catalyst_node: Optional[NodeTraceView] = None
    scenario_node: Optional[NodeTraceView] = None

    # Lineage stages from show_lineage()
    lineage_stages: List[Dict] = field(default_factory=list)

    # Evidence summary
    total_evidence: int = 0
    total_claims: int = 0

    banner: Optional[BannerView] = None

    @classmethod
    def build(cls, service: ReplayService, run_id: str) -> Optional["WarRoomView"]:
        trace = service.load_run(run_id)
        if not trace:
            return None

        lineage = service.show_lineage(run_id) or {}

        # Build node views for key roles
        key_nodes = {}
        for node_name in ("Research Manager", "Risk Judge", "Bull Researcher",
                          "Bear Researcher", "Catalyst Agent", "Scenario Agent"):
            out = service.show_node_output(run_id, node_name)
            inp = service.show_node_input(run_id, node_name)
            if out:
                key_nodes[node_name] = NodeTraceView.from_service_output(out, inp)

        return cls(
            run_id=run_id,
            ticker=trace.ticker,
            ticker_name=getattr(trace, "ticker_name", ""),
            trade_date=trace.trade_date,
            research_action=trace.research_action,
            confidence=trace.final_confidence,
            was_vetoed=trace.was_vetoed,
            risk_score=key_nodes.get("Risk Judge", NodeTraceView()).risk_score,
            risk_cleared=key_nodes.get("Risk Judge", NodeTraceView()).risk_cleared,
            synthesis_node=key_nodes.get("Research Manager"),
            risk_node=key_nodes.get("Risk Judge"),
            bull_node=key_nodes.get("Bull Researcher"),
            bear_node=key_nodes.get("Bear Researcher"),
            catalyst_node=key_nodes.get("Catalyst Agent"),
            scenario_node=key_nodes.get("Scenario Agent"),
            lineage_stages=lineage.get("stages", []),
            total_evidence=len(trace.total_evidence_ids),
            total_claims=len(trace.total_claim_ids),
            banner=BannerView.from_trace(trace),
        )


# ── Tier 1: Snapshot View ─────────────────────────────────────────────────

@dataclass
class SnapshotView:
    """Tier 1 — single-screen conclusion card.

    Answers: Is this ticker worth looking at? Why? What's the risk?
    6 blocks: conclusion, core drivers, main risks, evidence strength,
    upcoming catalysts, status lights.
    """
    run_id: str = ""
    ticker: str = ""
    ticker_name: str = ""           # Human-readable name (e.g. "贵州茅台")
    trade_date: str = ""

    # Block 1: Research conclusion
    research_action: str = ""       # BUY / HOLD / SELL / VETO
    action_label: str = ""          # 建议关注 / 维持观察 / 建议回避 / 风控否决
    action_class: str = ""          # CSS: buy / hold / sell / veto
    action_explanation: str = ""    # Product-level Chinese explanation
    confidence: float = -1.0
    one_line_summary: str = ""      # From PM structured conclusion or excerpt

    # Block 2: Core drivers (top 2-3)
    core_drivers: List[str] = field(default_factory=list)

    # Block 3: Main risks (top 2)
    main_risks: List[Dict] = field(default_factory=list)

    # Block 4: Evidence strength
    evidence_strength: str = ""     # HIGH / MEDIUM / LOW
    evidence_strength_class: str = ""
    total_evidence: int = 0
    total_claims: int = 0
    attributed_rate: float = 0.0

    # Block 5: Upcoming catalysts
    catalysts: List[Dict] = field(default_factory=list)

    # Block 6: Status lights
    risk_cleared: Optional[bool] = None
    compliance_status: str = ""
    freshness_ok: bool = True
    was_vetoed: bool = False

    # Bull vs Bear strength (for bar chart)
    bull_strength: int = 0          # number of bull claims
    bear_strength: int = 0          # number of bear claims

    # Fallback financial metrics (from fundamentals analyst text when vendor unavailable)
    metrics_fallback: Dict = field(default_factory=dict)

    # Degradation detection
    is_degraded: bool = False
    degradation_reasons: List[str] = field(default_factory=list)

    # Action Checklist (pillar scores from 4 analysts)
    pillar_checklist: List[Dict] = field(default_factory=list)
    # Each: {"pillar": "技术面", "score": 2, "emoji": "✅", "label": "多头排列确认"}

    # Risk Debate Summary (3 debaters)
    risk_debate_summary: List[Dict] = field(default_factory=list)
    # Each: {"stance": "激进", "recommendation": "BUY", "position_pct": "10%", "key_risk": "..."}

    # Battle Plan (from ResearchOutput)
    tradecard: Dict = field(default_factory=dict)
    trade_plan: Dict = field(default_factory=dict)

    # Historical signal tracking
    signal_history: List[Dict] = field(default_factory=list)

    banner: Optional[BannerView] = None

    @classmethod
    def build(cls, service: ReplayService, run_id: str) -> Optional["SnapshotView"]:
        from .decision_labels import (
            get_action_label, get_action_class, get_action_explanation,
            get_risk_label, SEVERITY_LABELS, SEVERITY_CSS,
        )

        trace = service.load_run(run_id)
        if not trace:
            return None

        action = trace.research_action or ""
        label = get_action_label(action)
        css = get_action_class(action)
        explanation = get_action_explanation(action)

        # Degradation check
        metrics = service.compute_metrics_from_trace(trace)
        nodes_list = service.list_nodes(run_id)
        failures = service.show_failures(run_id) or []
        is_degraded, degradation_reasons = _check_degradation(metrics, nodes_list, failures)

        # Extract key nodes
        pm_out = service.show_node_output(run_id, "Research Manager")
        risk_out = service.show_node_output(run_id, "Risk Judge")
        bull_out = service.show_node_output(run_id, "Bull Researcher")
        bear_out = service.show_node_output(run_id, "Bear Researcher")
        catalyst_out = service.show_node_output(run_id, "Catalyst Agent")

        # ── One-line summary: prefer structured conclusion, enforce 50-char limit ──
        one_line = ""
        if pm_out:
            pm_sd = pm_out.get("structured_data") or {}
            if pm_sd.get("conclusion"):
                one_line = pm_sd["conclusion"][:200]
            else:
                # Fallback: first substantive sentence from excerpt
                excerpt = pm_out.get("output_excerpt", "")
                for line in excerpt.split("\n"):
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#") or stripped.startswith("|") or stripped.startswith("---"):
                        continue
                    if stripped.startswith("**") and stripped.endswith("**"):
                        continue
                    if stripped.startswith(("-", "*", "•")) and len(stripped) < 200:
                        continue
                    for sep in ("。", "；"):
                        if sep in stripped:
                            one_line = stripped[:stripped.index(sep) + 1]
                            break
                    if not one_line:
                        one_line = stripped[:200]
                    break
        if not one_line:
            one_line = f"研究经理综合判断：{label}，置信度 {f'{trace.final_confidence:.0%}' if trace.final_confidence >= 0 else '—'}"
        # Strip internal tokens + enforce single-sentence limit
        one_line = _enforce_thesis_limit(one_line, max_chars=50)

        # ── Core drivers: prefer structured bull claims ──
        core_drivers = []
        if bull_out:
            bull_sd = bull_out.get("structured_data") or {}
            bull_claims_list = bull_sd.get("supporting_claims") or []
            if bull_claims_list:
                # Top 3 by confidence
                sorted_claims = sorted(bull_claims_list, key=lambda c: c.get("confidence", 0), reverse=True)
                for c in sorted_claims[:3]:
                    text = c.get("text", "")[:100]
                    if text:
                        core_drivers.append(text)
            else:
                # Fallback: extract from excerpt
                excerpt = bull_out.get("output_excerpt", "")
                for line in excerpt.split("\n"):
                    stripped = line.strip()
                    if stripped.startswith("**结论") or stripped.startswith("**核心"):
                        clean = stripped.strip("*#- ").strip()
                        if clean and len(clean) > 5:
                            core_drivers.append(clean[:120])
                    elif stripped.startswith("#### ") or stripped.startswith("### "):
                        clean = stripped.lstrip("#* ").strip()
                        if clean and len(clean) > 5:
                            core_drivers.append(clean[:120])
                    if len(core_drivers) >= 3:
                        break
                if not core_drivers:
                    for line in excerpt.split("\n"):
                        stripped = line.strip()
                        if stripped and not stripped.startswith("#") and not stripped.startswith("---") and len(stripped) > 20:
                            core_drivers.append(stripped[:150])
                            break

        # ── Main risks: prefer structured risk flags ──
        main_risks: list = []
        if risk_out:
            risk_sd = risk_out.get("structured_data") or {}
            risk_flags = risk_sd.get("risk_flags") or []
            if risk_flags:
                for f in risk_flags[:2]:
                    main_risks.append({
                        "category": get_risk_label(f.get("category", "")),
                        "severity": SEVERITY_LABELS.get(f.get("severity", "medium"), f.get("severity", "")),
                        "severity_class": SEVERITY_CSS.get(f.get("severity", "medium"), "hold"),
                        "description": f.get("description", ""),
                    })
            else:
                # Fallback: category-only labels
                for cat in (risk_out.get("risk_flag_categories") or [])[:2]:
                    main_risks.append({
                        "category": get_risk_label(cat),
                        "severity": "",
                        "severity_class": "hold",
                        "description": "",
                    })

        # Evidence strength (metrics already computed above for degradation check)
        binding_rate = metrics.claim_to_evidence_binding_rate if metrics else 0.0
        if binding_rate >= 0.7:
            ev_str, ev_cls = "HIGH", "high"
        elif binding_rate >= 0.4:
            ev_str, ev_cls = "MEDIUM", "medium"
        else:
            ev_str, ev_cls = "LOW", "low"

        # ── Catalysts: prefer structured data ──
        catalysts: list = []
        if catalyst_out:
            cat_sd = catalyst_out.get("structured_data") or {}
            cat_list = cat_sd.get("catalysts") or []
            if cat_list:
                for c in cat_list[:4]:
                    catalysts.append({
                        "event": c.get("event_description", "")[:120],
                        "date": c.get("expected_date", ""),
                        "direction": c.get("direction", ""),
                    })
            else:
                # Fallback: parse from excerpt
                excerpt = catalyst_out.get("output_excerpt", "")
                for line in excerpt.split("\n"):
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#") or stripped.startswith("---"):
                        continue
                    if stripped.startswith("|"):
                        if ":---" in stripped or "催化剂事件" in stripped or "事件描述" in stripped:
                            continue
                        cells = [c.strip() for c in stripped.split("|") if c.strip()]
                        if cells:
                            item = cells[0].strip("* ")
                            if item and len(item) > 3:
                                catalysts.append({"event": item[:120], "date": "", "direction": ""})
                        continue
                    if stripped.startswith(("-", "*", "•")):
                        clean = stripped.lstrip("-*• ").strip()
                        if clean and len(clean) > 10:
                            catalysts.append({"event": clean[:120], "date": "", "direction": ""})
                    if len(catalysts) >= 4:
                        break

        # Strip tokens from core drivers
        core_drivers = [_strip_internal_tokens(d) for d in core_drivers]
        core_drivers = [d for d in core_drivers if d]  # remove empty after stripping

        # Bull vs Bear claim counts
        bull_claims = bull_out.get("claims_produced", 0) if bull_out else 0
        bear_claims = bear_out.get("claims_produced", 0) if bear_out else 0

        # Fallback financial metrics from fundamentals analyst text
        metrics_fb: Dict = {}
        fund_out = service.show_node_output(run_id, "Fundamentals Analyst")
        if fund_out:
            fund_sd = fund_out.get("structured_data") or {}
            metrics_fb = fund_sd.get("metrics_fallback", {})

        # ── Pillar Checklist (Feature 2) ──
        from .decision_labels import PILLAR_EMOJI
        pillar_checklist: List[Dict] = []
        _pillar_map = [
            ("Market Analyst", "\u6280\u672f\u9762"),
            ("Fundamentals Analyst", "\u57fa\u672c\u9762"),
            ("News Analyst", "\u6d88\u606f\u9762"),
            ("Social Analyst", "\u60c5\u7eea\u9762"),
        ]
        for node_name, pillar_label in _pillar_map:
            nd_out = service.show_node_output(run_id, node_name)
            if nd_out:
                nd_sd = nd_out.get("structured_data") or {}
                raw_score = nd_sd.get("pillar_score")
                score = int(raw_score) if raw_score is not None else -1
                if score < 0:
                    continue
                score = min(max(score, 0), 2)
                emoji = PILLAR_EMOJI.get(score, "\u26aa")
                # Use first line of excerpt as label fallback
                excerpt = nd_out.get("output_excerpt", "")
                first_line = ""
                for ln in excerpt.split("\n"):
                    ln_stripped = ln.strip()
                    if ln_stripped and not ln_stripped.startswith("#") and len(ln_stripped) > 5:
                        first_line = _strip_internal_tokens(ln_stripped[:40])
                        break
                pillar_checklist.append({
                    "pillar": pillar_label,
                    "score": score,
                    "emoji": emoji,
                    "label": first_line,
                })

        # ── Risk Debate Summary (Feature 2) ──
        risk_debate_summary: List[Dict] = []
        _debater_map = [
            ("Aggressive Debator", "\u6fc0\u8fdb"),
            ("Conservative Debator", "\u4fdd\u5b88"),
            ("Neutral Debator", "\u4e2d\u6027"),
        ]
        for debater_node, stance_label in _debater_map:
            d_out = service.show_node_output(run_id, debater_node)
            if d_out:
                d_sd = d_out.get("structured_data") or {}
                risk_debate_summary.append({
                    "stance": stance_label,
                    "recommendation": d_sd.get("recommendation", ""),
                    "position_pct": d_sd.get("position_size_pct", ""),
                    "key_risk": _strip_internal_tokens(
                        str(d_sd.get("key_risk", ""))[:80]
                    ),
                })

        # ── Battle Plan (Feature 3) ──
        tradecard_data: Dict = {}
        trade_plan_data: Dict = {}
        ro_out = service.show_node_output(run_id, "ResearchOutput")
        if ro_out:
            ro_sd = ro_out.get("structured_data") or {}
            tradecard_data = ro_sd.get("tradecard") or {}
            trade_plan_data = ro_sd.get("trade_plan") or {}

        # ── Signal History (Feature 5) ──
        signal_history: List[Dict] = []
        try:
            past_runs = service.store.list_runs(ticker=trace.ticker, limit=10)
            count = 0
            for pr in past_runs:
                if pr.get("run_id") == run_id:
                    continue
                signal_history.append({
                    "trade_date": pr.get("trade_date", ""),
                    "action": pr.get("research_action", ""),
                    "confidence": 0.0,  # manifest doesn't store confidence
                })
                count += 1
                if count >= 5:
                    break
        except Exception:
            pass

        return cls(
            run_id=run_id,
            ticker=trace.ticker,
            ticker_name=getattr(trace, "ticker_name", ""),
            trade_date=trace.trade_date,
            research_action=action,
            action_label=label,
            action_class=css,
            action_explanation=explanation,
            confidence=trace.final_confidence,
            one_line_summary=one_line,
            core_drivers=core_drivers,
            main_risks=main_risks,
            evidence_strength=ev_str,
            evidence_strength_class=ev_cls,
            total_evidence=len(trace.total_evidence_ids),
            total_claims=len(trace.total_claim_ids),
            attributed_rate=binding_rate,
            catalysts=catalysts,
            risk_cleared=risk_out.get("risk_cleared") if risk_out else None,
            compliance_status=trace.compliance_status or "",
            freshness_ok=getattr(trace, "freshness_ok", True),
            was_vetoed=trace.was_vetoed,
            bull_strength=bull_claims,
            bear_strength=bear_claims,
            metrics_fallback=metrics_fb,
            is_degraded=is_degraded,
            degradation_reasons=degradation_reasons,
            pillar_checklist=pillar_checklist,
            risk_debate_summary=risk_debate_summary,
            tradecard=tradecard_data,
            trade_plan=trade_plan_data,
            signal_history=signal_history,
            banner=BannerView.from_trace(trace),
        )


# ── Tier 2: Research View ────────────────────────────────────────────────

@dataclass
class ResearchView:
    """Tier 2 — full research report (War Room).

    Answers: How was this conclusion reached? What are the bull/bear
    arguments? What scenarios exist? What should I watch next?
    """
    run_id: str = ""
    ticker: str = ""
    ticker_name: str = ""
    trade_date: str = ""

    # Conclusion (same as Tier 1)
    research_action: str = ""
    action_label: str = ""
    action_class: str = ""
    action_explanation: str = ""
    confidence: float = -1.0
    was_vetoed: bool = False
    risk_score: Optional[int] = None
    risk_cleared: Optional[bool] = None

    # Bull case
    bull_excerpt: str = ""
    bull_claims: List[Dict] = field(default_factory=list)
    bull_evidence_ids: List[str] = field(default_factory=list)

    # Bear case
    bear_excerpt: str = ""
    bear_claims: List[Dict] = field(default_factory=list)
    bear_evidence_ids: List[str] = field(default_factory=list)

    # PM Synthesis
    synthesis_excerpt: str = ""
    synthesis_detail: Dict = field(default_factory=dict)
    synthesis_evidence_ids: List[str] = field(default_factory=list)
    thesis_effect: str = ""

    # Scenario analysis
    scenario_excerpt: str = ""
    scenario_probs: Dict = field(default_factory=dict)

    # Risk review
    risk_excerpt: str = ""
    risk_flag_count: int = 0
    risk_flag_categories: List[str] = field(default_factory=list)
    risk_flags_detail: List[Dict] = field(default_factory=list)

    # Catalyst timeline
    catalyst_excerpt: str = ""

    # Invalidation conditions (what would make thesis fail)
    invalidation_signals: List[str] = field(default_factory=list)

    # Evidence summary
    total_evidence: int = 0
    total_claims: int = 0
    evidence_strength: str = ""

    # Lineage (simplified)
    lineage_stages: List[Dict] = field(default_factory=list)

    # Trade plan (public entry/exit framework, position-independent)
    trade_plan: Dict = field(default_factory=dict)

    # Degradation detection
    is_degraded: bool = False
    degradation_reasons: List[str] = field(default_factory=list)

    banner: Optional[BannerView] = None

    @classmethod
    def build(cls, service: ReplayService, run_id: str) -> Optional["ResearchView"]:
        from .decision_labels import (
            get_action_label, get_action_class, get_action_explanation,
            get_risk_label, SEVERITY_LABELS, SEVERITY_CSS,
        )

        trace = service.load_run(run_id)
        if not trace:
            return None

        action = trace.research_action or ""
        label = get_action_label(action)
        css = get_action_class(action)
        explanation = get_action_explanation(action)

        # Key node outputs
        bull_out = service.show_node_output(run_id, "Bull Researcher") or {}
        bear_out = service.show_node_output(run_id, "Bear Researcher") or {}
        pm_out = service.show_node_output(run_id, "Research Manager") or {}
        risk_out = service.show_node_output(run_id, "Risk Judge") or {}
        scenario_out = service.show_node_output(run_id, "Scenario Agent") or {}
        catalyst_out = service.show_node_output(run_id, "Catalyst Agent") or {}
        ro_out = service.show_node_output(run_id, "ResearchOutput") or {}

        lineage = service.show_lineage(run_id) or {}
        metrics = service.compute_metrics_from_trace(trace)

        # Degradation check
        nodes_list = service.list_nodes(run_id)
        failures_list = service.show_failures(run_id) or []
        is_degraded, degradation_reasons = _check_degradation(metrics, nodes_list, failures_list)
        binding_rate = metrics.claim_to_evidence_binding_rate if metrics else 0.0

        if binding_rate >= 0.7:
            ev_str = "HIGH"
        elif binding_rate >= 0.4:
            ev_str = "MEDIUM"
        else:
            ev_str = "LOW"

        # Pull evidence IDs from lineage
        bull_ev_ids = []
        bear_ev_ids = []
        pm_ev_ids = []
        for s in lineage.get("stages", []):
            if s.get("node") == "Bull Researcher":
                bull_ev_ids = s.get("evidence_consumed", [])
            elif s.get("node") == "Bear Researcher":
                bear_ev_ids = s.get("evidence_consumed", [])
            elif s.get("node") == "Research Manager":
                pm_ev_ids = s.get("evidence_consumed", [])

        # ── Bull claims: prefer structured data ──
        bull_sd = bull_out.get("structured_data") or {}
        bull_claims_list = bull_sd.get("supporting_claims") or []
        if bull_claims_list:
            bull_claims = [
                {
                    "id": c.get("claim_id", ""),
                    "text": c.get("text", ""),
                    "dimension": c.get("dimension", ""),
                    "confidence": c.get("confidence", 0),
                    "invalidation": c.get("invalidation", ""),
                    "evidence_ids": c.get("supports", []),
                }
                for c in bull_claims_list
            ]
        else:
            bull_claims = [{"id": c} for c in bull_out.get("claim_ids_produced", [])]

        # ── Bear claims: prefer structured data ──
        bear_sd = bear_out.get("structured_data") or {}
        bear_claims_list = bear_sd.get("supporting_claims") or bear_sd.get("opposing_claims") or []
        if bear_claims_list:
            bear_claims = [
                {
                    "id": c.get("claim_id", ""),
                    "text": c.get("text", ""),
                    "dimension": c.get("dimension", ""),
                    "confidence": c.get("confidence", 0),
                    "invalidation": c.get("invalidation", ""),
                    "evidence_ids": c.get("supports", []) + c.get("opposes", []),
                }
                for c in bear_claims_list
            ]
        else:
            bear_claims = [{"id": c} for c in bear_out.get("claim_ids_produced", [])]

        # ── PM Synthesis: prefer structured data ──
        pm_sd = pm_out.get("structured_data") or {}
        synthesis_excerpt = pm_sd.get("conclusion", "") or pm_out.get("output_excerpt", "")
        synthesis_detail = {}
        if pm_sd.get("base_case") or pm_sd.get("bull_case") or pm_sd.get("bear_case"):
            synthesis_detail = {
                "base_case": pm_sd.get("base_case", ""),
                "bull_case": pm_sd.get("bull_case", ""),
                "bear_case": pm_sd.get("bear_case", ""),
            }

        # ── Scenario: prefer structured data ──
        scn_sd = scenario_out.get("structured_data") or {}
        scenario_probs = {}
        if scn_sd.get("base_prob") is not None:
            scenario_probs = {
                "base_prob": scn_sd.get("base_prob", 0),
                "bull_prob": scn_sd.get("bull_prob", 0),
                "bear_prob": scn_sd.get("bear_prob", 0),
                "base_trigger": scn_sd.get("base_case_trigger", ""),
                "bull_trigger": scn_sd.get("bull_case_trigger", ""),
                "bear_trigger": scn_sd.get("bear_case_trigger", ""),
            }

        # ── Risk flags detail: prefer structured data ──
        risk_sd = risk_out.get("structured_data") or {}
        risk_flags_detail = []
        for f in (risk_sd.get("risk_flags") or []):
            risk_flags_detail.append({
                "category": get_risk_label(f.get("category", "")),
                "severity": SEVERITY_LABELS.get(f.get("severity", "medium"), f.get("severity", "")),
                "severity_class": SEVERITY_CSS.get(f.get("severity", "medium"), "hold"),
                "description": f.get("description", ""),
                "evidence_ids": f.get("bound_evidence_ids", []),
                "mitigant": f.get("mitigant", ""),
            })

        # ── Invalidation: prefer structured data ──
        invalidation = []
        risk_inval = risk_sd.get("invalidation_conditions") or []
        pm_inval = pm_sd.get("invalidation_conditions") or []
        if pm_inval:
            invalidation = pm_inval[:5]
        elif risk_inval:
            invalidation = risk_inval[:5]
        else:
            # Fallback: keyword search in bear excerpt
            bear_excerpt_text = bear_out.get("output_excerpt", "")
            for line in bear_excerpt_text.split("\n"):
                lower = line.lower()
                if any(kw in lower for kw in ("失效", "invalidat", "break", "跌破", "风险触发")):
                    stripped = line.strip().lstrip("-*•0123456789. ")
                    if stripped and len(stripped) > 10:
                        invalidation.append(stripped[:150])
            if not invalidation and risk_out.get("risk_flag_categories"):
                invalidation = [f"风险: {c}" for c in risk_out.get("risk_flag_categories", [])[:3]]

        # ── Trade plan: from ResearchOutput structured_data ──
        ro_sd = ro_out.get("structured_data") or {}
        trade_plan_data = ro_sd.get("trade_plan") or {}

        return cls(
            run_id=run_id,
            ticker=trace.ticker,
            ticker_name=getattr(trace, "ticker_name", ""),
            trade_date=trace.trade_date,
            research_action=action,
            action_label=label,
            action_class=css,
            action_explanation=explanation,
            confidence=trace.final_confidence,
            was_vetoed=trace.was_vetoed,
            risk_score=risk_out.get("risk_score"),
            risk_cleared=risk_out.get("risk_cleared"),
            bull_excerpt=bull_out.get("output_excerpt", ""),
            bull_claims=bull_claims,
            bull_evidence_ids=bull_ev_ids,
            bear_excerpt=bear_out.get("output_excerpt", ""),
            bear_claims=bear_claims,
            bear_evidence_ids=bear_ev_ids,
            synthesis_excerpt=synthesis_excerpt,
            synthesis_detail=synthesis_detail,
            synthesis_evidence_ids=pm_ev_ids,
            thesis_effect=pm_out.get("thesis_effect", ""),
            scenario_excerpt=scenario_out.get("output_excerpt", ""),
            scenario_probs=scenario_probs,
            risk_excerpt=risk_out.get("output_excerpt", ""),
            risk_flag_count=risk_out.get("risk_flag_count", 0),
            risk_flag_categories=risk_out.get("risk_flag_categories", []),
            risk_flags_detail=risk_flags_detail,
            catalyst_excerpt=catalyst_out.get("output_excerpt", ""),
            invalidation_signals=invalidation[:5],
            total_evidence=len(trace.total_evidence_ids),
            total_claims=len(trace.total_claim_ids),
            evidence_strength=ev_str,
            lineage_stages=lineage.get("stages", []),
            trade_plan=trade_plan_data,
            is_degraded=is_degraded,
            degradation_reasons=degradation_reasons,
            banner=BannerView.from_trace(trace),
        )


# ── Audit ─────────────────────────────────────────────────────────────────

@dataclass
class AuditView:
    """Audit page data — compliance, metrics, traceability."""
    run_id: str = ""
    ticker: str = ""
    ticker_name: str = ""
    trade_date: str = ""

    metrics: Optional[RunMetrics] = None
    failures: List[Dict] = field(default_factory=list)
    lineage_stages: List[Dict] = field(default_factory=list)

    # Parse quality per node
    parse_table: List[Dict] = field(default_factory=list)

    # Compliance nodes
    compliance_nodes: List[NodeTraceView] = field(default_factory=list)

    # Data freshness
    freshness_ok: bool = True
    stale_sources: List[Dict] = field(default_factory=list)
    vendor_freshness: List[Dict] = field(default_factory=list)

    # Trust signals (new)
    trust_signals: List[Dict] = field(default_factory=list)
    weakest_node: str = ""
    manual_check_items: List[str] = field(default_factory=list)

    # Audit conclusion (computed from trust signals)
    audit_conclusion_level: str = ""   # high / medium / low
    audit_conclusion_label: str = ""   # 高可信 / 中等可信 / 低可信
    audit_conclusion_text: str = ""    # Full explanation

    banner: Optional[BannerView] = None

    @classmethod
    def build(cls, service: ReplayService, run_id: str) -> Optional["AuditView"]:
        trace = service.load_run(run_id)
        if not trace:
            return None

        metrics = service.compute_metrics_from_trace(trace)
        failures = service.show_failures(run_id) or []
        lineage = service.show_lineage(run_id) or {}
        nodes = service.list_nodes(run_id)

        # Parse quality table
        parse_table = []
        for n in nodes:
            if n.get("parse_status"):
                out = service.show_node_output(run_id, n["node_name"])
                parse_table.append({
                    "node_name": n["node_name"],
                    "parse_status": n.get("parse_status", ""),
                    "parse_confidence": out.get("parse_confidence", -1) if out else -1,
                    "missing_fields": out.get("parse_missing_fields", []) if out else [],
                    "warnings": out.get("parse_warnings", []) if out else [],
                })

        # Compliance nodes
        comp_nodes = []
        for n in nodes:
            out = service.show_node_output(run_id, n["node_name"])
            if out and out.get("compliance_status"):
                inp = service.show_node_input(run_id, n["node_name"])
                comp_nodes.append(NodeTraceView.from_service_output(out, inp))

        # Freshness data from trace
        vendor_freshness_list = [
            {"key": k, **v}
            for k, v in getattr(trace, "vendor_freshness", {}).items()
        ]
        stale = getattr(trace, "stale_sources", [])
        freshness_ok = getattr(trace, "freshness_ok", True)

        # ── Trust signals ──
        # Strict thresholds: green is earned (≥90%), yellow is acceptable (≥70%), red flags real issues (<70%).
        trust_signals = []
        if metrics:
            def _signal(label, value, explanation, threshold_good=0.9, threshold_warn=0.7):
                if value >= threshold_good:
                    status = "good"
                elif value >= threshold_warn:
                    status = "warn"
                else:
                    status = "bad"
                return {"label": label, "value": value, "status": status, "explanation": explanation}

            trust_signals = [
                _signal("AI输出解析率", metrics.strict_parse_rate,
                        "AI输出能否被系统可靠解析为结构化数据"),
                _signal("论据有据可查", metrics.claim_to_evidence_binding_rate,
                        "每条论据是否都能追溯到具体数据源"),
                _signal("推理结构化程度", 1.0 - metrics.narrative_dependency_rate,
                        "分析过程是否使用了结构化论证而非纯叙事"),
                _signal("证据链完整性", metrics.replay_completeness_rate,
                        "所有分析节点是否都有完整的执行记录"),
                _signal("风险标记追溯", metrics.risk_flag_traceability_rate,
                        "每条风险标记是否都关联到具体证据"),
            ]

        # ── Weakest node(s) ──
        # Collect nodes below threshold AND nodes with unattributed claims.
        # Also always flag the node with the absolute lowest parse confidence.
        weak_nodes = []
        for p in parse_table:
            conf = p.get("parse_confidence", 1.0)
            if 0 <= conf < 0.85:
                weak_nodes.append(p["node_name"])
        for f in failures:
            for issue in f.get("issues", []):
                if issue.get("type") == "unattributed_claims":
                    name = f.get("node_name", "")
                    if name and name not in weak_nodes:
                        weak_nodes.append(name)
        # If no nodes below threshold, still flag the weakest by confidence
        if not weak_nodes and parse_table:
            worst = min(parse_table, key=lambda p: p.get("parse_confidence", 1.0))
            if worst.get("parse_confidence", 1.0) < 1.0:
                weak_nodes.append(worst["node_name"])
        # Cap at 3 most important, translate to Chinese
        from .decision_labels import get_node_label
        weak_labels = [get_node_label(n) for n in weak_nodes[:3]]
        weakest_node = " / ".join(weak_labels) if weak_labels else ""

        # ── Manual check items (consistent with weakest_node) ──
        manual_items = []
        if metrics and metrics.claim_to_evidence_binding_rate < 0.7:
            manual_items.append("部分论据缺少证据绑定，需人工核实数据来源")
        if metrics and metrics.strict_parse_rate < 0.7:
            manual_items.append("解析率偏低，部分AI输出未被完全结构化")
        if not freshness_ok:
            manual_items.append("存在过期数据源，需确认数据时效性")
        for f in failures:
            for issue in f.get("issues", []):
                if issue.get("type") == "unattributed_claims":
                    manual_items.append(f"{f['node_name']}: {issue['count']}条论据无证据支撑")
                    break

        # ── Audit conclusion ──
        from .decision_labels import compute_audit_conclusion
        ac_level, ac_label, ac_text = compute_audit_conclusion(trust_signals, weakest_node)

        return cls(
            run_id=run_id,
            ticker=trace.ticker,
            ticker_name=getattr(trace, "ticker_name", ""),
            trade_date=trace.trade_date,
            metrics=metrics,
            failures=failures,
            lineage_stages=lineage.get("stages", []),
            parse_table=parse_table,
            compliance_nodes=comp_nodes,
            freshness_ok=freshness_ok,
            stale_sources=stale,
            vendor_freshness=vendor_freshness_list,
            trust_signals=trust_signals,
            weakest_node=weakest_node,
            manual_check_items=manual_items,
            audit_conclusion_level=ac_level,
            audit_conclusion_label=ac_label,
            audit_conclusion_text=ac_text,
            banner=BannerView.from_trace(trace),
        )


# ── Multi-stock Divergence Pool ──────────────────────────────────────────

@dataclass
class StockDivergenceRow:
    """One row in the divergence pool — summarises a single stock's bull/bear."""
    run_id: str = ""
    ticker: str = ""
    ticker_name: str = ""
    trade_date: str = ""

    # Verdict
    action: str = ""         # BUY/SELL/HOLD/VETO
    action_label: str = ""   # 建议关注/回避/...
    action_class: str = ""   # buy/sell/hold/veto (CSS)
    confidence: float = 0.0
    risk_cleared: bool = False
    was_vetoed: bool = False

    # Top bull claims (sorted by confidence desc, max 3)
    bull_claims: List[Dict] = field(default_factory=list)
    # Top bear claims (sorted by confidence desc, max 3)
    bear_claims: List[Dict] = field(default_factory=list)

    # Risk flags (category + severity)
    risk_flags: List[Dict] = field(default_factory=list)

    # Key metrics (from metrics_fallback)
    pe: str = ""
    pb: str = ""
    market_cap: str = ""

    # Sparkline close prices (last ~30 days, for mini chart)
    sparkline_prices: List[float] = field(default_factory=list)

    # Trade plan (public entry/exit framework)
    trade_plan: Dict = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Human-readable stock label for card/table display."""
        if self.ticker_name:
            return f"{self.ticker} {self.ticker_name}"
        return self.ticker

    @property
    def short_ticker(self) -> str:
        """Ticker without exchange suffix for compact badges."""
        return self.ticker.split(".", 1)[0]

    @property
    def conviction_pct(self) -> int:
        """Confidence as rounded percentage for dashboards."""
        return int(round(max(self.confidence, 0.0) * 100))

    @property
    def bull_score(self) -> float:
        """Aggregate confidence of top bull claims."""
        return sum(float(c.get("confidence", 0) or 0) for c in self.bull_claims)

    @property
    def bear_score(self) -> float:
        """Aggregate confidence of top bear claims."""
        return sum(float(c.get("confidence", 0) or 0) for c in self.bear_claims)

    @property
    def bull_ratio(self) -> float:
        """Bull share in the bull/bear debate intensity."""
        total = self.bull_score + self.bear_score
        return self.bull_score / total if total > 0 else 0.5

    @property
    def bear_ratio(self) -> float:
        """Bear share in the bull/bear debate intensity."""
        return 1.0 - self.bull_ratio

    @property
    def signal_gap(self) -> float:
        """Net bull minus bear intensity for ranking/summary."""
        return self.bull_score - self.bear_score

    @property
    def risk_flag_count(self) -> int:
        """How many explicit risk flags this stock carries."""
        return len(self.risk_flags)

    @property
    def primary_risk_categories(self) -> List[str]:
        """Top risk categories for compact display."""
        return [rf.get("category", "") for rf in self.risk_flags if rf.get("category")][:2]

    @property
    def risk_state_label(self) -> str:
        """Readable risk state for customers."""
        if self.was_vetoed:
            return "风控否决"
        if self.risk_cleared and self.risk_flags:
            return "风控通过，附带风险"
        if self.risk_cleared:
            return "风控通过"
        if self.risk_flags:
            return "风险待跟踪"
        return "待校验"

    @property
    def risk_state_class(self) -> str:
        """CSS class for risk state badges."""
        if self.was_vetoed:
            return "veto"
        if self.risk_cleared and not self.risk_flags:
            return "buy"
        if self.risk_cleared:
            return "hold"
        return "sell"

    @classmethod
    def build(cls, service: ReplayService, run_id: str) -> Optional["StockDivergenceRow"]:
        from .decision_labels import get_action_label, get_action_class

        trace = service.load_run(run_id)
        if not trace:
            return None

        action = trace.research_action or "HOLD"
        bull_out = service.show_node_output(run_id, "Bull Researcher")
        bear_out = service.show_node_output(run_id, "Bear Researcher")
        risk_out = service.show_node_output(run_id, "Risk Judge")

        def _top_claims(node_out: Optional[Dict], max_n: int = 3) -> List[Dict]:
            if not node_out:
                return []
            sd = node_out.get("structured_data") or {}
            raw = sd.get("supporting_claims") or sd.get("opposing_claims") or []
            items = [
                {
                    "text": _strip_internal_tokens(c.get("text", "")[:120]),
                    "confidence": c.get("confidence", 0),
                    "supports": c.get("supports", []),
                }
                for c in raw if c.get("text")
            ]
            items.sort(key=lambda x: x["confidence"], reverse=True)
            return items[:max_n]

        # Risk flags
        risk_flags = []
        if risk_out:
            rsd = risk_out.get("structured_data") or {}
            for rf in rsd.get("risk_flags") or []:
                risk_flags.append({
                    "category": rf.get("category", ""),
                    "severity": rf.get("severity", ""),
                })

        # Metrics fallback
        fund_out = service.show_node_output(run_id, "Fundamentals Analyst")
        mf = {}
        if fund_out:
            fsd = fund_out.get("structured_data") or {}
            mf = fsd.get("metrics_fallback", {})

        # Sparkline prices (stored in Market Analyst structured_data)
        mkt_out = service.show_node_output(run_id, "Market Analyst")
        sparkline = []
        if mkt_out:
            msd = mkt_out.get("structured_data") or {}
            raw_prices = msd.get("price_history", [])
            sparkline = [float(p) for p in raw_prices if p is not None][:30]

        # Trade plan (from ResearchOutput structured_data)
        ro_out = service.show_node_output(run_id, "ResearchOutput")
        trade_plan_data = {}
        if ro_out:
            ro_sd = ro_out.get("structured_data") or {}
            trade_plan_data = ro_sd.get("trade_plan") or {}

        return cls(
            run_id=run_id,
            ticker=trace.ticker,
            ticker_name=getattr(trace, "ticker_name", ""),
            trade_date=trace.trade_date,
            action=action,
            action_label=get_action_label(action),
            action_class=get_action_class(action),
            confidence=trace.final_confidence,
            risk_cleared=risk_out.get("risk_cleared") if risk_out else False,
            was_vetoed=trace.was_vetoed,
            bull_claims=_top_claims(bull_out),
            bear_claims=_top_claims(bear_out),
            risk_flags=risk_flags,
            pe=mf.get("pe", ""),
            pb=mf.get("pb", ""),
            market_cap=mf.get("market_cap", ""),
            sparkline_prices=sparkline,
            trade_plan=trade_plan_data,
        )


@dataclass
class DivergencePoolView:
    """Multi-stock comparison — the divergence pool / war room."""
    trade_date: str = ""
    rows: List[StockDivergenceRow] = field(default_factory=list)
    total_stocks: int = 0
    buy_count: int = 0
    sell_count: int = 0
    hold_count: int = 0
    veto_count: int = 0

    @property
    def avg_confidence(self) -> float:
        """Average confidence across all covered stocks."""
        if not self.rows:
            return 0.0
        return sum(r.confidence for r in self.rows) / len(self.rows)

    @property
    def risk_alert_count(self) -> int:
        """Total number of visible risk flags across the pool."""
        return sum(r.risk_flag_count for r in self.rows)

    @property
    def top_risk_categories(self) -> List[Tuple[str, int]]:
        """Most common risk categories across all rows."""
        counts: Dict[str, int] = {}
        for row in self.rows:
            for risk in row.risk_flags:
                cat = risk.get("category", "")
                if cat:
                    counts[cat] = counts.get(cat, 0) + 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    @property
    def featured_long(self) -> Optional[StockDivergenceRow]:
        """Highest-conviction BUY idea."""
        for row in self.rows:
            if row.action.upper() == "BUY":
                return row
        return self.rows[0] if self.rows else None

    @property
    def featured_short(self) -> Optional[StockDivergenceRow]:
        """Highest-priority avoid/veto idea."""
        for row in self.rows:
            if row.action.upper() in ("SELL", "VETO"):
                return row
        return None

    @property
    def featured_watch(self) -> Optional[StockDivergenceRow]:
        """Most representative HOLD idea."""
        for row in self.rows:
            if row.action.upper() == "HOLD":
                return row
        return None

    @classmethod
    def build(cls, service: ReplayService, run_ids: List[str],
              trade_date: str = "") -> "DivergencePoolView":
        rows = []
        for rid in run_ids:
            row = StockDivergenceRow.build(service, rid)
            if row:
                rows.append(row)

        # Sort: BUY first (by confidence desc), then HOLD, then SELL, VETO last
        action_order = {"BUY": 0, "HOLD": 1, "SELL": 2, "VETO": 3}
        rows.sort(key=lambda r: (action_order.get(r.action.upper(), 9), -r.confidence))

        return cls(
            trade_date=trade_date or (rows[0].trade_date if rows else ""),
            rows=rows,
            total_stocks=len(rows),
            buy_count=sum(1 for r in rows if r.action.upper() == "BUY"),
            sell_count=sum(1 for r in rows if r.action.upper() == "SELL"),
            hold_count=sum(1 for r in rows if r.action.upper() == "HOLD"),
            veto_count=sum(1 for r in rows if r.action.upper() == "VETO"),
        )


def _normalize_consecutive_boards(raw) -> Dict:
    """Normalize consecutive_boards to Dict[str, List[Dict]].

    Accepts two schemas:
    - Dict[str, List[Dict]] — board_data format ({"1": [...], "2": [...]})
    - List[Dict] — recap format ([{"boards": 2, "stocks": [...]}])
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        result = {}
        for entry in raw:
            if isinstance(entry, dict):
                level = str(entry.get("boards", entry.get("level", 1)))
                stocks = entry.get("stocks", [])
                if isinstance(stocks, list):
                    result[level] = stocks
                else:
                    result[level] = []
        return result
    return {}


def _extract_breadth_counts(
    ctx: Dict, total_hint: int = 0,
) -> Tuple[int, int]:
    """Extract advance/decline counts from market_context when snapshot is missing.

    Fallback chain:
    1. Parse raw counts from breadth_risk_note (e.g. "505涨/4955跌")
    2. Estimate from advance_decline_ratio + total
    """
    import re

    # Try parsing from risk_note text
    note = str(ctx.get("breadth_risk_note", ""))
    m = re.search(r"(\d+)\s*涨\s*[/／]\s*(\d+)\s*跌", note)
    if m:
        return int(m.group(1)), int(m.group(2))

    # Fallback: ratio-based estimation
    ratio = ctx.get("advance_decline_ratio")
    if ratio is not None:
        try:
            ratio = float(ratio)
        except (ValueError, TypeError):
            return 0, 0
        if ratio <= 0:
            return 0, 0
        total = total_hint or 5460  # A-share market default
        adv = int(ratio / (1 + ratio) * total)
        dec = total - adv
        return adv, dec

    return 0, 0


@dataclass
class MarketView:
    """Market-level view for /market page."""
    trade_date: str = ""
    # Macro
    regime: str = ""
    regime_label: str = ""
    regime_class: str = ""
    position_cap: float = 1.0
    style_bias: str = ""
    client_summary: str = ""
    risk_alerts: str = ""
    market_weather: str = ""
    # Breadth
    breadth_state: str = ""
    breadth_label: str = ""
    breadth_class: str = ""
    advance_count: int = 0
    decline_count: int = 0
    limit_up_count: int = 0
    limit_down_count: int = 0
    breadth_trend: str = ""
    # Sector
    sector_leaders: List[str] = field(default_factory=list)
    avoid_sectors: List[str] = field(default_factory=list)
    rotation_phase: str = ""
    sector_momentum: list = field(default_factory=list)
    # Heatmap
    heatmap_data: Optional[Dict] = None
    # Index
    index_sparklines: Dict = field(default_factory=dict)
    # Board data (sector heatmap, limit stocks, consecutive boards)
    board_sectors: list = field(default_factory=list)          # [{sector, pct_change, ...}]
    limit_up_stocks: list = field(default_factory=list)        # [{ticker, name, sector, boards, ...}]
    limit_down_stocks: list = field(default_factory=list)      # [{ticker, name, sector, ...}]
    consecutive_boards: Dict = field(default_factory=dict)     # {"1": [...], "2": [...]}
    limit_sector_attribution: Dict = field(default_factory=dict)  # {sector: {count, stocks}}
    sector_stocks: Dict = field(default_factory=dict)  # {sector: [{ticker,name,pct_change,market_cap_yi}]}

    @classmethod
    def build(
        cls,
        market_context: Dict,
        market_snapshot=None,
        heatmap_data=None,
        board_data: Optional[Dict] = None,
    ) -> "MarketView":
        from .decision_labels import (
            get_regime_label, get_regime_class,
            get_breadth_label, get_breadth_class,
        )
        ctx = market_context or {}
        regime = ctx.get("regime", "NEUTRAL")
        breadth = ctx.get("breadth_state", "NARROW")

        # Extract snapshot data
        advance = 0
        decline = 0
        limit_up = 0
        limit_down = 0
        index_data = {}
        if market_snapshot:
            advance = getattr(market_snapshot, "advance_count", 0)
            decline = getattr(market_snapshot, "decline_count", 0)
            limit_up = getattr(market_snapshot, "limit_up_count", 0)
            limit_down = getattr(market_snapshot, "limit_down_count", 0)
            index_data = getattr(market_snapshot, "index_data", {})

        # Adaptive fallback: when snapshot breadth APIs failed, derive from
        # market_context (LLM agents always extract real numbers)
        if advance == 0 and decline == 0 and ctx:
            total_hint = getattr(market_snapshot, "total_stocks", 0) if market_snapshot else 0
            advance, decline = _extract_breadth_counts(ctx, total_hint)

        pcm = ctx.get("position_cap_multiplier", 1.0)
        if isinstance(pcm, str):
            try:
                pcm = float(pcm)
            except ValueError:
                pcm = 1.0

        return cls(
            trade_date=ctx.get("trade_date", ""),
            regime=regime,
            regime_label=get_regime_label(regime),
            regime_class=get_regime_class(regime),
            position_cap=pcm,
            style_bias=ctx.get("style_bias", ""),
            client_summary=ctx.get("client_summary", ""),
            risk_alerts=ctx.get("risk_alerts", ""),
            market_weather=ctx.get("market_weather", ""),
            breadth_state=breadth,
            breadth_label=get_breadth_label(breadth),
            breadth_class=get_breadth_class(breadth),
            advance_count=advance,
            decline_count=decline,
            limit_up_count=limit_up,
            limit_down_count=limit_down,
            breadth_trend=ctx.get("breadth_trend", ""),
            sector_leaders=ctx.get("sector_leaders", []),
            avoid_sectors=ctx.get("avoid_sectors", []),
            rotation_phase=ctx.get("rotation_phase", ""),
            sector_momentum=ctx.get("sector_momentum", []),
            heatmap_data=heatmap_data.to_dict() if hasattr(heatmap_data, "to_dict") else heatmap_data,
            index_sparklines=index_data,
            board_sectors=(board_data or {}).get("sectors", []),
            limit_up_stocks=(board_data or {}).get("limit_ups", []),
            limit_down_stocks=(board_data or {}).get("limit_downs", []),
            consecutive_boards=_normalize_consecutive_boards(
                (board_data or {}).get("consecutive_boards", {})),
            limit_sector_attribution=(board_data or {}).get("limit_sector_attribution", {}),
            sector_stocks=(board_data or {}).get("sector_stocks", {}),
        )
