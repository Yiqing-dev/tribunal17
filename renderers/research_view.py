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
    debate_crosstalk: List[Dict] = field(default_factory=list)
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

    # Cover-card + K-line card fields (parallels SnapshotView).
    # Derived in build() from Market Analyst price_history + signal log.
    metrics_fallback: Dict = field(default_factory=dict)
    industry_compare: Dict = field(default_factory=dict)
    stock_profile: Dict = field(default_factory=dict)
    calibration_summary: Dict = field(default_factory=dict)
    data_quality_flags: List[Dict] = field(default_factory=list)
    price_history: List[float] = field(default_factory=list)
    signal_history: List[Dict] = field(default_factory=list)
    report_diff: Dict = field(default_factory=dict)
    current_price: float = 0.0
    pct_change_5d: float = 0.0
    period_high: float = 0.0
    period_low: float = 0.0
    period_days: int = 0

    # Degradation detection
    is_degraded: bool = False
    degradation_reasons: List[str] = field(default_factory=list)

    # Research-quality badge, computed from the loaded trace itself.
    quality_grade: str = ""
    quality_score: float = 0.0
    quality_weak_dims: List[str] = field(default_factory=list)

    banner: Optional[BannerView] = None

    @classmethod
    def build(
        cls,
        service: ReplayService,
        run_id: str,
        *,
        report_diff: Optional[Dict] = None,
        previous_trace: Optional[RunTrace] = None,
    ) -> Optional["ResearchView"]:
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

        # ── Debate crosstalk (AQ-01/AQ-03): the bear's strongest rebuttals and
        #    how the PM ruled on the challenged bull claim. Surfaces REAL clash
        #    to the reader instead of a single opaque quality grade. ──
        _bull_text_by_id = {
            c.get("claim_id"): c.get("text", "")
            for c in (bull_sd.get("supporting_claims") or [])
        }
        _adj_by_id = {
            a.get("claim_id"): a for a in (pm_sd.get("adjudications") or [])
        }
        _rebuttals = sorted(
            (bear_sd.get("opposing_claims") or []),
            key=lambda r: (r.get("confidence") or 0),
            reverse=True,
        )
        debate_crosstalk = []
        for r in _rebuttals[:3]:
            tid = r.get("target_claim_id", "")
            adj = _adj_by_id.get(tid) or {}
            debate_crosstalk.append({
                "target_claim_id": tid,
                "target_claim_text": _bull_text_by_id.get(tid, ""),
                "rebuttal_text": r.get("text", ""),
                "rebuttal_confidence": r.get("confidence", -1.0),
                "pm_verdict": adj.get("verdict", ""),
                "pm_reason": adj.get("reason", ""),
            })

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

        # ── Cover-card + K-line + industry data (parallels SnapshotView) ──
        fund_out = service.show_node_output(run_id, "Fundamentals Analyst") or {}
        fund_sd = fund_out.get("structured_data") or {}
        metrics_fb_data = fund_sd.get("metrics_fallback", {}) or {}
        industry_cmp_data = fund_sd.get("industry_compare", {}) or {}
        stock_profile_data = fund_sd.get("stock_profile", {}) or {}
        calibration_data = fund_sd.get("calibration_summary", {}) or {}
        data_quality_flags = fund_sd.get("data_quality_flags", []) or []

        mkt_out = service.show_node_output(run_id, "Market Analyst") or {}
        mkt_sd = mkt_out.get("structured_data") or {}
        raw_prices = mkt_sd.get("price_history", []) or []
        price_history_data: List[float] = [float(p) for p in raw_prices if p is not None][:30]

        signal_history_data: List[Dict] = []
        previous_trace_for_diff = previous_trace
        try:
            from ..report_index import sort_run_entries

            past_runs = sort_run_entries(
                service.store.list_runs(ticker=trace.ticker, limit=0),
                newest_first=True,
            )
            count = 0
            for pr in past_runs:
                pr_rid = pr.get("run_id", "")
                if pr_rid == run_id:
                    continue
                pr_conf = -1.0
                if pr_rid:
                    try:
                        if previous_trace_for_diff and pr_rid == previous_trace_for_diff.run_id:
                            pr_trace = previous_trace_for_diff
                        else:
                            pr_trace = service.load_run(pr_rid)
                        if pr_trace and pr_trace.final_confidence >= 0:
                            pr_conf = float(pr_trace.final_confidence)
                        if pr_trace and previous_trace_for_diff is None:
                            previous_trace_for_diff = pr_trace
                        pr_action = (
                            "VETO" if pr_trace and pr_trace.was_vetoed
                            else (pr_trace.research_action if pr_trace else pr.get("research_action", ""))
                        )
                    except Exception:
                        pr_action = pr.get("research_action", "")
                else:
                    pr_action = pr.get("research_action", "")
                signal_history_data.append({
                    "trade_date": pr.get("trade_date", ""),
                    "action": pr_action,
                    "confidence": pr_conf,
                    "run_id": pr_rid,
                })
                count += 1
                if count >= 5:
                    break
        except Exception:
            pass

        report_diff_data: Dict = dict(report_diff or {})
        if not report_diff_data:
            try:
                from ..report_diff import compare_reports

                report_diff_data = compare_reports(previous_trace_for_diff, trace).to_dict()
            except Exception:
                report_diff_data = {}

        # Cover-card derivations from price history
        cur_price_data = 0.0
        pct_5d_data = 0.0
        hi_data = 0.0
        lo_data = 0.0
        days_data = 0
        if price_history_data:
            cur_price_data = float(price_history_data[-1])
            hi_data = float(max(price_history_data))
            lo_data = float(min(price_history_data))
            days_data = len(price_history_data)
            if len(price_history_data) >= 6:
                start_p = float(price_history_data[-6])
                if start_p > 0:
                    pct_5d_data = (cur_price_data - start_p) / start_p * 100.0

        quality_grade = ""
        quality_score = 0.0
        quality_weak_dims: List[str] = []
        try:
            from ..research_quality import evaluate_trace_quality
            qrec = evaluate_trace_quality(trace.to_dict())
            quality_grade = qrec.composite_grade
            quality_score = qrec.composite_score
            quality_weak_dims = list(qrec.weak_dimensions)
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
            confidence_defaulted=any(
                "confidence defaulted" in str(w)
                for w in pm_out.get("parse_warnings", [])
            ),
            was_vetoed=trace.was_vetoed,
            veto_source=getattr(trace, "veto_source", ""),
            risk_score=risk_out.get("risk_score"),
            risk_cleared=risk_out.get("risk_cleared"),
            bull_excerpt=bull_out.get("output_excerpt", ""),
            debate_crosstalk=debate_crosstalk,
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
            metrics_fallback=metrics_fb_data,
            industry_compare=industry_cmp_data,
            stock_profile=stock_profile_data,
            calibration_summary=calibration_data,
            data_quality_flags=data_quality_flags,
            price_history=price_history_data,
            signal_history=signal_history_data,
            report_diff=report_diff_data,
            current_price=cur_price_data,
            pct_change_5d=pct_5d_data,
            period_high=hi_data,
            period_low=lo_data,
            period_days=days_data,
            is_degraded=is_degraded,
            degradation_reasons=degradation_reasons,
            quality_grade=quality_grade,
            quality_score=quality_score,
            quality_weak_dims=quality_weak_dims,
            banner=BannerView.from_trace(trace),
        )
