"""
Trace Models — canonical data objects for run replay and observability.

Design principles:
- Store structured objects and hashes, not raw free-text blobs.
- Every NodeTrace captures *what went in* and *what came out* of a graph node.
- RunMetrics are computed from traces, not stored redundantly.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum

# A-share product — all timestamps in CST (UTC+8)
_CST = timezone(timedelta(hours=8))


def _now_cst() -> datetime:
    """Return timezone-aware 'now' in CST (Asia/Shanghai)."""
    return datetime.now(tz=_CST)
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class NodeStatus(str, Enum):
    """Execution status of a single graph node."""
    OK = "ok"
    WARN = "warn"          # Completed with warnings (fallback parse, low confidence)
    ERROR = "error"        # Node raised an exception
    SKIPPED = "skipped"    # Node was not executed in this run path


@dataclass
class NodeTrace:
    """Trace of a single graph node execution.

    Captures input/output hashes, referenced evidence/claim IDs,
    parse quality, compliance decisions, and timing.
    """
    run_id: str
    node_name: str
    seq: int                          # Execution order within run (0-based)
    timestamp: datetime = field(default_factory=_now_cst)
    duration_ms: float = 0.0

    status: NodeStatus = NodeStatus.OK

    # Input/output hashes (SHA-256 truncated to 16 hex chars)
    input_hash: str = ""
    output_hash: str = ""

    # Structured output excerpt (short summary, not full text)
    output_excerpt: str = ""          # Max 150000 chars — full agent output for semantic matching

    # Protocol metadata
    parse_status: str = ""            # ParseStatus value if applicable
    parse_confidence: float = -1.0    # -1 = not applicable
    parse_missing_fields: List[str] = field(default_factory=list)
    parse_warnings: List[str] = field(default_factory=list)

    # Evidence & claim lineage
    evidence_ids_referenced: List[str] = field(default_factory=list)
    claim_ids_referenced: List[str] = field(default_factory=list)
    claim_ids_produced: List[str] = field(default_factory=list)

    # Debate packet metadata (for Bull/Bear nodes)
    claims_produced: int = 0
    claims_attributed: int = 0
    claims_unattributed: int = 0

    # Synthesis metadata (for PM/Risk nodes)
    research_action: str = ""         # BUY/HOLD/SELL/VETO
    confidence: float = -1.0          # -1.0 sentinel: "not set"; finalize() skips if < 0
    thesis_effect: str = ""
    # Design note: risk_score (0-10 numeric assessment) and risk_cleared
    # (boolean pass/fail gate) are intentionally independent LLM outputs.
    # risk_cleared is NOT derived from risk_score — the risk_manager agent
    # evaluates qualitative factors beyond the numeric score. A high
    # risk_score can still have risk_cleared=True if mitigants exist.
    risk_score: Optional[int] = None
    risk_cleared: Optional[bool] = None
    max_position_pct: float = -1.0

    # Risk flags (for Risk Judge)
    risk_flag_count: int = 0
    risk_flag_categories: List[str] = field(default_factory=list)
    vetoed: bool = False
    veto_source: str = ""              # "agent_veto" | "risk_gate" | ""
    veto_reasons: List[str] = field(default_factory=list)

    # Compliance metadata (for publishing gate)
    compliance_status: str = ""       # PublishStatus value
    compliance_reasons: List[str] = field(default_factory=list)
    compliance_rules_fired: List[str] = field(default_factory=list)

    # Ledger transition
    ledger_prev_status: str = ""
    ledger_new_status: str = ""
    ledger_transition_reason: str = ""

    # Errors
    errors: List[str] = field(default_factory=list)

    # Rich structured data (protocol objects serialized as dicts)
    structured_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to dict for JSON storage."""
        d = {}
        for k, v in self.__dict__.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat()
            elif isinstance(v, Enum):
                d[k] = v.value
            else:
                d[k] = v
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "NodeTrace":
        """Deserialize from dict."""
        d = dict(d)  # shallow copy — avoid mutating caller's dict
        if "timestamp" in d and isinstance(d["timestamp"], str):
            d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        if "status" in d and isinstance(d["status"], str):
            try:
                d["status"] = NodeStatus(d["status"])
            except ValueError:
                logger.warning("Unknown NodeStatus '%s', defaulting to WARN", d["status"])
                d["status"] = NodeStatus.WARN
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RunTrace:
    """Complete trace of a single analysis run.

    Contains run-level metadata and the ordered list of NodeTraces.
    """
    run_id: str = field(default_factory=lambda: f"run-{uuid.uuid4().hex[:12]}")
    ticker: str = ""
    ticker_name: str = ""            # Human-readable name (e.g. "贵州茅台")
    trade_date: str = ""
    as_of: str = ""                   # Date the analysis was requested
    started_at: datetime = field(default_factory=_now_cst)
    completed_at: Optional[datetime] = None

    # Config snapshot (non-sensitive)
    market: str = ""
    language: str = ""
    llm_provider: str = ""
    novice_mode: bool = False

    # Node traces (ordered by seq)
    node_traces: List[NodeTrace] = field(default_factory=list)

    # Run-level summary (computed at end_run)
    total_nodes: int = 0
    error_count: int = 0
    warn_count: int = 0
    total_evidence_ids: List[str] = field(default_factory=list)
    total_claim_ids: List[str] = field(default_factory=list)

    # Final outputs
    research_action: str = ""
    final_confidence: float = -1.0
    compliance_status: str = ""
    was_vetoed: bool = False
    veto_source: str = ""              # "agent_veto" | "risk_gate" | ""
    pre_veto_action: str = ""          # Original action before risk gate forced VETO

    # Market context (injected from market layer agents)
    market_context: Dict = field(default_factory=dict)

    # Data freshness snapshot at run time
    freshness_ok: bool = True
    stale_sources: List[Dict] = field(default_factory=list)
    vendor_freshness: Dict[str, Dict] = field(default_factory=dict)

    def finalize(self):
        """Compute summary fields from node traces."""
        self.completed_at = _now_cst()
        self.total_nodes = len(self.node_traces)
        self.error_count = sum(1 for n in self.node_traces if n.status == NodeStatus.ERROR)
        self.warn_count = sum(1 for n in self.node_traces if n.status == NodeStatus.WARN)

        all_evidence = set()
        all_claims = set()
        for nt in self.node_traces:
            all_evidence.update(nt.evidence_ids_referenced)
            all_claims.update(nt.claim_ids_referenced)
            all_claims.update(nt.claim_ids_produced)

            # Capture final-stage outputs.
            # Risk Judge may lack research_action if RISK_OUTPUT omitted the field;
            # in that case, preserve the Research Manager's direction.
            if nt.node_name == "Research Manager" and nt.research_action:
                self.research_action = nt.research_action
                if nt.confidence >= 0:
                    self._pm_confidence = nt.confidence
            elif nt.node_name == "Risk Judge" and nt.research_action:
                self.research_action = nt.research_action
                # Only overwrite confidence if the node provides a meaningful value
                # (Risk Judge may not have its own confidence — use -1 sentinel to skip)
                if nt.confidence >= 0:
                    self.final_confidence = nt.confidence
            # Fallback: if ResearchOutput has action/confidence and upstream didn't set them
            if nt.node_name == "ResearchOutput":
                if not self.research_action and nt.research_action:
                    self.research_action = nt.research_action
                if self.final_confidence < 0 and nt.confidence >= 0:
                    self.final_confidence = nt.confidence
            if nt.vetoed:
                self.was_vetoed = True
                if nt.veto_source:
                    self.veto_source = nt.veto_source
                # Capture pre-veto action: when risk gate forces VETO,
                # Research Manager's action is the original intent.
                if nt.veto_source == "risk_gate" and nt.node_name == "Risk Judge":
                    # Look for Research Manager's original action
                    for pm_nt in self.node_traces:
                        if pm_nt.node_name == "Research Manager" and pm_nt.research_action:
                            self.pre_veto_action = pm_nt.research_action
                            break
            if nt.compliance_status:
                self.compliance_status = nt.compliance_status

        # PM confidence as third-priority fallback: if neither Risk Judge
        # nor ResearchOutput provided a valid confidence, use PM's.
        if self.final_confidence < 0 and hasattr(self, '_pm_confidence'):
            self.final_confidence = self._pm_confidence

        self.total_evidence_ids = sorted(all_evidence)
        self.total_claim_ids = sorted(all_claims)

    def to_dict(self) -> dict:
        d = {}
        for k, v in self.__dict__.items():
            if k.startswith("_"):
                # Persist known private attrs under un-prefixed keys
                if k == "_pm_confidence":
                    d["pm_confidence"] = v
                continue
            if k == "node_traces":
                d[k] = [nt.to_dict() for nt in v]
            elif isinstance(v, datetime):
                d[k] = v.isoformat()
            else:
                d[k] = v
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RunTrace":
        d = dict(d)  # shallow copy — avoid mutating caller's dict
        node_dicts = d.pop("node_traces", [])
        had_started_at = "started_at" in d
        for ts_field in ("started_at", "completed_at"):
            if ts_field in d and isinstance(d[ts_field], str):
                d[ts_field] = datetime.fromisoformat(d[ts_field])
            elif ts_field in d and d[ts_field] is None:
                pass  # keep None
        # Restore known private attrs before constructing
        pm_conf = d.pop("pm_confidence", None)
        rt = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        if not had_started_at:
            rt.started_at = None  # don't let default_factory mask missing data
        if pm_conf is not None:
            rt._pm_confidence = pm_conf
        rt.node_traces = [NodeTrace.from_dict(nd) for nd in node_dicts]
        return rt


@dataclass
class RunMetrics:
    """Computed metrics for a run — derived from RunTrace, never stored directly.

    These are the P5 metrics the user specified.
    """
    run_id: str = ""

    # Parse quality
    strict_parse_rate: float = 0.0     # Fraction of parseable nodes with STRICT_OK
    fallback_rate: float = 0.0         # Fraction with FALLBACK_USED
    failed_rate: float = 0.0           # Fraction with FAILED

    # Evidence protocol
    claim_to_evidence_binding_rate: float = 0.0   # claims with ≥1 evidence / total claims
    pm_claim_consumption_rate: float = 0.0        # PM-referenced claims / total claims produced
    narrative_dependency_rate: float = 0.0        # 1.0 if no structured claims existed

    # Risk & compliance
    risk_flag_traceability_rate: float = 0.0      # risk flags with evidence / total flags
    compliance_reason_capture_rate: float = 0.0   # compliance rules fired / rules checked
    replay_completeness_rate: float = 0.0         # nodes traced / nodes expected

    # Counts
    total_claims_produced: int = 0
    total_claims_attributed: int = 0
    total_evidence_referenced: int = 0
    total_risk_flags: int = 0
    risk_flags_with_evidence: int = 0

    # Data freshness
    data_freshness_ok: bool = True
    stale_source_count: int = 0


def compute_hash(text: str) -> str:
    """SHA-256 hash truncated to 16 hex chars."""
    if not text:
        return "0" * 16
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
