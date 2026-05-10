"""
Tier 1 Snapshot view model.

Answers: Is this ticker worth looking at? Why? What's the risk?
6 blocks: conclusion, core drivers, main risks, evidence strength,
upcoming catalysts, status lights.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..replay_service import ReplayService
from ..trace_models import RunTrace

from .views import (
    BannerView,
    _check_degradation,
    _strip_internal_tokens,
    _summarize_display_text,
)


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
    confidence_defaulted: bool = False  # True when PM confidence was defaulted to 0.5
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
    veto_source: str = ""

    # Bull vs Bear strength (for bar chart) — confidence-weighted sum (float)
    # Falls back to raw claim count when claims have no per-claim confidence.
    bull_strength: float = 0.0
    bear_strength: float = 0.0

    # Fallback financial metrics (from fundamentals analyst text when vendor unavailable)
    metrics_fallback: Dict = field(default_factory=dict)

    # Industry comparison + valuation percentile (injected via
    # bridge.generate_report(industry_data=...) → Fundamentals Analyst node sd).
    # Shape documented in akshare_collector.AkshareBundle.industry_compare.
    industry_compare: Dict = field(default_factory=dict)

    # Report-level research context
    stock_profile: Dict = field(default_factory=dict)
    calibration_summary: Dict = field(default_factory=dict)
    data_quality_flags: List[Dict] = field(default_factory=list)

    # Degradation detection
    is_degraded: bool = False
    degradation_reasons: List[str] = field(default_factory=list)

    # Action Checklist (pillar scores from 4 analysts)
    pillar_checklist: List[Dict] = field(default_factory=list)
    # Each: {"pillar": "技术面", "score": 2, "emoji": "✅", "label": "多头排列确认"}

    # Pillar consensus summary (derived from pillar_checklist)
    # {"bullish": 2, "bearish": 1, "neutral": 1, "total": 4,
    #  "verdict": "split"|"lean_bullish"|"lean_bearish"|"strong_bullish"|"strong_bearish"|"neutral",
    #  "tension": bool}  — tension=True when ≥3 pillars agree but action is HOLD
    pillar_consensus: Dict = field(default_factory=dict)

    # PM directional lean (research improvement #2): for HOLD actions, captures
    # PM's "if forced to pick a direction" stance. Empty string when not provided
    # or when action is BUY/SELL (in which case lean equals action).
    directional_lean: str = ""        # bullish / bearish / neutral / ""
    lean_reason: str = ""             # one-line justification

    # Risk Debate Summary (3 debaters)
    risk_debate_summary: List[Dict] = field(default_factory=list)
    # Each: {"stance": "激进", "recommendation": "BUY", "position_pct": "10%", "key_risk": "..."}

    # Battle Plan (from ResearchOutput)
    tradecard: Dict = field(default_factory=dict)
    trade_plan: Dict = field(default_factory=dict)

    # Historical signal tracking
    signal_history: List[Dict] = field(default_factory=list)

    # Visual enhancement fields
    price_history: List[float] = field(default_factory=list)
    previous_confidence: float = -1.0

    # Cover-card fields (derived from price_history + metrics_fallback when present)
    current_price: float = 0.0       # last price in history
    pct_change_5d: float = 0.0       # 5-day return % (price-anchored, not signal-anchored)
    period_high: float = 0.0         # max of available price_history (typically ~30d)
    period_low: float = 0.0          # min of available price_history
    period_days: int = 0             # length of price_history window

    # Research-quality grade (price-free internal yardstick)
    # See research_quality.evaluate_trace_quality() for the 7-dim scoring.
    quality_grade: str = ""          # A / B / C / D, "" when evaluation skipped
    quality_score: float = 0.0       # 0.0-1.0 composite
    quality_weak_dims: List[str] = field(default_factory=list)

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

        # ── One-line summary: prefer structured conclusion, allow longer text so
        # the hero doesn't end with a meaningless ellipsis. 240 chars (~80-120
        # zh chars) lets one full reasoning sentence land cleanly in the hero. ──
        one_line = ""
        directional_lean = ""
        lean_reason = ""
        if pm_out:
            pm_sd = pm_out.get("structured_data") or {}
            if pm_sd.get("conclusion"):
                one_line = _summarize_display_text(pm_sd["conclusion"], max_chars=240)
            else:
                one_line = _summarize_display_text(pm_out.get("output_excerpt", ""), max_chars=240)
            directional_lean = str(pm_sd.get("directional_lean", "") or "")
            lean_reason = str(pm_sd.get("lean_reason", "") or "")
        if not one_line:
            one_line = _summarize_display_text(
                f"研究经理综合判断：{label}，置信度 {f'{trace.final_confidence:.0%}' if trace.final_confidence >= 0 else '—'}",
                max_chars=240,
            )

        # ── Core drivers: prefer structured bull claims ──
        core_drivers = []
        _driver_keys = set()

        def _append_driver(text: str) -> None:
            cleaned = _summarize_display_text(text, max_chars=120)
            if not cleaned:
                return
            # Exact-match dedup: numeric variants ("ROE 12%" vs "ROE 8%") are
            # legitimately distinct claims and should both be shown.
            if cleaned in _driver_keys:
                return
            _driver_keys.add(cleaned)
            core_drivers.append(cleaned)

        if bull_out:
            bull_sd = bull_out.get("structured_data") or {}
            bull_claims_list = bull_sd.get("supporting_claims") or []
            if bull_claims_list:
                # Top 3 by confidence
                sorted_claims = sorted(bull_claims_list, key=lambda c: c.get("confidence", 0), reverse=True)
                for c in sorted_claims[:3]:
                    _append_driver(c.get("text", ""))
            else:
                # Fallback: extract from excerpt
                excerpt = bull_out.get("output_excerpt", "")
                for line in excerpt.split("\n"):
                    stripped = line.strip()
                    if stripped.startswith("**结论") or stripped.startswith("**核心"):
                        clean = stripped.strip("*#- ").strip()
                        if clean and len(clean) > 5:
                            _append_driver(clean)
                    elif stripped.startswith("#### ") or stripped.startswith("### "):
                        clean = stripped.lstrip("#* ").strip()
                        if clean and len(clean) > 5:
                            _append_driver(clean)
                    if len(core_drivers) >= 3:
                        break
                if not core_drivers:
                    _append_driver(excerpt)

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

        # Bull vs Bear strength — confidence-weighted sum, fallback to count.
        # Sums per-claim confidence so a bear case backed by 8 claims at 0.85
        # registers as 6.8 strength while a bull case of 16 claims at 0.45
        # registers as 7.2 — much more honest than raw 8 vs 16. Falls back to
        # claim count when no per-claim confidence is available (older traces).
        def _weighted_or_count(node_out, claims_key: str) -> float:
            if not node_out:
                return 0.0
            sd = node_out.get("structured_data") or {}
            claims_list = sd.get(claims_key) or []
            confs = []
            for c in claims_list:
                if not isinstance(c, dict):
                    continue
                v = c.get("confidence")
                try:
                    f = float(v) if v is not None else 0.0
                except (TypeError, ValueError):
                    f = 0.0
                if f > 0:
                    confs.append(f)
            if confs:
                return float(sum(confs))
            return float(node_out.get("claims_produced", 0) or 0)

        bull_claims = _weighted_or_count(bull_out, "supporting_claims")
        bear_claims = _weighted_or_count(bear_out, "opposing_claims")

        # Fallback financial metrics + industry comparison data injected via
        # bridge.generate_report(industry_data=...).
        metrics_fb: Dict = {}
        industry_cmp: Dict = {}
        fund_out = service.show_node_output(run_id, "Fundamentals Analyst")
        if fund_out:
            fund_sd = fund_out.get("structured_data") or {}
            metrics_fb = fund_sd.get("metrics_fallback", {})
            industry_cmp = fund_sd.get("industry_compare", {}) or {}
            stock_profile_data = fund_sd.get("stock_profile", {}) or {}
            calibration_data = fund_sd.get("calibration_summary", {}) or {}
            data_quality_flags = fund_sd.get("data_quality_flags", []) or []
        else:
            stock_profile_data = {}
            calibration_data = {}
            data_quality_flags = []

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
                try:
                    score = int(raw_score) if raw_score is not None else -1
                except (ValueError, TypeError):
                    score = -1
                if score < 0:
                    continue
                score = min(max(score, 0), 4)
                emoji = PILLAR_EMOJI.get(score, "\u26aa")
                first_line = _summarize_display_text(nd_out.get("output_excerpt", ""), max_chars=40)
                if not first_line:
                    bias = "偏多" if score >= 3 else ("中性" if score == 2 else "偏空")
                    first_line = f"维度评分 {score}/4，综合判断{bias}"
                pillar_checklist.append({
                    "pillar": pillar_label,
                    "score": score,
                    "emoji": emoji,
                    "label": first_line,
                })

        # ── Fallback: fill missing pillars from tradecard.pillars ──
        if len(pillar_checklist) < 4:
            _fb_out = service.show_node_output(run_id, "ResearchOutput")
            if _fb_out:
                _fb_pillars = (
                    (_fb_out.get("structured_data") or {})
                    .get("tradecard", {})
                    .get("pillars", {})
                )
                if _fb_pillars:
                    _existing = {p["pillar"] for p in pillar_checklist}
                    _fb_map = [
                        ("market_score", "\u6280\u672f\u9762"),
                        ("fundamental_score", "\u57fa\u672c\u9762"),
                        ("news_score", "\u6d88\u606f\u9762"),
                        ("sentiment_score", "\u60c5\u7eea\u9762"),
                    ]
                    for _key, _lbl in _fb_map:
                        if _lbl in _existing:
                            continue
                        _raw = _fb_pillars.get(_key)
                        if _raw is None and _key == "news_score":
                            _raw = _fb_pillars.get("macro_score")
                        if _raw is None:
                            continue
                        try:
                            _sc = int(_raw)
                        except (ValueError, TypeError):
                            continue
                        if _sc < 0:
                            continue
                        _sc = min(max(_sc, 0), 4)
                        pillar_checklist.append({
                            "pillar": _lbl,
                            "score": _sc,
                            "emoji": PILLAR_EMOJI.get(_sc, "\u26aa"),
                            "label": "",
                        })

        # ── Pillar Consensus Summary (research improvement #1) ──
        # Score scale: 0/1 = bearish, 2 = neutral, 3/4 = bullish
        _bull = sum(1 for p in pillar_checklist if p.get("score", -1) >= 3)
        _bear = sum(1 for p in pillar_checklist if 0 <= p.get("score", -1) <= 1)
        _neut = sum(1 for p in pillar_checklist if p.get("score", -1) == 2)
        _total = _bull + _bear + _neut
        if _total >= 3:
            if _bull >= 3:
                _verdict = "strong_bullish" if _bull == 4 else "lean_bullish"
            elif _bear >= 3:
                _verdict = "strong_bearish" if _bear == 4 else "lean_bearish"
            elif _bull == _bear:
                _verdict = "split"
            elif _bull > _bear:
                _verdict = "lean_bullish"
            elif _bear > _bull:
                _verdict = "lean_bearish"
            else:
                _verdict = "neutral"
        else:
            _verdict = "insufficient"
        # Tension flag: ≥3 pillars agree on direction but PM action is HOLD
        _action_upper = (action or "").upper()
        _tension = (
            _action_upper == "HOLD"
            and (_bull >= 3 or _bear >= 3)
        )
        pillar_consensus = {
            "bullish": _bull,
            "bearish": _bear,
            "neutral": _neut,
            "total": _total,
            "verdict": _verdict,
            "tension": _tension,
        }

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
        # Load per-run confidence for the sparkline. Manifest stores only the
        # action string, so we dereference each trace — capped at 5 entries
        # to bound load time.
        signal_history: List[Dict] = []
        try:
            past_runs = service.store.list_runs(ticker=trace.ticker, limit=10)
            count = 0
            for pr in past_runs:
                pr_rid = pr.get("run_id", "")
                if pr_rid == run_id:
                    continue
                pr_conf = 0.0
                if pr_rid:
                    try:
                        pr_trace = service.store.load(pr_rid)
                        if pr_trace and pr_trace.final_confidence >= 0:
                            pr_conf = float(pr_trace.final_confidence)
                    except Exception:
                        pass
                signal_history.append({
                    "trade_date": pr.get("trade_date", ""),
                    "action": pr.get("research_action", ""),
                    "confidence": pr_conf,
                    "run_id": pr_rid,
                })
                count += 1
                if count >= 5:
                    break
        except Exception:
            pass

        # ── Price History (for sparkline + cover card) ──
        _price_history: List[float] = []
        mkt_out = service.show_node_output(run_id, "Market Analyst")
        if mkt_out:
            _msd = (mkt_out.get("structured_data") or {})
            _raw_prices = _msd.get("price_history", [])
            _price_history = [float(p) for p in _raw_prices if p is not None][:30]

        # Derive cover-card fields from price history (no new data source needed)
        _current_price = 0.0
        _pct_5d = 0.0
        _hi = 0.0
        _lo = 0.0
        _days = 0
        if _price_history:
            _current_price = float(_price_history[-1])
            _hi = float(max(_price_history))
            _lo = float(min(_price_history))
            _days = len(_price_history)
            if len(_price_history) >= 6:
                _start = float(_price_history[-6])
                if _start > 0:
                    _pct_5d = (_current_price - _start) / _start * 100.0

        # Research-quality grade — price-free internal yardstick
        _quality_grade = ""
        _quality_score = 0.0
        _quality_weak: List[str] = []
        try:
            from ..research_quality import evaluate_trace_quality
            _qrec = evaluate_trace_quality(trace.to_dict())
            _quality_grade = _qrec.composite_grade
            _quality_score = _qrec.composite_score
            _quality_weak = list(_qrec.weak_dimensions)
        except Exception:
            pass

        # ── Previous confidence (for trend arrow) ──
        _prev_conf = -1.0
        if signal_history:
            # manifest doesn't store confidence; load trace if available
            _prev_rid = signal_history[0].get("run_id", "")
            if _prev_rid:
                try:
                    _pt = service.store.load(_prev_rid)
                    if _pt:
                        _prev_conf = _pt.final_confidence
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
                for w in (pm_out or {}).get("parse_warnings", [])
            ),
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
            veto_source=getattr(trace, "veto_source", ""),
            bull_strength=bull_claims,
            bear_strength=bear_claims,
            metrics_fallback=metrics_fb,
            industry_compare=industry_cmp,
            stock_profile=stock_profile_data,
            calibration_summary=calibration_data,
            data_quality_flags=data_quality_flags,
            is_degraded=is_degraded,
            degradation_reasons=degradation_reasons,
            pillar_checklist=pillar_checklist,
            pillar_consensus=pillar_consensus,
            directional_lean=directional_lean,
            lean_reason=lean_reason,
            risk_debate_summary=risk_debate_summary,
            tradecard=tradecard_data,
            trade_plan=trade_plan_data,
            signal_history=signal_history,
            price_history=_price_history,
            previous_confidence=_prev_conf,
            current_price=_current_price,
            pct_change_5d=_pct_5d,
            period_high=_hi,
            period_low=_lo,
            period_days=_days,
            quality_grade=_quality_grade,
            quality_score=_quality_score,
            quality_weak_dims=_quality_weak,
            banner=BannerView.from_trace(trace),
        )
