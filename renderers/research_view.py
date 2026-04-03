"""
Tier 2 Research view model.

Answers: How was this conclusion reached? What are the bull/bear
arguments? What scenarios exist? What should I watch next?
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..replay_service import ReplayService
from ..trace_models import RunTrace

from .views import (
    BannerView,
    _check_degradation,
    _strip_internal_tokens,
)


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
    confidence_defaulted: bool = False  # True when PM confidence was defaulted to 0.5
    was_vetoed: bool = False
    veto_source: str = ""
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
                "probs_defaulted": scn_sd.get("probs_defaulted", False),
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
            confidence_defaulted=any(
                "confidence defaulted" in str(w)
                for w in pm_out.get("parse_warnings", [])
            ),
            was_vetoed=trace.was_vetoed,
            veto_source=getattr(trace, "veto_source", ""),
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
