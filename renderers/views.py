"""
Read models for the dashboard — the contract between routes and templates.

These reshape ReplayService outputs into presentation-ready objects.
Templates receive these views, never raw NodeTrace/RunTrace instances.

Three-tier report hierarchy (same evidence chain, different compression):
- Tier 1 SnapshotView: Conclusion + signals + brief risk (single screen)
- Tier 2 ResearchView: Full research logic — bull/bear, evidence, scenarios, thesis
- Tier 3 AuditView:    Trustworthiness — evidence chains, replay, parser, compliance, history

This module is a facade: shared utilities and small shared classes live here,
while the large view classes are defined in dedicated sub-modules and
re-exported for backward compatibility.
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
    # Guard against pathologically long text (ReDoS mitigation)
    if len(text) > 200_000:
        text = text[:200_000]

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
    # General claim IDs such as clm-u001, clm-r011.
    text = re.sub(r'clm-[A-Za-z0-9_-]+', '', text, flags=re.IGNORECASE)
    # Standalone hex IDs like 79107dc0-2, ab5df0c6.
    # Require at least one a-f letter so legitimate six-digit tickers
    # such as 601985 are preserved in user-facing copy.
    text = re.sub(
        r'\b(?=[0-9A-Fa-f-]{6,}\b)(?=[0-9A-Fa-f-]*[A-Fa-f])[0-9A-Fa-f]{6,}(?:-\d+)?\b',
        '',
        text,
    )
    # Bracket-enclosed ID lists such as [-1, 79107dc0-2, 79107dc0-5].
    # Require a comma, negative sentinel, or hex letters so plain numeric
    # brackets like [123456] are not stripped.
    text = re.sub(r'\[(?=[^\]]*(?:,|-\d|[A-Fa-f]))[\s,\-\d0-9A-Fa-f]*\]', '', text)
    # Bracketed claim adjudication bundles like [clm-u001 ACCEPT, clm-r011 DEFER].
    text = re.sub(r'\[[^\]]*clm-[^\]]*\]', '', text, flags=re.IGNORECASE)
    # If claim IDs were stripped earlier, bracket bundles can degrade into
    # [ACCEPT, DEFER] style residues; strip those too.
    text = re.sub(
        r'\[\s*(?:(?:ACCEPT|REJECT|DEFER|SUPPORTED|UNSUPPORTED)(?:\s+at\s+\d+(?:\.\d+)?)?\s*,?\s*)+\]',
        '',
        text,
        flags=re.IGNORECASE,
    )
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


_DISPLAY_META_PREFIXES = (
    "分析日期", "目标", "标的", "当前价", "现价", "窗口", "视野", "展望",
    "市场", "模式", "资本", "角色定位", "决策框架", "基准先验", "历史校准",
    "PM 裁决", "Regime", "分析师", "Horizon", "Target", "Date",
)

_DISPLAY_META_HEADINGS = {
    "执行摘要", "开场陈述", "证据清单", "Evidence Anchors", "Evidence Bundle",
    "Evidence Registry", "证据编号系统", "核心立场", "TL;DR",
}


def _clean_display_text(text: str) -> str:
    """Normalize markdown-heavy agent text for user-facing UI snippets."""
    if not text:
        return ""
    text = _strip_internal_tokens(text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r'\bclaims?\b', '论据', text, flags=re.IGNORECASE)
    text = re.sub(r'^\s{0,3}#{1,6}\s*', '', text)
    text = re.sub(r'^\s*(?:[-*•]+|\d+[.)、])\s*', '', text)
    text = re.sub(r'^\s*\|\s*', '', text)
    # Strip common structured prefixes while preserving the actual content.
    text = re.sub(
        r'^\s*(?:CLAIM(?:-[A-Z0-9]+)?|EVIDENCE(?:-[A-Z0-9]+)?|CONFIDENCE|INVALIDATION|FACT|INTERP|DISPROVE|结论|摘要|TL;DR)\s*[:：]\s*',
        '',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r'\s+', ' ', text)
    return text.strip(" |-:：")


def _is_display_noise_line(text: str) -> bool:
    """Return True when a line is metadata/markup rather than human-readable content."""
    raw = (text or "").strip()
    if not raw:
        return True
    if raw.startswith("```"):
        return True
    if raw.startswith("|") and raw.count("|") >= 2:
        return True
    if raw.startswith("#"):
        return True
    if all(ch in "-=_*| " for ch in raw):
        return True

    cleaned = _clean_display_text(raw)
    if not cleaned:
        return True
    if cleaned in _DISPLAY_META_HEADINGS:
        return True

    for prefix in _DISPLAY_META_PREFIXES:
        if re.match(rf'^{re.escape(prefix)}\s*[:：]', cleaned, flags=re.IGNORECASE):
            return True

    return False


def _truncate_display_text(text: str, max_chars: int = 120) -> str:
    """Safely truncate display text without cutting obvious tokens mid-phrase."""
    cleaned = _clean_display_text(text)
    if not cleaned:
        return ""

    for sep in ("。", "！", "？", "；"):
        idx = cleaned.find(sep)
        if 8 <= idx <= max_chars:
            return cleaned[:idx + 1]

    if len(cleaned) <= max_chars:
        return cleaned

    boundary_chars = "。；，、 ,）)]"
    cut = max(cleaned.rfind(ch, 0, max_chars + 1) for ch in boundary_chars)
    if cut >= max_chars // 2:
        clipped = cleaned[:cut]
    else:
        clipped = cleaned[:max_chars]
    clipped = clipped.rstrip(" ，、；")
    # No ellipsis when the cut landed on natural sentence punctuation — the
    # reader already knows the sentence ended cleanly.
    if clipped and clipped[-1] in "。！？；":
        return clipped
    return clipped + "…"


def _summarize_display_text(text: str, max_chars: int = 120) -> str:
    """Extract a human-readable one-liner from raw agent output."""
    if not text:
        return ""

    for raw_line in str(text).splitlines():
        if _is_display_noise_line(raw_line):
            continue
        cleaned = _clean_display_text(raw_line)
        if cleaned:
            return _truncate_display_text(cleaned, max_chars=max_chars)

    # Fallback: flatten everything and try one last cleanup pass.
    flattened = _clean_display_text(" ".join(str(text).splitlines()))
    return _truncate_display_text(flattened, max_chars=max_chars)


def _enforce_thesis_limit(text: str, max_chars: int = 50) -> str:
    """Enforce single-sentence, max_chars limit on thesis text."""
    text = _clean_display_text(text)
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
            if isinstance(trace.started_at, datetime)
            else ("\u2014" if trace.started_at is None else str(trace.started_at)),
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
    veto_source: str = ""              # "agent_veto" | "risk_gate" | ""
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
            veto_source=entry.get("veto_source", ""),
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
    veto_source: str = ""
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
            veto_source=getattr(trace, "veto_source", ""),
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


# ── Re-exports from sub-modules ──────────────────────────────────────────
# All external callers import from views.py — these re-exports maintain
# backward compatibility so no callers need changes.

from .snapshot_view import SnapshotView
from .research_view import ResearchView
from .audit_view import AuditView
from .pool_view import StockDivergenceRow, DivergencePoolView
from .market_view import MarketView, _normalize_consecutive_boards, _extract_breadth_counts

__all__ = [
    # Shared utilities
    "_strip_internal_tokens",
    "_clean_display_text",
    "_truncate_display_text",
    "_summarize_display_text",
    "_enforce_thesis_limit",
    "_check_degradation",
    # Shared small views (defined here)
    "BannerView",
    "RunSummaryView",
    "NodeTraceView",
    "WarRoomView",
    # Re-exported from sub-modules
    "SnapshotView",
    "ResearchView",
    "AuditView",
    "StockDivergenceRow",
    "DivergencePoolView",
    "MarketView",
    "_normalize_consecutive_boards",
    "_extract_breadth_counts",
]
