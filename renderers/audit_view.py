"""
Tier 3 Audit view model.

Compliance, metrics, traceability — deep-dive audit page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..replay_service import ReplayService
from ..trace_models import RunMetrics, RunTrace


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

    # Report-level research context
    stock_profile: Dict = field(default_factory=dict)
    calibration_summary: Dict = field(default_factory=dict)
    data_quality_flags: List[Dict] = field(default_factory=list)

    # K-line card fields (no cover card on audit — that's tearsheet territory)
    price_history: List[float] = field(default_factory=list)
    signal_history: List[Dict] = field(default_factory=list)
    period_days: int = 0

    # Backward-compat for K-line card consumer (audit doesn't show these prominently
    # but renderer pulls them via getattr — populating saves a None-check downstream)
    current_price: float = 0.0
    period_high: float = 0.0
    period_low: float = 0.0

    # Research-quality badge, computed from the loaded trace itself.
    quality_grade: str = ""
    quality_score: float = 0.0
    quality_weak_dims: List[str] = field(default_factory=list)

    banner: Optional[BannerView] = None

    @classmethod
    def build(cls, service: ReplayService, run_id: str) -> Optional["AuditView"]:
        from .views import BannerView, NodeTraceView

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

        fund_out = service.show_node_output(run_id, "Fundamentals Analyst") or {}
        fund_sd = fund_out.get("structured_data") or {}
        stock_profile_data = fund_sd.get("stock_profile", {}) or {}
        calibration_data = fund_sd.get("calibration_summary", {}) or {}
        data_quality_flags = fund_sd.get("data_quality_flags", []) or []

        # ── K-line data (price + past signals) ──
        mkt_out = service.show_node_output(run_id, "Market Analyst") or {}
        mkt_sd = mkt_out.get("structured_data") or {}
        raw_prices = mkt_sd.get("price_history", []) or []
        ph_data: List[float] = [float(p) for p in raw_prices if p is not None][:30]
        sh_data: List[Dict] = []
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
                pr_action = pr.get("research_action", "")
                if pr_rid:
                    try:
                        pr_trace = service.load_run(pr_rid)
                        if pr_trace and pr_trace.final_confidence >= 0:
                            pr_conf = float(pr_trace.final_confidence)
                        if pr_trace:
                            pr_action = "VETO" if pr_trace.was_vetoed else (pr_trace.research_action or pr_action)
                    except Exception:
                        pass
                sh_data.append({
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
        cur_p = float(ph_data[-1]) if ph_data else 0.0
        hi_p = float(max(ph_data)) if ph_data else 0.0
        lo_p = float(min(ph_data)) if ph_data else 0.0

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
            stock_profile=stock_profile_data,
            calibration_summary=calibration_data,
            data_quality_flags=data_quality_flags,
            price_history=ph_data,
            signal_history=sh_data,
            period_days=len(ph_data),
            current_price=cur_p,
            period_high=hi_p,
            period_low=lo_p,
            quality_grade=quality_grade,
            quality_score=quality_score,
            quality_weak_dims=quality_weak_dims,
            banner=BannerView.from_trace(trace),
        )
